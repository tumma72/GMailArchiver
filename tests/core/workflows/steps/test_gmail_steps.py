"""Behavior tests for Gmail workflow steps.

These tests verify the Gmail steps' behavior from a user's perspective:
- ScanGmailMessagesStep: Lists messages from Gmail matching criteria
- FilterGmailMessagesStep: Filters out already-archived messages
- DeleteGmailMessagesStep: Deletes or trashes messages from Gmail
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.gmail import (
    DeleteGmailInput,
    DeleteGmailMessagesStep,
    FilterGmailInput,
    FilterGmailMessagesStep,
    ScanGmailInput,
    ScanGmailMessagesStep,
)


@dataclass
class MockFilterResult:
    """Mock filter result matching ArchiverFacade.filter_already_archived output."""

    to_archive: list[str]
    already_archived_count: int
    duplicate_count: int
    total_skipped: int


class TestScanGmailMessagesStepBehavior:
    """Test ScanGmailMessagesStep behavior."""

    @pytest.fixture
    def mock_archiver(self) -> MagicMock:
        """Create mock ArchiverFacade."""
        archiver = MagicMock()
        archiver.list_messages_for_archive = AsyncMock()
        return archiver

    @pytest.mark.asyncio
    async def test_scans_messages_with_age_threshold(self, mock_archiver: MagicMock) -> None:
        """Given age threshold, scans Gmail for matching messages."""
        mock_archiver.list_messages_for_archive.return_value = (
            "before:2024/01/01",
            [{"id": "msg1", "threadId": "t1"}, {"id": "msg2", "threadId": "t2"}],
        )

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, ScanGmailInput(age_threshold="3y"))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_count == 2
        assert result.data.gmail_query == "before:2024/01/01"
        assert len(result.data.messages) == 2

    @pytest.mark.asyncio
    async def test_accepts_string_input(self, mock_archiver: MagicMock) -> None:
        """Step accepts string age threshold directly."""
        mock_archiver.list_messages_for_archive.return_value = ("before:2024/01/01", [])

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, "3y")

        assert result.success is True
        mock_archiver.list_messages_for_archive.assert_called_once_with("3y")

    @pytest.mark.asyncio
    async def test_handles_no_messages_found(self, mock_archiver: MagicMock) -> None:
        """When no messages match criteria, returns empty result."""
        mock_archiver.list_messages_for_archive.return_value = ("before:2024/01/01", [])

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, "3y")

        assert result.success is True
        assert result.data is not None
        assert result.data.total_count == 0
        assert result.data.messages == []

    @pytest.mark.asyncio
    async def test_stores_results_in_context(self, mock_archiver: MagicMock) -> None:
        """Step stores scan results in context for subsequent steps."""
        messages = [{"id": "msg1", "threadId": "t1"}, {"id": "msg2", "threadId": "t2"}]
        mock_archiver.list_messages_for_archive.return_value = ("before:2024/01/01", messages)

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        await step.execute(context, "3y")

        assert context.get(ContextKeys.GMAIL_QUERY) == "before:2024/01/01"
        assert context.get(ContextKeys.MESSAGES) == messages
        assert context.get(ContextKeys.MESSAGE_IDS) == ["msg1", "msg2"]

    @pytest.mark.asyncio
    async def test_handles_api_errors(self, mock_archiver: MagicMock) -> None:
        """Step returns failure result when API call fails."""
        mock_archiver.list_messages_for_archive.side_effect = Exception("API Error")

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, "3y")

        assert result.success is False
        assert "API Error" in str(result.error)

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        mock_archiver = MagicMock()
        step = ScanGmailMessagesStep(mock_archiver)

        assert step.name == "scan_gmail"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_reports_progress_with_messages(self, mock_archiver: MagicMock) -> None:
        """Step reports progress when messages are found."""
        mock_archiver.list_messages_for_archive.return_value = (
            "before:2024/01/01",
            [{"id": "msg1", "threadId": "t1"}],
        )

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

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, "3y", progress)

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "Found" in call_arg and "1" in call_arg

    @pytest.mark.asyncio
    async def test_reports_progress_no_messages(self, mock_archiver: MagicMock) -> None:
        """Step reports progress when no messages found."""
        mock_archiver.list_messages_for_archive.return_value = ("before:2024/01/01", [])

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

        step = ScanGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, "3y", progress)

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "No messages found" in call_arg


class TestFilterGmailMessagesStepBehavior:
    """Test FilterGmailMessagesStep behavior."""

    @pytest.fixture
    def mock_archiver(self) -> MagicMock:
        """Create mock ArchiverFacade."""
        archiver = MagicMock()
        archiver.filter_already_archived = AsyncMock()
        return archiver

    @pytest.mark.asyncio
    async def test_filters_already_archived(self, mock_archiver: MagicMock) -> None:
        """Given message IDs, filters out already-archived messages."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg3"],
            already_archived_count=1,
            duplicate_count=1,
            total_skipped=2,
        )

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(
            context, FilterGmailInput(message_ids=["msg1", "msg2", "msg3"], incremental=True)
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.to_archive == ["msg3"]
        assert result.data.already_archived_count == 1
        assert result.data.duplicate_count == 1

    @pytest.mark.asyncio
    async def test_accepts_list_input(self, mock_archiver: MagicMock) -> None:
        """Step accepts list of message IDs directly."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg1", "msg2"],
            already_archived_count=0,
            duplicate_count=0,
            total_skipped=0,
        )

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, ["msg1", "msg2"])

        assert result.success is True
        mock_archiver.filter_already_archived.assert_called_once_with(["msg1", "msg2"], True)

    @pytest.mark.asyncio
    async def test_reads_from_context(self, mock_archiver: MagicMock) -> None:
        """When input_data is None, reads message IDs from context."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg1"],
            already_archived_count=0,
            duplicate_count=0,
            total_skipped=0,
        )

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()
        context.set(ContextKeys.MESSAGE_IDS, ["msg1"])

        result = await step.execute(context, None)

        assert result.success is True
        mock_archiver.filter_already_archived.assert_called_once_with(["msg1"], True)

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, mock_archiver: MagicMock) -> None:
        """Given empty message list, returns empty result without calling API."""
        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, FilterGmailInput(message_ids=[], incremental=True))

        assert result.success is True
        assert result.data is not None
        assert result.data.to_archive == []
        mock_archiver.filter_already_archived.assert_not_called()

    @pytest.mark.asyncio
    async def test_stores_results_in_context(self, mock_archiver: MagicMock) -> None:
        """Step stores filter results in context for subsequent steps."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg3"],
            already_archived_count=1,
            duplicate_count=1,
            total_skipped=2,
        )

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        await step.execute(context, ["msg1", "msg2", "msg3"])

        assert context.get(ContextKeys.TO_ARCHIVE) == ["msg3"]
        assert context.get(ContextKeys.SKIPPED_COUNT) == 2
        assert context.get(ContextKeys.DUPLICATE_COUNT) == 1

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        mock_archiver = MagicMock()
        step = FilterGmailMessagesStep(mock_archiver)

        assert step.name == "filter_gmail"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_reports_progress_with_archived_and_duplicates(
        self, mock_archiver: MagicMock
    ) -> None:
        """Step reports progress showing archived and duplicate counts."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg3"],
            already_archived_count=1,
            duplicate_count=1,
            total_skipped=2,
        )

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

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, ["msg1", "msg2", "msg3"], progress)

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "1" in call_arg and "archive" in call_arg.lower()

    @pytest.mark.asyncio
    async def test_reports_progress_without_duplicates(self, mock_archiver: MagicMock) -> None:
        """Step reports progress when no duplicates found."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg1", "msg2"],
            already_archived_count=0,
            duplicate_count=0,
            total_skipped=0,
        )

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

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, ["msg1", "msg2"], progress)

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "2" in call_arg and "archive" in call_arg.lower()

    @pytest.mark.asyncio
    async def test_handles_filter_errors(self, mock_archiver: MagicMock) -> None:
        """Step returns failure result when filtering fails."""
        mock_archiver.filter_already_archived.side_effect = Exception("Database error")

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()

        result = await step.execute(context, ["msg1", "msg2"])

        assert result.success is False
        assert "Database error" in str(result.error)

    @pytest.mark.asyncio
    async def test_reads_incremental_from_context(self, mock_archiver: MagicMock) -> None:
        """When input is None and incremental is in context, uses that value."""
        mock_archiver.filter_already_archived.return_value = MockFilterResult(
            to_archive=["msg1"],
            already_archived_count=0,
            duplicate_count=0,
            total_skipped=0,
        )

        step = FilterGmailMessagesStep(mock_archiver)
        context = StepContext()
        context.set(ContextKeys.MESSAGE_IDS, ["msg1"])
        context.set("incremental", False)

        result = await step.execute(context, None)

        assert result.success is True
        mock_archiver.filter_already_archived.assert_called_once_with(["msg1"], False)


class TestDeleteGmailMessagesStepBehavior:
    """Test DeleteGmailMessagesStep behavior."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock GmailClient."""
        client = MagicMock()
        client.delete_messages_permanent = AsyncMock()
        client.trash_messages = AsyncMock()
        return client

    @pytest.fixture
    def mock_storage(self) -> MagicMock:
        """Create mock HybridStorage."""
        storage = MagicMock()
        storage.get_message_ids_for_archive = AsyncMock()
        return storage

    @pytest.mark.asyncio
    async def test_trashes_messages_by_default(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Given archive file, moves messages to trash."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1", "msg2"}

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(context, DeleteGmailInput(archive_file="archive.mbox"))

        assert result.success is True
        assert result.data is not None
        assert result.data.deleted_count == 2
        assert result.data.permanent is False
        mock_client.trash_messages.assert_called_once()
        mock_client.delete_messages_permanent.assert_not_called()

    @pytest.mark.asyncio
    async def test_permanently_deletes_when_requested(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Given permanent=True, permanently deletes messages."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1", "msg2"}

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(
            context, DeleteGmailInput(archive_file="archive.mbox", permanent=True)
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.permanent is True
        mock_client.delete_messages_permanent.assert_called_once()
        mock_client.trash_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_string_input(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Step accepts archive file path string directly."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1"}

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(context, "archive.mbox")

        assert result.success is True
        mock_storage.get_message_ids_for_archive.assert_called_once_with("archive.mbox")

    @pytest.mark.asyncio
    async def test_handles_no_messages_to_delete(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """When archive has no messages in database, returns empty result."""
        mock_storage.get_message_ids_for_archive.return_value = set()

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(context, "archive.mbox")

        assert result.success is True
        assert result.data is not None
        assert result.data.deleted_count == 0
        mock_client.trash_messages.assert_not_called()
        mock_client.delete_messages_permanent.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_api_errors(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Step returns failure result when API call fails."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1"}
        mock_client.trash_messages.side_effect = Exception("API Error")

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(context, "archive.mbox")

        assert result.success is False
        assert "API Error" in str(result.error)

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        mock_client = MagicMock()
        mock_storage = MagicMock()
        step = DeleteGmailMessagesStep(mock_client, mock_storage)

        assert step.name == "delete_gmail"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_reports_progress_when_trashing(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Step reports progress when trashing messages."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1", "msg2"}

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

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(context, "archive.mbox", progress)

        assert result.success is True
        task_cm.complete.assert_called_once()
        call_arg = task_cm.complete.call_args[0][0]
        assert "2" in call_arg

    @pytest.mark.asyncio
    async def test_reports_progress_when_permanently_deleting(
        self, mock_client: MagicMock, mock_storage: MagicMock
    ) -> None:
        """Step reports progress when permanently deleting messages."""
        mock_storage.get_message_ids_for_archive.return_value = {"msg1"}

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

        step = DeleteGmailMessagesStep(mock_client, mock_storage)
        context = StepContext()

        result = await step.execute(
            context, DeleteGmailInput(archive_file="archive.mbox", permanent=True), progress
        )

        assert result.success is True
        mock_client.delete_messages_permanent.assert_called_once()
        task_cm.complete.assert_called_once()
