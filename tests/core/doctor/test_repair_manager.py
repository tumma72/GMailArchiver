"""Tests for RepairManager class.

Tests the auto-repair functionality for database and lock file issues.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.core.doctor._repair import FixResult, RepairManager


class TestFixResult:
    """Tests for FixResult dataclass."""

    def test_fix_result_success(self):
        """Test FixResult creation for successful fix."""
        result = FixResult(
            check_name="Database schema",
            success=True,
            message="Successfully created database",
        )

        assert result.check_name == "Database schema"
        assert result.success is True
        assert "created" in result.message

    def test_fix_result_failure(self):
        """Test FixResult creation for failed fix."""
        result = FixResult(
            check_name="FTS index",
            success=False,
            message="Failed to clean FTS index",
        )

        assert result.check_name == "FTS index"
        assert result.success is False
        assert "Failed" in result.message


class TestRepairManagerInitialization:
    """Tests for RepairManager initialization."""

    def test_init_with_db_manager(self, tmp_path):
        """Test RepairManager initialization with db_manager."""
        db_path = tmp_path / "test.db"
        mock_db_manager = MagicMock()

        manager = RepairManager(db_path, mock_db_manager)

        assert manager.db_path == db_path
        assert manager.db_manager is mock_db_manager

    def test_init_without_db_manager(self, tmp_path):
        """Test RepairManager initialization without db_manager."""
        db_path = tmp_path / "test.db"

        manager = RepairManager(db_path, None)

        assert manager.db_path == db_path
        assert manager.db_manager is None


class TestRepairManagerFixMissingDatabase:
    """Tests for fix_missing_database method."""

    @pytest.mark.asyncio
    async def test_fix_missing_database_success(self, tmp_path):
        """Test successfully creating missing database."""
        db_path = tmp_path / "new.db"
        manager = RepairManager(db_path, None)

        with patch("gmailarchiver.data.db_manager.DBManager") as MockDBManager:
            mock_db = AsyncMock()
            mock_db.conn = AsyncMock()
            mock_db.conn.execute = AsyncMock()
            mock_db.conn.commit = AsyncMock()
            mock_db.close = AsyncMock()

            MockDBManager.return_value = mock_db

            result = await manager.fix_missing_database()

            assert result.success is True
            assert "created" in result.message.lower()
            assert "v1.1" in result.message
            mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fix_missing_database_connection_fails(self, tmp_path):
        """Test fix_missing_database when connection initialization fails."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        with patch("gmailarchiver.data.db_manager.DBManager") as MockDBManager:
            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock(side_effect=RuntimeError("Connection failed"))
            mock_db.close = AsyncMock()

            MockDBManager.return_value = mock_db

            result = await manager.fix_missing_database()

            assert result.success is False
            assert "Failed to create database" in result.message

    @pytest.mark.asyncio
    async def test_fix_missing_database_pragma_fails(self, tmp_path):
        """Test fix_missing_database when PRAGMA execution fails."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        with patch("gmailarchiver.data.db_manager.DBManager") as MockDBManager:
            mock_db = AsyncMock()
            mock_db.conn = AsyncMock()
            mock_db.conn.execute = AsyncMock(side_effect=RuntimeError("PRAGMA failed"))
            mock_db.close = AsyncMock()

            MockDBManager.return_value = mock_db

            result = await manager.fix_missing_database()

            assert result.success is False

    @pytest.mark.asyncio
    async def test_fix_missing_database_conn_none(self, tmp_path):
        """Test fix_missing_database when db.conn is None after init."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        with patch("gmailarchiver.data.db_manager.DBManager") as MockDBManager:
            mock_db = AsyncMock()
            mock_db.conn = None  # Connection not initialized
            mock_db.close = AsyncMock()

            MockDBManager.return_value = mock_db

            result = await manager.fix_missing_database()

            assert result.success is False
            assert "not initialized" in result.message


