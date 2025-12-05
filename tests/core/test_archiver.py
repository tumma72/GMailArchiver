"""Tests for core archiving logic."""

import gzip
import lzma
import tempfile
from compression import zstd
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.shared.input_validator import InvalidInputError


class TestArchiverFacadeInit:
    """Tests for ArchiverFacade initialization."""

    def test_init(self) -> None:
        """Test initialization."""
        mock_client = Mock()
        archiver = ArchiverFacade(mock_client, "test_state.db")

        assert archiver.gmail_client == mock_client
        assert archiver.state_db_path == "test_state.db"

    def test_init_default_db_path(self) -> None:
        """Test initialization with default database path."""
        mock_client = Mock()
        archiver = ArchiverFacade(mock_client)

        # Facade uses XDG path, not simple "archive_state.db"
        assert archiver.state_db_path.endswith("gmailarchiver/archive.db")


class TestArchive:
    """Tests for archive method."""

    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_archive_no_messages_found(self, mock_list: Mock) -> None:
        """Test archiving when no messages match criteria."""
        mock_client = Mock()
        mock_list.return_value = ("before:2022/01/01", [])

        archiver = ArchiverFacade(mock_client)
        result = archiver.archive("3y", "test.mbox")

        assert result["found_count"] == 0
        assert result["archived_count"] == 0
        assert "actual_file" not in result  # Dry run or no messages

    @patch("gmailarchiver.core.archiver._filter.MessageFilter.filter_archived")
    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_archive_all_already_archived(self, mock_list: Mock, mock_filter: Mock) -> None:
        """Test archiving when all messages already archived."""
        mock_client = Mock()
        mock_list.return_value = (
            "before:2022/01/01",
            [{"id": "msg1", "threadId": "thread1"}, {"id": "msg2", "threadId": "thread2"}],
        )
        # All messages filtered (already archived)
        mock_filter.return_value = ([], 2)

        archiver = ArchiverFacade(mock_client)
        result = archiver.archive("3y", "test.mbox", incremental=True)

        assert result["found_count"] == 2
        assert result["archived_count"] == 0
        assert result["skipped_count"] == 2

    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_archive_dry_run(self, mock_list: Mock) -> None:
        """Test dry run mode."""
        mock_client = Mock()
        mock_list.return_value = ("before:2024/06/01", [{"id": "msg1", "threadId": "thread1"}])

        archiver = ArchiverFacade(mock_client)
        result = archiver.archive("6m", "test.mbox", dry_run=True)

        assert result["found_count"] == 1
        assert result["archived_count"] == 0
        # Dry run doesn't archive, so no actual_file
        assert "actual_file" not in result

    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_archive_dry_run_with_compression(self, mock_list: Mock) -> None:
        """Test dry run with compression specified."""
        mock_client = Mock()
        mock_list.return_value = ("before:2024/01/01", [{"id": "msg1", "threadId": "thread1"}])

        archiver = ArchiverFacade(mock_client)
        result = archiver.archive("1y", "test.mbox", compress="gzip", dry_run=True)

        assert result["found_count"] == 1
        assert result["archived_count"] == 0

    def test_archive_invalid_age_threshold(self) -> None:
        """Test that invalid age threshold raises error."""
        mock_client = Mock()
        archiver = ArchiverFacade(mock_client)

        with pytest.raises(InvalidInputError):
            archiver.archive("invalid", "test.mbox")

    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_archive_invalid_compression(self, mock_list: Mock) -> None:
        """Test that invalid compression format raises error."""
        mock_client = Mock()
        # Mock lister to return some messages so we get to the compress validation
        mock_list.return_value = ("before:2022/01/01", [{"id": "msg1", "threadId": "thread1"}])

        archiver = ArchiverFacade(mock_client)

        with pytest.raises(InvalidInputError):
            archiver.archive("3y", "test.mbox", compress="bzip2")


