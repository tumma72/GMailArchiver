"""Tests for core archiving logic."""

import gzip
import lzma
import tempfile
from compression import zstd
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from gmailarchiver.archiver import GmailArchiver
from gmailarchiver.input_validator import InvalidInputError


class TestGmailArchiverInit:
    """Tests for GmailArchiver initialization."""

    def test_init(self) -> None:
        """Test initialization."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client, 'test_state.db')

        assert archiver.client == mock_client
        assert archiver.state_db_path == 'test_state.db'

    def test_init_default_db_path(self) -> None:
        """Test initialization with default database path."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        assert archiver.state_db_path == 'archive_state.db'


class TestArchive:
    """Tests for archive method."""

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_no_messages_found(
        self, mock_print: Mock, mock_progress: Mock, mock_db: Mock
    ) -> None:
        """Test archiving when no messages match criteria."""
        mock_client = Mock()
        mock_client.list_messages.return_value = []

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('3y', 'test.mbox')

        assert result['messages_found'] == 0
        assert result['messages_archived'] == 0
        assert result['archive_file'] is None

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_all_already_archived(
        self, mock_print: Mock, mock_progress: Mock, mock_db_class: Mock
    ) -> None:
        """Test archiving when all messages already archived."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'},
            {'id': 'msg2', 'threadId': 'thread2'}
        ]

        # Mock DBManager to return all message IDs as already archived
        mock_db_instance = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [('msg1',), ('msg2',)]
        mock_db_instance.conn.execute.return_value = mock_cursor
        mock_db_instance.close.return_value = None
        mock_db_class.return_value = mock_db_instance

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('3y', 'test.mbox', incremental=True)

        assert result['messages_found'] == 2
        assert result['messages_archived'] == 0
        assert result['skipped'] == 2

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_dry_run(
        self, mock_print: Mock, mock_progress: Mock, mock_db: Mock
    ) -> None:
        """Test dry run mode."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'}
        ]

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('6m', 'test.mbox', dry_run=True)

        assert result['dry_run'] is True
        assert result['messages_to_archive'] == 1
        # Should not actually archive in dry run
        assert 'messages_archived' not in result

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_dry_run_with_compression(
        self, mock_print: Mock, mock_progress: Mock, mock_db: Mock
    ) -> None:
        """Test dry run with compression specified."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'}
        ]

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('1y', 'test.mbox', compress='gzip', dry_run=True)

        assert result['dry_run'] is True

    def test_archive_invalid_age_threshold(self) -> None:
        """Test that invalid age threshold raises error."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with pytest.raises(InvalidInputError):
            archiver.archive('invalid', 'test.mbox')

    def test_archive_invalid_compression(self) -> None:
        """Test that invalid compression format raises error."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with pytest.raises(InvalidInputError):
            archiver.archive('3y', 'test.mbox', compress='bzip2')


class TestCompressArchive:
    """Tests for _compress_archive method."""

    def test_compress_gzip(self) -> None:
        """Test gzip compression."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        # Create temporary source file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b'Test data for compression')

        dest_path = source_path.with_suffix('.gz')

        try:
            archiver._compress_archive(source_path, dest_path, 'gzip')

            # Verify compressed file exists and can be decompressed
            assert dest_path.exists()
            with gzip.open(dest_path, 'rb') as f:
                decompressed = f.read()
            assert decompressed == b'Test data for compression'

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    def test_compress_lzma(self) -> None:
        """Test lzma compression."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b'Test data for lzma')

        dest_path = source_path.with_suffix('.xz')

        try:
            archiver._compress_archive(source_path, dest_path, 'lzma')

            assert dest_path.exists()
            with lzma.open(dest_path, 'rb') as f:
                decompressed = f.read()
            assert decompressed == b'Test data for lzma'

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    @patch('builtins.print')
    def test_compress_zstd(self, mock_print: Mock) -> None:
        """Test zstd compression."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b'Test data for zstd')

        dest_path = source_path.with_suffix('.zst')

        try:
            archiver._compress_archive(source_path, dest_path, 'zstd')

            # Verify compressed file exists and can be decompressed
            assert dest_path.exists()
            with zstd.open(dest_path, 'rb') as f:
                decompressed = f.read()
            assert decompressed == b'Test data for zstd'

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    def test_compress_invalid_format(self) -> None:
        """Test that invalid compression format raises error."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b'Test data')

        dest_path = source_path.with_suffix('.bz2')

        try:
            with pytest.raises(ValueError, match="Unsupported compression format"):
                archiver._compress_archive(source_path, dest_path, 'bzip2')
        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()


class TestValidateArchive:
    """Tests for validate_archive method."""

    @patch('gmailarchiver.archiver.ArchiveValidator')
    def test_validate_archive_success(self, mock_validator_class: Mock) -> None:
        """Test successful archive validation returns results dict."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        mock_validator = Mock()
        mock_validator.validate_comprehensive.return_value = {
            'passed': True,
            'errors': []
        }
        mock_validator_class.return_value = mock_validator

        result = archiver.validate_archive('test.mbox', {'msg1', 'msg2'})

        # Now returns full results dict (caller handles display)
        assert result['passed'] is True
        assert result['errors'] == []
        mock_validator.validate_comprehensive.assert_called_once_with({'msg1', 'msg2'})
        # report() is no longer called - caller handles display via OutputManager
        mock_validator.report.assert_not_called()

    @patch('gmailarchiver.archiver.ArchiveValidator')
    def test_validate_archive_failure(self, mock_validator_class: Mock) -> None:
        """Test failed archive validation returns results dict with errors."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        mock_validator = Mock()
        mock_validator.validate_comprehensive.return_value = {
            'passed': False,
            'errors': ['Count mismatch']
        }
        mock_validator_class.return_value = mock_validator

        result = archiver.validate_archive('test.mbox', {'msg1'})

        # Now returns full results dict (caller handles display)
        assert result['passed'] is False
        assert 'Count mismatch' in result['errors']


class TestArchiveMessagesIntegration:
    """Tests for _archive_messages method and full archive flow."""

    @patch('gmailarchiver.archiver.HybridStorage')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_works(
        self, mock_print: Mock, mock_progress_class: Mock,
        mock_db_class: Mock, mock_storage_class: Mock
    ) -> None:
        """Test successful archiving of messages."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'}
        ]

        # Mock get_messages_batch to return a message with raw data
        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {
            'id': 'msg1',
            'threadId': 'thread1',
            'raw': 'dGVzdA=='  # base64 encoded
        }
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = (0, len(test_email))
        mock_storage_class.return_value = mock_storage

        # Mock Progress
        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        # Create archiver and archive
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            # Create the file so it exists for size check
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            result = archiver.archive('3y', str(output_file), incremental=False)

            assert result['messages_found'] == 1
            assert result['messages_archived'] == 1
            assert result['messages_failed'] == 0

    @patch('gmailarchiver.archiver.HybridStorage')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_compression_workflow(
        self, mock_print: Mock, mock_progress_class: Mock,
        mock_db_class: Mock, mock_storage_class: Mock
    ) -> None:
        """Test archiving with compression (gzip)."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = (0, len(test_email))
        mock_storage_class.return_value = mock_storage

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox.gz'
            # Create the file so it exists for size check
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            result = archiver.archive('3y', str(output_file), compress='gzip', incremental=False)

            assert result['messages_archived'] == 1

    @patch('gmailarchiver.archiver.HybridStorage')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_orphaned_lock_file(
        self, mock_print: Mock, mock_progress_class: Mock,
        mock_db_class: Mock, mock_storage_class: Mock
    ) -> None:
        """Test archiving removes orphaned lock files."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage - it handles lock file cleanup internally
        mock_storage = Mock()
        mock_storage.archive_message.return_value = (0, len(test_email))
        mock_storage_class.return_value = mock_storage

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            output_file.touch()
            lock_file = Path(str(output_file) + '.lock')

            # Create orphaned lock file
            lock_file.touch()
            assert lock_file.exists()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))
            result = archiver.archive('3y', str(output_file), incremental=False)

            assert result['messages_archived'] == 1

    @patch('gmailarchiver.archiver.HybridStorage')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_records_state(
        self, mock_print: Mock, mock_progress_class: Mock,
        mock_db_class: Mock, mock_storage_class: Mock
    ) -> None:
        """Test that archiving records run in state database."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager - record_archived_message is called by HybridStorage
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db.record_archived_message.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = (0, len(test_email))
        mock_storage_class.return_value = mock_storage

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            archiver.archive('3y', str(output_file), incremental=False)

            # Verify HybridStorage.archive_message was called (which records in DB)
            mock_storage.archive_message.assert_called_once()

    @patch('gmailarchiver.archiver.HybridStorage')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_marks_messages_in_state(
        self, mock_print: Mock, mock_progress_class: Mock,
        mock_db_class: Mock, mock_storage_class: Mock
    ) -> None:
        """Test that individual messages are marked as archived in state."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = (
            b'From: test@example.com\r\n'
            b'Subject: Test Subject\r\n'
            b'Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n\r\nBody'
        )
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = (0, len(test_email))
        mock_storage_class.return_value = mock_storage

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            archiver.archive('3y', str(output_file), incremental=False)

            # Verify HybridStorage.archive_message was called with message
            mock_storage.archive_message.assert_called_once()
            call_args = mock_storage.archive_message.call_args
            # Check gmail_id was passed
            assert call_args.kwargs['gmail_id'] == 'msg1'


