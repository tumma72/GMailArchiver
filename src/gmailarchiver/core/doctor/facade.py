"""System diagnostics and auto-repair facade for Gmail Archiver."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity, DiagnosticsRunner
from gmailarchiver.core.doctor._repair import FixResult, RepairManager
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage


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
        self,
        db_path: Path,
        storage: HybridStorage | None,
        validate_schema: bool = True,
        auto_create: bool = True,
    ) -> None:
        """Initialize doctor (internal - use create() instead).

        Args:
            db_path: Path to SQLite database file
            storage: Pre-initialized HybridStorage instance (or None if not available)
            validate_schema: Whether to validate schema on init
            auto_create: Whether to auto-create database if missing
        """
        self.db_path = db_path
        self.validate_schema = validate_schema
        self.auto_create = auto_create
        self._storage = storage

    @classmethod
    async def create(
        cls,
        db_path: str,
        storage: HybridStorage | None = None,
        validate_schema: bool = True,
        auto_create: bool = True,
    ) -> Self:
        """Create and initialize Doctor instance.

        Args:
            db_path: Path to SQLite database file
            storage: Pre-initialized HybridStorage instance (or None to create new)
            validate_schema: Whether to validate schema on init
            auto_create: Whether to auto-create database if missing

        Returns:
            Initialized Doctor instance
        """
        path = Path(db_path) if db_path != ":memory:" else Path(":memory:")

        # Create storage if not provided
        if storage is None:
            db_manager = await cls._create_db_manager(path, auto_create)
            if db_manager:
                storage = HybridStorage(db_manager)
            else:
                storage = None

        return cls(path, storage, validate_schema, auto_create)

    @staticmethod
    async def _create_db_manager(db_path: Path, auto_create: bool) -> DBManager | None:
        """Create DBManager instance, handling errors gracefully."""
        try:
            if str(db_path) == ":memory:":
                db = DBManager(":memory:", validate_schema=False, auto_create=True)
                await db.initialize()
                return db
            elif db_path.exists():
                # For diagnostics, we don't want to fail on schema validation
                # Doctor needs to be able to inspect databases with any schema version
                db = DBManager(str(db_path), validate_schema=False, auto_create=False)
                await db.initialize()
                return db
            elif auto_create:
                db = DBManager(str(db_path), validate_schema=False, auto_create=True)
                await db.initialize()
                return db
            else:
                return None
        except Exception:
            return None

    def _get_db_manager(self) -> DBManager | None:
        """Get cached DBManager instance from storage."""
        return self._storage.db if self._storage else None

    async def check_archive_health(self) -> list[CheckResult]:
        """Check archive and database health (4 checks).

        Returns:
            List of CheckResult for database-related checks
        """
        diagnostics = DiagnosticsRunner(self.db_path, self._storage)

        checks: list[CheckResult] = []
        checks.append(await diagnostics.check_database_schema())
        checks.append(await diagnostics.check_database_integrity())
        checks.append(await diagnostics.check_orphaned_fts())
        checks.append(await diagnostics.check_archive_files_exist())

        return checks

    async def check_environment_health(self) -> list[CheckResult]:
        """Check Python environment health (4 checks).

        Returns:
            List of CheckResult for environment-related checks
        """
        diagnostics = DiagnosticsRunner(self.db_path, self._storage)

        checks: list[CheckResult] = []
        checks.append(diagnostics.check_python_version())
        checks.append(diagnostics.check_dependencies())
        checks.append(diagnostics.check_oauth_token())
        checks.append(diagnostics.check_credentials_file())

        return checks

    async def check_system_health(self) -> list[CheckResult]:
        """Check system health (4 checks).

        Returns:
            List of CheckResult for system-related checks
        """
        diagnostics = DiagnosticsRunner(self.db_path, self._storage)

        checks: list[CheckResult] = []
        checks.append(diagnostics.check_disk_space())
        checks.append(diagnostics.check_write_permissions())
        checks.append(diagnostics.check_stale_locks())
        checks.append(diagnostics.check_temp_directory())

        return checks

    async def run_diagnostics(self) -> DoctorReport:
        """Run all diagnostic checks.

        Returns:
            DoctorReport with results of all checks
        """
        checks: list[CheckResult] = []

        # Use the granular methods for each category
        checks.extend(await self.check_archive_health())
        checks.extend(await self.check_environment_health())
        checks.extend(await self.check_system_health())

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

    async def run_auto_fix(self) -> list[FixResult]:
        """Run auto-fix for all fixable issues.

        Returns:
            List of FixResult for each attempted fix
        """
        results: list[FixResult] = []

        # Run diagnostics to find fixable issues
        report = await self.run_diagnostics()

        # Initialize repair manager
        db_manager = self._get_db_manager()
        repair = RepairManager(self.db_path, db_manager)

        for check in report.checks:
            if check.fixable and check.severity != CheckSeverity.OK:
                # Attempt to fix based on check name
                if "schema" in check.name.lower() and "not found" in check.message.lower():
                    results.append(await repair.fix_missing_database())
                elif "orphaned" in check.name.lower():
                    results.append(await repair.fix_orphaned_fts())
                elif "lock" in check.name.lower():
                    results.append(repair.fix_stale_locks())
                # Note: Some issues like expired token require user action (re-auth)

        return results

    # Delegation methods for direct access to diagnostics/repair
    async def check_database_schema(self) -> CheckResult:
        """Check database schema version."""
        return await DiagnosticsRunner(self.db_path, self._storage).check_database_schema()

    async def check_database_integrity(self) -> CheckResult:
        """Check database integrity."""
        return await DiagnosticsRunner(self.db_path, self._storage).check_database_integrity()

    async def check_orphaned_fts(self) -> CheckResult:
        """Check for orphaned FTS records."""
        return await DiagnosticsRunner(self.db_path, self._storage).check_orphaned_fts()

    async def check_archive_files_exist(self) -> CheckResult:
        """Check that archive files exist."""
        return await DiagnosticsRunner(self.db_path, self._storage).check_archive_files_exist()

    def check_python_version(self) -> CheckResult:
        """Check Python version."""
        return DiagnosticsRunner(self.db_path, self._storage).check_python_version()

    def check_dependencies(self) -> CheckResult:
        """Check dependencies."""
        return DiagnosticsRunner(self.db_path, self._storage).check_dependencies()

    def check_oauth_token(self) -> CheckResult:
        """Check OAuth token."""
        return DiagnosticsRunner(self.db_path, self._storage).check_oauth_token()

    def check_credentials_file(self) -> CheckResult:
        """Check credentials file."""
        return DiagnosticsRunner(self.db_path, self._storage).check_credentials_file()

    def check_disk_space(self) -> CheckResult:
        """Check disk space."""
        return DiagnosticsRunner(self.db_path, self._storage).check_disk_space()

    def check_write_permissions(self) -> CheckResult:
        """Check write permissions."""
        return DiagnosticsRunner(self.db_path, self._storage).check_write_permissions()

    def check_stale_locks(self) -> CheckResult:
        """Check stale locks."""
        return DiagnosticsRunner(self.db_path, self._storage).check_stale_locks()

    def check_temp_directory(self) -> CheckResult:
        """Check temp directory."""
        return DiagnosticsRunner(self.db_path, self._storage).check_temp_directory()

    async def check_mbox_offsets(self, archive_file: str | None = None) -> CheckResult:
        """Check mbox offset accuracy.

        Args:
            archive_file: Optional specific archive file to check

        Returns:
            CheckResult with offset validation status
        """
        return await DiagnosticsRunner(self.db_path, self._storage).check_mbox_offsets(
            archive_file=archive_file
        )

    async def fix_missing_database(self) -> FixResult:
        """Fix missing database."""
        db_manager = self._get_db_manager()
        return await RepairManager(self.db_path, db_manager).fix_missing_database()

    async def fix_orphaned_fts(self) -> FixResult:
        """Fix orphaned FTS records."""
        db_manager = self._get_db_manager()
        return await RepairManager(self.db_path, db_manager).fix_orphaned_fts()

    def fix_stale_locks(self) -> FixResult:
        """Fix stale locks."""
        db_manager = self._get_db_manager()
        return RepairManager(self.db_path, db_manager).fix_stale_locks()

    async def close(self) -> None:
        """Close resources."""
        # Close database connection to prevent resource warnings
        if self._storage is not None and self._storage.db is not None:
            await self._storage.db.close()

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit - ensures resources are closed."""
        await self.close()
