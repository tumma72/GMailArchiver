"""Test that no print() statements bypass OutputManager.

This test suite ensures all user-facing output goes through OutputManager
for consistency and JSON output support.
"""

import builtins
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.archiver import GmailArchiver
from gmailarchiver.auth import GmailAuthenticator
from gmailarchiver.output import OutputManager
from gmailarchiver.validator import ArchiveValidator


class TestNoPrintStatements:
    """Test that modules don't use bare print() statements."""

    def test_auth_uses_output_manager_not_print(self) -> None:
        """Test that GmailAuthenticator uses OutputManager instead of print()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            token_file = temp_path / "token.json"

            # Create a corrupt token file to trigger error path
            token_file.write_text("{invalid json")

            # Create credentials file for OAuth flow
            creds_file = temp_path / "credentials.json"
            creds_data = {
                'installed': {
                    'client_id': 'test',
                    'client_secret': 'test',
                    'auth_uri': 'https://test',
                    'token_uri': 'https://test'
                }
            }
            import json
            creds_file.write_text(json.dumps(creds_data))

            # Mock the OAuth flow
            with patch('gmailarchiver.auth.InstalledAppFlow') as MockFlow:
                mock_flow = Mock()
                mock_cred = Mock()
                mock_cred.valid = True
                mock_cred.to_json.return_value = json.dumps({})
                mock_flow.run_local_server.return_value = mock_cred
                MockFlow.from_client_secrets_file.return_value = mock_flow

                # Patch print to detect if it's called
                with patch('builtins.print') as mock_print:
                    output = OutputManager()
                    auth = GmailAuthenticator(
                        credentials_file=str(creds_file),
                        token_file=str(token_file),
                        validate_paths=False,
                        output=output
                    )
                    auth.authenticate()

                    # print() should NOT be called - all output through OutputManager
                    assert not mock_print.called, \
                        f"print() was called {mock_print.call_count} times in auth.py"

    def test_archiver_uses_output_manager_not_print(self) -> None:
        """Test that GmailArchiver uses OutputManager instead of print()."""
        mock_client = Mock()
        mock_client.delete_messages_permanent.return_value = 5

        output = OutputManager()
        archiver = GmailArchiver(mock_client, output=output)

        # Patch print to detect if it's called
        with patch('builtins.print') as mock_print:
            archiver.delete_archived_messages(['msg1'], permanent=True)

            # print() should NOT be called - all output through OutputManager
            assert not mock_print.called, \
                f"print() was called {mock_print.call_count} times in archiver.py"

    def test_archiver_compression_uses_output_manager(self) -> None:
        """Test that compression messages use OutputManager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            source = temp_path / "test.mbox"
            dest = temp_path / "test.mbox.gz"
            source.write_bytes(b"test data")

            mock_client = Mock()
            output = OutputManager()
            archiver = GmailArchiver(mock_client, output=output)

            # Patch print to detect if it's called
            with patch('builtins.print') as mock_print:
                archiver._compress_archive(source, dest, 'gzip')

                # print() should NOT be called
                assert not mock_print.called, \
                    f"print() was called during compression in archiver.py"

    def test_validator_uses_output_manager_not_print(self) -> None:
        """Test that ArchiveValidator uses OutputManager instead of print()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            output = OutputManager()
            validator = ArchiveValidator(str(mbox_path), output=output)

            results = {
                'count_check': True,
                'database_check': True,
                'integrity_check': True,
                'spot_check': True,
                'errors': [],
                'passed': True
            }

            # Patch print to detect if it's called
            with patch('builtins.print') as mock_print:
                validator.report(results)

                # print() should NOT be called - all output through OutputManager
                assert not mock_print.called, \
                    f"print() was called {mock_print.call_count} times in validator.py"


class TestBackwardCompatibility:
    """Test backward compatibility when OutputManager is not provided."""

    def test_archiver_falls_back_to_print(self) -> None:
        """Test that archiver falls back to print() when no OutputManager."""
        mock_client = Mock()
        mock_client.delete_messages_permanent.return_value = 5

        # No OutputManager provided (backward compat)
        archiver = GmailArchiver(mock_client)

        # Should use print() as fallback
        with patch('builtins.print') as mock_print:
            archiver.delete_archived_messages(['msg1'], permanent=True)

            # print() SHOULD be called as fallback
            assert mock_print.called, \
                "print() should be called as fallback when no OutputManager"

    def test_validator_falls_back_to_print(self) -> None:
        """Test that validator falls back to print() when no OutputManager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            # No OutputManager provided (backward compat)
            validator = ArchiveValidator(str(mbox_path))

            results = {
                'count_check': True,
                'database_check': True,
                'integrity_check': True,
                'spot_check': True,
                'errors': [],
                'passed': True
            }

            # Should use print() as fallback
            with patch('builtins.print') as mock_print:
                validator.report(results)

                # print() SHOULD be called as fallback
                assert mock_print.called, \
                    "print() should be called as fallback when no OutputManager"
