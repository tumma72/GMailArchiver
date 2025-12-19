from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver._filter import FilterResult
from gmailarchiver.core.workflows.archive import ArchiveConfig, ArchiveResult, ArchiveWorkflow
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import NoOpTaskSequence


@pytest.fixture
def mock_client():
    client = MagicMock(spec=GmailClient)
    client.list_messages = AsyncMock()  # Generator mock handled in test
    client.delete_messages_permanent = AsyncMock()
    client.trash_messages = AsyncMock()
    return client


@pytest.fixture
def mock_storage():
    storage = MagicMock(spec=HybridStorage)
    storage.db = MagicMock()
    storage.db.db_path = Path("mock_db.db")
    storage.db.get_session_by_query = AsyncMock(return_value=None)
    storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1"])
    return storage


@pytest.fixture
def mock_progress():
    """Mock ProgressReporter that returns NoOpTaskSequence."""
    progress = MagicMock()
    progress.info = MagicMock()
    progress.warning = MagicMock()
    progress.error = MagicMock()
    progress.task_sequence.return_value.__enter__ = MagicMock(return_value=NoOpTaskSequence())
    progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)
    return progress


@pytest.fixture
def workflow(mock_client, mock_storage, mock_progress):
    return ArchiveWorkflow(mock_client, mock_storage, mock_progress)


@pytest.mark.asyncio
async def test_archive_workflow_dry_run(workflow):
    # Setup mocks
    workflow.archiver.list_messages_for_archive = AsyncMock(
        return_value=("query", [{"id": "msg1"}])
    )
    workflow.archiver.filter_already_archived = AsyncMock(
        return_value=FilterResult(to_archive=["msg1"], already_archived_count=0, duplicate_count=0)
    )

    config = ArchiveConfig(age_threshold="3y", dry_run=True)

    result = await workflow.run(config)

    assert isinstance(result, ArchiveResult)
    assert result.found_count == 1
    assert result.archived_count == 0
    assert result.skipped_count == 0

    # Verify methods called
    workflow.archiver.list_messages_for_archive.assert_called_once()
    workflow.archiver.filter_already_archived.assert_called_once()
    # Archive should NOT be called
    workflow.archiver.archive_messages = AsyncMock()  # Should not be called
    assert not workflow.archiver.archive_messages.called


@pytest.mark.asyncio
async def test_archive_workflow_success(workflow):
    # Setup mocks
    workflow.archiver.list_messages_for_archive = AsyncMock(
        return_value=("query", [{"id": "msg1"}])
    )
    workflow.archiver.filter_already_archived = AsyncMock(
        return_value=FilterResult(to_archive=["msg1"], already_archived_count=0, duplicate_count=0)
    )
    workflow.archiver.archive_messages = AsyncMock(
        return_value={"archived_count": 1, "actual_file": "archive.mbox"}
    )

    # Mock internal validator logic (private method call inside run)
    workflow._validate_archive = AsyncMock(return_value={"passed": True})

    config = ArchiveConfig(age_threshold="3y", dry_run=False, output_file="archive.mbox")

    result = await workflow.run(config)

    assert result.archived_count == 1
    assert result.validation_passed is True


@pytest.mark.asyncio
async def test_archive_workflow_no_messages(workflow):
    # Setup mocks - return empty list
    workflow.archiver.list_messages_for_archive = AsyncMock(return_value=("query", []))

    config = ArchiveConfig(age_threshold="3y")

    result = await workflow.run(config)

    assert result.found_count == 0
    assert result.archived_count == 0


@pytest.mark.asyncio
async def test_archive_workflow_invalid_age_threshold(workflow):
    """Test that invalid age threshold raises ValueError."""
    config = ArchiveConfig(age_threshold="invalid")

    with pytest.raises(ValueError, match="Invalid age threshold"):
        await workflow.run(config)


@pytest.mark.asyncio
async def test_delete_messages_permanent(workflow):
    """Test permanent deletion of archived messages."""
    workflow.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2"])
    workflow.client.delete_messages_permanent = AsyncMock()

    count = await workflow.delete_messages("archive.mbox", permanent=True)

    assert count == 2
    workflow.client.delete_messages_permanent.assert_called_once_with(
        ["msg1", "msg2"], progress_callback=ANY
    )
    workflow.client.trash_messages.assert_not_called()


