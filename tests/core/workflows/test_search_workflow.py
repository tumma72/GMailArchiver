"""Behavior tests for SearchWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given a query, it searches messages in the database
- Reports progress during search
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.core.workflows.search import (
    SearchConfig,
    SearchWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


class TestSearchWorkflowBehavior:
    """Test SearchWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_reports_progress_with_results(
        self, hybrid_storage: HybridStorage
    ) -> None:
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

        config = SearchConfig(
            query="test",
            state_db=str(hybrid_storage.db.db_path),
        )

        workflow = SearchWorkflow(hybrid_storage, progress=progress)

        # Mock the search facade to return results
        mock_search_result = MagicMock()
        mock_search_result.total_results = 5
        mock_search_result.results = [MagicMock() for _ in range(5)]

        with patch("gmailarchiver.core.workflows.search.SearchFacade") as MockSearch:
            mock_search_instance = AsyncMock()
            mock_search_instance.search = AsyncMock(return_value=mock_search_result)

            # Set up async context manager
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_search_instance)
            mock_context_manager.__aexit__ = AsyncMock()
            MockSearch.create = AsyncMock(return_value=mock_context_manager)

            result = await workflow.run(config)

        # Verify progress was called with completion message
        task_cm.complete.assert_called()
        call_args = task_cm.complete.call_args_list[0][0][0]
        assert "5" in call_args  # Should show count

    @pytest.mark.asyncio
    async def test_reports_progress_no_results(
        self, hybrid_storage: HybridStorage
    ) -> None:
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

        config = SearchConfig(
            query="nonexistent",
            state_db=str(hybrid_storage.db.db_path),
        )

        workflow = SearchWorkflow(hybrid_storage, progress=progress)

        # Mock the search facade to return no results
        mock_search_result = MagicMock()
        mock_search_result.total_results = 0
        mock_search_result.results = []

        with patch("gmailarchiver.core.workflows.search.SearchFacade") as MockSearch:
            mock_search_instance = AsyncMock()
            mock_search_instance.search = AsyncMock(return_value=mock_search_result)

            # Set up async context manager
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_search_instance)
            mock_context_manager.__aexit__ = AsyncMock()
            MockSearch.create = AsyncMock(return_value=mock_context_manager)

            result = await workflow.run(config)

        # Verify progress was called with no results message
        task_cm.complete.assert_called()
        call_args = task_cm.complete.call_args_list[0][0][0]
        assert "No messages found" in call_args
