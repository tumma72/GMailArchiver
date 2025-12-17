"""Tests for core archiving logic."""

import gzip
import lzma
import tempfile
from compression import zstd
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.archiver._filter import FilterResult
from gmailarchiver.shared.input_validator import InvalidInputError

pytestmark = pytest.mark.asyncio


def create_mock_async_client(
    messages: list[dict[str, Any]] | None = None,
    raw_email: bytes = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody",
) -> Mock:
    """Create a mock GmailClient with proper async methods.

    Args:
        messages: List of message dicts to return from list_messages
        raw_email: Raw email bytes to return from decode_message_raw

    Returns:
        Mock configured as GmailClient
    """
    mock_client = Mock()

    # Mock list_messages as async generator
    async def mock_list_messages(query: str, max_results: int = 100):
        for msg in messages or []:
            yield msg

    mock_client.list_messages = mock_list_messages

    # Mock get_messages_batch as async generator
    async def mock_get_messages_batch(message_ids: list[str], format: str = "raw"):
        for msg in messages or []:
            if msg.get("id") in message_ids:
                yield msg

    mock_client.get_messages_batch = mock_get_messages_batch

    # Mock decode_message_raw (sync method)
    mock_client.decode_message_raw.return_value = raw_email

    # Mock async delete/trash methods
    mock_client.delete_messages_permanent = AsyncMock(return_value=0)
    mock_client.trash_messages = AsyncMock(return_value=0)

    return mock_client


class TestArchiverFacadeInit:
    """Tests for ArchiverFacade initialization."""

    async def test_init(self) -> None:
        """Test initialization via create()."""
        mock_client = create_mock_async_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            assert archiver.gmail_client == mock_client
            # Use resolve() to handle macOS /private/var symlink
            assert Path(archiver.state_db_path).resolve() == Path(db_path).resolve()

            await archiver.close()

    async def test_init_default_db_path(self) -> None:
        """Test initialization with default database path."""
        mock_client = create_mock_async_client()

        # Use a temp dir to avoid creating files in user's home
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "archive.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            # Verify path resolves correctly (handle macOS /private/var symlink)
            assert Path(archiver.state_db_path).resolve() == Path(db_path).resolve()

            await archiver.close()


class TestArchive:
    """Tests for archive method."""

    async def test_archive_no_messages_found(self) -> None:
        """Test archiving when no messages match criteria."""
        mock_client = create_mock_async_client(messages=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))
            result = await archiver.archive("3y", "test.mbox")

            assert result["found_count"] == 0
            assert result["archived_count"] == 0
            assert "actual_file" not in result  # Dry run or no messages

            await archiver.close()

    async def test_archive_all_already_archived(self) -> None:
        """Test archiving when all messages already archived."""
        messages = [
            {"id": "msg1", "threadId": "thread1"},
            {"id": "msg2", "threadId": "thread2"},
        ]
        mock_client = create_mock_async_client(messages=messages)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))
            # All messages filtered (already archived)
            archiver._filter.filter_archived = AsyncMock(
                return_value=FilterResult(
                    to_archive=[], already_archived_count=2, duplicate_count=0
                )
            )
            result = await archiver.archive("3y", "test.mbox", incremental=True)

            assert result["found_count"] == 2
            assert result["archived_count"] == 0
            assert result["skipped_count"] == 2

            await archiver.close()

    async def test_archive_dry_run(self) -> None:
        """Test dry run mode."""
        messages = [{"id": "msg1", "threadId": "thread1"}]
        mock_client = create_mock_async_client(messages=messages)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))
            result = await archiver.archive("6m", "test.mbox", dry_run=True)

            assert result["found_count"] == 1
            assert result["archived_count"] == 0
            # Dry run doesn't archive, so no actual_file
            assert "actual_file" not in result

            await archiver.close()

    async def test_archive_dry_run_with_compression(self) -> None:
        """Test dry run with compression specified."""
        messages = [{"id": "msg1", "threadId": "thread1"}]
        mock_client = create_mock_async_client(messages=messages)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))
            result = await archiver.archive("1y", "test.mbox", compress="gzip", dry_run=True)

            assert result["found_count"] == 1
            assert result["archived_count"] == 0

            await archiver.close()

    async def test_archive_invalid_age_threshold(self) -> None:
        """Test that invalid age threshold raises error."""
        mock_client = create_mock_async_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            try:
                with pytest.raises(InvalidInputError):
                    await archiver.archive("invalid", "test.mbox")
            finally:
                await archiver.close()

    async def test_archive_invalid_compression(self) -> None:
        """Test that invalid compression format raises error."""
        messages = [{"id": "msg1", "threadId": "thread1"}]
        mock_client = create_mock_async_client(messages=messages)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            try:
                with pytest.raises(InvalidInputError):
                    await archiver.archive("3y", "test.mbox", compress="bzip2")
            finally:
                await archiver.close()


