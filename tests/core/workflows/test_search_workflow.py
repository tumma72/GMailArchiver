"""Behavior tests for SearchWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given a query, it searches messages in the database
- Reports progress during search
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.search._types import SearchResults
from gmailarchiver.core.workflows.search import (
    SearchConfig,
    SearchResult,
    SearchWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


@pytest.fixture
def mock_storage():
    """Create mock HybridStorage."""
    storage = MagicMock(spec=HybridStorage)
    storage.search_messages = AsyncMock()
    return storage


class TestSearchWorkflowBehavior:
    """Test SearchWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_storage):
        """Search returns results from storage."""
        # Setup mock search results
        mock_msg = MagicMock()
        mock_msg.gmail_id = "msg1"
        mock_msg.rfc_message_id = "<msg1@test.com>"
        mock_msg.subject = "Test Subject"
        mock_msg.from_addr = "sender@test.com"
        mock_msg.to_addr = "recipient@test.com"
        mock_msg.date = "2024-01-01 10:00:00"
        mock_msg.body_preview = "Test body preview"
        mock_msg.archive_file = "archive.mbox"
        mock_msg.mbox_offset = 100
        mock_msg.relevance_score = 1.5

        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 1
        mock_results.results = [mock_msg]
        mock_storage.search_messages.return_value = mock_results

        workflow = SearchWorkflow(mock_storage)
        config = SearchConfig(query="test")

        result = await workflow.run(config)

        assert isinstance(result, SearchResult)
        assert result.total_count == 1
        assert len(result.messages) == 1
        assert result.messages[0]["gmail_id"] == "msg1"
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_search_with_no_results(self, mock_storage):
        """Search returns empty result when no matches."""
        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 0
        mock_results.results = []
        mock_storage.search_messages.return_value = mock_results

        workflow = SearchWorkflow(mock_storage)
        config = SearchConfig(query="nonexistent")

        result = await workflow.run(config)

        assert result.total_count == 0
        assert len(result.messages) == 0

    @pytest.mark.asyncio
    async def test_reports_progress_with_results(self, mock_storage):
        """Reports progress when results are found."""
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        # Setup mock results
        mock_msg = MagicMock()
        mock_msg.gmail_id = "msg1"
        mock_msg.rfc_message_id = "<msg1@test.com>"
        mock_msg.subject = "Test"
        mock_msg.from_addr = "a@test.com"
        mock_msg.to_addr = "b@test.com"
        mock_msg.date = "2024-01-01"
        mock_msg.body_preview = "Preview"
        mock_msg.archive_file = "archive.mbox"
        mock_msg.mbox_offset = 0
        mock_msg.relevance_score = 1.0

        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 5
        mock_results.results = [mock_msg] * 5
        mock_storage.search_messages.return_value = mock_results

        config = SearchConfig(query="test")
        workflow = SearchWorkflow(mock_storage, progress=progress)

        result = await workflow.run(config)

        # Verify progress was called with completion message
        task_cm.complete.assert_called()
        call_args = task_cm.complete.call_args_list[0][0][0]
        assert "5" in call_args  # Should show count

    @pytest.mark.asyncio
    async def test_reports_progress_no_results(self, mock_storage):
        """Reports progress when no results are found."""
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 0
        mock_results.results = []
        mock_storage.search_messages.return_value = mock_results

        config = SearchConfig(query="nonexistent")
        workflow = SearchWorkflow(mock_storage, progress=progress)

        result = await workflow.run(config)

        # Verify progress was called with no results message
        task_cm.complete.assert_called()
        call_args = task_cm.complete.call_args_list[0][0][0]
        assert "No messages found" in call_args

    @pytest.mark.asyncio
    async def test_sort_ascending(self, mock_storage):
        """Search returns results sorted ascending by date."""
        # Create messages with different dates
        mock_msg1 = MagicMock()
        mock_msg1.gmail_id = "msg1"
        mock_msg1.rfc_message_id = "<msg1@test.com>"
        mock_msg1.subject = "Test 1"
        mock_msg1.from_addr = "a@test.com"
        mock_msg1.to_addr = "b@test.com"
        mock_msg1.date = "2024-01-01"
        mock_msg1.body_preview = ""
        mock_msg1.archive_file = "archive.mbox"
        mock_msg1.mbox_offset = 0
        mock_msg1.relevance_score = 1.0

        mock_msg2 = MagicMock()
        mock_msg2.gmail_id = "msg2"
        mock_msg2.rfc_message_id = "<msg2@test.com>"
        mock_msg2.subject = "Test 2"
        mock_msg2.from_addr = "a@test.com"
        mock_msg2.to_addr = "b@test.com"
        mock_msg2.date = "2024-01-15"
        mock_msg2.body_preview = ""
        mock_msg2.archive_file = "archive.mbox"
        mock_msg2.mbox_offset = 100
        mock_msg2.relevance_score = 1.0

        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 2
        mock_results.results = [mock_msg2, mock_msg1]  # Out of order
        mock_storage.search_messages.return_value = mock_results

        workflow = SearchWorkflow(mock_storage)
        config = SearchConfig(query="test", sort_ascending=True)

        result = await workflow.run(config)

        # First message should be oldest
        assert result.messages[0]["date"] == "2024-01-01"
        assert result.messages[1]["date"] == "2024-01-15"

    @pytest.mark.asyncio
    async def test_sort_descending_default(self, mock_storage):
        """Search returns results sorted descending by date (default)."""
        mock_msg1 = MagicMock()
        mock_msg1.gmail_id = "msg1"
        mock_msg1.rfc_message_id = "<msg1@test.com>"
        mock_msg1.subject = "Test 1"
        mock_msg1.from_addr = "a@test.com"
        mock_msg1.to_addr = "b@test.com"
        mock_msg1.date = "2024-01-01"
        mock_msg1.body_preview = ""
        mock_msg1.archive_file = "archive.mbox"
        mock_msg1.mbox_offset = 0
        mock_msg1.relevance_score = 1.0

        mock_msg2 = MagicMock()
        mock_msg2.gmail_id = "msg2"
        mock_msg2.rfc_message_id = "<msg2@test.com>"
        mock_msg2.subject = "Test 2"
        mock_msg2.from_addr = "a@test.com"
        mock_msg2.to_addr = "b@test.com"
        mock_msg2.date = "2024-01-15"
        mock_msg2.body_preview = ""
        mock_msg2.archive_file = "archive.mbox"
        mock_msg2.mbox_offset = 100
        mock_msg2.relevance_score = 1.0

        mock_results = MagicMock(spec=SearchResults)
        mock_results.total_results = 2
        mock_results.results = [mock_msg1, mock_msg2]  # Out of order
        mock_storage.search_messages.return_value = mock_results

        workflow = SearchWorkflow(mock_storage)
        config = SearchConfig(query="test")  # Default sort_ascending=False

        result = await workflow.run(config)

        # First message should be newest
        assert result.messages[0]["date"] == "2024-01-15"
        assert result.messages[1]["date"] == "2024-01-01"
