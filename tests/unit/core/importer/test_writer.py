"""Unit tests for importer DatabaseWriter module.

Tests database operations, deduplication, and batch writing.
All tests use mocks - no actual database I/O.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from gmailarchiver.core.importer._reader import MessageMetadata
from gmailarchiver.core.importer._writer import DatabaseWriter, WriteResult


@pytest.mark.unit
class TestDatabaseWriterInit:
    """Tests for DatabaseWriter initialization."""

    def test_init(self) -> None:
        """Test initialization with database manager."""
        mock_db = Mock()
        writer = DatabaseWriter(mock_db)
        assert writer.db == mock_db


@pytest.mark.unit
class TestDatabaseWriterLoadExistingIds:
    """Tests for loading existing RFC Message-IDs."""

    @pytest.mark.asyncio
    async def test_load_existing_ids_success(self) -> None:
        """Test loading existing IDs from database."""
        mock_db = Mock()
        mock_db.get_all_rfc_message_ids = AsyncMock(
            return_value={"<msg1@example.com>", "<msg2@example.com>"}
        )

        writer = DatabaseWriter(mock_db)
        existing_ids = await writer.load_existing_ids()

        assert existing_ids == {"<msg1@example.com>", "<msg2@example.com>"}
        mock_db.get_all_rfc_message_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_existing_ids_empty_table(self) -> None:
        """Test loading from empty table."""
        mock_db = Mock()
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())

        writer = DatabaseWriter(mock_db)
        existing_ids = await writer.load_existing_ids()

        assert existing_ids == set()

    @pytest.mark.asyncio
    async def test_load_existing_ids_table_missing(self) -> None:
        """Test loading when table doesn't exist yet."""
        mock_db = Mock()
        mock_db.get_all_rfc_message_ids = AsyncMock(side_effect=Exception("Table does not exist"))

        writer = DatabaseWriter(mock_db)
        existing_ids = await writer.load_existing_ids()

        assert existing_ids == set()


@pytest.mark.unit
class TestDatabaseWriterIsDuplicate:
    """Tests for duplicate detection."""

    def test_is_duplicate_existing(self) -> None:
        """Test detecting duplicate in existing IDs."""
        mock_db = Mock()
        writer = DatabaseWriter(mock_db)

        # Simulate existing IDs
        writer.existing_ids = {"<msg1@example.com>"}
        writer.session_ids = set()

        assert writer.is_duplicate("<msg1@example.com>") is True

    def test_is_duplicate_in_session(self) -> None:
        """Test detecting duplicate within current session."""
        mock_db = Mock()
        writer = DatabaseWriter(mock_db)

        writer.existing_ids = set()
        writer.session_ids = {"<msg2@example.com>"}

        assert writer.is_duplicate("<msg2@example.com>") is True

    def test_is_duplicate_not_found(self) -> None:
        """Test when message is not a duplicate."""
        mock_db = Mock()
        writer = DatabaseWriter(mock_db)

        writer.existing_ids = {"<msg1@example.com>"}
        writer.session_ids = {"<msg2@example.com>"}

        assert writer.is_duplicate("<msg3@example.com>") is False