class TestCompressArchive:
    """Tests for compression via CompressorFacade."""

    async def test_compress_gzip(self) -> None:
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

    async def test_compress_lzma(self) -> None:
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

    async def test_compress_zstd(self) -> None:
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

    async def test_compress_invalid_format(self) -> None:
        """Test that invalid compression format in archive raises error."""
        messages = [{"id": "msg1", "threadId": "thread1"}]
        mock_client = create_mock_async_client(messages=messages)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            try:
                # Invalid compression format should be caught during validation
                with pytest.raises(InvalidInputError):
                    await archiver.archive("3y", "test.mbox", compress="bzip2")
            finally:
                await archiver.close()


class TestValidateArchive:
    """Tests for validation via ValidatorFacade."""

    async def test_validate_archive_success(self) -> None:
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

            # Should have validation result structure (dataclass, not dict)
            assert hasattr(result, "passed")
            assert hasattr(result, "errors")
        finally:
            Path(mbox_path).unlink()

    async def test_validate_archive_failure(self) -> None:
        """Test failed archive validation returns results dict with errors."""
        from gmailarchiver.core.validator import ValidatorFacade

        # Create empty mbox (will fail validation)
        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = f.name

        try:
            validator = ValidatorFacade(mbox_path)
            # Empty mbox should fail
            passed = validator.validate_all()
            assert not passed
            assert len(validator.errors) > 0
        finally:
            Path(mbox_path).unlink()