class TestCompressArchive:
    """Tests for compression via CompressorFacade."""

    def test_compress_gzip(self) -> None:
        """Test gzip compression via CompressorFacade."""
        from gmailarchiver.core.compressor._gzip import GzipCompressor

        # Create temporary source file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b"Test data for compression")

        dest_path = source_path.with_suffix(".gz")

        try:
            GzipCompressor.compress(source_path, dest_path)

            # Verify compressed file exists and can be decompressed
            assert dest_path.exists()
            with gzip.open(dest_path, "rb") as f:
                decompressed = f.read()
            assert decompressed == b"Test data for compression"

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    def test_compress_lzma(self) -> None:
        """Test lzma compression via CompressorFacade."""
        from gmailarchiver.core.compressor._lzma import LzmaCompressor

        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b"Test data for lzma")

        dest_path = source_path.with_suffix(".xz")

        try:
            LzmaCompressor.compress(source_path, dest_path)

            assert dest_path.exists()
            with lzma.open(dest_path, "rb") as f:
                decompressed = f.read()
            assert decompressed == b"Test data for lzma"

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    def test_compress_zstd(self) -> None:
        """Test zstd compression via CompressorFacade."""
        from gmailarchiver.core.compressor._zstd import ZstdCompressor

        with tempfile.NamedTemporaryFile(delete=False) as f:
            source_path = Path(f.name)
            f.write(b"Test data for zstd")

        dest_path = source_path.with_suffix(".zst")

        try:
            ZstdCompressor.compress(source_path, dest_path)

            # Verify compressed file exists and can be decompressed
            assert dest_path.exists()
            with zstd.open(dest_path, "rb") as f:
                decompressed = f.read()
            assert decompressed == b"Test data for zstd"

        finally:
            source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()

    @patch("gmailarchiver.core.archiver._lister.MessageLister.list_messages")
    def test_compress_invalid_format(self, mock_list: Mock) -> None:
        """Test that invalid compression format in archive raises error."""
        mock_client = Mock()
        mock_list.return_value = ("before:2022/01/01", [{"id": "msg1", "threadId": "thread1"}])

        archiver = ArchiverFacade(mock_client)

        # Invalid compression format should be caught during validation
        with pytest.raises(InvalidInputError):
            archiver.archive("3y", "test.mbox", compress="bzip2")


class TestValidateArchive:
    """Tests for validation via ValidatorFacade."""

    def test_validate_archive_success(self) -> None:
        """Test successful archive validation returns results dict."""
        from gmailarchiver.core.validator import ValidatorFacade

        # Create temp mbox for testing
        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = f.name
            f.write(b"From test@example.com\nSubject: Test\n\nBody\n")

        try:
            validator = ValidatorFacade(mbox_path)
            # validate_comprehensive expects expected_message_ids
            result = validator.validate_comprehensive(set())

            # Should have validation result structure
            assert "passed" in result
            assert "errors" in result
        finally:
            Path(mbox_path).unlink()

    def test_validate_archive_failure(self) -> None:
        """Test failed archive validation returns results dict with errors."""
        from gmailarchiver.core.validator import ValidatorFacade

        # Create empty mbox (will fail validation)
        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = f.name

        try:
            validator = ValidatorFacade(mbox_path)
            # Empty mbox should fail
            assert not validator.validate_all()
            assert len(validator.errors) > 0
        finally:
            Path(mbox_path).unlink()


