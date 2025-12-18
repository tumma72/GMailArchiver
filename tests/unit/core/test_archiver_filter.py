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
        # Mock get_all_rfc_message_ids to return empty set (no RFC-ID duplicates)
        db.get_all_rfc_message_ids = AsyncMock(return_value=set())
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
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())

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
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())

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
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())

        filter_module = MessageFilter(db_manager=mock_db)
        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(message_ids, incremental=True)

        # Should return all messages if connection is None
        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_with_rfc_message_id_duplicates(self):
        """Test filtering by RFC Message-ID when duplicates exist."""
        mock_db = Mock()
        cursor = Mock()
        # No Gmail ID matches
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)
        # Simulate RFC Message-ID duplicates in database
        mock_db.get_all_rfc_message_ids = AsyncMock(
            return_value={"<msg001@example.com>", "<msg002@example.com>"}
        )

        filter_module = MessageFilter(db_manager=mock_db)

        # Create mock Gmail client
        mock_gmail = Mock()

        # Simulate Gmail API responses with RFC Message-IDs
        async def mock_batch_generator(message_ids, format):
            for mid in message_ids:
                yield {
                    "id": mid,
                    "payload": {
                        "headers": [{"name": "Message-ID", "value": f"<{mid}@example.com>"}]
                    },
                }

        mock_gmail.get_messages_batch = mock_batch_generator

        message_ids = ["msg001", "msg002", "msg003"]

        result = await filter_module.filter_archived(
            message_ids, incremental=True, gmail_client=mock_gmail
        )

        # msg001 and msg002 should be filtered as duplicates by RFC Message-ID
        assert result.to_archive == ["msg003"]
        assert result.already_archived_count == 0
        assert result.duplicate_count == 2

    @pytest.mark.asyncio
    async def test_filter_with_rfc_message_id_exception(self):
        """Test handling exception when fetching RFC Message-IDs."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)
        # Simulate exception when getting RFC Message-IDs
        mock_db.get_all_rfc_message_ids = AsyncMock(side_effect=Exception("Database error"))

        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()
        message_ids = ["msg001", "msg002"]

        result = await filter_module.filter_archived(
            message_ids, incremental=True, gmail_client=mock_gmail
        )

        # Should return all messages if RFC ID lookup fails
        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_skips_rfc_check_when_no_known_ids(self):
        """Test that RFC Message-ID check is skipped when no IDs are known."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)
        # Empty set of known RFC IDs
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())

        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()
        mock_gmail.get_messages_batch = AsyncMock()  # Should not be called

        message_ids = ["msg001", "msg002"]

        result = await filter_module.filter_archived(
            message_ids, incremental=True, gmail_client=mock_gmail
        )

        # Should not call Gmail API if no known RFC IDs
        assert result.to_archive == message_ids
        assert result.already_archived_count == 0
        assert result.duplicate_count == 0

    @pytest.mark.asyncio
    async def test_filter_skips_rfc_check_when_no_messages_after_gmail_filter(self):
        """Test RFC check skipped when all messages filtered by Gmail ID."""
        mock_db = Mock()
        cursor = Mock()
        # All messages already archived by Gmail ID
        cursor.fetchall = AsyncMock(return_value=[("msg001",), ("msg002",)])
        mock_db.conn = Mock()
        mock_db.conn.execute = AsyncMock(return_value=cursor)
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value={"<dup@example.com>"})

        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()
        mock_gmail.get_messages_batch = AsyncMock()  # Should not be called

        message_ids = ["msg001", "msg002"]

        result = await filter_module.filter_archived(
            message_ids, incremental=True, gmail_client=mock_gmail
        )

        # All filtered by Gmail ID, RFC check not needed
        assert result.to_archive == []
        assert result.already_archived_count == 2
        assert result.duplicate_count == 0


