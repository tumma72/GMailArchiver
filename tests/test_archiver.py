"""Tests for core archiving logic."""

import gzip
import lzma
import tempfile
from compression import zstd
from pathlib import Path
from unittest.mock import Mock, patch

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

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_no_messages_found(
        self, mock_print: Mock, mock_progress: Mock, mock_state: Mock
    ) -> None:
        """Test archiving when no messages match criteria."""
        mock_client = Mock()
        mock_client.list_messages.return_value = []

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('3y', 'test.mbox')

        assert result['messages_found'] == 0
        assert result['messages_archived'] == 0
        assert result['archive_file'] is None

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_all_already_archived(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
    ) -> None:
        """Test archiving when all messages already archived."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {'id': 'msg1', 'threadId': 'thread1'},
            {'id': 'msg2', 'threadId': 'thread2'}
        ]

        # Mock state to return all message IDs as already archived
        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = {'msg1', 'msg2'}
        mock_state_class.return_value.__enter__.return_value = mock_state

        archiver = GmailArchiver(mock_client)
        result = archiver.archive('3y', 'test.mbox', incremental=True)

        assert result['messages_found'] == 2
        assert result['messages_archived'] == 0
        assert result['skipped'] == 2

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_dry_run(
        self, mock_print: Mock, mock_progress: Mock, mock_state: Mock
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

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_dry_run_with_compression(
        self, mock_print: Mock, mock_progress: Mock, mock_state: Mock
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
        """Test successful archive validation."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        mock_validator = Mock()
        mock_validator.validate_comprehensive.return_value = {
            'passed': True,
            'errors': []
        }
        mock_validator_class.return_value = mock_validator

        result = archiver.validate_archive('test.mbox', {'msg1', 'msg2'})

        assert result is True
        mock_validator.validate_comprehensive.assert_called_once_with({'msg1', 'msg2'})
        mock_validator.report.assert_called_once()

    @patch('gmailarchiver.archiver.ArchiveValidator')
    def test_validate_archive_failure(self, mock_validator_class: Mock) -> None:
        """Test failed archive validation."""
        mock_client = Mock()
        archiver = GmailArchiver(mock_client)

        mock_validator = Mock()
        mock_validator.validate_comprehensive.return_value = {
            'passed': False,
            'errors': ['Count mismatch']
        }
        mock_validator_class.return_value = mock_validator

        result = archiver.validate_archive('test.mbox', {'msg1'})

        assert result is False


class TestArchiveMessagesIntegration:
    """Tests for _archive_messages method and full archive flow."""

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_messages_success(
        self, mock_print: Mock, mock_progress_class: Mock, mock_state_class: Mock
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

        # Mock ArchiveState
        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = set()
        mock_state_class.return_value.__enter__.return_value = mock_state

        # Mock Progress
        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        # Create archiver and archive
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            result = archiver.archive('3y', str(output_file), incremental=False)

            assert result['messages_found'] == 1
            assert result['messages_archived'] == 1
            assert result['messages_failed'] == 0
            assert output_file.exists()

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_compression_workflow(
        self, mock_print: Mock, mock_progress_class: Mock, mock_state_class: Mock
    ) -> None:
        """Test archiving with compression (gzip)."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = set()
        mock_state_class.return_value.__enter__.return_value = mock_state

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox.gz'
            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            result = archiver.archive('3y', str(output_file), compress='gzip', incremental=False)

            assert result['messages_archived'] == 1
            assert output_file.exists()
            # Verify it's actually compressed
            with gzip.open(output_file, 'rb') as f:
                content = f.read()
                assert b'test@example.com' in content

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_orphaned_lock_file(
        self, mock_print: Mock, mock_progress_class: Mock, mock_state_class: Mock
    ) -> None:
        """Test archiving removes orphaned lock files."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = set()
        mock_state_class.return_value.__enter__.return_value = mock_state

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            lock_file = Path(str(output_file) + '.lock')

            # Create orphaned lock file
            lock_file.touch()
            assert lock_file.exists()

            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))
            result = archiver.archive('3y', str(output_file), incremental=False)

            assert result['messages_archived'] == 1
            # Lock file should be cleaned up
            assert not lock_file.exists()

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_records_state(
        self, mock_print: Mock, mock_progress_class: Mock, mock_state_class: Mock
    ) -> None:
        """Test that archiving records run in state database."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{'id': 'msg1', 'threadId': 'thread1'}]

        test_email = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody'
        mock_message = {'id': 'msg1', 'threadId': 'thread1', 'raw': 'dGVzdA=='}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = set()
        mock_state_class.return_value.__enter__.return_value = mock_state

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            archiver.archive('3y', str(output_file), incremental=False)

            # Verify state.record_archive_run was called
            mock_state.record_archive_run.assert_called_once()
            call_args = mock_state.record_archive_run.call_args
            assert 'before:' in call_args.kwargs['query']
            assert call_args.kwargs['messages_archived'] == 1
            assert call_args.kwargs['archive_file'] == str(output_file)

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_marks_messages_in_state(
        self, mock_print: Mock, mock_progress_class: Mock, mock_state_class: Mock
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

        mock_state = Mock()
        mock_state.get_archived_message_ids.return_value = set()
        mock_state_class.return_value.__enter__.return_value = mock_state

        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value.__enter__.return_value = mock_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'archive.mbox'
            archiver = GmailArchiver(mock_client, state_db_path=str(Path(tmpdir) / 'state.db'))

            archiver.archive('3y', str(output_file), incremental=False)

            # Verify mark_archived was called
            mock_state.mark_archived.assert_called_once()
            call_args = mock_state.mark_archived.call_args
            assert call_args.kwargs['gmail_id'] == 'msg1'
            assert call_args.kwargs['archive_file'] == str(output_file)
            assert call_args.kwargs['subject'] == 'Test Subject'
            assert call_args.kwargs['from_addr'] == 'test@example.com'


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


class TestV11OffsetTracking:
    """Tests for v1.1 offset tracking during archiving."""

    @patch('gmailarchiver.archiver.ArchiveState')
    @patch('gmailarchiver.archiver.Progress')
    @patch('builtins.print')
    def test_archive_with_v1_1_schema_tracks_offsets(
        self, mock_print: Mock, mock_progress: Mock, mock_state_class: Mock
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
                CREATE TABLE schema_version (
                    version TEXT PRIMARY KEY,
                    migrated_timestamp TEXT
                )
            ''')
            conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
            conn.commit()
            conn.close()

            # Configure mock_state_class to return real ArchiveState with validate_path=False
            from gmailarchiver.state import ArchiveState as RealArchiveState

            def create_state(db_path):
                """Create ArchiveState with validation disabled."""
                return RealArchiveState(db_path, validate_path=False)

            mock_state_class.side_effect = create_state

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
            mock_message = {
                'id': 'msg123',
                'raw': '',  # Will be replaced by decode_message_raw
                'threadId': 'thread123',
                'labelIds': ['INBOX', 'IMPORTANT']
            }

            def mock_get_messages_batch(ids):
                """Mock batch message retrieval."""
                return [mock_message]

            mock_client.decode_message_raw.return_value = raw_email
            mock_client.get_messages_batch = mock_get_messages_batch

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
            assert len(mbox) == 1
            extracted_msg = mbox[0]
            assert extracted_msg['Subject'] == 'Test Subject'