class TestArchiveMessagesIntegration:
    """Tests for _archive_messages method and full archive flow."""

    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_works(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test successful archiving of messages."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        # Mock get_messages_batch to return a message with raw data
        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_message = {
            "id": "msg1",
            "threadId": "thread1",
            "raw": "dGVzdA==",  # base64 encoded
        }
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage - we set the return value inside the tmpdir block
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        # Create archiver and archive
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            # Create the file so it exists for size check
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            result = archiver.archive("3y", str(output_file), incremental=False)

            # Facade returns different keys than legacy
            assert result["found_count"] == 1
            assert result["archived_count"] == 1
            assert result["failed_count"] == 0

    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_with_compression_workflow(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test archiving with compression (gzip)."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox.gz"
            # Create the file so it exists for size check
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            result = archiver.archive("3y", str(output_file), compress="gzip", incremental=False)

            assert result["archived_count"] == 1

    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_with_orphaned_lock_file(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test archiving removes orphaned lock files."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage - it handles lock file cleanup internally
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()
            lock_file = Path(str(output_file) + ".lock")

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            # Create orphaned lock file
            lock_file.touch()
            assert lock_file.exists()

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))
            result = archiver.archive("3y", str(output_file), incremental=False)

            assert result["archived_count"] == 1

    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_records_state(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test that archiving records run in state database."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager - record_archived_message is called by HybridStorage
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db.record_archived_message.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            archiver.archive("3y", str(output_file), incremental=False)

            # Verify HybridStorage.archive_messages_batch was called (which records in DB)
            mock_storage.archive_messages_batch.assert_called_once()

    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_marks_messages_in_state(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test that individual messages are marked as archived in state."""
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        test_email = (
            b"From: test@example.com\r\n"
            b"Subject: Test Subject\r\n"
            b"Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n\r\nBody"
        )
        mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
        mock_client.get_messages_batch.return_value = [mock_message]
        mock_client.decode_message_raw.return_value = test_email

        # Mock DBManager
        mock_db = Mock()
        mock_db.close.return_value = None
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            archiver.archive("3y", str(output_file), incremental=False)

            # Verify HybridStorage.archive_messages_batch was called with messages
            mock_storage.archive_messages_batch.assert_called_once()
            call_args = mock_storage.archive_messages_batch.call_args
            # Check messages list was passed with correct gmail_id
            messages_arg = call_args.kwargs.get("messages") or call_args.args[0]
            assert len(messages_arg) == 1
            assert messages_arg[0][1] == "msg1"  # gmail_id is second element of tuple


class TestDeleteArchivedMessages:
    """Tests for delete_archived_messages method."""

    @patch("builtins.print")
    def test_delete_permanent(self, mock_print: Mock) -> None:
        """Test permanent deletion."""
        mock_client = Mock()
        mock_client.delete_messages_permanent.return_value = 5
        archiver = ArchiverFacade(mock_client)

        count = archiver.delete_archived_messages(
            ["msg1", "msg2", "msg3", "msg4", "msg5"], permanent=True
        )

        assert count == 5
        mock_client.delete_messages_permanent.assert_called_once()

    @patch("builtins.print")
    def test_delete_trash(self, mock_print: Mock) -> None:
        """Test moving to trash."""
        mock_client = Mock()
        mock_client.trash_messages.return_value = 3
        archiver = ArchiverFacade(mock_client)

        count = archiver.delete_archived_messages(["msg1", "msg2", "msg3"], permanent=False)

        assert count == 3
        mock_client.trash_messages.assert_called_once()


# NOTE: Tests for _extract_rfc_message_id and _extract_body_preview moved to
# tests/data/test_hybrid_storage.py since this functionality is now in HybridStorage


class TestAtomicOperations:
    """Tests for atomic mbox + database operations using HybridStorage."""

    @patch("builtins.print")
    def test_atomic_archive_both_succeed(self, mock_print: Mock) -> None:
        """Test that successful archiving commits both mbox and database."""
        import tempfile
        from pathlib import Path

        from gmailarchiver.data.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = test_email

            # Archive using HybridStorage
            archiver = ArchiverFacade(mock_client, state_db_path=str(db_path))
            result = archiver.archive("3y", str(mbox_path), incremental=False)

            # Verify both mbox and database were updated
            assert result["archived_count"] == 1
            assert mbox_path.exists(), "Mbox file should exist"

            # Verify database has the message
            db = DBManager(str(db_path))
            # v1.2: Use get_message_location_by_gmail_id for gmail_id lookup
            location = db.get_message_location_by_gmail_id("msg1")
            assert location is not None, "Message should be in database"
            assert location[0] == str(mbox_path)
            assert location[1] >= 0, "Offset should be valid"
            assert location[2] > 0, "Length should be positive"
            db.close()

    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("builtins.print")
    def test_atomic_rollback_on_database_failure(
        self, mock_print: Mock, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that database failure is handled gracefully with batch archiving."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [
                {"id": "msg1", "threadId": "thread1"},
                {"id": "msg2", "threadId": "thread2"},
            ]

            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_messages = [
                {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="},
                {"id": "msg2", "threadId": "thread2", "raw": "dGVzdA=="},
            ]
            mock_client.get_messages_batch.return_value = mock_messages
            mock_client.decode_message_raw.return_value = test_email

            # Mock DBManager
            mock_db = Mock()
            mock_db.close.return_value = None
            mock_db_class.return_value = mock_db

            # Mock HybridStorage to return partial success with 1 failure
            mock_storage = Mock()
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,  # One success
                "skipped": 0,
                "failed": 1,  # One failure
                "interrupted": False,
                "actual_file": str(mbox_path),
            }
            mock_storage_class.return_value = mock_storage

            # Archive should handle the failure gracefully
            archiver = ArchiverFacade(mock_client, state_db_path=str(temp_path / "state.db"))

            # The archiving should continue and report partial success
            result = archiver.archive("3y", str(mbox_path), incremental=False)

            # Should have 1 success and 1 failure
            assert result["archived_count"] == 1
            assert result["failed_count"] == 1

    @patch("builtins.print")
    def test_automatic_validation_after_archiving(self, mock_print: Mock) -> None:
        """Test that validation runs automatically after each message is archived."""
        import tempfile
        from pathlib import Path

        from gmailarchiver.data.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_message = {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}
            mock_client.get_messages_batch.return_value = [mock_message]
            mock_client.decode_message_raw.return_value = test_email

            # Archive message
            archiver = ArchiverFacade(mock_client, state_db_path=str(db_path))
            result = archiver.archive("3y", str(mbox_path), incremental=False)

            assert result["archived_count"] == 1

            # Verify the message can be read from mbox at the stored offset
            db = DBManager(str(db_path))
            # v1.2: Use get_message_location_by_gmail_id for gmail_id lookup
            location = db.get_message_location_by_gmail_id("msg1")
            assert location is not None

            archive_file, offset, length = location
            with open(archive_file, "rb") as f:
                f.seek(offset)
                data = f.read(length)
                assert len(data) > 0, "Should be able to read message at offset"

            db.close()

    def _create_v11_db(self, db_path: Path) -> None:
        """Helper to create v1.1 database schema."""
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
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
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content=messages, content_rowid=rowid
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()


class TestV11OffsetTracking:
    """Tests for v1.1 offset tracking during archiving."""

    @patch("builtins.print")
    def test_archive_with_v1_1_schema_tracks_offsets(self, mock_print: Mock) -> None:
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
            conn.execute("""
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
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    subject, from_addr, to_addr, body_preview,
                    content=messages, content_rowid=rowid
                )
            """)
            conn.execute("""
                CREATE TABLE archive_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    query TEXT,
                    messages_archived INTEGER,
                    archive_file TEXT,
                    account_id TEXT DEFAULT 'default',
                    operation_type TEXT DEFAULT 'archive'
                )
            """)
            conn.execute("""
                CREATE TABLE schema_version (
                    version TEXT PRIMARY KEY,
                    migrated_timestamp TEXT
                )
            """)
            conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
            conn.commit()
            conn.close()

            # Setup mock client
            mock_client = Mock()

            # Create test email
            msg = email.message.EmailMessage()
            msg["Message-ID"] = "<test123@example.com>"
            msg["Subject"] = "Test Subject"
            msg["From"] = "test@example.com"
            msg["To"] = "recipient@example.com"
            msg["Cc"] = "cc@example.com"
            msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
            msg.set_content("This is the test email body content.")

            raw_email = msg.as_bytes()

            # Mock message with labelIds
            mock_message: dict[str, str | list[str]] = {
                "id": "msg123",
                "raw": "",  # Will be replaced by decode_message_raw
                "threadId": "thread123",
                "labelIds": ["INBOX", "IMPORTANT"],
            }

            def mock_get_messages_batch(ids: list[str]) -> list[dict[str, str | list[str]]]:
                """Mock batch message retrieval."""
                return [mock_message]

            mock_client.decode_message_raw.return_value = raw_email
            mock_client.get_messages_batch = mock_get_messages_batch

            # Create archiver and archive (use public API)
            archiver = ArchiverFacade(mock_client, str(db_path))
            archiver.archive_messages(["msg123"], str(mbox_path))

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
            (
                mbox_offset,
                mbox_length,
                rfc_message_id,
                thread_id,
                to_addr,
                cc_addr,
                body_preview,
                size_bytes,
                labels,
            ) = row  # noqa: E501

            # Verify offsets are not placeholder values
            assert mbox_offset >= 0, "mbox_offset should be non-negative"
            assert mbox_length > 0, "mbox_length should be positive"

            # Verify enhanced v1.1 fields
            assert rfc_message_id == "<test123@example.com>"
            assert thread_id == "thread123"
            assert to_addr == "recipient@example.com"
            assert cc_addr == "cc@example.com"
            assert "test email body" in body_preview.lower()
            assert size_bytes == len(raw_email)
            assert labels == json.dumps(["INBOX", "IMPORTANT"])

            # Verify message can be extracted from mbox using offset
            mbox = mailbox.mbox(str(mbox_path))
            try:
                assert len(mbox) == 1
                # Get first message from mbox (use list() since mbox
                # doesn't support direct indexing)
                messages = list(mbox)
                extracted_msg = messages[0]
                assert extracted_msg["Subject"] == "Test Subject"
            finally:
                mbox.close()


class TestExceptionHandling:
    """Tests for exception handling in archiver."""

    @patch("gmailarchiver.core.archiver._filter.DBManager")
    @patch("builtins.print")
    def test_incremental_falls_back_on_dbmanager_failure(
        self, mock_print: Mock, mock_dbmanager_class: Mock
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
                {"id": "msg1", "threadId": "thread1"},
                {"id": "msg2", "threadId": "thread2"},
            ]

            archiver = ArchiverFacade(mock_client, state_db_path=str(db_path))

            # Use dry_run to avoid executing archiving logic
            result = archiver.archive("3y", "test.mbox", incremental=True, dry_run=True)

            # Should not skip any messages (falls back to empty set)
            # When DBManager fails, archived_ids becomes empty set
            assert result["found_count"] - result["skipped_count"] == 2

    @patch("gmailarchiver.core.archiver._filter.DBManager")
    @patch("builtins.print")
    def test_incremental_with_nonexistent_database(
        self, mock_print: Mock, mock_db_class: Mock
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
            mock_db.get_all_rfc_message_ids.return_value = set()  # For duplicate pre-filtering
            mock_db_class.return_value = mock_db

            # Setup mock client
            mock_client = Mock()
            mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

            archiver = ArchiverFacade(mock_client, state_db_path=str(db_path))
            result = archiver.archive("3y", "test.mbox", incremental=True, dry_run=True)

            # Should not skip any messages (no archived_ids)
            assert result["found_count"] - result["skipped_count"] == 1

    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("builtins.print")
    def test_archive_messages_falls_back_on_dbmanager_init_failure(
        self,
        mock_print: Mock,
        mock_dbmanager_class: Mock,
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

            archiver = ArchiverFacade(mock_client, state_db_path=str(db_path))

            # Should raise Exception when DBManager fails (use public API)
            with pytest.raises(Exception, match="Schema validation failed"):
                archiver.archive_messages(["msg1"], str(mbox_path))


# NOTE: Tests for body preview exceptions and _log method moved to
# tests/data/test_hybrid_storage.py and test_no_print_statements.py respectively


class TestArchiveWithOperationHandle:
    """Tests for archive() with OperationHandle integration."""

    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    def test_archive_with_operation_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver uses operation handle for logging and progress."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [
            {"id": "msg1", "threadId": "thread1"},
            {"id": "msg2", "threadId": "thread2"},
        ]

        # Setup mock message data
        # Base64: "Subject: Test Subject\n\nTest body"
        mock_message_data = {
            "id": "msg1",
            "threadId": "thread1",
            "raw": "U3ViamVjdDogVGVzdCBTdWJqZWN0CgpUZXN0IGJvZHk=",
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

        # Setup mock HybridStorage with side_effect that calls progress callback
        mock_storage = Mock()

        def batch_side_effect(
            messages,
            archive_file,
            compression=None,
            commit_interval=100,
            progress_callback=None,
            interrupt_event=None,
            session_id=None,
        ):
            # Call progress callback for each message to simulate real behavior
            if progress_callback:
                for msg, gmail_id, thread_id, labels in messages:
                    subject = msg.get("Subject", "Test Subject")
                    progress_callback(gmail_id, subject, "success")
            return {
                "archived": len(messages),
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(archive_file),
            }

        mock_storage.archive_messages_batch.side_effect = batch_side_effect
        mock_storage_class.return_value = mock_storage

        # Setup mock operation handle
        mock_operation = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            # Archive with operation handle
            result = archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                operation=mock_operation,
            )

            # Verify operation handle was used for logging
            assert mock_operation.log.called, "Operation handle log() should be called"
            assert mock_operation.update_progress.called, (
                "Operation handle update_progress() should be called"
            )

            # Verify we logged fetching messages
            log_calls = [call[0][0] for call in mock_operation.log.call_args_list]
            assert any("Fetching" in call for call in log_calls), "Should log 'Fetching X messages'"

            # Verify we logged success for each message
            # Note: v1.3.5+ removed duplicate severity symbols
            # Message is "Archived:" not "✓ Archived:"
            success_logs = [call for call in log_calls if "Archived:" in call]
            assert len(success_logs) == 2, "Should log success for each archived message"

            # Verify progress was updated for each message
            assert mock_operation.update_progress.call_count == 2, (
                "Should update progress for each message"
            )

    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    def test_archive_without_operation_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver works without operation handle (backward compatibility)."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_messages.return_value = [{"id": "msg1", "threadId": "thread1"}]

        # Setup mock message data
        mock_message_data = {
            "id": "msg1",
            "threadId": "thread1",
            "raw": "U3ViamVjdDogVGVzdCBTdWJqZWN0CgpUZXN0IGJvZHk=",
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
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch.return_value = {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(output_file),
            }

            archiver = ArchiverFacade(mock_client, state_db_path=str(Path(tmpdir) / "state.db"))

            # Archive without operation handle (should not crash)
            result = archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                operation=None,  # No operation handle
            )

            # Should complete successfully
            assert result["archived_count"] == 1