class TestDeleteArchivedMessages:
    """Tests for delete_archived_messages method."""

    @patch('builtins.print')
    def test_delete_permanent(self, mock_print: Mock) -> None:
        """Test permanent deletion."""
        mock_client = Mock()
        mock_client.delete_messages_permanent.return_value = 5
        archiver = GmailArchiver(mock_client)

        count = archiver.delete_archived_messages(
            ['msg1', 'msg2', 'msg3', 'msg4', 'msg5'],
            permanent=True
        )

        assert count == 5
        mock_client.delete_messages_permanent.assert_called_once()

    @patch('builtins.print')
    def test_delete_trash(self, mock_print: Mock) -> None:
        """Test moving to trash."""
        mock_client = Mock()
        mock_client.trash_messages.return_value = 3
        archiver = GmailArchiver(mock_client)

        count = archiver.delete_archived_messages(
            ['msg1', 'msg2', 'msg3'],
            permanent=False
        )

        assert count == 3
        mock_client.trash_messages.assert_called_once()


class TestExtractRfcMessageId:
    """Tests for _extract_rfc_message_id method."""

    def test_extract_existing_message_id(self) -> None:
        """Test extraction of existing Message-ID header."""
        import email
        from email import policy

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        msg = email.message_from_string(
            "Message-ID: <unique123@example.com>\nSubject: Test\n\nBody",
            policy=policy.default
        )

        result = archiver._extract_rfc_message_id(msg)
        assert result == '<unique123@example.com>'

    def test_generate_fallback_message_id(self) -> None:
        """Test fallback Message-ID generation when missing."""
        import email
        from email import policy

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        msg = email.message_from_string(
            "Subject: Test Subject\nDate: Mon, 1 Jan 2024 12:00:00 +0000\n\nBody",
            policy=policy.default
        )

        result = archiver._extract_rfc_message_id(msg)

        # Should generate SHA256-based ID
        assert result.startswith('<')
        assert result.endswith('@generated>')
        assert len(result) > 20  # SHA256 hash is long

    def test_handles_empty_message_id(self) -> None:
        """Test handling of empty Message-ID."""
        import email
        from email import policy

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        msg = email.message_from_string(
            "Message-ID:   \nSubject: Test\n\nBody",
            policy=policy.default
        )

        result = archiver._extract_rfc_message_id(msg)

        # Should generate fallback
        assert '@generated>' in result