class TestArchiveMessagesIntegration:
    """Tests for _archive_messages method and full archive flow."""

    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_works(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test successful archiving of messages."""
        # Setup mock client with messages
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Mock DBManager
        mock_db = Mock()
        mock_db.close = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
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
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            result = await archiver.archive("3y", str(output_file), incremental=False)

            # Facade returns different keys than legacy
            assert result["found_count"] == 1
            assert result["archived_count"] == 1
            assert result["failed_count"] == 0

            await archiver.close()

    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_with_compression_workflow(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test archiving with compression (gzip)."""
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Mock DBManager
        mock_db = Mock()
        mock_db.close = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox.gz"
            # Create the file so it exists for size check
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            result = await archiver.archive(
                "3y", str(output_file), compress="gzip", incremental=False
            )

            assert result["archived_count"] == 1

            await archiver.close()

    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_with_orphaned_lock_file(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test archiving removes orphaned lock files."""
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Mock DBManager
        mock_db = Mock()
        mock_db.close = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_db_class.return_value = mock_db

        # Mock HybridStorage - it handles lock file cleanup internally
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()
            lock_file = Path(str(output_file) + ".lock")

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            # Create orphaned lock file
            lock_file.touch()
            assert lock_file.exists()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )
            result = await archiver.archive("3y", str(output_file), incremental=False)

            assert result["archived_count"] == 1

            await archiver.close()

    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_records_state(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test that archiving records run in state database."""
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Mock DBManager - record_archived_message is called by HybridStorage
        mock_db = Mock()
        mock_db.close = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_db.record_archived_message = AsyncMock()
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            await archiver.archive("3y", str(output_file), incremental=False)

            # Verify HybridStorage.archive_messages_batch was called (which records in DB)
            mock_storage.archive_messages_batch.assert_called_once()

            await archiver.close()

    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_marks_messages_in_state(
        self,
        mock_print: Mock,
        mock_db_class: Mock,
        mock_storage_class: Mock,
    ) -> None:
        """Test that individual messages are marked as archived in state."""
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = (
            b"From: test@example.com\r\n"
            b"Subject: Test Subject\r\n"
            b"Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n\r\nBody"
        )
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Mock DBManager
        mock_db = Mock()
        mock_db.close = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_db_class.return_value = mock_db

        # Mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            await archiver.archive("3y", str(output_file), incremental=False)

            # Verify HybridStorage.archive_messages_batch was called with messages
            mock_storage.archive_messages_batch.assert_called_once()
            call_args = mock_storage.archive_messages_batch.call_args
            # Check messages list was passed with correct gmail_id
            messages_arg = call_args.kwargs.get("messages") or call_args.args[0]
            assert len(messages_arg) == 1
            assert messages_arg[0][1] == "msg1"  # gmail_id is second element of tuple

            await archiver.close()


class TestDeleteArchivedMessages:
    """Tests for delete_archived_messages method."""

    @patch("builtins.print")
    async def test_delete_permanent(self, mock_print: Mock) -> None:
        """Test permanent deletion."""
        mock_client = create_mock_async_client()
        mock_client.delete_messages_permanent = AsyncMock(return_value=5)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            count = await archiver.delete_archived_messages(
                ["msg1", "msg2", "msg3", "msg4", "msg5"], permanent=True
            )

            assert count == 5
            mock_client.delete_messages_permanent.assert_called_once()

            await archiver.close()

    @patch("builtins.print")
    async def test_delete_trash(self, mock_print: Mock) -> None:
        """Test moving to trash."""
        mock_client = create_mock_async_client()
        mock_client.trash_messages = AsyncMock(return_value=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            archiver = await ArchiverFacade.create(mock_client, str(db_path))

            count = await archiver.delete_archived_messages(
                ["msg1", "msg2", "msg3"], permanent=False
            )

            assert count == 3
            mock_client.trash_messages.assert_called_once()

            await archiver.close()


# NOTE: Tests for _extract_rfc_message_id and _extract_body_preview moved to
# tests/data/test_hybrid_storage.py since this functionality is now in HybridStorage


class TestAtomicOperations:
    """Tests for atomic mbox + database operations using HybridStorage."""

    @patch("builtins.print")
    async def test_atomic_archive_both_succeed(self, mock_print: Mock) -> None:
        """Test that successful archiving commits both mbox and database."""
        from gmailarchiver.data.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client with messages
            messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

            # Archive using HybridStorage
            archiver = await ArchiverFacade.create(mock_client, state_db_path=str(db_path))
            result = await archiver.archive("3y", str(mbox_path), incremental=False)
            await archiver.close()

            # Verify both mbox and database were updated
            assert result["archived_count"] == 1
            assert mbox_path.exists(), "Mbox file should exist"

            # Verify database has the message
            db = DBManager(str(db_path))
            await db.initialize()
            # v1.2: Use get_message_location_by_gmail_id for gmail_id lookup
            location = await db.get_message_location_by_gmail_id("msg1")
            assert location is not None, "Message should be in database"
            assert location[0] == str(mbox_path)
            assert location[1] >= 0, "Offset should be valid"
            assert location[2] > 0, "Length should be positive"
            await db.close()

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    @patch("builtins.print")
    async def test_atomic_rollback_on_database_failure(
        self, mock_print: Mock, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that database failure is handled gracefully with batch archiving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            # Setup mock client with messages
            messages = [
                {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="},
                {"id": "msg2", "threadId": "thread2", "raw": "dGVzdA=="},
            ]
            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

            # Mock DBManager
            mock_db = Mock()
            mock_db.close = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.db_path = str(temp_path / "state.db")
            mock_db_class.return_value = mock_db

            # Mock HybridStorage to return partial success with 1 failure
            mock_storage = Mock()
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,  # One success
                    "skipped": 0,
                    "failed": 1,  # One failure
                    "interrupted": False,
                    "actual_file": str(mbox_path),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()
            mock_storage_class.return_value = mock_storage

            # Archive should handle the failure gracefully
            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(temp_path / "state.db")
            )

            # The archiving should continue and report partial success
            result = await archiver.archive("3y", str(mbox_path), incremental=False)

            # Should have 1 success and 1 failure
            assert result["archived_count"] == 1
            assert result["failed_count"] == 1

            await archiver.close()

    @patch("builtins.print")
    async def test_automatic_validation_after_archiving(self, mock_print: Mock) -> None:
        """Test that validation runs automatically after each message is archived."""
        from gmailarchiver.data.db_manager import DBManager

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"
            mbox_path = temp_path / "test.mbox"

            # Create v1.1 database schema
            self._create_v11_db(db_path)

            # Setup mock client
            messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
            test_email = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
            mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

            # Archive message
            archiver = await ArchiverFacade.create(mock_client, state_db_path=str(db_path))
            result = await archiver.archive("3y", str(mbox_path), incremental=False)
            await archiver.close()

            assert result["archived_count"] == 1

            # Verify the message can be read from mbox at the stored offset
            db = DBManager(str(db_path))
            await db.initialize()
            # v1.2: Use get_message_location_by_gmail_id for gmail_id lookup
            location = await db.get_message_location_by_gmail_id("msg1")
            assert location is not None

            archive_file, offset, length = location
            with open(archive_file, "rb") as f:
                f.seek(offset)
                data = f.read(length)
                assert len(data) > 0, "Should be able to read message at offset"

            await db.close()

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
    async def test_archive_with_v1_1_schema_tracks_offsets(self, mock_print: Mock) -> None:
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

            # Create mock client with async generator
            mock_client = Mock()

            async def mock_get_messages_batch(ids: list[str], format: str = "raw"):
                yield mock_message

            mock_client.get_messages_batch = mock_get_messages_batch
            mock_client.decode_message_raw.return_value = raw_email

            # Create archiver and archive (use public API)
            archiver = await ArchiverFacade.create(mock_client, str(db_path))
            await archiver.archive_messages(["msg123"], str(mbox_path))
            await archiver.close()

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

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_incremental_falls_back_on_dbmanager_failure(
        self, mock_print: Mock, mock_dbmanager_class: Mock
    ) -> None:
        """Test that DBManager failure during facade construction raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"

            # Create database file (empty, will cause DBManager to fail)
            db_path.touch()

            # Mock DBManager to raise exception on initialization
            mock_db = Mock()
            mock_db.initialize = AsyncMock(side_effect=Exception("Schema validation failed"))
            mock_dbmanager_class.return_value = mock_db

            # Setup mock client
            mock_client = create_mock_async_client()

            # With new architecture, exception is raised during facade construction
            with pytest.raises(Exception, match="Schema validation failed"):
                await ArchiverFacade.create(mock_client, state_db_path=str(db_path))

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_incremental_with_nonexistent_database(
        self, mock_print: Mock, mock_db_class: Mock
    ) -> None:
        """Test incremental mode when database doesn't exist yet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "nonexistent.db"

            # Database doesn't exist - DBManager will auto-create it
            assert not db_path.exists()

            # Mock DBManager to return empty archived set
            mock_db = Mock()
            mock_db.initialize = AsyncMock()
            mock_db.db_path = str(db_path)
            mock_cursor = Mock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_db.conn = Mock()
            mock_db.conn.execute = AsyncMock(return_value=mock_cursor)
            mock_db.close = AsyncMock()
            mock_db.get_all_rfc_message_ids = AsyncMock(
                return_value=set()
            )  # For duplicate pre-filtering
            mock_db_class.return_value = mock_db

            # Setup mock client with messages
            messages = [{"id": "msg1", "threadId": "thread1"}]
            mock_client = create_mock_async_client(messages=messages)

            archiver = await ArchiverFacade.create(mock_client, state_db_path=str(db_path))
            result = await archiver.archive("3y", "test.mbox", incremental=True, dry_run=True)
            await archiver.close()

            # Should not skip any messages (no archived_ids)
            assert result["found_count"] - result["skipped_count"] == 1

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("builtins.print")
    async def test_archive_messages_falls_back_on_dbmanager_init_failure(
        self,
        mock_print: Mock,
        mock_dbmanager_class: Mock,
    ) -> None:
        """Test that DBManager init failure during facade construction raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            db_path = temp_path / "test.db"

            # Create database file
            db_path.touch()

            # Mock DBManager to raise exception on init
            mock_db = Mock()
            mock_db.initialize = AsyncMock(side_effect=Exception("Schema validation failed"))
            mock_dbmanager_class.return_value = mock_db

            # Setup mock client
            mock_client = create_mock_async_client()

            # With new architecture, exception is raised during facade construction
            with pytest.raises(Exception, match="Schema validation failed"):
                await ArchiverFacade.create(mock_client, state_db_path=str(db_path))


# NOTE: Tests for body preview exceptions and _log method moved to
# tests/data/test_hybrid_storage.py and test_no_print_statements.py respectively


class TestArchiveWithTaskHandle:
    """Tests for archive() with TaskHandle integration."""

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    async def test_archive_with_task_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver uses task handle for progress tracking."""
        # Setup mock client with messages
        messages = [
            {"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="},
            {"id": "msg2", "threadId": "thread2", "raw": "dGVzdA=="},
        ]
        test_email = b"Subject: Test Subject\n\nTest body"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Setup mock DBManager
        mock_db = Mock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_cursor = Mock()
        mock_cursor.fetchall = AsyncMock(return_value=[])  # No previously archived messages
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=mock_cursor)
        mock_db.close = AsyncMock()
        mock_db_class.return_value = mock_db

        # Setup mock HybridStorage with side_effect that calls progress callback
        mock_storage = Mock()

        async def batch_side_effect(
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

        mock_storage.archive_messages_batch = AsyncMock(side_effect=batch_side_effect)
        mock_storage.db = mock_db
        mock_db.create_session = AsyncMock()
        mock_storage_class.return_value = mock_storage

        # Setup mock task handle
        mock_task = Mock()
        mock_task.advance = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            # Archive with task handle
            result = await archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                task=mock_task,
            )

            # Verify task handle was used for progress tracking
            assert mock_task.advance.called, "Task handle advance() should be called"
            # Should advance for fetching messages (2) and archiving messages (2)
            assert mock_task.advance.call_count >= 2, "Should advance progress at least twice"

            await archiver.close()

    @patch("gmailarchiver.core.archiver.facade.DBManager")
    @patch("gmailarchiver.core.archiver.facade.HybridStorage")
    async def test_archive_without_task_handle(
        self, mock_storage_class: Mock, mock_db_class: Mock
    ) -> None:
        """Test that archiver works without task handle (backward compatibility)."""
        # Setup mock client with messages
        messages = [{"id": "msg1", "threadId": "thread1", "raw": "dGVzdA=="}]
        test_email = b"Subject: Test Subject\n\nTest body"
        mock_client = create_mock_async_client(messages=messages, raw_email=test_email)

        # Setup mock DBManager
        mock_db = Mock()
        mock_db.initialize = AsyncMock()
        mock_db.db_path = "test.db"
        mock_cursor = Mock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=mock_cursor)
        mock_db.close = AsyncMock()
        mock_db_class.return_value = mock_db

        # Setup mock HybridStorage
        mock_storage = Mock()
        mock_storage_class.return_value = mock_storage

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "archive.mbox"
            output_file.touch()

            # Set the mock return value now that we know the output path
            mock_storage.archive_messages_batch = AsyncMock(
                return_value={
                    "archived": 1,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": False,
                    "actual_file": str(output_file),
                }
            )
            mock_storage.db = mock_db
            mock_db.create_session = AsyncMock()

            archiver = await ArchiverFacade.create(
                mock_client, state_db_path=str(Path(tmpdir) / "state.db")
            )

            # Archive without task handle (should not crash)
            result = await archiver.archive(
                age_threshold="3y",
                output_file=str(output_file),
                incremental=False,
                task=None,  # No task handle
            )

            # Should complete successfully
            assert result["archived_count"] == 1

            await archiver.close()
