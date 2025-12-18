from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
    workflow.client.delete_messages_permanent.assert_called_once_with(["msg1", "msg2"])
    workflow.client.trash_messages.assert_not_called()


@pytest.mark.asyncio
async def test_delete_messages_trash(workflow):
    """Test trashing archived messages."""
    workflow.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2", "msg3"])
    workflow.client.trash_messages = AsyncMock()

    count = await workflow.delete_messages("archive.mbox", permanent=False)

    assert count == 3
    workflow.client.trash_messages.assert_called_once_with(["msg1", "msg2", "msg3"])
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

    assert result == "partial_archive.mbox"
    mock_progress.info.assert_any_call("Resuming partial archive: partial_archive.mbox")
    mock_progress.info.assert_any_call("Progress: 100/500 messages already archived")


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


@pytest.mark.asyncio
async def test_scan_messages_without_progress(mock_client, mock_storage):
    """Test scanning messages without progress reporter."""
    workflow = ArchiveWorkflow(mock_client, mock_storage, progress=None)
    workflow.archiver.list_messages_for_archive = AsyncMock(
        return_value=("query", [{"id": "msg1"}, {"id": "msg2"}])
    )

    result = await workflow._scan_messages("3y")

    assert result["query"] == "query"
    assert len(result["messages"]) == 2
    workflow.archiver.list_messages_for_archive.assert_called_once_with("3y")


@pytest.mark.asyncio
async def test_filter_messages_with_duplicates_and_archived(workflow):
    """Test filtering with both duplicates and already archived messages."""
    from gmailarchiver.core.archiver._filter import FilterResult

    workflow.archiver.filter_already_archived = AsyncMock(
        return_value=FilterResult(
            to_archive=["msg3"],
            already_archived_count=2,
            duplicate_count=1,
        )
    )

    result = await workflow._filter_messages([{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}], True)

    assert result["to_archive"] == ["msg3"]
    assert result["skipped_count"] == 3
    assert result["already_archived_count"] == 2
    assert result["duplicate_count"] == 1


@pytest.mark.asyncio
async def test_filter_messages_without_progress(mock_client, mock_storage):
    """Test filtering messages without progress reporter."""
    from gmailarchiver.core.archiver._filter import FilterResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, progress=None)
    workflow.archiver.filter_already_archived = AsyncMock(
        return_value=FilterResult(to_archive=["msg1"], already_archived_count=0, duplicate_count=0)
    )

    result = await workflow._filter_messages([{"id": "msg1"}], True)

    assert result["to_archive"] == ["msg1"]
    workflow.archiver.filter_already_archived.assert_called_once_with(["msg1"], True)


@pytest.mark.asyncio
async def test_archive_messages_interrupted(workflow):
    """Test archiving that gets interrupted."""
    workflow.archiver.archive_messages = AsyncMock(
        return_value={"archived_count": 5, "interrupted": True, "actual_file": "archive.mbox"}
    )

    result = await workflow._archive_messages(["msg1", "msg2"], "archive.mbox", None, "query")

    assert result["interrupted"] is True
    assert result["archived_count"] == 5


@pytest.mark.asyncio
async def test_archive_messages_no_messages_archived(workflow):
    """Test archiving when no messages were archived."""
    workflow.archiver.archive_messages = AsyncMock(
        return_value={"archived_count": 0, "interrupted": False, "actual_file": "archive.mbox"}
    )

    result = await workflow._archive_messages([], "archive.mbox", None, "query")

    assert result["archived_count"] == 0


@pytest.mark.asyncio
async def test_archive_messages_error_handling(workflow):
    """Test error handling during archiving returns failure result."""
    workflow.archiver.archive_messages = AsyncMock(side_effect=Exception("Archive failed"))

    # Step catches exceptions and returns failure result with default values
    result = await workflow._archive_messages(["msg1"], "archive.mbox", None, "query")

    assert result["archived_count"] == 0
    assert result["failed_count"] == 0
    assert result["interrupted"] is False


@pytest.mark.asyncio
async def test_archive_messages_without_progress(mock_client, mock_storage):
    """Test archiving messages without progress reporter."""
    workflow = ArchiveWorkflow(mock_client, mock_storage, progress=None)
    workflow.archiver.archive_messages = AsyncMock(
        return_value={"archived_count": 3, "actual_file": "archive.mbox"}
    )

    result = await workflow._archive_messages(
        ["msg1", "msg2", "msg3"], "archive.mbox", "gzip", "query"
    )

    assert result["archived_count"] == 3
    workflow.archiver.archive_messages.assert_called_once_with(
        ["msg1", "msg2", "msg3"], "archive.mbox", "gzip", None, "query"
    )


@pytest.mark.asyncio
async def test_validate_archive_success(workflow, tmp_path):
    """Test successful archive validation."""
    from unittest.mock import MagicMock, patch

    # Create a dummy archive file
    archive_file = tmp_path / "archive.mbox"
    archive_file.write_text("From sender@example.com\nSubject: Test\n\nBody\n")

    workflow.storage.db.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2"])

    # Mock ValidationResult
    mock_validation_result = MagicMock()
    mock_validation_result.count_check = True
    mock_validation_result.database_check = True
    mock_validation_result.integrity_check = True
    mock_validation_result.spot_check = True
    mock_validation_result.passed = True
    mock_validation_result.errors = []

    # Patch ValidatorFacade in the step module where it's used
    with patch("gmailarchiver.core.workflows.steps.validate.ValidatorFacade") as MockValidator:
        mock_validator_instance = MagicMock()
        mock_validator_instance.validate_comprehensive = MagicMock(
            return_value=mock_validation_result
        )
        mock_validator_instance.close = AsyncMock()
        MockValidator.return_value = mock_validator_instance

        result = await workflow._validate_archive(str(archive_file))

        assert result["passed"] is True
        assert result["count_check"] is True
        assert result["database_check"] is True
        assert result["integrity_check"] is True
        assert result["spot_check"] is True
        assert result["errors"] == []


