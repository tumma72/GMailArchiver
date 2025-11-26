"""Tests for authentication module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.connectors.auth import SCOPES, GmailAuthenticator
from gmailarchiver.shared.path_validator import PathTraversalError


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_credentials():
    """Create mock credentials object."""
    creds = Mock()
    creds.valid = True
    creds.expired = False
    creds.refresh_token = "mock_refresh_token"
    creds.to_json.return_value = json.dumps(
        {
            "token": "mock_token",
            "refresh_token": "mock_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client_id",
            "client_secret": "mock_client_secret",
            "scopes": SCOPES,
        }
    )
    return creds


class TestGmailAuthenticatorInit:
    """Tests for GmailAuthenticator initialization."""

    def test_default_initialization(self):
        """Test initialization with default parameters."""
        # Should use bundled credentials and XDG token path
        auth = GmailAuthenticator()

        # Should use bundled credentials in src/gmailarchiver/connectors/config/
        assert "connectors/config/oauth_credentials.json" in str(auth.credentials_file)
        # Should use XDG-compliant path for token
        assert "gmailarchiver" in str(auth.token_file)
        assert "token.json" in str(auth.token_file.name)
        assert auth._creds is None

    def test_custom_file_paths(self, temp_dir):
        """Test initialization with custom file paths."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            auth = GmailAuthenticator(
                credentials_file="my_creds.json",
                token_file="my_token.json",
                validate_paths=False,  # Disable validation for tests
            )

            assert auth.credentials_file.name == "my_creds.json"
            assert auth.token_file.name == "my_token.json"
        finally:
            os.chdir(original_cwd)

    def test_path_traversal_blocked_credentials(self):
        """Test that path traversal is blocked for credentials file."""
        with pytest.raises(PathTraversalError):
            GmailAuthenticator(credentials_file="../../etc/passwd")

    def test_path_traversal_blocked_token(self):
        """Test that path traversal is blocked for token file."""
        with pytest.raises(PathTraversalError):
            GmailAuthenticator(token_file="../../etc/passwd")

    def test_absolute_path_outside_cwd_blocked(self):
        """Test that absolute paths outside CWD are blocked."""
        with pytest.raises(PathTraversalError):
            GmailAuthenticator(credentials_file="/etc/passwd")


