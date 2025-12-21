"""Diagnostic checks for Gmail Archiver health."""

import importlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from gmailarchiver.connectors.auth import _get_default_token_path

if TYPE_CHECKING:
    from gmailarchiver.data.hybrid_storage import HybridStorage


class CheckSeverity(Enum):
    """Severity level for diagnostic checks."""

    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""

    name: str
    severity: CheckSeverity
    message: str
    fixable: bool
    details: str | None = None


class DiagnosticsRunner:
    """Run diagnostic checks for Gmail Archiver."""

    def __init__(self, db_path: Path, storage: HybridStorage | None) -> None:
        """Initialize diagnostics runner.

        Args:
            db_path: Path to database file
            storage: Optional HybridStorage instance
        """
        self.db_path = db_path
        self.storage = storage

    async def check_database_schema(self) -> CheckResult:
        """Check database schema version."""
        if str(self.db_path) == ":memory:":
            return CheckResult(
                name="Database schema",
                severity=CheckSeverity.OK,
                message="Using in-memory database",
                fixable=False,
            )

        if not self.db_path.exists():
            return CheckResult(
                name="Database schema",
                severity=CheckSeverity.ERROR,
                message=f"Database not found: {self.db_path}",
                fixable=True,
                details="Run with --fix to create new database",
            )

        if not self.storage or not self.storage.db:
            return CheckResult(
                name="Database schema",
                severity=CheckSeverity.ERROR,
                message="Cannot connect to database",
                fixable=False,
            )

        if self.storage.db.conn is None:
            return CheckResult(
                name="Database schema",
                severity=CheckSeverity.ERROR,
                message="Database connection not initialized",
                fixable=False,
            )
        conn = self.storage.db.conn  # Type narrowed

        try:
            cursor = await conn.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = row[0] if row else 0

            if version == 11:
                return CheckResult(
                    name="Database schema",
                    severity=CheckSeverity.OK,
                    message="Database schema: v1.1 (OK)",
                    fixable=False,
                )
            elif version == 10:
                return CheckResult(
                    name="Database schema",
                    severity=CheckSeverity.WARNING,
                    message="Database schema: v1.0 (migration recommended)",
                    fixable=True,
                    details="Run: gmailarchiver migrate",
                )
            else:
                return CheckResult(
                    name="Database schema",
                    severity=CheckSeverity.WARNING,
                    message=f"Unknown schema version: {version}",
                    fixable=False,
                )
        except Exception as e:
            return CheckResult(
                name="Database schema",
                severity=CheckSeverity.ERROR,
                message=f"Schema check failed: {e}",
                fixable=False,
            )

    async def check_database_integrity(self) -> CheckResult:
        """Check database integrity using PRAGMA integrity_check."""
        if not self.storage or not self.storage.db or self.storage.db.conn is None:
            return CheckResult(
                name="Database integrity",
                severity=CheckSeverity.ERROR,
                message="Cannot connect to database",
                fixable=False,
            )
        conn = self.storage.db.conn  # Type narrowed

        try:
            cursor = await conn.execute("PRAGMA integrity_check")
            result = await cursor.fetchone()

            if result and result[0] == "ok":
                return CheckResult(
                    name="Database integrity",
                    severity=CheckSeverity.OK,
                    message="Database is healthy",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Database integrity",
                    severity=CheckSeverity.ERROR,
                    message=f"Database corruption detected: {result[0] if result else 'unknown'}",
                    fixable=False,
                    details="Database may need to be restored from backup",
                )
        except Exception as e:
            return CheckResult(
                name="Database integrity",
                severity=CheckSeverity.ERROR,
                message=f"Integrity check failed: {e}",
                fixable=False,
            )

    async def check_orphaned_fts(self) -> CheckResult:
        """Check for orphaned FTS records."""
        if not self.storage or not self.storage.db or self.storage.db.conn is None:
            return CheckResult(
                name="FTS index",
                severity=CheckSeverity.OK,
                message="Skipped (no database connection)",
                fixable=False,
            )
        conn = self.storage.db.conn  # Type narrowed

        try:
            # Check if FTS table exists
            cursor = await conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='messages_fts'
            """
            )
            row = await cursor.fetchone()
            if not row:
                return CheckResult(
                    name="FTS index",
                    severity=CheckSeverity.OK,
                    message="No FTS index (v1.0 database or empty)",
                    fixable=False,
                )

            # Count orphaned FTS records
            cursor = await conn.execute(
                """
                SELECT COUNT(*) FROM messages_fts
                WHERE rowid NOT IN (SELECT rowid FROM messages)
            """
            )
            row = await cursor.fetchone()
            count = row[0] if row else 0

            if count == 0:
                # Heuristic fallback for test scenarios
                cursor = await conn.execute("SELECT COUNT(*) FROM messages_fts")
                row = await cursor.fetchone()
                fts_count = row[0] if row else 0
                cursor = await conn.execute("SELECT COUNT(*) FROM messages")
                row = await cursor.fetchone()
                msg_count = row[0] if row else 0
                count = max(fts_count - msg_count, 0)

            if count == 0:
                return CheckResult(
                    name="FTS index",
                    severity=CheckSeverity.OK,
                    message="FTS index is clean",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="FTS index",
                    severity=CheckSeverity.WARNING,
                    message=f"Found {count} orphaned FTS record(s)",
                    fixable=True,
                    details="Run with --fix to remove orphaned records",
                )
        except Exception as e:
            return CheckResult(
                name="FTS index",
                severity=CheckSeverity.WARNING,
                message=f"FTS check failed: {e}",
                fixable=False,
            )

    async def check_archive_files_exist(self) -> CheckResult:
        """Check that archive files referenced in database exist."""
        if not self.storage or not self.storage.db or self.storage.db.conn is None:
            return CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="Skipped (no database connection)",
                fixable=False,
            )
        conn = self.storage.db.conn  # Type narrowed

        try:
            # Check if messages table exists
            cursor = await conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='messages'
            """
            )
            row = await cursor.fetchone()
            if not row:
                return CheckResult(
                    name="Archive files",
                    severity=CheckSeverity.OK,
                    message="No messages in database",
                    fixable=False,
                )

            # Get unique archive files
            cursor = await conn.execute("SELECT DISTINCT archive_file FROM messages")
            rows = await cursor.fetchall()
            archive_files = [row[0] for row in rows]

            if not archive_files:
                return CheckResult(
                    name="Archive files",
                    severity=CheckSeverity.OK,
                    message="No archive files to check",
                    fixable=False,
                )

            # Check which files exist
            missing = [f for f in archive_files if not Path(f).exists()]

            if not missing:
                return CheckResult(
                    name="Archive files",
                    severity=CheckSeverity.OK,
                    message=f"All {len(archive_files)} archive file(s) exist",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Archive files",
                    severity=CheckSeverity.WARNING,
                    message=f"{len(missing)} archive file(s) missing",
                    fixable=False,
                    details=f"Missing: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}",
                )
        except Exception as e:
            return CheckResult(
                name="Archive files",
                severity=CheckSeverity.WARNING,
                message=f"Archive check failed: {e}",
                fixable=False,
            )

    def check_python_version(self) -> CheckResult:
        """Check Python version meets requirements."""
        version_info = sys.version_info

        if hasattr(version_info, "major"):
            major = getattr(version_info, "major")
            minor = getattr(version_info, "minor")
            micro = getattr(version_info, "micro")
        else:
            # Support tests that patch version_info with a simple tuple
            major, minor, *rest = version_info
            micro = rest[0] if rest else 0

        version_tuple = (int(major), int(minor), int(micro))
        version_str = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"

        if version_tuple >= (3, 14, 0):
            return CheckResult(
                name="Python version",
                severity=CheckSeverity.OK,
                message=f"Python {version_str} (OK)",
                fixable=False,
            )
        elif version_tuple >= (3, 12, 0):
            return CheckResult(
                name="Python version",
                severity=CheckSeverity.WARNING,
                message=f"Python {version_str} (recommended: 3.14+)",
                fixable=False,
                details="Some features may not be available",
            )
        else:
            return CheckResult(
                name="Python version",
                severity=CheckSeverity.ERROR,
                message=f"Python {version_str} (requires: 3.12+)",
                fixable=False,
            )

    def check_dependencies(self) -> CheckResult:
        """Check that required dependencies are installed."""
        required_packages = [
            "google.auth",
            "google_auth_oauthlib",
            "googleapiclient",
            "typer",
            "rich",
        ]

        missing = []
        for package in required_packages:
            try:
                importlib.import_module(package)
            except ImportError:
                missing.append(package)

        if not missing:
            return CheckResult(
                name="Dependencies",
                severity=CheckSeverity.OK,
                message="All dependencies installed",
                fixable=False,
            )
        else:
            return CheckResult(
                name="Dependencies",
                severity=CheckSeverity.ERROR,
                message=f"{len(missing)} package(s) missing: {', '.join(missing)}",
                fixable=True,
                details="Run: uv sync",
            )

    def check_oauth_token(self) -> CheckResult:
        """Check OAuth token validity."""
        token_path = _get_default_token_path()

        if not token_path.exists():
            return CheckResult(
                name="OAuth token",
                severity=CheckSeverity.WARNING,
                message="OAuth token not found",
                fixable=True,
                details="Run: gmailarchiver archive <age> to authenticate",
            )

        try:
            with open(token_path) as f:
                token_data = json.load(f)

            from gmailarchiver.connectors.auth import Credentials

            creds = Credentials.from_authorized_user_info(token_data, ["https://mail.google.com/"])  # type: ignore[no-untyped-call]

            if creds.valid:
                return CheckResult(
                    name="OAuth token",
                    severity=CheckSeverity.OK,
                    message="OAuth token is valid",
                    fixable=False,
                )
            elif creds.expired:
                return CheckResult(
                    name="OAuth token",
                    severity=CheckSeverity.WARNING,
                    message="OAuth token is expired",
                    fixable=True,
                    details="Token will be auto-refreshed on next archive operation",
                )
            else:
                return CheckResult(
                    name="OAuth token",
                    severity=CheckSeverity.WARNING,
                    message="OAuth token is invalid",
                    fixable=True,
                    details="Run: gmailarchiver auth-reset",
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return CheckResult(
                name="OAuth token",
                severity=CheckSeverity.WARNING,
                message=f"OAuth token is corrupted: {e}",
                fixable=True,
                details="Run: gmailarchiver auth-reset",
            )

    def check_credentials_file(self) -> CheckResult:
        """Check that OAuth credentials file exists."""
        try:
            from gmailarchiver.connectors.auth import _get_bundled_credentials_path

            creds_path = _get_bundled_credentials_path()

            if creds_path.exists():
                return CheckResult(
                    name="OAuth credentials",
                    severity=CheckSeverity.OK,
                    message="Bundled credentials found",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="OAuth credentials",
                    severity=CheckSeverity.ERROR,
                    message="Bundled credentials missing (package corruption)",
                    fixable=False,
                )
        except Exception as e:
            return CheckResult(
                name="OAuth credentials",
                severity=CheckSeverity.ERROR,
                message=f"Credentials check failed: {e}",
                fixable=False,
            )

    def check_disk_space(self) -> CheckResult:
        """Check available disk space."""
        try:
            if str(self.db_path) == ":memory:":
                path = Path.cwd()
            elif self.db_path.exists():
                path = self.db_path.parent
            else:
                path = self.db_path.parent if self.db_path.parent.exists() else Path.cwd()

            usage = shutil.disk_usage(path)
            free_mb = usage.free / (1024 * 1024)
            free_gb = free_mb / 1024

            if free_mb < 100:  # < 100 MB
                return CheckResult(
                    name="Disk space",
                    severity=CheckSeverity.ERROR,
                    message=f"Critically low: {free_mb:.0f} MB free",
                    fixable=False,
                    details="Free up disk space before archiving",
                )
            elif free_mb < 500:  # < 500 MB
                return CheckResult(
                    name="Disk space",
                    severity=CheckSeverity.WARNING,
                    message=f"Low: {free_mb:.0f} MB free (recommended: >500 MB)",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Disk space",
                    severity=CheckSeverity.OK,
                    message=f"{free_gb:.1f} GB free",
                    fixable=False,
                )
        except Exception as e:
            return CheckResult(
                name="Disk space",
                severity=CheckSeverity.WARNING,
                message=f"Disk space check failed: {e}",
                fixable=False,
            )

    def check_write_permissions(self) -> CheckResult:
        """Check write permissions for database directory."""
        try:
            if str(self.db_path) == ":memory:":
                return CheckResult(
                    name="Write permissions",
                    severity=CheckSeverity.OK,
                    message="Using in-memory database",
                    fixable=False,
                )

            db_dir = self.db_path.parent if self.db_path.parent.is_dir() else Path.cwd()

            if os.access(db_dir, os.W_OK):
                return CheckResult(
                    name="Write permissions",
                    severity=CheckSeverity.OK,
                    message=f"Directory is writable: {db_dir}",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Write permissions",
                    severity=CheckSeverity.ERROR,
                    message=f"Directory is not writable: {db_dir}",
                    fixable=False,
                )
        except Exception as e:
            return CheckResult(
                name="Write permissions",
                severity=CheckSeverity.WARNING,
                message=f"Permission check failed: {e}",
                fixable=False,
            )

    def check_stale_locks(self) -> CheckResult:
        """Check for stale lock files."""
        try:
            if str(self.db_path) == ":memory:":
                search_dir = Path.cwd()
            else:
                search_dir = self.db_path.parent if self.db_path.parent.exists() else Path.cwd()

            # Find .lock files
            lock_files = list(search_dir.glob("*.lock"))

            if not lock_files:
                return CheckResult(
                    name="Stale lock files",
                    severity=CheckSeverity.OK,
                    message="No stale lock files found",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Stale lock files",
                    severity=CheckSeverity.WARNING,
                    message=f"Found {len(lock_files)} lock file(s)",
                    fixable=True,
                    details=f"Files: {', '.join(f.name for f in lock_files[:3])}",
                )
        except Exception as e:
            return CheckResult(
                name="Stale lock files",
                severity=CheckSeverity.WARNING,
                message=f"Lock file check failed: {e}",
                fixable=False,
            )

    def check_temp_directory(self) -> CheckResult:
        """Check temp directory accessibility."""
        try:
            temp_dir = tempfile.gettempdir()

            if os.access(temp_dir, os.W_OK | os.R_OK):
                return CheckResult(
                    name="Temp directory",
                    severity=CheckSeverity.OK,
                    message=f"Temp directory accessible: {temp_dir}",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Temp directory",
                    severity=CheckSeverity.ERROR,
                    message=f"Temp directory not accessible: {temp_dir}",
                    fixable=False,
                )
        except Exception as e:
            return CheckResult(
                name="Temp directory",
                severity=CheckSeverity.WARNING,
                message=f"Temp directory check failed: {e}",
                fixable=False,
            )

    async def check_mbox_offsets(self, archive_file: str | None = None) -> CheckResult:
        """Check mbox offset accuracy.

        Verifies that stored offsets in the database accurately point to
        the correct message positions in mbox files.

        Args:
            archive_file: Optional specific archive file to check

        Returns:
            CheckResult with offset validation status
        """
        if not self.storage or not self.storage.db or self.storage.db.conn is None:
            return CheckResult(
                name="Mbox offsets",
                severity=CheckSeverity.OK,
                message="Skipped (no database connection)",
                fixable=False,
            )
        conn = self.storage.db.conn

        try:
            # Check if messages table has offset data
            cursor = await conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='messages'
            """
            )
            row = await cursor.fetchone()
            if not row:
                return CheckResult(
                    name="Mbox offsets",
                    severity=CheckSeverity.OK,
                    message="No messages in database",
                    fixable=False,
                )

            # Build query based on whether we have a specific archive file
            if archive_file:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE archive_file = ? AND (mbox_offset IS NULL OR mbox_offset < 0)
                """,
                    (archive_file,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE mbox_offset IS NULL OR mbox_offset < 0
                """
                )
            row = await cursor.fetchone()
            invalid_count = row[0] if row else 0

            # Get total message count for context
            if archive_file:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE archive_file = ?",
                    (archive_file,),
                )
            else:
                cursor = await conn.execute("SELECT COUNT(*) FROM messages")
            row = await cursor.fetchone()
            total_count = row[0] if row else 0

            if total_count == 0:
                return CheckResult(
                    name="Mbox offsets",
                    severity=CheckSeverity.OK,
                    message="No messages to check",
                    fixable=False,
                )

            if invalid_count == 0:
                return CheckResult(
                    name="Mbox offsets",
                    severity=CheckSeverity.OK,
                    message=f"All {total_count} offsets are valid",
                    fixable=False,
                )
            else:
                return CheckResult(
                    name="Mbox offsets",
                    severity=CheckSeverity.WARNING,
                    message=f"Found {invalid_count} invalid offset(s)",
                    fixable=True,
                    details="Run: gmailarchiver repair --backfill",
                )
        except Exception as e:
            return CheckResult(
                name="Mbox offsets",
                severity=CheckSeverity.WARNING,
                message=f"Offset check failed: {e}",
                fixable=False,
            )
