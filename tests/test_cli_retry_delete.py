"""Tests for retry-delete CLI command."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
from gmailarchiver.state import ArchiveState

runner = CliRunner()


@pytest.fixture
def temp_state_db():
    """Create a temporary state database with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_state.db'

        # Create database with archived messages
        with ArchiveState(str(db_path), validate_path=False) as state:
            # Add test messages
            archive_file = 'archive_20251114.mbox'
            for i in range(5):
                state.mark_archived(
                    gmail_id=f'msg_{i}',
                    archive_file=archive_file,
                    subject=f'Test Subject {i}',
                    from_addr='test@example.com',
                    message_date='2025-01-01'
                )

        yield str(db_path), archive_file


class TestRetryDeleteCommand:
    """Tests for retry-delete command."""

    def test_retry_delete_success(self, temp_state_db):
        """Test successful retry deletion of archived messages."""
        db_path, archive_file = temp_state_db

        with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth, \
             patch('gmailarchiver.__main__.GmailClient') as MockClient, \
             patch('gmailarchiver.__main__.GmailArchiver') as MockArchiver:

            # Mock authenticator with valid scopes
            mock_auth = Mock()
            mock_creds = Mock()
            mock_auth.authenticate.return_value = mock_creds
            mock_auth.validate_scopes.return_value = True
            MockAuth.return_value = mock_auth

            # Mock client
            mock_client = Mock()
            MockClient.return_value = mock_client

            # Mock archiver
            mock_archiver = Mock()
            MockArchiver.return_value = mock_archiver

            # Run command (trash, not permanent)
            result = runner.invoke(app, [
                'retry-delete',
                archive_file,
                '--state-db', db_path
            ])

            assert result.exit_code == 0
            mock_auth.authenticate.assert_called_once()
            mock_auth.validate_scopes.assert_called_once_with(['https://mail.google.com/'])
            mock_archiver.delete_archived_messages.assert_called_once()

    def test_retry_delete_missing_file(self, temp_state_db):
        """Test error when archive file not in database."""
        db_path, _ = temp_state_db

        result = runner.invoke(app, [
            'retry-delete',
            'nonexistent_archive.mbox',
            '--state-db', db_path
        ])

        assert result.exit_code == 1
        assert 'No archived messages found' in result.stdout

    def test_retry_delete_missing_scope(self, temp_state_db):
        """Test error when credentials lack deletion permission."""
        db_path, archive_file = temp_state_db

        with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth:
            # Mock authenticator with insufficient scopes
            mock_auth = Mock()
            mock_creds = Mock()
            mock_auth.authenticate.return_value = mock_creds
            mock_auth.validate_scopes.return_value = False  # Missing deletion scope
            MockAuth.return_value = mock_auth

            result = runner.invoke(app, [
                'retry-delete',
                archive_file,
                '--state-db', db_path
            ])

            assert result.exit_code == 1
            assert 'Missing deletion permission' in result.stdout
            assert 'auth-reset' in result.stdout

    def test_retry_delete_with_confirmation_success(self, temp_state_db):
        """Test permanent deletion with correct confirmation."""
        db_path, archive_file = temp_state_db

        with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth, \
             patch('gmailarchiver.__main__.GmailClient') as MockClient, \
             patch('gmailarchiver.__main__.GmailArchiver') as MockArchiver:

            # Mock authenticator
            mock_auth = Mock()
            mock_creds = Mock()
            mock_auth.authenticate.return_value = mock_creds
            mock_auth.validate_scopes.return_value = True
            MockAuth.return_value = mock_auth

            # Mock client
            mock_client = Mock()
            MockClient.return_value = mock_client

            # Mock archiver
            mock_archiver = Mock()
            MockArchiver.return_value = mock_archiver

            # Provide correct confirmation
            result = runner.invoke(app, [
                'retry-delete',
                archive_file,
                '--permanent',
                '--state-db', db_path
            ], input='DELETE 5 MESSAGES\n')

            assert result.exit_code == 0
            mock_archiver.delete_archived_messages.assert_called_once()
            # Verify permanent=True was passed
            call_args = mock_archiver.delete_archived_messages.call_args
            assert call_args[1]['permanent'] is True

    def test_retry_delete_with_confirmation_cancelled(self, temp_state_db):
        """Test permanent deletion cancelled with wrong confirmation."""
        db_path, archive_file = temp_state_db

        with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth:
            # Mock authenticator
            mock_auth = Mock()
            mock_creds = Mock()
            mock_auth.authenticate.return_value = mock_creds
            mock_auth.validate_scopes.return_value = True
            MockAuth.return_value = mock_auth

            # Provide wrong confirmation
            result = runner.invoke(app, [
                'retry-delete',
                archive_file,
                '--permanent',
                '--state-db', db_path
            ], input='wrong confirmation\n')

            assert result.exit_code == 0
            assert 'cancelled' in result.stdout.lower()

    def test_retry_delete_without_permanent_flag(self, temp_state_db):
        """Test that default behavior is trash (not permanent deletion)."""
        db_path, archive_file = temp_state_db

        with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth, \
             patch('gmailarchiver.__main__.GmailClient') as MockClient, \
             patch('gmailarchiver.__main__.GmailArchiver') as MockArchiver:

            # Mock authenticator
            mock_auth = Mock()
            mock_creds = Mock()
            mock_auth.authenticate.return_value = mock_creds
            mock_auth.validate_scopes.return_value = True
            MockAuth.return_value = mock_auth

            # Mock client
            mock_client = Mock()
            MockClient.return_value = mock_client

            # Mock archiver
            mock_archiver = Mock()
            MockArchiver.return_value = mock_archiver

            # Run without --permanent flag
            result = runner.invoke(app, [
                'retry-delete',
                archive_file,
                '--state-db', db_path
            ])

            assert result.exit_code == 0
            mock_archiver.delete_archived_messages.assert_called_once()
            # Verify permanent=False was passed (default)
            call_args = mock_archiver.delete_archived_messages.call_args
            assert call_args[1]['permanent'] is False


class TestRetryDeleteIntegration:
    """Integration tests for retry-delete with real state database."""

    def test_retry_delete_retrieves_correct_message_ids(self):
        """Test that retry-delete retrieves the correct message IDs from database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test_state.db'
            archive_file = 'archive_test.mbox'

            # Create database with messages
            expected_ids = [f'msg_{i}' for i in range(3)]
            with ArchiveState(str(db_path), validate_path=False) as state:
                for msg_id in expected_ids:
                    state.mark_archived(
                        gmail_id=msg_id,
                        archive_file=archive_file,
                        subject='Test',
                        from_addr='test@example.com',
                        message_date='2025-01-01'
                    )

            with patch('gmailarchiver.__main__.GmailAuthenticator') as MockAuth, \
                 patch('gmailarchiver.__main__.GmailClient') as MockClient, \
                 patch('gmailarchiver.__main__.GmailArchiver') as MockArchiver:

                mock_auth = Mock()
                mock_creds = Mock()
                mock_auth.authenticate.return_value = mock_creds
                mock_auth.validate_scopes.return_value = True
                MockAuth.return_value = mock_auth

                mock_client = Mock()
                MockClient.return_value = mock_client

                mock_archiver = Mock()
                MockArchiver.return_value = mock_archiver

                result = runner.invoke(app, [
                    'retry-delete',
                    archive_file,
                    '--state-db', str(db_path)
                ])

                assert result.exit_code == 0
                # Verify correct message IDs were passed
                call_args = mock_archiver.delete_archived_messages.call_args
                actual_ids = call_args[0][0]
                assert set(actual_ids) == set(expected_ids)
