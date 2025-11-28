"""Unit tests for MessageFilter (archiver package internal module).

This module contains fast, isolated unit tests with no I/O or external
dependencies. DBManager is mocked to avoid database access.
"""

from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.archiver._filter import MessageFilter


class TestMessageFilter:
    """Unit tests for MessageFilter internal module."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db = Mock()
        cursor = Mock()
        # Simulate database with msg001 and msg002 already archived
        cursor.fetchall.return_value = [("msg001",), ("msg002",)]
        db.conn.execute.return_value = cursor
        db.close = Mock()
        return db

    @pytest.fixture
    def filter_module(self):
        """Create MessageFilter instance."""
        return MessageFilter(state_db_path="/tmp/test.db")

    @pytest.mark.unit
    def test_filter_with_incremental_false(self, filter_module):
        """Test that incremental=False returns all messages."""
        message_ids = ["msg001", "msg002", "msg003"]

        filtered, skipped = filter_module.filter_archived(message_ids, incremental=False)

        assert filtered == message_ids
        assert skipped == 0

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_with_incremental_true(self, mock_db_class, filter_module, mock_db_manager):
        """Test filtering out already-archived messages."""
        mock_db_class.return_value = mock_db_manager
        message_ids = ["msg001", "msg002", "msg003", "msg004"]

        filtered, skipped = filter_module.filter_archived(message_ids, incremental=True)

        # msg001 and msg002 should be filtered out
        assert filtered == ["msg003", "msg004"]
        assert skipped == 2

        # Should query database for archived IDs
        mock_db_manager.conn.execute.assert_called_once()
        query = mock_db_manager.conn.execute.call_args[0][0]
        assert "SELECT gmail_id FROM messages" in query
        assert "gmail_id IS NOT NULL" in query

        # Should close database connection
        mock_db_manager.close.assert_called_once()

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_with_no_archived_messages(self, mock_db_class, filter_module):
        """Test filtering when no messages are archived."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = []
        mock_db.conn.execute.return_value = cursor
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        message_ids = ["msg001", "msg002", "msg003"]

        filtered, skipped = filter_module.filter_archived(message_ids, incremental=True)

        assert filtered == message_ids
        assert skipped == 0

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_with_all_archived(self, mock_db_class, filter_module):
        """Test filtering when all messages are already archived."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = [("msg001",), ("msg002",), ("msg003",)]
        mock_db.conn.execute.return_value = cursor
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        message_ids = ["msg001", "msg002", "msg003"]

        filtered, skipped = filter_module.filter_archived(message_ids, incremental=True)

        assert filtered == []
        assert skipped == 3

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_handles_database_error(self, mock_db_class, filter_module):
        """Test that database errors are handled gracefully."""
        mock_db_class.side_effect = Exception("Database error")

        message_ids = ["msg001", "msg002", "msg003"]

        # Should return all messages if database fails
        filtered, skipped = filter_module.filter_archived(message_ids, incremental=True)

        assert filtered == message_ids
        assert skipped == 0

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_with_empty_message_list(self, mock_db_class, filter_module, mock_db_manager):
        """Test filtering with empty message list."""
        mock_db_class.return_value = mock_db_manager

        filtered, skipped = filter_module.filter_archived([], incremental=True)

        assert filtered == []
        assert skipped == 0

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_validates_schema(self, mock_db_class, filter_module):
        """Test that DBManager is created with correct parameters."""
        mock_db = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = []
        mock_db.conn.execute.return_value = cursor
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        filter_module.filter_archived(["msg001"], incremental=True)

        # Should create DBManager with validate_schema=False and auto_create=True
        mock_db_class.assert_called_once_with(
            "/tmp/test.db", validate_schema=False, auto_create=True
        )

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._filter.DBManager")
    def test_filter_excludes_null_gmail_ids(self, mock_db_class, filter_module, mock_db_manager):
        """Test that query excludes NULL gmail_ids (deleted messages)."""
        mock_db_class.return_value = mock_db_manager

        filter_module.filter_archived(["msg003"], incremental=True)

        # Should include WHERE clause to exclude NULL gmail_ids
        query = mock_db_manager.conn.execute.call_args[0][0]
        assert "gmail_id IS NOT NULL" in query