@pytest.mark.unit
class TestDatabaseWriterWriteMessage:
    """Tests for writing single message."""

    @pytest.mark.asyncio
    async def test_write_message_success(self) -> None:
        """Test successfully writing a message."""
        mock_db = Mock()
        mock_db.record_archived_message = AsyncMock()
        writer = DatabaseWriter(mock_db)
        writer.existing_ids = set()
        writer.session_ids = set()

        metadata = MessageMetadata(
            gmail_id="gmail123",
            rfc_message_id="<test@example.com>",
            thread_id="thread123",
            subject="Test",
            from_addr="sender@example.com",
            to_addr="receiver@example.com",
            cc_addr=None,
            date="Mon, 01 Jan 2024 12:00:00 +0000",
            archive_file="/tmp/archive.mbox",
            mbox_offset=0,
            mbox_length=100,
            body_preview="Test body",
            checksum="abc123",
            size_bytes=100,
            account_id="default",
        )

        result = await writer.write_message(metadata, skip_duplicates=True)

        assert result == WriteResult.IMPORTED
        assert "<test@example.com>" in writer.session_ids
        mock_db.record_archived_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_message_duplicate_skipped(self) -> None:
        """Test skipping duplicate message when skip_duplicates=True."""
        mock_db = Mock()
        writer = DatabaseWriter(mock_db)
        writer.existing_ids = {"<test@example.com>"}
        writer.session_ids = set()

        metadata = MessageMetadata(
            gmail_id=None,
            rfc_message_id="<test@example.com>",
            thread_id=None,
            subject="Test",
            from_addr="sender@example.com",
            to_addr="receiver@example.com",
            cc_addr=None,
            date="Mon, 01 Jan 2024 12:00:00 +0000",
            archive_file="/tmp/archive.mbox",
            mbox_offset=0,
            mbox_length=100,
            body_preview="",
            checksum="abc123",
            size_bytes=100,
            account_id="default",
        )

        result = await writer.write_message(metadata, skip_duplicates=True)

        assert result == WriteResult.SKIPPED

    @pytest.mark.asyncio
    async def test_write_message_duplicate_replaced(self) -> None:
        """Test replacing duplicate when skip_duplicates=False."""
        mock_db = Mock()
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=None)
        mock_db.conn.commit = AsyncMock()

        writer = DatabaseWriter(mock_db)
        writer.existing_ids = {"<test@example.com>"}
        writer.session_ids = set()

        metadata = MessageMetadata(
            gmail_id="gmail456",
            rfc_message_id="<test@example.com>",
            thread_id="thread456",
            subject="Updated Test",
            from_addr="sender@example.com",
            to_addr="receiver@example.com",
            cc_addr=None,
            date="Mon, 01 Jan 2024 12:00:00 +0000",
            archive_file="/tmp/archive.mbox",
            mbox_offset=100,
            mbox_length=200,
            body_preview="Updated body",
            checksum="def456",
            size_bytes=200,
            account_id="default",
        )

        result = await writer.write_message(metadata, skip_duplicates=False)

        assert result == WriteResult.IMPORTED
        assert "<test@example.com>" in writer.session_ids
        # Should use INSERT OR REPLACE via direct SQL
        mock_db.conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_message_database_error(self) -> None:
        """Test handling database errors during write."""
        mock_db = Mock()
        mock_db.record_archived_message = AsyncMock(
            side_effect=Exception("DB constraint violation")
        )
        mock_db.rollback = AsyncMock()

        writer = DatabaseWriter(mock_db)
        writer.existing_ids = set()
        writer.session_ids = set()

        metadata = MessageMetadata(
            gmail_id=None,
            rfc_message_id="<test@example.com>",
            thread_id=None,
            subject="Test",
            from_addr="sender@example.com",
            to_addr="receiver@example.com",
            cc_addr=None,
            date="Mon, 01 Jan 2024 12:00:00 +0000",
            archive_file="/tmp/archive.mbox",
            mbox_offset=0,
            mbox_length=100,
            body_preview="",
            checksum="abc123",
            size_bytes=100,
            account_id="default",
        )

        result = await writer.write_message(metadata, skip_duplicates=True)

        assert result == WriteResult.FAILED
        mock_db.rollback.assert_called_once()


@pytest.mark.unit
class TestDatabaseWriterRecordArchiveRun:
    """Tests for recording archive run."""

    @pytest.mark.asyncio
    async def test_record_archive_run(self) -> None:
        """Test recording import operation in archive_runs."""
        mock_db = Mock()
        mock_db.record_archive_run = AsyncMock()
        writer = DatabaseWriter(mock_db)

        await writer.record_archive_run(
            archive_file="/tmp/archive.mbox",
            messages_count=42,
            account_id="default",
        )

        mock_db.record_archive_run.assert_called_once_with(
            operation="import",
            messages_count=42,
            archive_file="/tmp/archive.mbox",
            account_id="default",
        )


@pytest.mark.unit
class TestWriteResult:
    """Tests for WriteResult enum."""

    def test_write_result_values(self) -> None:
        """Test WriteResult enum values."""
        assert WriteResult.IMPORTED.value == "imported"
        assert WriteResult.SKIPPED.value == "skipped"
        assert WriteResult.FAILED.value == "failed"
