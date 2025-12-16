from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.core.workflows.status import StatusConfig, StatusResult, StatusWorkflow
from gmailarchiver.data.schema_manager import SchemaVersion


@pytest.fixture
def mock_db_path(tmp_path):
    p = tmp_path / "archive_state.db"
    p.touch()
    return p


@pytest.fixture
def workflow():
    return StatusWorkflow()


@pytest.mark.asyncio
async def test_status_workflow_success(workflow, mock_db_path):
    config = StatusConfig(state_db=mock_db_path, verbose=False)

    # Mock SchemaManager
    with patch("gmailarchiver.core.workflows.status.SchemaManager") as MockSchemaMgr:
        mock_mgr = MockSchemaMgr.return_value
        mock_mgr.detect_version = AsyncMock(return_value=SchemaVersion.V1_1)

        # Mock DBManager
        with patch("gmailarchiver.core.workflows.status.DBManager") as MockDBMgr:
            mock_db = MockDBMgr.return_value
            mock_db.initialize = AsyncMock()
            mock_db.get_message_count = AsyncMock(return_value=123)
            mock_db.get_archive_runs = AsyncMock(
                return_value=[
                    {"run_id": 1, "archive_file": "file1.mbox"},
                    {"run_id": 2, "archive_file": "file2.mbox"},
                    {"run_id": 3, "archive_file": "file1.mbox"},
                ]
            )
            mock_db.close = AsyncMock()

            result = await workflow.run(config)

            assert isinstance(result, StatusResult)
            assert result.schema_version == "1.1"
            assert result.total_messages == 123
            assert len(result.recent_runs) == 3
            assert result.archive_files_count == 2  # file1, file2
            assert "file1.mbox" in result.archive_files_sample
            assert "file2.mbox" in result.archive_files_sample


@pytest.mark.asyncio
async def test_status_workflow_missing_db(workflow, tmp_path):
    missing_path = tmp_path / "missing.db"
    config = StatusConfig(state_db=missing_path)

    with pytest.raises(FileNotFoundError):
        await workflow.run(config)


@pytest.mark.asyncio
async def test_status_workflow_v1_fallback(workflow, mock_db_path):
    config = StatusConfig(state_db=mock_db_path)

    with patch("gmailarchiver.core.workflows.status.SchemaManager") as MockSchemaMgr:
        mock_mgr = MockSchemaMgr.return_value
        mock_mgr.detect_version = AsyncMock(return_value=SchemaVersion.V1_0)

        with patch("gmailarchiver.core.workflows.status.DBManager") as MockDBMgr:
            mock_db = MockDBMgr.return_value
            mock_db.initialize = AsyncMock()
            # Simulate failure on new schema query
            mock_db.get_message_count = AsyncMock(side_effect=Exception("Table not found"))
            mock_db.conn = MagicMock()
            # Mock raw cursor for fallback
            mock_cursor = AsyncMock()
            mock_cursor.fetchone = AsyncMock(return_value=(456,))
            mock_db.conn.execute = AsyncMock(return_value=mock_cursor)
            mock_db.close = AsyncMock()

            result = await workflow.run(config)

            assert result.total_messages == 456
            # Check that both v1.0 fallbacks were called (message count and archive files)
            calls = [call[0][0] for call in mock_db.conn.execute.call_args_list]
            assert "SELECT COUNT(*) FROM archived_messages" in calls
            assert "SELECT DISTINCT archive_file FROM archived_messages" in calls
