"""Repair workflow for database diagnostics and auto-fix.

This workflow uses the WorkflowComposer + Step architecture:
1. DiagnoseStep: Run full diagnostics and identify issues
2. AutoFixStep: Attempt to auto-fix fixable issues (conditional on dry_run)
3. ValidateRepairStep: Re-validate after repair to confirm fixes (conditional)
"""

from dataclasses import dataclass, field
from typing import Any

from gmailarchiver.core.doctor._diagnostics import CheckSeverity
from gmailarchiver.core.doctor._repair import FixResult
from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import StepContext, WorkflowError
from gmailarchiver.core.workflows.steps.repair import (
    AutoFixStep,
    DiagnoseStep,
    ValidateRepairStep,
)
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
    details: list[str] = field(default_factory=list)
    remaining_issues: int = 0
    validation_passed: bool = True


class RepairWorkflow:
    """Workflow for repairing database issues.

    This workflow runs diagnostics and optionally attempts to auto-fix
    detected issues. Uses Doctor facade for all repair operations.

    Architecture: 3-step workflow via WorkflowComposer
    1. DiagnoseStep: Always runs - identifies issues
    2. AutoFixStep: Runs when dry_run=False
    3. ValidateRepairStep: Runs when dry_run=False AND issues_fixed > 0
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

        # Create steps
        self._diagnose_step = DiagnoseStep()
        self._auto_fix_step = AutoFixStep()
        self._validate_step = ValidateRepairStep()

        # Create workflow composer with conditional steps
        self._composer = (
            WorkflowComposer("repair")
            .add_step(self._diagnose_step)
            .add_conditional_step(self._auto_fix_step, self._should_fix)
            .add_conditional_step(self._validate_step, self._should_validate)
        )

    @staticmethod
    def _should_fix(ctx: StepContext) -> bool:
        """Condition for auto-fix step: only when not in dry run mode."""
        config: dict[str, Any] = ctx.get("config", {}) or {}
        return not config.get("dry_run", True)

    @staticmethod
    def _should_validate(ctx: StepContext) -> bool:
        """Condition for validate step: only when not dry run AND issues were fixed."""
        config: dict[str, Any] = ctx.get("config", {}) or {}
        if config.get("dry_run", True):
            return False
        issues_fixed: int = ctx.get("issues_fixed", 0) or 0
        return issues_fixed > 0

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

        # Create context and inject dependencies
        context = StepContext()
        context.set("doctor", doctor)
        context.set(
            "config",
            {
                "state_db": config.state_db,
                "backfill": config.backfill,
                "dry_run": config.dry_run,
            },
        )

        try:
            # Execute workflow
            await self._composer.run(None, progress=self.progress, context=context)

            # Extract results from context
            issues_found: int = context.get("issues_found", 0) or 0
            issues_fixed: int = context.get("issues_fixed", 0) or 0
            remaining_issues: int = context.get("remaining_issues", 0) or 0
            validation_passed: bool = context.get("validation_passed", True) or True

            # Build details from diagnosis report
            diagnosis_report = context.get("diagnosis_report")
            if diagnosis_report:
                for check in diagnosis_report.checks:
                    if check.severity != CheckSeverity.OK:
                        details.append(f"{check.name}: {check.message}")

            # Add fix results to details
            fix_results: list[FixResult] = context.get("fix_results", []) or []
            if fix_results:
                for fix_result in fix_results:
                    if fix_result.success:
                        details.append(f"Fixed: {fix_result.message}")
                    else:
                        details.append(f"Failed: {fix_result.message}")

            # Add backfill results to details
            if config.backfill and issues_fixed > 0:
                # Check if there were backfills done by checking if issues_fixed
                # exceeds fix_results successful count
                successful_fixes = sum(1 for r in fix_results if r.success)
                backfill_count = issues_fixed - successful_fixes
                if backfill_count > 0:
                    details.append(f"Backfilled {backfill_count} messages")

            return RepairResult(
                issues_found=issues_found,
                issues_fixed=issues_fixed,
                dry_run=config.dry_run,
                details=details,
                remaining_issues=remaining_issues,
                validation_passed=validation_passed,
            )

        except WorkflowError:
            # Re-raise the original exception if stored in context
            original_exception = context.get("_exception")
            if original_exception is not None:
                raise original_exception
            raise

        finally:
            await doctor.close()
