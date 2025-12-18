"""Behavior tests for CheckDuplicatesStep.

These tests verify the step's behavior from a user's perspective:
- Given messages and a database, it identifies which are duplicates
- It respects the skip_duplicates setting
"""

import pytest

from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.filter import (
    CheckDuplicatesStep,
    FilterInput,
)
from gmailarchiver.data.db_manager import DBManager


class TestCheckDuplicatesStepBehavior:
    """Test CheckDuplicatesStep behavior."""

    @pytest.mark.asyncio
    async def test_filters_out_duplicates(self, db_manager_with_messages: DBManager) -> None:
        """Given messages including duplicates, filters them out."""
        step = CheckDuplicatesStep(db_manager_with_messages)
        context = StepContext()

        # 3 messages: 2 are duplicates of existing, 1 is new
        scanned_messages = [
            ("<existing1@example.com>", 0, 100),  # duplicate
            ("<existing2@example.com>", 100, 100),  # duplicate
            ("<new@example.com>", 200, 100),  # new
        ]

        result = await step.execute(context, FilterInput(scanned_messages, skip_duplicates=True))

        assert result.success is True
        assert result.data is not None
        assert result.data.new_count == 1
        assert result.data.duplicate_count == 2
        # Only the new message should be in to_process
        assert len(result.data.to_process) == 1
        assert result.data.to_process[0][0] == "<new@example.com>"

    @pytest.mark.asyncio
    async def test_all_new_when_database_empty(self, db_manager: DBManager) -> None:
        """Given empty database, all messages are new."""
        step = CheckDuplicatesStep(db_manager)
        context = StepContext()

        scanned_messages = [
            ("<msg1@example.com>", 0, 100),
            ("<msg2@example.com>", 100, 100),
            ("<msg3@example.com>", 200, 100),
        ]

        result = await step.execute(context, FilterInput(scanned_messages, skip_duplicates=True))

        assert result.success is True
        assert result.data is not None
        assert result.data.new_count == 3
        assert result.data.duplicate_count == 0
        assert len(result.data.to_process) == 3

    @pytest.mark.asyncio
    async def test_skip_duplicates_false_keeps_all(
        self, db_manager_with_messages: DBManager
    ) -> None:
        """When skip_duplicates=False, all messages are kept."""
        step = CheckDuplicatesStep(db_manager_with_messages)
        context = StepContext()

        scanned_messages = [
            ("<existing1@example.com>", 0, 100),  # would be duplicate
            ("<new@example.com>", 100, 100),
        ]

        result = await step.execute(context, FilterInput(scanned_messages, skip_duplicates=False))

        assert result.success is True
        assert result.data is not None
        assert result.data.new_count == 2  # All kept
        assert result.data.duplicate_count == 0
        assert len(result.data.to_process) == 2

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, db_manager: DBManager) -> None:
        """Given empty message list, returns empty result."""
        step = CheckDuplicatesStep(db_manager)
        context = StepContext()

        result = await step.execute(context, FilterInput([], skip_duplicates=True))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_count == 0
        assert result.data.new_count == 0
        assert result.data.to_process == []

    @pytest.mark.asyncio
    async def test_reads_from_context_when_no_input(self, db_manager: DBManager) -> None:
        """When input_data is None, reads messages from context."""
        step = CheckDuplicatesStep(db_manager)
        context = StepContext()

        # Store messages in context (as ScanMboxStep would)
        context.set(
            ContextKeys.MESSAGES,
            [
                ("<ctx1@example.com>", 0, 100),
                ("<ctx2@example.com>", 100, 100),
            ],
        )

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        assert result.data.new_count == 2

    @pytest.mark.asyncio
    async def test_accepts_list_directly(self, db_manager: DBManager) -> None:
        """Step accepts a list of tuples directly as input."""
        step = CheckDuplicatesStep(db_manager)
        context = StepContext()

        scanned_messages = [
            ("<direct1@example.com>", 0, 100),
            ("<direct2@example.com>", 100, 100),
        ]

        # Pass list directly instead of FilterInput
        result = await step.execute(context, scanned_messages)

        assert result.success is True
        assert result.data is not None
        assert result.data.new_count == 2

    @pytest.mark.asyncio
    async def test_stores_results_in_context(self, db_manager_with_messages: DBManager) -> None:
        """Step stores filter results in context for subsequent steps."""
        step = CheckDuplicatesStep(db_manager_with_messages)
        context = StepContext()

        scanned_messages = [
            ("<existing1@example.com>", 0, 100),
            ("<new@example.com>", 100, 100),
        ]

        await step.execute(context, FilterInput(scanned_messages, skip_duplicates=True))

        # Check context has results
        assert ContextKeys.DUPLICATE_COUNT in context
        assert context.get(ContextKeys.DUPLICATE_COUNT) == 1

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        # Create a minimal mock db_manager
        from unittest.mock import MagicMock

        mock_db = MagicMock()
        step = CheckDuplicatesStep(mock_db)

        assert step.name == "check_duplicates"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_output_has_correct_totals(self, db_manager_with_messages: DBManager) -> None:
        """Output includes correct total counts."""
        step = CheckDuplicatesStep(db_manager_with_messages)
        context = StepContext()

        scanned_messages = [
            ("<existing1@example.com>", 0, 100),
            ("<existing2@example.com>", 100, 100),
            ("<new1@example.com>", 200, 100),
            ("<new2@example.com>", 300, 100),
        ]

        result = await step.execute(context, FilterInput(scanned_messages, skip_duplicates=True))

        assert result.data is not None
        assert result.data.total_count == 4
        assert result.data.new_count == 2
        assert result.data.duplicate_count == 2


class TestCheckDuplicatesStepWithProgress:
    """Test filtering with progress reporting."""

    @pytest.mark.asyncio
    async def test_reports_progress_with_duplicates(
        self, db_manager_with_messages: DBManager
    ) -> None:
        """Filter reports progress with duplicate count when found."""
        from unittest.mock import MagicMock

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

        step = CheckDuplicatesStep(db_manager_with_messages)
        context = StepContext()

        scanned_messages = [
            ("<existing1@example.com>", 0, 100),  # duplicate
            ("<new@example.com>", 100, 100),  # new
        ]

        result = await step.execute(
            context, FilterInput(scanned_messages, skip_duplicates=True), progress
        )

        assert result.success is True
        progress.task_sequence.assert_called_once()
        # Check that complete was called with duplicate info
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "1" in call_arg and "duplicate" in call_arg.lower()

    @pytest.mark.asyncio
    async def test_reports_progress_without_duplicates(self, db_manager: DBManager) -> None:
        """Filter reports progress without duplicate count when none found."""
        from unittest.mock import MagicMock

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

        step = CheckDuplicatesStep(db_manager)
        context = StepContext()

        scanned_messages = [
            ("<new1@example.com>", 0, 100),
            ("<new2@example.com>", 100, 100),
        ]

        result = await step.execute(
            context, FilterInput(scanned_messages, skip_duplicates=True), progress
        )

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "2" in call_arg and "process" in call_arg.lower()
