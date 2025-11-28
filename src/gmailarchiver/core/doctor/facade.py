"""System diagnostics and auto-repair facade for Gmail Archiver."""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity, DiagnosticsRunner
from gmailarchiver.core.doctor._repair import FixResult, RepairManager


@dataclass
class DoctorReport:
    """Complete diagnostic report."""

    overall_status: CheckSeverity
    checks: list[CheckResult]
    checks_passed: int
    warnings: int
    errors: int
    fixable_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON output."""
        return {
            "overall_status": self.overall_status.value,
            "checks_passed": self.checks_passed,
            "warnings": self.warnings,
            "errors": self.errors,
            "checks": [
                {
                    "name": check.name,
                    "severity": check.severity.value,
                    "message": check.message,
                    "fixable": check.fixable,
                    "details": check.details,
                }
                for check in self.checks
            ],
            "fixable_issues": self.fixable_issues,
        }


class Doctor:
    """System diagnostics and auto-repair for Gmail Archiver."""

    def __init__(
        self, db_path: str, validate_schema: bool = True, auto_create: bool = True
    ) -> None:
        """Initialize doctor with database path.

        Args:
            db_path: Path to SQLite database file
            validate_schema: Whether to validate schema on init
            auto_create: Whether to auto-create database if missing
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else Path(":memory:")
        self.validate_schema = validate_schema
        self.auto_create = auto_create
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection | None:
        """Get database connection, handling errors gracefully."""
        if self._conn:
            return self._conn

        try:
            if str(self.db_path) == ":memory:":
                self._conn = sqlite3.connect(":memory:")
            elif self.db_path.exists():
                self._conn = sqlite3.connect(str(self.db_path))
            else:
                return None

            self._conn.row_factory = sqlite3.Row
            return self._conn
        except (sqlite3.Error, PermissionError):
            return None

    def run_diagnostics(self) -> DoctorReport:
        """Run all diagnostic checks.

        Returns:
            DoctorReport with results of all checks
        """
        conn = self._get_connection()
        diagnostics = DiagnosticsRunner(self.db_path, conn)

        checks: list[CheckResult] = []

        # Database checks
        checks.append(diagnostics.check_database_schema())
        checks.append(diagnostics.check_database_integrity())
        checks.append(diagnostics.check_orphaned_fts())
        checks.append(diagnostics.check_archive_files_exist())

        # Environment checks
        checks.append(diagnostics.check_python_version())
        checks.append(diagnostics.check_dependencies())
        checks.append(diagnostics.check_oauth_token())
        checks.append(diagnostics.check_credentials_file())

        # System checks
        checks.append(diagnostics.check_disk_space())
        checks.append(diagnostics.check_write_permissions())
        checks.append(diagnostics.check_stale_locks())
        checks.append(diagnostics.check_temp_directory())

        # Calculate summary
        checks_passed = sum(1 for c in checks if c.severity == CheckSeverity.OK)
        warnings = sum(1 for c in checks if c.severity == CheckSeverity.WARNING)
        errors = sum(1 for c in checks if c.severity == CheckSeverity.ERROR)

        # Determine overall status
        if errors > 0:
            overall_status = CheckSeverity.ERROR
        elif warnings > 0:
            overall_status = CheckSeverity.WARNING
        else:
            overall_status = CheckSeverity.OK

        # Collect fixable issues
        fixable_issues = [
            check.name for check in checks if check.fixable and check.severity != CheckSeverity.OK
        ]

        return DoctorReport(
            overall_status=overall_status,
            checks=checks,
            checks_passed=checks_passed,
            warnings=warnings,
            errors=errors,
            fixable_issues=fixable_issues,
        )

    def run_auto_fix(self) -> list[FixResult]:
        """Run auto-fix for all fixable issues.

        Returns:
            List of FixResult for each attempted fix
        """
        results: list[FixResult] = []

        # Run diagnostics to find fixable issues
        report = self.run_diagnostics()

        # Initialize repair manager
        conn = self._get_connection()
        repair = RepairManager(self.db_path, conn)

        for check in report.checks:
            if check.fixable and check.severity != CheckSeverity.OK:
                # Attempt to fix based on check name
                if "schema" in check.name.lower() and "not found" in check.message.lower():
                    results.append(repair.fix_missing_database())
                elif "orphaned" in check.name.lower():
                    results.append(repair.fix_orphaned_fts())
                elif "lock" in check.name.lower():
                    results.append(repair.fix_stale_locks())
                # Note: Some issues like expired token require user action (re-auth)

        return results

    # Delegation methods for direct access to diagnostics/repair
    def check_database_schema(self) -> CheckResult:
        """Check database schema version."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_database_schema()

    def check_database_integrity(self) -> CheckResult:
        """Check database integrity."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_database_integrity()

    def check_orphaned_fts(self) -> CheckResult:
        """Check for orphaned FTS records."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_orphaned_fts()

    def check_archive_files_exist(self) -> CheckResult:
        """Check that archive files exist."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_archive_files_exist()

    def check_python_version(self) -> CheckResult:
        """Check Python version."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_python_version()

    def check_dependencies(self) -> CheckResult:
        """Check dependencies."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_dependencies()

    def check_oauth_token(self) -> CheckResult:
        """Check OAuth token."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_oauth_token()

    def check_credentials_file(self) -> CheckResult:
        """Check credentials file."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_credentials_file()

    def check_disk_space(self) -> CheckResult:
        """Check disk space."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_disk_space()

    def check_write_permissions(self) -> CheckResult:
        """Check write permissions."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_write_permissions()

    def check_stale_locks(self) -> CheckResult:
        """Check stale locks."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_stale_locks()

    def check_temp_directory(self) -> CheckResult:
        """Check temp directory."""
        conn = self._get_connection()
        return DiagnosticsRunner(self.db_path, conn).check_temp_directory()

    def fix_missing_database(self) -> FixResult:
        """Fix missing database."""
        conn = self._get_connection()
        return RepairManager(self.db_path, conn).fix_missing_database()

    def fix_orphaned_fts(self) -> FixResult:
        """Fix orphaned FTS records."""
        conn = self._get_connection()
        return RepairManager(self.db_path, conn).fix_orphaned_fts()

    def fix_stale_locks(self) -> FixResult:
        """Fix stale locks."""
        conn = self._get_connection()
        return RepairManager(self.db_path, conn).fix_stale_locks()

    def __del__(self) -> None:
        """Close database connection on cleanup."""
        if self._conn:
            self._conn.close()