class TestGmailAuthenticatorAuthenticate:
    """Tests for authenticate method."""

    def test_load_existing_token_json(self, temp_dir, mock_credentials):
        """Test loading existing token from JSON file."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Create a valid token.json file
            token_file = Path(temp_dir) / "token.json"
            token_data = {
                "token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "mock_client_id",
                "client_secret": "mock_client_secret",
                "scopes": SCOPES,
            }
            token_file.write_text(json.dumps(token_data))

            # Mock Credentials.from_authorized_user_info
            with patch("gmailarchiver.connectors.auth.Credentials") as MockCreds:
                mock_cred_instance = Mock()
                mock_cred_instance.valid = True
                MockCreds.from_authorized_user_info.return_value = mock_cred_instance

                auth = GmailAuthenticator(token_file="token.json", validate_paths=False)
                result = auth.authenticate()

                # Verify credentials were loaded from JSON
                MockCreds.from_authorized_user_info.assert_called_once_with(token_data, SCOPES)
                assert result == mock_cred_instance
        finally:
            os.chdir(original_cwd)

    def test_missing_credentials_file_error(self, temp_dir):
        """Test that missing credentials.json raises FileNotFoundError."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            auth = GmailAuthenticator(
                credentials_file="nonexistent_credentials.json",
                token_file="token.json",  # Use local token file, not XDG default
                validate_paths=False,  # Disable validation for tests
            )

            with pytest.raises(FileNotFoundError) as exc_info:
                auth.authenticate()

            # Updated error message for bundled credentials
            assert "OAuth credentials file not found" in str(exc_info.value)
            assert "reinstall" in str(exc_info.value).lower()
        finally:
            os.chdir(original_cwd)

    def test_refresh_expired_token(self, temp_dir):
        """Test refreshing an expired token."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Create a token file with expired credentials
            token_file = Path(temp_dir) / "token.json"
            token_data = {
                "token": "expired_token",
                "refresh_token": "valid_refresh_token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "mock_client_id",
                "client_secret": "mock_client_secret",
                "scopes": SCOPES,
            }
            token_file.write_text(json.dumps(token_data))

            with (
                patch("gmailarchiver.connectors.auth.Credentials") as MockCreds,
                patch("gmailarchiver.connectors.auth.Request") as MockRequest,
            ):
                # Mock expired credentials
                mock_cred_instance = Mock()
                mock_cred_instance.valid = False
                mock_cred_instance.expired = True
                mock_cred_instance.refresh_token = "valid_refresh_token"
                MockCreds.from_authorized_user_info.return_value = mock_cred_instance

                # After refresh, credentials become valid
                def make_valid(request):
                    mock_cred_instance.valid = True

                mock_cred_instance.refresh.side_effect = make_valid
                mock_cred_instance.to_json.return_value = json.dumps(token_data)

                auth = GmailAuthenticator(token_file="token.json", validate_paths=False)
                result = auth.authenticate()

                # Verify refresh was called
                mock_cred_instance.refresh.assert_called_once()
                assert result.valid
        finally:
            os.chdir(original_cwd)

    def test_save_token_as_json(self, temp_dir):
        """Test that token is saved as JSON, not pickle."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Create credentials file
            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            with patch("gmailarchiver.connectors.auth.InstalledAppFlow") as MockFlow:
                # Mock the OAuth flow
                mock_flow_instance = Mock()
                mock_cred_instance = Mock()
                mock_cred_instance.valid = True
                mock_cred_instance.to_json.return_value = json.dumps(
                    {
                        "token": "new_token",
                        "refresh_token": "new_refresh_token",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": "mock_client_id",
                        "client_secret": "mock_client_secret",
                        "scopes": SCOPES,
                    }
                )

                mock_flow_instance.run_local_server.return_value = mock_cred_instance
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",
                    validate_paths=False,  # Disable validation for tests
                )
                auth.authenticate()

                # Verify token.json was created and is valid JSON
                token_file = Path(temp_dir) / "token.json"
                assert token_file.exists()

                # Should be readable as JSON (not pickle)
                with open(token_file) as f:
                    token_content = json.load(f)

                assert "token" in token_content
                assert "refresh_token" in token_content
        finally:
            os.chdir(original_cwd)

    def test_credentials_property(self, temp_dir):
        """Test the credentials property."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            auth = GmailAuthenticator(validate_paths=False)

            # Initially None
            assert auth.credentials is None

            # Set credentials
            mock_creds = Mock()
            auth._creds = mock_creds

            # Should return the credentials
            assert auth.credentials == mock_creds
        finally:
            os.chdir(original_cwd)


class TestGmailAuthenticatorRevoke:
    """Tests for revoke method."""

    def test_revoke_deletes_token_file(self, temp_dir):
        """Test that revoke deletes the token file."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Create a token file
            token_file = Path(temp_dir) / "token.json"
            token_file.write_text("{}")

            auth = GmailAuthenticator(token_file="token.json", validate_paths=False)
            auth._creds = Mock()

            # Revoke
            auth.revoke()

            # Token file should be deleted
            assert not token_file.exists()

            # Credentials should be None
            assert auth._creds is None
        finally:
            os.chdir(original_cwd)

    def test_revoke_nonexistent_token_file(self, temp_dir):
        """Test that revoke handles nonexistent token file gracefully."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            auth = GmailAuthenticator(token_file="nonexistent.json", validate_paths=False)
            auth._creds = Mock()

            # Should not raise an error
            auth.revoke()

            # Credentials should be None
            assert auth._creds is None
        finally:
            os.chdir(original_cwd)


class TestBackwardCompatibility:
    """Tests for backward compatibility with pickle-based tokens."""

    def test_migration_from_pickle_to_json(self, temp_dir):
        """Test that users can migrate from pickle to JSON tokens."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Simulate a user who has an old token.pickle file
            # They should delete it and re-authenticate to get token.json

            # Old pickle file (should be ignored)
            pickle_file = Path(temp_dir) / "token.pickle"
            pickle_file.write_bytes(b"old pickle data")

            # Create credentials file
            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            with patch("gmailarchiver.connectors.auth.InstalledAppFlow") as MockFlow:
                mock_flow_instance = Mock()
                mock_cred_instance = Mock()
                mock_cred_instance.valid = True
                mock_cred_instance.to_json.return_value = json.dumps(
                    {
                        "token": "new_token",
                        "refresh_token": "new_refresh_token",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": "mock_client_id",
                        "client_secret": "mock_client_secret",
                        "scopes": SCOPES,
                    }
                )

                mock_flow_instance.run_local_server.return_value = mock_cred_instance
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                # User creates new authenticator with default token.json
                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",
                    validate_paths=False,  # Disable validation for tests
                )
                auth.authenticate()

                # New token.json should be created
                token_json = Path(temp_dir) / "token.json"
                assert token_json.exists()

                # Old pickle file still exists (user should delete manually)
                assert pickle_file.exists()
        finally:
            os.chdir(original_cwd)