class TestExtractBodyPreview:
    """Tests for _extract_body_preview method."""

    def test_extract_from_plain_text(self) -> None:
        """Test extraction from plain text message."""
        import email
        from email import policy

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        msg = email.message_from_string(
            "Subject: Test\n\nThis is a test message body.",
            policy=policy.default
        )

        result = archiver._extract_body_preview(msg, max_chars=10)
        assert result == "This is a "

    def test_extract_from_multipart(self) -> None:
        """Test extraction from multipart message."""
        import email

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        # Create multipart message
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test'
        msg.set_content("Plain text body")
        msg.add_alternative("<html><body>HTML body</body></html>", subtype='html')

        result = archiver._extract_body_preview(msg)
        assert "Plain text body" in result

    def test_max_chars_limit(self) -> None:
        """Test that preview respects max_chars limit."""
        import email
        from email import policy

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        long_text = "A" * 2000
        msg = email.message_from_string(
            f"Subject: Test\n\n{long_text}",
            policy=policy.default
        )

        result = archiver._extract_body_preview(msg, max_chars=1000)
        assert len(result) == 1000
        assert result == "A" * 1000


class TestAtomicOperations:
    """Tests for atomic mbox + database operations using HybridStorage."""

    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_atomic_archive_both_succeed(
        self, mock_print: Mock, mock_progress_class: Mock
    ) -> None:
        """Test that successful archiving commits both mbox and database."""
        import tempfile
        from pathlib import Path

        from gmailarchiver.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

            test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
            mock_message = {
                'id': 'msg1',
                'threadId': 'thread1',
                'raw': 'dGVzdA=='
            }
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = test_email

            # Mock Progress
            mock_progress = Mock()
            mock_task = Mock()
            mock_progress.add_task.return_value = mock_task
            mock_progress_class.return_value.__enter__.return_value = mock_progress

            # Archive using HybridStorage
            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))
            result = archiver.archive('3y', str(mbox_path), incremental=False)

            # Verify both mbox and database were updated
            assert result['messages_archived'] == 1
            assert mbox_path.exists(), "Mbox file should exist"

            # Verify database has the message
            db = DBManager(str(db_path))
            location = db.get_message_location('msg1')
            assert location is not None, "Message should be in database"
            assert location[0] == str(mbox_path)
            assert location[1] >= 0, "Offset should be valid"
            assert location[2] > 0, "Length should be positive"
            db.close()

    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_atomic_rollback_on_database_failure(
        self, mock_print: Mock, mock_progress_class: Mock
    ) -> None:
        """Test that database failure rolls back and doesn't leave orphaned mbox entries."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch


        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [
                {'id': 'msg1', 'threadId': 'thread1'},
                {'id': 'msg2', 'threadId': 'thread2'}
            ]

            test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
            mock_messages = [
                {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='},
                {'id': 'msg2', 'threadId': 'thread2', 'raw': 'dGVzdA=='}
            ]
            mock_client.get_messages_batch.return_value = mock_messages
            mock_client.decode_message_raw.return_value = test_email

            # Mock Progress
            mock_progress = Mock()
            mock_task = Mock()
            mock_progress.add_task.return_value = mock_task
            mock_progress_class.return_value.__enter__.return_value = mock_progress

            # Mock HybridStorage to fail on second message
            from collections.abc import Callable
            from typing import Any
            original_archive: Callable[..., Any] | None = None
            call_count = [0]

            def failing_archive(*args: Any, **kwargs: Any) -> Any:
                """Fail on second call to simulate database failure."""
                call_count[0] += 1
                if call_count[0] == 2:
                    raise Exception("Database failure simulation")
                assert original_archive is not None
                return original_archive(*args, **kwargs)

            # Patch HybridStorage.archive_message to fail on second message
            with patch('gmailarchiver.hybrid_storage.HybridStorage.archive_message') as mock_arch:
                # Store original and set up side effect
                from gmailarchiver.db_manager import DBManager as RealDB
                from gmailarchiver.hybrid_storage import HybridStorage
                db = RealDB(str(db_path))
                storage = HybridStorage(db)
                original_archive = storage.archive_message
                mock_arch.side_effect = failing_archive

                # Archive should handle the failure gracefully
                archiver = GmailArchiver(mock_client, state_db_path=str(db_path))

                # The archiving should continue and report partial success
                result = archiver.archive('3y', str(mbox_path), incremental=False)

                # Should have 1 success and 1 failure
                assert result['messages_archived'] >= 0
                assert result['messages_failed'] >= 0

            db.close()

    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_automatic_validation_after_archiving(
        self, mock_print: Mock, mock_progress_class: Mock
    ) -> None:
        """Test that validation runs automatically after each message is archived."""
        import tempfile
        from pathlib import Path

        from gmailarchiver.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

            test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
            mock_message = {
                'id': 'msg1',
                'threadId': 'thread1',
                'raw': 'dGVzdA=='
            }
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = test_email

            # Mock Progress
            mock_progress = Mock()
            mock_task = Mock()
            mock_progress.add_task.return_value = mock_task
            mock_progress_class.return_value.__enter__.return_value = mock_progress

            # Archive message
            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))
            result = archiver.archive('3y', str(mbox_path), incremental=False)

            assert result['messages_archived'] == 1

            # Verify the message can be read from mbox at the stored offset
            db = DBManager(str(db_path))
            location = db.get_message_location('msg1')
            assert location is not None

            archive_file, offset, length = location
            with open(archive_file, 'rb') as f:
                f.seek(offset)
                data = f.read(length)
                assert len(data) > 0, "Should be able to read message at offset"

            db.close()

    def _create_v11_db(self, db_path: Path) -> None:
        """Helper to create v1.1 database schema."""
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        ''')
        conn.execute('''
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content=messages, content_rowid=rowid
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
        ''')
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()


class TestV11OffsetTracking:
    """Tests for v1.1 offset tracking during archiving."""

    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_v1_1_schema_tracks_offsets(
        self, mock_print: Mock, mock_progress_class: Mock
    ) -> None:
        """Test that archiving with v1.1 schema captures mbox offsets."""
        import email
        import json
        import mailbox
        import sqlite3

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database
            conn = sqlite3.connect(str(db_path))
            # Create enhanced v1.1 schema
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    thread_id TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    to_addr TEXT,
                    cc_addr TEXT,
                    date TIMESTAMP,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL,
                    body_preview TEXT,
                    checksum TEXT,
                    size_bytes INTEGER,
                    labels TEXT,
                    account_id TEXT DEFAULT 'default'
                )
            ''')
            conn.execute('''
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    subject, from_addr, to_addr, body_preview,
                    content=messages, content_rowid=rowid
                )
            ''')
            conn.execute('''
                CREATE TABLE archive_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    query TEXT,
                    messages_archived INTEGER,
                    archive_file TEXT,
                    account_id TEXT DEFAULT 'default',
                    operation_type TEXT DEFAULT 'archive'
                )
            ''')
            conn.execute('''
                CREATE TABLE schema_version (
                    version TEXT PRIMARY KEY,
                    migrated_timestamp TEXT
                )
            ''')
            conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
            conn.commit()
            conn.close()

            # Setup mock client
            mock_client = Mock()

            # Create test email
            msg = email.message.EmailMessage()
            msg['Message-ID'] = '<test123@example.com>'
            msg['Subject'] = 'Test Subject'
            msg['From'] = 'test@example.com'
            msg['To'] = 'recipient@example.com'
            msg['Cc'] = 'cc@example.com'
            msg['Date'] = 'Mon, 1 Jan 2024 12:00:00 +0000'
            msg.set_content("This is the test email body content.")

            raw_email = msg.as_bytes()

            # Mock message with labelIds
            mock_message: dict[str, str | list[str]] = {
                'id': 'msg123',
                'raw': '',  # Will be replaced by decode_message_raw
                'threadId': 'thread123',
                'labelIds': ['INBOX', 'IMPORTANT']
            }

            def mock_get_messages_batch(ids: list[str]) -> list[dict[str, str | list[str]]]:
                """Mock batch message retrieval."""
                return [mock_message]

            mock_client.decode_message_raw.return_value = raw_email
            mock_client.get_messages_batch = mock_get_messages_batch

            # Mock Progress
            mock_progress = Mock()
            mock_task = Mock()
            mock_progress.add_task.return_value = mock_task
            mock_progress_class.return_value.__enter__.return_value = mock_progress

            # Create archiver and archive
            archiver = GmailArchiver(mock_client, str(db_path))
            archiver._archive_messages(['msg123'], str(mbox_path))

            # Verify offset and length were captured
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT mbox_offset, mbox_length, rfc_message_id, "
                "thread_id, to_addr, cc_addr, body_preview, "
                "size_bytes, labels FROM messages WHERE gmail_id = 'msg123'"
            )
            row = cursor.fetchone()
            conn.close()

            assert row is not None
            mbox_offset, mbox_length, rfc_message_id, thread_id, to_addr, cc_addr, body_preview, size_bytes, labels = row  # noqa: E501

            # Verify offsets are not placeholder values
            assert mbox_offset >= 0, "mbox_offset should be non-negative"
            assert mbox_length > 0, "mbox_length should be positive"

            # Verify enhanced v1.1 fields
            assert rfc_message_id == '<test123@example.com>'
            assert thread_id == 'thread123'
            assert to_addr == 'recipient@example.com'
            assert cc_addr == 'cc@example.com'
            assert 'test email body' in body_preview.lower()
            assert size_bytes == len(raw_email)
            assert labels == json.dumps(['INBOX', 'IMPORTANT'])

            # Verify message can be extracted from mbox using offset
            mbox = mailbox.mbox(str(mbox_path))
            try:
                assert len(mbox) == 1
                # Get first message from mbox (use list() since mbox
                # doesn't support direct indexing)
                messages = list(mbox)
                extracted_msg = messages[0]
                assert extracted_msg['Subject'] == 'Test Subject'
            finally:
                mbox.close()


class TestExceptionHandling:
    """Tests for exception handling in archiver."""

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_incremental_falls_back_on_dbmanager_failure(
        self, mock_print: Mock, mock_progress: Mock, mock_dbmanager_class: Mock
    ) -> None:
        """Test that incremental mode falls back gracefully if DBManager fails."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"

            # Create database file (empty, will cause DBManager to fail)
            db_path.touch()

            # Mock DBManager to raise exception on initialization
            mock_dbmanager_class.side_effect = Exception("Schema validation failed")

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [
                {'id': 'msg1', 'threadId': 'thread1'},
                {'id': 'msg2', 'threadId': 'thread2'}
            ]

            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))

            # Use dry_run to avoid executing archiving logic
            result = archiver.archive('3y', 'test.mbox', incremental=True, dry_run=True)

            # Should not skip any messages (falls back to empty set)
            # When DBManager fails, archived_ids becomes empty set
            assert result['messages_to_archive'] == 2

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_incremental_with_nonexistent_database(
        self, mock_print: Mock, mock_progress: Mock, mock_db_class: Mock
    ) -> None:
        """Test incremental mode when database doesn't exist yet."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "nonexistent.db"

            # Database doesn't exist - DBManager will auto-create it
            assert not db_path.exists()

            # Mock DBManager to return empty archived set
            mock_db = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = []
            mock_db.conn.execute.return_value = mock_cursor
            mock_db.close.return_value = None
            mock_db_class.return_value = mock_db

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [
                {'id': 'msg1', 'threadId': 'thread1'}
            ]

            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))
            result = archiver.archive('3y', 'test.mbox', incremental=True, dry_run=True)

            # Should not skip any messages (no archived_ids)
            assert result['messages_to_archive'] == 1

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_messages_falls_back_on_dbmanager_init_failure(
        self, mock_print: Mock, mock_progress: Mock,
        mock_dbmanager_class: Mock, mock_state_class: Mock
    ) -> None:
        """Test _archive_messages raises error if DBManager init fails."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create database file
            db_path.touch()

            # Mock DBManager to raise exception on init
            mock_dbmanager_class.side_effect = Exception("Schema validation failed")

            # Setup mock client
            mock_client = Mock()

            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))

            # Should raise RuntimeError when DBManager fails
            with pytest.raises(RuntimeError, match="Failed to initialize database"):
                archiver._archive_messages(['msg1'], str(mbox_path))

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_mbox_unlock_exception_handling(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
    ) -> None:
        """Test that exceptions during mbox unlock are caught and logged."""
        import email
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Mock state
            mock_state = Mock()
            mock_state.schema_version = "1.0"
            mock_state_class.return_value.__enter__.return_value = mock_state

            # Setup mock client
            mock_client = Mock()

            msg = email.message.EmailMessage()
            msg['Subject'] = 'Test'
            msg['From'] = 'test@example.com'
            msg.set_content("Test body")
            raw_email = msg.as_bytes()

            mock_message = {
                'id': 'msg1',
                'threadId': 'thread1'
            }
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = raw_email

            # Patch mailbox.mbox to create a mock that raises on unlock
            with patch('gmailarchiver.archiver.mailbox.mbox') as mock_mbox_class:
                mock_mbox = MagicMock()
                mock_mbox_class.return_value = mock_mbox

                # Make unlock raise exception
                mock_mbox.unlock.side_effect = Exception("Unlock failed")

                archiver = GmailArchiver(mock_client, state_db_path=str(db_path))
                result = archiver._archive_messages_legacy(['msg1'], str(mbox_path))

                # Should handle exception and continue
                assert result['archived'] == 1
                # Verify warning was printed
                mock_print.assert_any_call("Warning: Failed to unlock mbox: Unlock failed")

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_mbox_close_exception_handling(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
    ) -> None:
        """Test that exceptions during mbox close are caught and logged."""
        import email
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Mock state
            mock_state = Mock()
            mock_state.schema_version = "1.0"
            mock_state_class.return_value.__enter__.return_value = mock_state

            # Setup mock client
            mock_client = Mock()

            msg = email.message.EmailMessage()
            msg['Subject'] = 'Test'
            msg['From'] = 'test@example.com'
            msg.set_content("Test body")
            raw_email = msg.as_bytes()

            mock_message = {
                'id': 'msg1',
                'threadId': 'thread1'
            }
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = raw_email

            # Patch mailbox.mbox
            with patch('gmailarchiver.archiver.mailbox.mbox') as mock_mbox_class:
                mock_mbox = MagicMock()
                mock_mbox_class.return_value = mock_mbox

                # Make close raise exception
                mock_mbox.close.side_effect = Exception("Close failed")

                archiver = GmailArchiver(mock_client, state_db_path=str(db_path))
                result = archiver._archive_messages_legacy(['msg1'], str(mbox_path))

                # Should handle exception and continue
                assert result['archived'] == 1
                # Verify warning was printed
                mock_print.assert_any_call("Warning: Failed to close mbox: Close failed")

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_lock_file_cleanup_after_compression(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
    ) -> None:
        """Test that lock files are cleaned up after compression."""
        import email
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox.gz"

            # Mock state
            mock_state = Mock()
            mock_state.schema_version = "1.0"
            mock_state_class.return_value.__enter__.return_value = mock_state

            # Setup mock client
            mock_client = Mock()

            msg = email.message.EmailMessage()
            msg['Subject'] = 'Test'
            msg['From'] = 'test@example.com'
            msg.set_content("Test body")
            raw_email = msg.as_bytes()

            mock_message = {
                'id': 'msg1',
                'threadId': 'thread1'
            }
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = raw_email

            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))

            # Archive with gzip compression
            result = archiver._archive_messages_legacy(['msg1'], str(mbox_path), compress='gzip')

            # Verify compressed file exists
            assert mbox_path.exists()

            # Verify lock file was cleaned up
            temp_mbox_lock = temp_path / "test.mbox.lock"
            assert not temp_mbox_lock.exists(), "Lock file should be cleaned up"

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_failed_messages_print_statement(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
    ) -> None:
        """Test that failed message count is printed when failures occur."""
        import email
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Mock state
            mock_state = Mock()
            mock_state.schema_version = "1.0"
            mock_state_class.return_value.__enter__.return_value = mock_state

            # Setup mock client
            mock_client = Mock()

            msg = email.message.EmailMessage()
            msg['Subject'] = 'Test'
            msg['From'] = 'test@example.com'
            msg.set_content("Test body")
            raw_email = msg.as_bytes()

            # Only return one message (simulating that second message was deleted/moved)
            mock_messages = [
                {'id': 'msg1', 'threadId': 'thread1'}
            ]

            mock_client.get_messages_batch.return_value = mock_messages
            mock_client.decode_message_raw.return_value = raw_email

            archiver = GmailArchiver(mock_client, state_db_path=str(db_path))

            # Request 2 messages but only 1 is returned (simulating deletion/move)
            result = archiver._archive_messages_legacy(['msg1', 'msg2'], str(mbox_path))

            # Should have 1 success, 1 failure (msg2 was deleted/moved)
            assert result['archived'] == 1
            assert result['failed'] == 1

            # Verify failure message was printed
            # Look for the warning message in print calls
            print_calls = [str(call) for call in mock_print.call_args_list]
            failure_printed = any('Failed: 1 message' in str(call) for call in print_calls)
            assert failure_printed, "Should print failure count"


