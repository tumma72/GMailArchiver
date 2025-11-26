"""Tests for OAuth scope validation and scope changes."""

import tempfile
from unittest.mock import Mock

from gmailarchiver.connectors.auth import SCOPES, GmailAuthenticator


class TestOAuthScopes:
    """Tests for OAuth scope configuration."""

    def test_scopes_include_full_gmail_access(self):
        """Test that SCOPES includes full Gmail access for deletion support."""
        # CRITICAL: Must include 'https://mail.google.com/' for deletion permission
        # The gmail.modify scope does NOT include permanent deletion
        assert "https://mail.google.com/" in SCOPES, (
            "SCOPES must include 'https://mail.google.com/' for deletion support. "
            "The 'gmail.modify' scope is insufficient for permanent deletion."
        )


class TestScopeValidation:
    """Tests for scope validation functionality."""

    def test_validate_scopes_with_full_access(self):
        """Test validate_scopes returns True when credentials have full Gmail access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # Mock credentials with full Gmail access
            mock_creds = Mock()
            mock_creds.scopes = ["https://mail.google.com/"]
            auth._creds = mock_creds

            # Should return True - full access covers all operations
            required_scopes = ["https://mail.google.com/"]
            assert auth.validate_scopes(required_scopes) is True

    def test_validate_scopes_missing_required(self):
        """Test validate_scopes returns False when missing required scopes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # Mock credentials with only readonly scope
            mock_creds = Mock()
            mock_creds.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
            auth._creds = mock_creds

            # Should return False - missing full Gmail access
            required_scopes = ["https://mail.google.com/"]
            assert auth.validate_scopes(required_scopes) is False

    def test_validate_scopes_no_credentials(self):
        """Test validate_scopes returns False when no credentials exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # No credentials set
            auth._creds = None

            # Should return False
            required_scopes = ["https://mail.google.com/"]
            assert auth.validate_scopes(required_scopes) is False

    def test_validate_scopes_credentials_without_scopes(self):
        """Test validate_scopes returns False when credentials lack scope info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # Mock credentials without scopes attribute
            mock_creds = Mock()
            mock_creds.scopes = None
            auth._creds = mock_creds

            # Should return False
            required_scopes = ["https://mail.google.com/"]
            assert auth.validate_scopes(required_scopes) is False

    def test_validate_scopes_full_access_covers_subset(self):
        """Test that full Gmail access satisfies any subset of Gmail operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # Mock credentials with full Gmail access
            mock_creds = Mock()
            mock_creds.scopes = ["https://mail.google.com/"]
            auth._creds = mock_creds

            # Any Gmail-related scope should be satisfied by full access
            assert auth.validate_scopes(["https://www.googleapis.com/auth/gmail.readonly"]) is True
            assert auth.validate_scopes(["https://www.googleapis.com/auth/gmail.modify"]) is True
            assert auth.validate_scopes(["https://mail.google.com/"]) is True

    def test_validate_scopes_specific_scopes_check(self):
        """Test that specific scope checking works when full access not present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = GmailAuthenticator(validate_paths=False)

            # Mock credentials with specific scopes (no full access)
            mock_creds = Mock()
            mock_creds.scopes = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
            ]
            auth._creds = mock_creds

            # Should validate that required scopes are present
            assert auth.validate_scopes(["https://www.googleapis.com/auth/gmail.readonly"]) is True
            assert auth.validate_scopes(["https://www.googleapis.com/auth/gmail.modify"]) is True

            # Should fail for scopes not present
            assert auth.validate_scopes(["https://mail.google.com/"]) is False
