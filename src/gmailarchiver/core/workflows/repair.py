"""Repair workflow for database diagnostics and auto-fix."""

from dataclasses import dataclass

from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class RepairConfig:
    """Configuration for repair operation."""

    state_db: str
    backfill: bool = False  # backfill missing offsets/message-ids
    dry_run: bool = False


@dataclass
class RepairResult:
    """Result of repair operation."""

    issues_found: int
    issues_fixed: int
    dry_run: bool
    details: list[str]


class RepairWorkflow:
    """Workflow for repairing database issues.

    This workflow runs diagnostics and optionally attempts to auto-fix
    detected issues. Uses Doctor facade for all repair operations.
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize repair workflow.

        Args:
            storage: HybridStorage instance for database access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: RepairConfig) -> RepairResult:
        """Execute the repair workflow.

        Args:
            config: Repair configuration dataclass

        Returns:
            RepairResult with operation outcomes
        """
        details: list[str] = []

        # Create Doctor instance
        doctor = await Doctor.create(
            db_path=config.state_db,
            validate_schema=False,  # Doctor needs to inspect any schema version
            auto_create=False,
        )

        try:
            # Run diagnostics
            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task("Running diagnostics") as task:
                        report = await doctor.run_diagnostics()
                        task.complete(f"Found {report.errors} errors, {report.warnings} warnings")
            else:
                report = await doctor.run_diagnostics()

            issues_found = report.errors + report.warnings

            # Collect details for non-OK checks
            for check in report.checks:
                if check.severity.value != "OK":
                    details.append(f"{check.name}: {check.message}")

            # If dry run, don't fix anything
            if config.dry_run:
                return RepairResult(
                    issues_found=issues_found,
                    issues_fixed=0,
                    dry_run=True,
                    details=details,
                )

            # Attempt auto-fix
            issues_fixed = 0
            if report.fixable_issues:
                if self.progress:
                    with self.progress.task_sequence() as seq:
                        with seq.task(
                            "Attempting auto-fix", total=len(report.fixable_issues)
                        ) as task:
                            fix_results = await doctor.run_auto_fix()
                            for fix_result in fix_results:
                                if fix_result.success:
                                    issues_fixed += 1
                                    details.append(f"Fixed: {fix_result.message}")
                                else:
                                    details.append(f"Failed: {fix_result.message}")
                                task.advance(1)
                            task.complete(f"Fixed {issues_fixed} issues")
                else:
                    fix_results = await doctor.run_auto_fix()
                    for fix_result in fix_results:
                        if fix_result.success:
                            issues_fixed += 1
                            details.append(f"Fixed: {fix_result.message}")
                        else:
                            details.append(f"Failed: {fix_result.message}")

            # Handle backfill if requested
            if config.backfill:
                if self.progress:
                    with self.progress.task_sequence() as seq:
                        with seq.task("Backfilling missing offsets") as task:
                            backfill_count = await self._backfill_offsets(doctor)
                            if backfill_count > 0:
                                issues_fixed += backfill_count
                                details.append(f"Backfilled {backfill_count} messages")
                                task.complete(f"Backfilled {backfill_count} messages")
                            else:
                                task.complete("No backfill needed")
                else:
                    backfill_count = await self._backfill_offsets(doctor)
                    if backfill_count > 0:
                        issues_fixed += backfill_count
                        details.append(f"Backfilled {backfill_count} messages")

            return RepairResult(
                issues_found=issues_found,
                issues_fixed=issues_fixed,
                dry_run=False,
                details=details,
            )

        finally:
            await doctor.close()

    async def _backfill_offsets(self, doctor: Doctor) -> int:
        """Backfill missing offsets from mbox files.

        Args:
            doctor: Doctor instance with database access

        Returns:
            Number of messages backfilled
        """
        # Get messages with invalid offsets
        db_manager = doctor._get_db_manager()
        if not db_manager:
            return 0

        invalid_messages = await db_manager.get_messages_with_invalid_offsets()
        if not invalid_messages:
            return 0

        # Use MigrationManager for backfill
        from gmailarchiver.data.migration import MigrationManager

        migrator = MigrationManager(db_manager.db_path)
        try:
            return await migrator.backfill_offsets_from_mbox(invalid_messages)
        finally:
            await migrator._close()