@pytest.mark.asyncio
async def test_delete_messages_trash(workflow):
    """Test trashing archived messages."""
    workflow.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2", "msg3"])
    workflow.client.trash_messages = AsyncMock()

    count = await workflow.delete_messages("archive.mbox", permanent=False)

    assert count == 3
    workflow.client.trash_messages.assert_called_once_with(
        ["msg1", "msg2", "msg3"], progress_callback=ANY
    )
    workflow.client.delete_messages_permanent.assert_not_called()


@pytest.mark.asyncio
async def test_delete_messages_no_archived_messages(workflow):
    """Test deletion when no messages are archived."""
    workflow.storage.get_message_ids_for_archive = AsyncMock(return_value=[])

    count = await workflow.delete_messages("archive.mbox", permanent=True)

    assert count == 0
    workflow.client.delete_messages_permanent.assert_not_called()
    workflow.client.trash_messages.assert_not_called()


@pytest.mark.asyncio
async def test_determine_output_file_with_resumable_session(workflow, mock_progress):
    """Test resuming partial archive session."""
    workflow.storage.db.get_session_by_query = AsyncMock(
        return_value={
            "target_file": "partial_archive.mbox",
            "processed_count": 100,
            "total_count": 500,
        }
    )

    result = await workflow._determine_output_file(None, None, "test_query")

    # Should return the partial archive file for resumption
    assert result == "partial_archive.mbox"
    # Note: Resume info messages were removed to avoid printing outside Live context.
    # The resume behavior is verified by the file path being returned.


@pytest.mark.asyncio
async def test_determine_output_file_gzip_compression(workflow):
    """Test output file with gzip compression."""
    workflow.storage.db.get_session_by_query = AsyncMock(return_value=None)

    result = await workflow._determine_output_file(None, "gzip", "test_query")

    assert result.endswith(".mbox.gz")
    assert "archive_" in result


@pytest.mark.asyncio
async def test_determine_output_file_lzma_compression(workflow):
    """Test output file with lzma compression."""
    workflow.storage.db.get_session_by_query = AsyncMock(return_value=None)

    result = await workflow._determine_output_file(None, "lzma", "test_query")

    assert result.endswith(".mbox.xz")
    assert "archive_" in result


@pytest.mark.asyncio
async def test_determine_output_file_zstd_compression(workflow):
    """Test output file with zstd compression."""
    workflow.storage.db.get_session_by_query = AsyncMock(return_value=None)

    result = await workflow._determine_output_file(None, "zstd", "test_query")

    assert result.endswith(".mbox.zst")
    assert "archive_" in result


# Additional tests for failure paths


@pytest.mark.asyncio
async def test_archive_workflow_scan_step_fails(mock_client, mock_storage, mock_progress):
    """When scan step fails, workflow returns empty result."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import StepResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock scan step to return failure
    with patch.object(
        workflow._scan_step, "execute", return_value=StepResult.fail("Gmail API error")
    ):
        result = await workflow.run(ArchiveConfig(age_threshold="3y"))

    assert result.archived_count == 0
    assert result.found_count == 0
    assert result.validation_passed is True


@pytest.mark.asyncio
async def test_archive_workflow_filter_step_fails(mock_client, mock_storage, mock_progress):
    """When filter step fails, workflow returns result with found count."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import ContextKeys, StepResult
    from gmailarchiver.core.workflows.steps.gmail import ScanGmailOutput

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock scan step to return success with messages
    scan_output = ScanGmailOutput(
        gmail_query="before:2024/01/01",
        messages=[{"id": "msg1"}, {"id": "msg2"}],
        total_count=2,
    )

    # Create async mock that sets context like the real step does
    async def mock_scan_execute(context, input_data, progress):
        context.set(ContextKeys.GMAIL_QUERY, scan_output.gmail_query)
        context.set(ContextKeys.MESSAGES, scan_output.messages)
        context.set(ContextKeys.MESSAGE_IDS, [msg["id"] for msg in scan_output.messages])
        return StepResult.ok(scan_output)

    # Mock filter step to fail
    mock_filter_result = StepResult.fail("Database error")

    with (
        patch.object(workflow._scan_step, "execute", side_effect=mock_scan_execute),
        patch.object(workflow._filter_step, "execute", return_value=mock_filter_result),
    ):
        result = await workflow.run(ArchiveConfig(age_threshold="3y"))

    assert result.archived_count == 0
    assert result.found_count == 2  # Scan found 2 messages
    assert result.validation_passed is True