@pytest.mark.unit
class TestMessageFilterRfcId:
    """Unit tests for RFC Message-ID filtering logic."""

    @pytest.mark.asyncio
    async def test_extract_message_id_header_found(self):
        """Test extracting Message-ID header when present."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {
            "id": "msg001",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Message-ID", "value": "<abc123@example.com>"},
                    {"name": "Subject", "value": "Test"},
                ]
            },
        }

        result = filter_module._extract_message_id_header(msg_data)
        assert result == "<abc123@example.com>"

    @pytest.mark.asyncio
    async def test_extract_message_id_header_case_insensitive(self):
        """Test Message-ID header extraction is case-insensitive."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {
            "payload": {
                "headers": [
                    {"name": "message-id", "value": "<xyz@example.com>"},
                ]
            }
        }

        result = filter_module._extract_message_id_header(msg_data)
        assert result == "<xyz@example.com>"

    @pytest.mark.asyncio
    async def test_extract_message_id_header_strips_whitespace(self):
        """Test that Message-ID header value is stripped of whitespace."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {
            "payload": {
                "headers": [
                    {"name": "Message-ID", "value": "  <test@example.com>  "},
                ]
            }
        }

        result = filter_module._extract_message_id_header(msg_data)
        assert result == "<test@example.com>"

    @pytest.mark.asyncio
    async def test_extract_message_id_header_not_found(self):
        """Test extracting Message-ID when header is missing."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Test"},
                ]
            }
        }

        result = filter_module._extract_message_id_header(msg_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_message_id_header_empty_value(self):
        """Test extracting Message-ID when value is empty."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {
            "payload": {
                "headers": [
                    {"name": "Message-ID", "value": ""},
                ]
            }
        }

        result = filter_module._extract_message_id_header(msg_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_message_id_header_no_payload(self):
        """Test extracting Message-ID when payload is missing."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {"id": "msg001"}

        result = filter_module._extract_message_id_header(msg_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_message_id_header_no_headers(self):
        """Test extracting Message-ID when headers list is missing."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        msg_data = {"payload": {}}

        result = filter_module._extract_message_id_header(msg_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_filter_by_rfc_id_with_mixed_results(self):
        """Test _filter_by_rfc_id with mix of duplicates and non-duplicates."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()

        # Simulate Gmail API responses
        async def mock_batch_generator(message_ids, format):
            responses = {
                "msg001": "<dup1@example.com>",  # Duplicate
                "msg002": "<unique@example.com>",  # Not duplicate
                "msg003": "<dup2@example.com>",  # Duplicate
                "msg004": None,  # No Message-ID header
            }
            for mid in message_ids:
                msg_data = {"id": mid, "payload": {"headers": []}}
                if responses[mid]:
                    msg_data["payload"]["headers"] = [
                        {"name": "Message-ID", "value": responses[mid]}
                    ]
                yield msg_data

        mock_gmail.get_messages_batch = mock_batch_generator

        known_rfc_ids = {"<dup1@example.com>", "<dup2@example.com>"}
        message_ids = ["msg001", "msg002", "msg003", "msg004"]

        duplicates, non_duplicates = await filter_module._filter_by_rfc_id(
            message_ids, mock_gmail, known_rfc_ids
        )

        assert set(duplicates) == {"msg001", "msg003"}
        assert set(non_duplicates) == {"msg002", "msg004"}

    @pytest.mark.asyncio
    async def test_filter_by_rfc_id_all_duplicates(self):
        """Test _filter_by_rfc_id when all messages are duplicates."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()

        async def mock_batch_generator(message_ids, format):
            for mid in message_ids:
                yield {
                    "id": mid,
                    "payload": {"headers": [{"name": "Message-ID", "value": f"<{mid}@dup.com>"}]},
                }

        mock_gmail.get_messages_batch = mock_batch_generator

        known_rfc_ids = {"<msg001@dup.com>", "<msg002@dup.com>"}
        message_ids = ["msg001", "msg002"]

        duplicates, non_duplicates = await filter_module._filter_by_rfc_id(
            message_ids, mock_gmail, known_rfc_ids
        )

        assert duplicates == ["msg001", "msg002"]
        assert non_duplicates == []

    @pytest.mark.asyncio
    async def test_filter_by_rfc_id_no_duplicates(self):
        """Test _filter_by_rfc_id when no messages are duplicates."""
        mock_db = Mock()
        filter_module = MessageFilter(db_manager=mock_db)

        mock_gmail = Mock()

        async def mock_batch_generator(message_ids, format):
            for mid in message_ids:
                yield {
                    "id": mid,
                    "payload": {
                        "headers": [{"name": "Message-ID", "value": f"<{mid}@unique.com>"}]
                    },
                }

        mock_gmail.get_messages_batch = mock_batch_generator

        known_rfc_ids = {"<other@example.com>"}
        message_ids = ["msg001", "msg002"]

        duplicates, non_duplicates = await filter_module._filter_by_rfc_id(
            message_ids, mock_gmail, known_rfc_ids
        )

        assert duplicates == []
        assert non_duplicates == ["msg001", "msg002"]


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
