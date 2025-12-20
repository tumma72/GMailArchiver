"""Tests for StatusWorkflow."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.workflows.status import StatusConfig, StatusResult, StatusWorkflow
from gmailarchiver.data.hybrid_storage import ArchiveStats


@pytest.fixture
def mock_storage():
    """Create mock HybridStorage."""
    storage = MagicMock()
    storage.get_archive_stats = AsyncMock()
    storage.get_recent_runs = AsyncMock()
    return storage


@pytest.mark.asyncio
async def test_status_workflow_success(mock_storage):
    """Test successful status retrieval."""
    # Setup mock stats
    mock_storage.get_archive_stats.return_value = ArchiveStats(
        total_messages=123,
        archive_files=["file1.mbox", "file2.mbox"],
        schema_version="1.1",
        database_size_bytes=1024000,
        recent_runs=[],
    )
    mock_storage.get_recent_runs.return_value = [
        {
            "run_id": 1,
            "archive_file": "file1.mbox",
            "run_timestamp": "2024-01-01",
            "messages_archived": 50,
        },
        {
            "run_id": 2,
            "archive_file": "file2.mbox",
            "run_timestamp": "2024-01-02",
            "messages_archived": 73,
        },
    ]

    workflow = StatusWorkflow(mock_storage)
    config = StatusConfig(verbose=False)

    result = await workflow.run(config)

    assert isinstance(result, StatusResult)
    assert result.schema_version == "1.1"
    assert result.total_messages == 123
    assert result.archive_files_count == 2
    assert "file1.mbox" in result.archive_files
    assert "file2.mbox" in result.archive_files
    assert len(result.recent_runs) == 2


@pytest.mark.asyncio
async def test_status_workflow_verbose_gets_more_runs(mock_storage):
    """Test that verbose mode requests more runs."""
    mock_storage.get_archive_stats.return_value = ArchiveStats(
        total_messages=100,
        archive_files=[],
        schema_version="1.1",
        database_size_bytes=1000,
        recent_runs=[],
    )
    mock_storage.get_recent_runs.return_value = []

    workflow = StatusWorkflow(mock_storage)
    config = StatusConfig(verbose=True)

    await workflow.run(config)

    # Verbose mode should request 10 runs (default limit is 5)
    mock_storage.get_recent_runs.assert_called_once_with(limit=10)


@pytest.mark.asyncio
async def test_status_workflow_empty_archive(mock_storage):
    """Test status with empty archive."""
    mock_storage.get_archive_stats.return_value = ArchiveStats(
        total_messages=0,
        archive_files=[],
        schema_version="1.1",
        database_size_bytes=4096,
        recent_runs=[],
    )
    mock_storage.get_recent_runs.return_value = []

    workflow = StatusWorkflow(mock_storage)
    config = StatusConfig()

    result = await workflow.run(config)

    assert result.total_messages == 0
    assert result.archive_files_count == 0
    assert len(result.recent_runs) == 0


@pytest.mark.asyncio
async def test_status_workflow_with_progress_reporter(mock_storage):
    """Test that progress reporter is called."""
    mock_storage.get_archive_stats.return_value = ArchiveStats(
        total_messages=42,
        archive_files=["archive.mbox"],
        schema_version="1.1",
        database_size_bytes=2048,
        recent_runs=[],
    )
    mock_storage.get_recent_runs.return_value = []

    mock_progress = MagicMock()
    mock_seq = MagicMock()
    mock_task = MagicMock()
    mock_progress.task_sequence.return_value.__enter__ = MagicMock(return_value=mock_seq)
    mock_progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)
    mock_seq.task.return_value.__enter__ = MagicMock(return_value=mock_task)
    mock_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    workflow = StatusWorkflow(mock_storage, progress=mock_progress)
    config = StatusConfig()

    result = await workflow.run(config)

    assert result.total_messages == 42
    # Progress reporter should have been used
    mock_progress.task_sequence.assert_called()


@pytest.mark.asyncio
async def test_status_result_archive_files_count_property():
    """Test StatusResult.archive_files_count property."""
    result = StatusResult(
        schema_version="1.1",
        database_size_bytes=1000,
        total_messages=50,
        archive_files=["a.mbox", "b.mbox", "c.mbox"],
        recent_runs=[],
    )

    assert result.archive_files_count == 3