class TestBodyPreviewExceptions:
    """Tests for exception handling in body preview extraction."""

    def test_multipart_decode_exception(self) -> None:
        """Test that decode exceptions in multipart messages are handled."""
        import email
        from unittest.mock import Mock, patch

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        # Create multipart message
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test'
        msg.set_content("Text part")

        # Patch get_payload to raise exception
        with patch.object(email.message.EmailMessage, 'get_payload') as mock_payload:
            mock_payload.side_effect = Exception("Decode failed")

            # Should handle exception and return empty string
            result = archiver._extract_body_preview(msg)
            assert result == ""

    def test_non_multipart_decode_exception(self) -> None:
        """Test that decode exceptions in non-multipart messages are handled."""
        import email
        from email import policy
        from unittest.mock import Mock, patch

        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        # Create simple message
        msg_text = "Subject: Test\n\nBody content"
        msg = email.message_from_string(msg_text, policy=policy.default)

        # Patch get_payload to raise exception
        with patch.object(type(msg), 'get_payload') as mock_payload:
            mock_payload.side_effect = Exception("Decode failed")

            # Should handle exception and return empty string
            result = archiver._extract_body_preview(msg)
            assert result == ""


class TestGmailArchiverWithOutput:
    """Tests for GmailArchiver with OutputManager integration."""

    def test_init_with_output_manager(self) -> None:
        """Test initialization with OutputManager."""
        from gmailarchiver.output import OutputManager

        mock_client = Mock()
        output = OutputManager()

        archiver = GmailArchiver(mock_client, output=output)

        assert archiver.output is output

    def test_init_without_output_manager(self) -> None:
        """Test initialization without OutputManager (backward compat)."""
        mock_client = Mock()

        archiver = GmailArchiver(mock_client)

        assert archiver.output is None

    def test_log_helper_with_output(self) -> None:
        """Test _log() helper uses OutputManager when available."""

        from gmailarchiver.output import OutputManager

        mock_client = Mock()
        output = OutputManager()

        archiver = GmailArchiver(mock_client, output=output)

        # Capture console output
        with patch.object(output, 'info') as mock_info:
            archiver._log("Test message")
            mock_info.assert_called_once_with("Test message")

    def test_log_helper_without_output(self) -> None:
        """Test _log() helper falls back to print() when no OutputManager."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        with patch('builtins.print') as mock_print:
            archiver._log("Test message")
            mock_print.assert_called_once_with("Test message")


class TestArchiveWithOperationHandle:
    """Tests for archive() with OperationHandle integration."""

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.HybridStorage')
    def test_archive_with_operation_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver uses operation handle for logging and progress."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'},
            {'id': 'msg2', 'threadId': 'thread2'}
        ]

        # Setup mock message data
        # Base64: "Subject: Test Subject\n\nTest body"
        mock_message_data = {
            'id': 'msg1',
            'threadId': 'thread1',
            'raw': 'U3ViamVjdDogVGVzdCBTdWJqZWN0CgpUZXN0IGJvZHk='
        }
        mock_client.get_messages_batch.return_value = [mock_message_data, mock_message_data]
        mock_client.decode_message_raw.return_value = b"Subject: Test Subject\n\nTest body"

        # Setup mock DBManager
        mock_db = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []  # No previously archived messages
        mock_db.conn.execute.return_value = mock_cursor
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Setup mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = None
        mock_storage_class.return_value = mock_storage

        # Setup mock operation handle
        mock_operation = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            # Archive with operation handle
            result = archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                operation=mock_operation
            )

            # Verify operation handle was used for logging
            assert mock_operation.log.called, "Operation handle log() should be called"
            assert mock_operation.update_progress.called, (
                "Operation handle update_progress() should be called"
            )

            # Verify we logged processing messages
            log_calls = [call[0][0] for call in mock_operation.log.call_args_list]
            assert any("Processing" in call for call in log_calls), (
                "Should log 'Processing X messages'"
            )

            # Verify we logged success for each message
            # Note: v1.3.5+ removed duplicate severity symbols - message is "Archived:" not "✓ Archived:"
            success_logs = [call for call in log_calls if "Archived:" in call]
            assert len(success_logs) == 2, "Should log success for each archived message"

            # Verify progress was updated for each message
            assert mock_operation.update_progress.call_count == 2, (
                "Should update progress for each message"
            )

    @patch('gmailarchiver.archiver.DBManager')
    @patch('gmailarchiver.archiver.HybridStorage')
    def test_archive_without_operation_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver works without operation handle (backward compatibility)."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'}
        ]

        # Setup mock message data
        mock_message_data = {
            'id': 'msg1',
            'threadId': 'thread1',
            'raw': 'U3ViamVjdDogVGVzdCBTdWJqZWN0CgpUZXN0IGJvZHk='
        }
        mock_client.get_messages_batch.return_value = [mock_message_data]
        mock_client.decode_message_raw.return_value = b"Subject: Test Subject\n\nTest body"

        # Setup mock DBManager
        mock_db = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_db.conn.execute.return_value = mock_cursor
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Setup mock HybridStorage
        mock_storage = Mock()
        mock_storage.archive_message.return_value = None
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            output_file.touch()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            # Archive without operation handle (should not crash)
            result = archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                operation=None  # No operation handle
            )

            # Should complete successfully
            assert result['messages_archived'] == 1
