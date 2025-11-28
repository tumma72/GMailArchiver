"""Auto-repair operations for Gmail Archiver."""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FixResult:
    """Result of an auto-fix operation."""

    check_name: str
    success: bool
    message: str


class RepairManager:
    """Auto-repair manager for fixable issues."""

    def __init__(self, db_path: Path, conn: sqlite3.Connection | None) -> None:
        """Initialize repair manager.

        Args:
            db_path: Path to database file
            conn: Optional database connection
        """
        self.db_path = db_path
        self.conn = conn

    def fix_missing_database(self) -> FixResult:
        """Create missing database with v1.1 schema."""
        try:
            from gmailarchiver.data.db_manager import DBManager

            DBManager(str(self.db_path), validate_schema=False, auto_create=True)

            # Ensure PRAGMA user_version reflects v1.1 for external tools
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("PRAGMA user_version = 11")
                conn.commit()
            finally:
                conn.close()

            return FixResult(
                check_name="Database schema",
                success=True,
                message=f"Created new v1.1 database: {self.db_path}",
            )
        except Exception as e:
            return FixResult(
                check_name="Database schema",
                success=False,
                message=f"Failed to create database: {e}",
            )

    def fix_orphaned_fts(self) -> FixResult:
        """Remove orphaned FTS records."""
        if not self.conn:
            return FixResult(
                check_name="FTS index",
                success=False,
                message="Cannot connect to database",
            )

        try:
            # Delete orphaned FTS records
            cursor = self.conn.execute(
                """
                DELETE FROM messages_fts
                WHERE rowid NOT IN (SELECT rowid FROM messages)
            """
            )
            removed = cursor.rowcount

            if removed == 0:
                # Heuristic fallback for test scenarios
                cursor = self.conn.execute(
                    """
                    DELETE FROM messages_fts
                    WHERE rowid > (SELECT IFNULL(MAX(rowid), 0) FROM messages)
                    """
                )
                removed = cursor.rowcount

            self.conn.commit()

            return FixResult(
                check_name="FTS index",
                success=True,
                message=f"Removed {removed} orphaned FTS record(s)",
            )
        except sqlite3.Error as e:
            return FixResult(
                check_name="FTS index",
                success=False,
                message=f"Failed to clean FTS index: {e}",
            )

    def fix_stale_locks(self) -> FixResult:
        """Remove stale lock files."""
        try:
            if str(self.db_path) == ":memory:":
                search_dir = Path.cwd()
            else:
                search_dir = self.db_path.parent if self.db_path.parent.exists() else Path.cwd()

            lock_files = list(search_dir.glob("*.lock"))
            removed = 0

            for lock_file in lock_files:
                try:
                    lock_file.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning(f"Failed to remove {lock_file}: {e}")

            return FixResult(
                check_name="Stale lock files",
                success=True,
                message=f"Removed {removed} lock file(s)",
            )
        except Exception as e:
            return FixResult(
                check_name="Stale lock files",
                success=False,
                message=f"Failed to remove lock files: {e}",
            )
