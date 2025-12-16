from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.cli.output import OutputManager
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver._filter import FilterResult
from gmailarchiver.core.workflows.archive import ArchiveConfig, ArchiveResult, ArchiveWorkflow
from gmailarchiver.data.hybrid_storage import HybridStorage


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
def mock_output():
    return MagicMock(spec=OutputManager)


@pytest.fixture
def workflow(mock_client, mock_storage, mock_output):
    return ArchiveWorkflow(mock_client, mock_storage, mock_output)


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