class TestRepairManagerFixOrphanedFTS:
    """Tests for fix_orphaned_fts method."""

    @pytest.mark.asyncio
    async def test_fix_orphaned_fts_no_db_manager(self, tmp_path):
        """Test fix_orphaned_fts when no db_manager available."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        result = await manager.fix_orphaned_fts()

        assert result.success is False
        assert "Cannot connect to database" in result.message

    @pytest.mark.asyncio
    async def test_fix_orphaned_fts_success(self, tmp_path):
        """Test successfully removing orphaned FTS records."""
        db_path = tmp_path / "test.db"
        mock_db_manager = MagicMock()
        mock_conn = AsyncMock()
        mock_db_manager.conn = mock_conn

        # Mock cursor with rowcount
        cursor = AsyncMock()
        cursor.rowcount = 3
        mock_conn.execute = AsyncMock(return_value=cursor)
        mock_conn.commit = AsyncMock()

        manager = RepairManager(db_path, mock_db_manager)

        result = await manager.fix_orphaned_fts()

        assert result.success is True
        assert "Removed 3 orphaned" in result.message
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_fix_orphaned_fts_fallback_heuristic(self, tmp_path):
        """Test fix_orphaned_fts falls back to heuristic when first delete returns 0."""
        db_path = tmp_path / "test.db"
        mock_db_manager = MagicMock()
        mock_conn = AsyncMock()
        mock_db_manager.conn = mock_conn

        # First call returns 0, second call returns 2
        cursor1 = AsyncMock()
        cursor1.rowcount = 0
        cursor2 = AsyncMock()
        cursor2.rowcount = 2
        mock_conn.execute = AsyncMock(side_effect=[cursor1, cursor2])
        mock_conn.commit = AsyncMock()

        manager = RepairManager(db_path, mock_db_manager)

        result = await manager.fix_orphaned_fts()

        assert result.success is True
        assert "Removed 2 orphaned" in result.message

    @pytest.mark.asyncio
    async def test_fix_orphaned_fts_no_connection(self, tmp_path):
        """Test fix_orphaned_fts when conn is None."""
        db_path = tmp_path / "test.db"
        mock_db_manager = MagicMock()
        mock_db_manager.conn = None

        manager = RepairManager(db_path, mock_db_manager)

        result = await manager.fix_orphaned_fts()

        assert result.success is False
        assert "not initialized" in result.message

    @pytest.mark.asyncio
    async def test_fix_orphaned_fts_exception(self, tmp_path):
        """Test fix_orphaned_fts when database operation raises exception."""
        db_path = tmp_path / "test.db"
        mock_db_manager = MagicMock()
        mock_conn = AsyncMock()
        mock_db_manager.conn = mock_conn
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("Database locked"))

        manager = RepairManager(db_path, mock_db_manager)

        result = await manager.fix_orphaned_fts()

        assert result.success is False
        assert "Failed to clean FTS index" in result.message


class TestRepairManagerFixStaleLocks:
    """Tests for fix_stale_locks method."""

    def test_fix_stale_locks_removes_lock_files(self, tmp_path):
        """Test fix_stale_locks removes existing lock files."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        # Create lock files
        lock1 = tmp_path / "file1.lock"
        lock2 = tmp_path / "file2.lock"
        lock1.touch()
        lock2.touch()

        result = manager.fix_stale_locks()

        assert result.success is True
        assert "Removed 2 lock file(s)" in result.message
        assert not lock1.exists()
        assert not lock2.exists()

    def test_fix_stale_locks_no_lock_files(self, tmp_path):
        """Test fix_stale_locks when no lock files exist."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        result = manager.fix_stale_locks()

        assert result.success is True
        assert "Removed 0 lock file(s)" in result.message

    def test_fix_stale_locks_with_nonexistent_db_path(self, tmp_path):
        """Test fix_stale_locks with nonexistent database path."""
        # Use a path that doesn't exist to simulate a similar scenario
        db_path = tmp_path / "nonexistent" / "test.db"
        manager = RepairManager(db_path, None)

        # Should handle gracefully when parent directory doesn't exist
        result = manager.fix_stale_locks()

        assert result.success is True
        assert "lock" in result.message.lower()

    def test_fix_stale_locks_partial_permission_failure(self, tmp_path):
        """Test fix_stale_locks continues when one file cannot be deleted."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        # Create lock files
        lock1 = tmp_path / "file1.lock"
        lock2 = tmp_path / "file2.lock"
        lock1.touch()
        lock2.touch()

        # Mock unlink to fail on first call, succeed on second
        call_count = [0]

        def mock_unlink():
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("Cannot delete")

        with patch.object(Path, "unlink", side_effect=mock_unlink):
            result = manager.fix_stale_locks()

            # Should still succeed and report what it could do
            assert result.success is True

    def test_fix_stale_locks_nonexistent_parent_directory(self):
        """Test fix_stale_locks when parent directory doesn't exist."""
        db_path = Path("/nonexistent/path/test.db")
        manager = RepairManager(db_path, None)

        # Should fallback to cwd
        result = manager.fix_stale_locks()

        assert result.success is True

    def test_fix_stale_locks_exception_handling(self, tmp_path):
        """Test fix_stale_locks handles unexpected exceptions."""
        db_path = tmp_path / "test.db"
        manager = RepairManager(db_path, None)

        # Create lock file
        lock1 = tmp_path / "file1.lock"
        lock1.touch()

        # Mock glob to raise exception
        with patch.object(Path, "glob", side_effect=RuntimeError("Glob failed")):
            result = manager.fix_stale_locks()

            assert result.success is False
            assert "Failed to remove lock files" in result.message
