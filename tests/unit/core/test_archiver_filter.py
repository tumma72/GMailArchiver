"""Unit tests for MessageFilter (archiver package internal module).

This module contains fast, isolated unit tests with no I/O or external
dependencies. DBManager is mocked to avoid database access.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from gmailarchiver.core.archiver._filter import FilterResult, MessageFilter


@pytest.mark.unit
class TestMessageFilter:
    """Unit tests for MessageFilter internal module."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db = Mock()
        cursor = Mock()
        # Simulate database with msg001 and msg002 already archived
        cursor.fetchall = AsyncMock(return_value=[("msg001",), ("msg002",)])
        db.conn = Mock()
        db.conn.execute = AsyncMock(return_value=cursor)
        db.close = AsyncMock()
        return db

    @pytest.fixture
    def filter_module(self, mock_db_manager):
        """Create MessageFilter instance."""
        return MessageFilter(db_manager=mock_db_manager)

    @pytest.mark.asyncio
    async def test_filter_with_incremental_false(self, filter_module):
        """Test that incremental=False returns all messages."""
        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(message_ids, incremental=False)

        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0
        assert result.total_skipped == 0

    @pytest.mark.asyncio
    async def test_filter_with_incremental_true(self, filter_module, mock_db_manager):
        """Test filtering out already-archived messages."""
        message_ids = ["msg001", "msg002", "msg003", "msg004"]

        result = await filter_module.filter_archived(message_ids, incremental=True)

        # msg001 and msg002 should be filtered out
        assert result.to_archive == ["msg003", "msg004"]
        assert result.already_archived_count == 2
        assert result.duplicate_count == 0
        assert result.total_skipped == 2

        # Should query database for archived IDs
        mock_db_manager.conn.execute.assert_called_once()
        query = mock_db_manager.conn.execute.call_args[0][0]
        assert "SELECT gmail_id FROM messages" in query
        assert "gmail_id IS NOT NULL" in query

    @pytest.mark.asyncio
    async def test_filter_with_no_archived_messages(self):
        """Test filtering when no messages are archived."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        filter_module = MessageFilter(db_manager=mock_db)
        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(message_ids, incremental=True)

        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_with_all_archived(self):
        """Test filtering when all messages are already archived."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall = AsyncMock(return_value=[("msg001",), ("msg002",), ("msg003",)])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        filter_module = MessageFilter(db_manager=mock_db)
        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(message_ids, incremental=True)

        assert result.to_archive == []
        assert result.already_archived_count == 3
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_handles_database_error(self):
        """Test that database errors are handled gracefully."""
        mock_db = Mock()
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(side_effect=Exception("Database error"))

        filter_module = MessageFilter(db_manager=mock_db)
        message_ids = ["msg001", "msg002", "msg003"]

        # Should return all messages if database fails
        result = await filter_module.filter_archived(message_ids, incremental=True)

        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_with_empty_message_list(self, filter_module):
        """Test filtering with empty message list."""
        result = await filter_module.filter_archived([], incremental=True)

        assert result.to_archive == []
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_excludes_null_gmail_ids(self, filter_module):
        """Test that query excludes NULL gmail_ids (deleted messages)."""
        await filter_module.filter_archived(["msg003"], incremental=True)

        # Should include WHERE clause to exclude NULL gmail_ids
        query = filter_module.db_manager.conn.execute.call_args[0][0]
        assert "gmail_id IS NOT NULL" in query

    @pytest.mark.asyncio
    async def test_filter_with_none_connection(self):
        """Test filtering when database connection is None."""
        mock_db = Mock()
        mock_db.conn = None  # Simulate no connection

        filter_module = MessageFilter(db_manager=mock_db)
        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(message_ids, incremental=True)

        # Should return all messages if connection is None
        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0


@pytest.mark.unit
class TestFilterResult:
    """Unit tests for FilterResult dataclass."""

    def test_total_skipped_property(self):
        """Test that total_skipped returns sum of archived and duplicates."""
        result = FilterResult(
            to_archive=["msg001"],
            already_archived_count=5,
            duplicate_count=3,
        )
        assert result.total_skipped == 8

    def test_total_skipped_with_zeros(self):
        """Test total_skipped when counts are zero."""
        result = FilterResult(
            to_archive=["msg001", "msg002"],
            already_archived_count=0,
            duplicate_count=0,
        )
        assert result.total_skipped == 0
