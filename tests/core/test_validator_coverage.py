"""Additional tests for ValidatorFacade to improve coverage.

These tests target specific uncovered lines in validator/facade.py
to achieve 95%+ coverage.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gmailarchiver.core.validator import ValidatorFacade
from gmailarchiver.data.db_manager import DBManager


class TestValidatorCloseMethod:
    """Tests for ValidatorFacade.close() method (lines 114-116)."""

    @pytest.mark.asyncio
    async def test_close_owned_db_manager(self) -> None:
        """Test close() closes db_manager when owned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = Path(tmpdir) / "test.mbox"
            db_path = Path(tmpdir) / "test.db"

            # Create empty mbox and db
            archive_path.touch()
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE messages (gmail_id TEXT)")
            conn.close()

            # Create validator without passing db_manager (so it owns it)
            validator = ValidatorFacade(str(archive_path), str(db_path))

            # Trigger db_manager creation (async)
            _ = await validator._get_db_manager()

            # Now close should work (async)
            await validator.close()

            # Verify db_manager is None after close
            assert validator._db_manager is None

    @pytest.mark.asyncio
    async def test_close_external_db_manager(self) -> None:
        """Test close() does not close external db_manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = Path(tmpdir) / "test.mbox"
            db_path = Path(tmpdir) / "test.db"

            # Create empty mbox and db
            archive_path.touch()
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE messages (gmail_id TEXT)")
            conn.close()

            # Create external db_manager (async init)
            db_manager = DBManager(str(db_path), validate_schema=False, auto_create=False)
            await db_manager.initialize()

            # Create validator with external db_manager
            validator = ValidatorFacade(str(archive_path), str(db_path), db_manager=db_manager)

            # Close validator (async)
            await validator.close()

            # External db_manager should still be valid (not closed)
            assert validator._db_manager is not None
            await db_manager.close()


class TestValidatorGetDbManager:
    """Tests for ValidatorFacade._get_db_manager() method (lines 109-110)."""

    @pytest.mark.asyncio
    async def test_get_db_manager_exception_handling(self) -> None:
        """Test _get_db_manager returns None on exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = Path(tmpdir) / "test.mbox"
            db_path = Path(tmpdir) / "test.db"

            # Create valid db file
            archive_path.touch()
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE messages (gmail_id TEXT)")
            conn.close()

            validator = ValidatorFacade(str(archive_path), str(db_path))

            # Mock DBManager to raise exception on initialize
            with patch("gmailarchiver.core.validator.facade.DBManager") as MockDBManager:
                mock_instance = MockDBManager.return_value
                mock_instance.initialize.side_effect = Exception("DB error")

                result = await validator._get_db_manager()

                # Should return None on exception
                assert result is None