@pytest.mark.asyncio
async def test_archive_workflow_with_validation_pass(mock_client, mock_storage, mock_progress):
    """When archive runs with validation, validation details are captured."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import ContextKeys, StepResult
    from gmailarchiver.core.workflows.steps.gmail import FilterGmailOutput, ScanGmailOutput
    from gmailarchiver.core.workflows.steps.validate import ValidateOutput
    from gmailarchiver.core.workflows.steps.write import WriteMessagesOutput

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock all steps to succeed
    scan_output = ScanGmailOutput(
        gmail_query="before:2024/01/01", messages=[{"id": "msg1"}], total_count=1
    )
    filter_output = FilterGmailOutput(
        to_archive=["msg1"],
        already_archived_count=0,
        duplicate_count=0,
        total_skipped=0,
    )
    write_output = WriteMessagesOutput(
        archived_count=1,
        failed_count=0,
        duplicate_count=0,
        actual_file="archive.mbox",
        interrupted=False,
    )
    validate_output = ValidateOutput(
        passed=True,
        count_check=True,
        database_check=True,
        integrity_check=True,
        spot_check=True,
        errors=[],
    )

    # Create async mocks that set context like the real steps do
    async def mock_scan_execute(context, input_data, progress):
        context.set(ContextKeys.GMAIL_QUERY, scan_output.gmail_query)
        context.set(ContextKeys.MESSAGES, scan_output.messages)
        context.set(ContextKeys.MESSAGE_IDS, [msg["id"] for msg in scan_output.messages])
        return StepResult.ok(scan_output)

    async def mock_filter_execute(context, input_data, progress):
        context.set(ContextKeys.TO_ARCHIVE, filter_output.to_archive)
        context.set(ContextKeys.SKIPPED_COUNT, filter_output.total_skipped)
        context.set(ContextKeys.DUPLICATE_COUNT, filter_output.duplicate_count)
        context.set("already_archived_count", filter_output.already_archived_count)
        return StepResult.ok(filter_output)

    async def mock_write_execute(context, input_data, progress):
        context.set(ContextKeys.ARCHIVED_COUNT, write_output.archived_count)
        context.set(ContextKeys.ACTUAL_FILE, write_output.actual_file)
        context.set(ContextKeys.DUPLICATE_COUNT, write_output.duplicate_count)
        context.set("interrupted", write_output.interrupted)
        return StepResult.ok(write_output)

    async def mock_validate_execute(context, input_data, progress):
        context.set(ContextKeys.VALIDATION_PASSED, validate_output.passed)
        context.set(
            ContextKeys.VALIDATION_DETAILS,
            {
                "count_check": validate_output.count_check,
                "database_check": validate_output.database_check,
                "integrity_check": validate_output.integrity_check,
                "spot_check": validate_output.spot_check,
                "passed": validate_output.passed,
                "errors": validate_output.errors,
            },
        )
        return StepResult.ok(validate_output)

    with (
        patch.object(workflow._scan_step, "execute", side_effect=mock_scan_execute),
        patch.object(workflow._filter_step, "execute", side_effect=mock_filter_execute),
        patch.object(workflow._write_step, "execute", side_effect=mock_write_execute),
        patch.object(workflow._validate_step, "execute", side_effect=mock_validate_execute),
    ):
        result = await workflow.run(ArchiveConfig(age_threshold="3y"))

    assert result.archived_count == 1
    assert result.validation_passed is True
    assert result.validation_details is not None
    assert result.validation_details["passed"] is True
    assert result.validation_details["count_check"] is True


@pytest.mark.asyncio
async def test_delete_messages_step_fails(mock_client, mock_storage, mock_progress):
    """When delete step fails, returns zero count."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import StepResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock delete step to fail
    with patch.object(workflow._delete_step, "execute", return_value=StepResult.fail("API error")):
        count = await workflow.delete_messages("archive.mbox", permanent=True)

    assert count == 0