@pytest.mark.asyncio
async def test_validate_archive_failure(workflow, tmp_path):
    """Test failed archive validation."""
    from unittest.mock import MagicMock, patch

    # Create a dummy archive file
    archive_file = tmp_path / "archive.mbox"
    archive_file.write_text("From sender@example.com\nSubject: Test\n\nBody\n")

    workflow.storage.db.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2"])

    # Mock ValidationResult
    mock_validation_result = MagicMock()
    mock_validation_result.count_check = True
    mock_validation_result.database_check = False
    mock_validation_result.integrity_check = True
    mock_validation_result.spot_check = False
    mock_validation_result.passed = False
    mock_validation_result.errors = ["Database mismatch", "Spot check failed"]

    # Patch ValidatorFacade in the step module where it's used
    with patch("gmailarchiver.core.workflows.steps.validate.ValidatorFacade") as MockValidator:
        mock_validator_instance = MagicMock()
        mock_validator_instance.validate_comprehensive = MagicMock(
            return_value=mock_validation_result
        )
        mock_validator_instance.close = AsyncMock()
        MockValidator.return_value = mock_validator_instance

        result = await workflow._validate_archive(str(archive_file))

        assert result["passed"] is False
        assert result["count_check"] is True
        assert result["database_check"] is False
        assert result["spot_check"] is False
        assert len(result["errors"]) == 2


@pytest.mark.asyncio
async def test_validate_archive_cleanup(workflow, tmp_path):
    """Test that validator is always closed after validation."""
    from unittest.mock import MagicMock, patch

    # Create a dummy archive file
    archive_file = tmp_path / "archive.mbox"
    archive_file.write_text("From sender@example.com\nSubject: Test\n\nBody\n")

    workflow.storage.db.get_message_ids_for_archive = AsyncMock(return_value=["msg1"])

    mock_validation_result = MagicMock()
    mock_validation_result.count_check = True
    mock_validation_result.database_check = True
    mock_validation_result.integrity_check = True
    mock_validation_result.spot_check = True
    mock_validation_result.passed = True
    mock_validation_result.errors = []

    # Patch ValidatorFacade in the step module where it's used
    with patch("gmailarchiver.core.workflows.steps.validate.ValidatorFacade") as MockValidator:
        mock_validator_instance = MagicMock()
        mock_validator_instance.validate_comprehensive = MagicMock(
            return_value=mock_validation_result
        )
        mock_validator_instance.close = AsyncMock()
        MockValidator.return_value = mock_validator_instance

        try:
            await workflow._validate_archive(str(archive_file))
        finally:
            # Verify close was called
            mock_validator_instance.close.assert_called_once()


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

    from gmailarchiver.core.workflows.step import StepResult
    from gmailarchiver.core.workflows.steps.gmail import ScanGmailOutput

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock scan step to return success with messages
    scan_output = ScanGmailOutput(
        gmail_query="before:2024/01/01",
        messages=[{"id": "msg1"}, {"id": "msg2"}],
        total_count=2,
    )
    mock_scan_result = StepResult.ok(scan_output)

    # Mock filter step to fail
    mock_filter_result = StepResult.fail("Database error")

    with (
        patch.object(workflow._scan_step, "execute", return_value=mock_scan_result),
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

    from gmailarchiver.core.workflows.step import StepResult
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
        archived_count=1, failed_count=0, actual_file="archive.mbox", interrupted=False
    )
    validate_output = ValidateOutput(
        passed=True,
        count_check=True,
        database_check=True,
        integrity_check=True,
        spot_check=True,
        errors=[],
    )

    with (
        patch.object(workflow._scan_step, "execute", return_value=StepResult.ok(scan_output)),
        patch.object(
            workflow._filter_step, "execute", return_value=StepResult.ok(filter_output)
        ),
        patch.object(workflow._write_step, "execute", return_value=StepResult.ok(write_output)),
        patch.object(
            workflow._validate_step, "execute", return_value=StepResult.ok(validate_output)
        ),
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


@pytest.mark.asyncio
async def test_scan_messages_step_fails(mock_client, mock_storage, mock_progress):
    """When deprecated _scan_messages fails, returns empty result."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import StepResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock scan step to fail
    with patch.object(workflow._scan_step, "execute", return_value=StepResult.fail("API error")):
        result = await workflow._scan_messages("3y")

    assert result["query"] == ""
    assert result["messages"] == []


@pytest.mark.asyncio
async def test_filter_messages_step_fails(mock_client, mock_storage, mock_progress):
    """When deprecated _filter_messages fails, returns empty result."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import StepResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock filter step to fail
    with patch.object(workflow._filter_step, "execute", return_value=StepResult.fail("DB error")):
        result = await workflow._filter_messages([{"id": "msg1"}], incremental=True)

    assert result["to_archive"] == []
    assert result["skipped_count"] == 0
    assert result["already_archived_count"] == 0
    assert result["duplicate_count"] == 0


@pytest.mark.asyncio
async def test_validate_archive_step_fails(mock_client, mock_storage, mock_progress):
    """When deprecated _validate_archive fails, returns failure result."""
    from unittest.mock import patch

    from gmailarchiver.core.workflows.step import StepResult

    workflow = ArchiveWorkflow(mock_client, mock_storage, mock_progress)

    # Mock validate step to fail
    with patch.object(
        workflow._validate_step, "execute", return_value=StepResult.fail("Validation error")
    ):
        result = await workflow._validate_archive("archive.mbox")

    assert result["passed"] is False
    assert result["errors"] == ["Validation step failed"]