class TestAuthErrorPaths:
    """Tests for error handling paths in authentication."""

    def test_corrupt_token_json(self, temp_dir):
        """Test handling of corrupted token JSON file."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # Create a corrupted token.json file
            token_file = Path(temp_dir) / "token.json"
            token_file.write_text("{invalid json")

            # Create credentials file for re-authentication
            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            patch_target = "gmailarchiver.connectors.auth.InstalledAppFlow"
            with patch(patch_target) as MockFlow, patch("builtins.print"):
                mock_flow_instance = Mock()
                mock_cred_instance = Mock()
                mock_cred_instance.valid = True
                mock_cred_instance.to_json.return_value = json.dumps({})

                mock_flow_instance.run_local_server.return_value = mock_cred_instance
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",
                    validate_paths=False,
                )
                # Should handle corrupt JSON and re-authenticate
                result = auth.authenticate()
                assert result is not None

        finally:
            os.chdir(original_cwd)

    def test_token_refresh_failure(self, temp_dir):
        """Test handling of token refresh failure."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            token_file = Path(temp_dir) / "token.json"
            token_data = {
                "token": "expired_token",
                "refresh_token": "invalid_refresh_token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "mock_client_id",
                "client_secret": "mock_client_secret",
                "scopes": SCOPES,
            }
            token_file.write_text(json.dumps(token_data))

            # Create credentials file for fallback
            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            with (
                patch("gmailarchiver.connectors.auth.Credentials") as MockCreds,
                patch("gmailarchiver.connectors.auth.InstalledAppFlow") as MockFlow,
                patch("builtins.print"),
            ):
                # Mock expired credentials that fail to refresh
                mock_cred_instance = Mock()
                mock_cred_instance.valid = False
                mock_cred_instance.expired = True
                mock_cred_instance.refresh_token = "invalid"
                MockCreds.from_authorized_user_info.return_value = mock_cred_instance

                # Refresh fails
                mock_cred_instance.refresh.side_effect = Exception("Refresh failed")

                # Fallback to OAuth flow
                mock_flow_instance = Mock()
                mock_new_cred = Mock()
                mock_new_cred.valid = True
                mock_new_cred.to_json.return_value = json.dumps({})
                mock_flow_instance.run_local_server.return_value = mock_new_cred
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",
                    validate_paths=False,
                )
                result = auth.authenticate()

                # Should fall back to OAuth flow
                assert result is not None

        finally:
            os.chdir(original_cwd)

    def test_oauth_flow_failure(self, temp_dir):
        """Test handling of OAuth flow failure."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            patch_target = "gmailarchiver.connectors.auth.InstalledAppFlow"
            with patch(patch_target) as MockFlow, patch("builtins.print"):
                mock_flow_instance = Mock()
                mock_flow_instance.run_local_server.side_effect = Exception("Auth failed")
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",  # Use local token file, not XDG default
                    validate_paths=False,
                )

                with pytest.raises(Exception, match="Auth failed"):
                    auth.authenticate()

        finally:
            os.chdir(original_cwd)

    def test_token_save_failure(self, temp_dir):
        """Test handling of token save failure."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            creds_file = Path(temp_dir) / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "mock_client_id",
                    "client_secret": "mock_client_secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            creds_file.write_text(json.dumps(creds_data))

            with (
                patch("gmailarchiver.connectors.auth.InstalledAppFlow") as MockFlow,
                patch(
                    "builtins.open",
                    side_effect=[
                        # First open for credentials file succeeds
                        open(creds_file),
                        # Second open for token file fails
                        OSError("Cannot write token"),
                    ],
                ),
                patch("builtins.print"),
            ):
                mock_flow_instance = Mock()
                mock_cred_instance = Mock()
                mock_cred_instance.valid = True
                mock_cred_instance.to_json.return_value = json.dumps({})
                mock_flow_instance.run_local_server.return_value = mock_cred_instance
                MockFlow.from_client_secrets_file.return_value = mock_flow_instance

                auth = GmailAuthenticator(
                    credentials_file="credentials.json",
                    token_file="token.json",  # Use local token file, not XDG default
                    validate_paths=False,
                )

                # Should complete auth even if save fails
                result = auth.authenticate()
                assert result is not None

        finally:
            os.chdir(original_cwd)
