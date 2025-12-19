"""Behavior tests for WriteMessagesStep.

These tests verify the step's behavior from a user's perspective:
- Archives messages to mbox file
- Reports progress and results correctly
- Handles interruptions gracefully
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.write import (
    WriteMessagesInput,
    WriteMessagesStep,
)


class TestWriteMessagesStepBehavior:
    """Test WriteMessagesStep behavior."""

    @pytest.fixture
    def mock_archiver(self) -> MagicMock:
        """Create mock ArchiverFacade."""
        archiver = MagicMock()
        archiver.archive_messages = AsyncMock()
        return archiver

    @pytest.mark.asyncio
    async def test_archives_messages_to_file(self, mock_archiver: MagicMock) -> None:
        """Given message IDs, archives them to mbox file."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 100,
            "failed_count": 0,
            "actual_file": "archive_20241218.mbox",
            "interrupted": False,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(
                message_ids=["msg1", "msg2", "msg3"],
                output_file="archive.mbox",
                compress=None,
            ),
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.archived_count == 100
        assert result.data.failed_count == 0
        assert result.data.interrupted is False

    @pytest.mark.asyncio
    async def test_reads_from_context(self, mock_archiver: MagicMock) -> None:
        """When input_data is None, reads configuration from context."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 2,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": False,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()
        context.set(ContextKeys.TO_ARCHIVE, ["msg1", "msg2"])
        context.set(ContextKeys.ARCHIVE_FILE, "archive.mbox")
        context.set(ContextKeys.GMAIL_QUERY, "before:2024/01/01")

        result = await step.execute(context, None)

        assert result.success is True
        mock_archiver.archive_messages.assert_called_once()
        call_args = mock_archiver.archive_messages.call_args
        assert call_args[0][0] == ["msg1", "msg2"]
        assert call_args[0][1] == "archive.mbox"

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, mock_archiver: MagicMock) -> None:
        """Given empty message list, returns empty result without calling archiver."""
        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=[], output_file="archive.mbox"),
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.archived_count == 0
        mock_archiver.archive_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_interruption(self, mock_archiver: MagicMock) -> None:
        """When archiving is interrupted, returns partial result."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 50,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": True,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.interrupted is True
        assert result.data.archived_count == 50

    @pytest.mark.asyncio
    async def test_stores_results_in_context(self, mock_archiver: MagicMock) -> None:
        """Step stores archive results in context for subsequent steps."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 100,
            "failed_count": 0,
            "actual_file": "archive_20241218.mbox.gz",
            "interrupted": False,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        await step.execute(
            context,
            WriteMessagesInput(
                message_ids=["msg1"],
                output_file="archive.mbox",
                compress="gzip",
            ),
        )

        assert context.get(ContextKeys.ARCHIVED_COUNT) == 100
        assert context.get(ContextKeys.ACTUAL_FILE) == "archive_20241218.mbox.gz"

    @pytest.mark.asyncio
    async def test_passes_compression_option(self, mock_archiver: MagicMock) -> None:
        """Step passes compression option to archiver."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 1,
            "failed_count": 0,
            "actual_file": "archive.mbox.gz",
            "interrupted": False,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        await step.execute(
            context,
            WriteMessagesInput(
                message_ids=["msg1"],
                output_file="archive.mbox",
                compress="gzip",
                gmail_query="before:2024/01/01",
            ),
        )

        mock_archiver.archive_messages.assert_called_once()
        call_args = mock_archiver.archive_messages.call_args
        assert call_args[0][2] == "gzip"  # compress argument
        assert call_args[0][4] == "before:2024/01/01"  # gmail_query argument

    @pytest.mark.asyncio
    async def test_handles_errors(self, mock_archiver: MagicMock) -> None:
        """Step returns failure result when archiving fails."""
        mock_archiver.archive_messages.side_effect = Exception("Disk full")

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
        )

        assert result.success is False
        assert "Disk full" in str(result.error)

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        mock_archiver = MagicMock()
        step = WriteMessagesStep(mock_archiver)

        assert step.name == "write_messages"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_reports_count_in_metadata(self, mock_archiver: MagicMock) -> None:
        """Step result includes count in metadata."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 42,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": False,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
        )

        assert result.success is True
        assert result.metadata.get("count") == 42

    @pytest.mark.asyncio
    async def test_reports_progress_during_archive(self, mock_archiver: MagicMock) -> None:
        """Step reports progress with task handle."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 100,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": False,
        }

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

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1", "msg2"], output_file="archive.mbox"),
            progress,
        )

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "100" in call_arg

    @pytest.mark.asyncio
    async def test_reports_progress_on_interruption(self, mock_archiver: MagicMock) -> None:
        """Step reports progress when interrupted."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 50,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": True,
        }

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

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
            progress,
        )

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "Interrupted" in call_arg

    @pytest.mark.asyncio
    async def test_reports_progress_no_messages(self, mock_archiver: MagicMock) -> None:
        """Step reports progress when no messages archived."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 0,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": False,
        }

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

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
            progress,
        )

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "No messages" in call_arg

    @pytest.mark.asyncio
    async def test_writes_interrupted_to_context(self, mock_archiver: MagicMock) -> None:
        """When write is interrupted, step writes 'interrupted' key to context as True."""
        mock_archiver.archive_messages.return_value = {
            "archived_count": 50,
            "failed_count": 0,
            "actual_file": "archive.mbox",
            "interrupted": True,
        }

        step = WriteMessagesStep(mock_archiver)
        context = StepContext()

        await step.execute(
            context,
            WriteMessagesInput(message_ids=["msg1"], output_file="archive.mbox"),
        )

        assert "interrupted" in context
        assert context.get("interrupted") is True
