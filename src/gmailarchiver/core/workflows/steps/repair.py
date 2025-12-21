"""Repair steps for database diagnostics, auto-fix, and validation.

This module provides steps for running repair operations:
- DiagnoseStep: Run full diagnostics and identify issues
- AutoFixStep: Attempt to auto-fix fixable issues (with optional backfill)
- ValidateRepairStep: Re-validate after repair to confirm fixes
"""

from typing import Any

from gmailarchiver.core.doctor._diagnostics import CheckSeverity
from gmailarchiver.core.doctor._repair import FixResult
from gmailarchiver.core.doctor.facade import Doctor, DoctorReport
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


class DiagnoseStep:
    """Step that runs full diagnostics and identifies issues.

    Runs all diagnostic checks via the Doctor facade and identifies
    fixable issues for the auto-fix step.

    Input: None (uses doctor from context)
    Output: DoctorReport (stored in context["diagnosis_report"])
    Context: Reads "doctor"; sets "diagnosis_report", "fixable_issues", "issues_found"
    """

    name = "diagnose"
    description = "Running diagnostics"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[DoctorReport]:
        """Run full diagnostics.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with DoctorReport data
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Running diagnostics") as task:
                        report = await doctor.run_diagnostics()
                        task.complete(f"Found {report.errors} errors, {report.warnings} warnings")
            else:
                report = await doctor.run_diagnostics()

            # Store results in context
            context.set("diagnosis_report", report)
            context.set("fixable_issues", report.fixable_issues)

            # Count non-OK checks as issues
            issues_found = sum(1 for check in report.checks if check.severity != CheckSeverity.OK)
            context.set("issues_found", issues_found)

            return StepResult.ok(report)

        except Exception as e:
            # Store exception for potential re-raise by workflow
            context.set("_exception", e)
            return StepResult.fail(f"Diagnostics failed: {e}")


class AutoFixStep:
    """Step that attempts to auto-fix fixable issues.

    Uses the Doctor facade to auto-fix detected issues. Optionally runs
    backfill for missing offsets via MigrationManager when config.backfill=True.

    Input: None (uses doctor and config from context)
    Output: list[FixResult] (stored in context["fix_results"])
    Context: Reads "doctor", "config", "fixable_issues";
             sets "fix_results", "issues_fixed"
    """

    name = "auto_fix"
    description = "Attempting auto-fix"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[list[FixResult]]:
        """Attempt auto-fix for all fixable issues.

        Args:
            context: Shared step context (expects "doctor", "fixable_issues" keys)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with list of FixResult data
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        fixable_issues: list[str] = context.get("fixable_issues", []) or []
        config: dict[str, Any] = context.get("config", {}) or {}
        issues_fixed = 0
        fix_results: list[FixResult] = []

        try:
            # Run auto-fix if there are fixable issues
            if fixable_issues:
                if progress:
                    with progress.task_sequence() as seq:
                        with seq.task("Attempting auto-fix", total=len(fixable_issues)) as task:
                            fix_results = await doctor.run_auto_fix()
                            for fix_result in fix_results:
                                if fix_result.success:
                                    issues_fixed += 1
                                task.advance(1)
                            task.complete(f"Fixed {issues_fixed} issues")
                else:
                    fix_results = await doctor.run_auto_fix()
                    for fix_result in fix_results:
                        if fix_result.success:
                            issues_fixed += 1

            # Handle backfill if requested
            if config.get("backfill", False):
                backfill_count = await self._run_backfill(context, doctor, progress)
                issues_fixed += backfill_count

            # Store results in context
            context.set("fix_results", fix_results)
            context.set("issues_fixed", issues_fixed)

            return StepResult.ok(fix_results)

        except Exception as e:
            # Store exception for potential re-raise by workflow
            context.set("_exception", e)
            return StepResult.fail(f"Auto-fix failed: {e}")

    async def _run_backfill(
        self,
        context: StepContext,
        doctor: Doctor,
        progress: ProgressReporter | None,
    ) -> int:
        """Run backfill for missing offsets.

        Args:
            context: Step context (may contain migration_manager for testing)
            doctor: Doctor facade with database access
            progress: Optional progress reporter

        Returns:
            Number of messages backfilled
        """
        import asyncio

        # Get messages with invalid offsets
        # Note: _get_db_manager is a sync method, but in tests with AsyncMock
        # it may return a coroutine, so we handle both cases
        db_manager_result = doctor._get_db_manager()
        if asyncio.iscoroutine(db_manager_result):
            db_manager = await db_manager_result
        else:
            db_manager = db_manager_result

        if not db_manager:
            return 0

        invalid_messages = await db_manager.get_messages_with_invalid_offsets()
        if not invalid_messages:
            return 0

        # Use migration manager from context (for testing) or create new one
        migration_manager = context.get("migration_manager")

        if migration_manager is None:
            from gmailarchiver.data.migration import MigrationManager

            migration_manager = MigrationManager(db_manager.db_path)

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Backfilling missing offsets") as task:
                        count = await migration_manager.backfill_offsets_from_mbox(invalid_messages)
                        task.complete(f"Backfilled {count} messages")
            else:
                count = await migration_manager.backfill_offsets_from_mbox(invalid_messages)

            return count
        finally:
            # Always close migration manager
            await migration_manager._close()


class ValidateRepairStep:
    """Step that validates repair results by re-running diagnostics.

    Re-runs diagnostics to check if issues have been resolved.
    Compares remaining issues to initial issues to determine success.

    Input: None (uses doctor from context)
    Output: Dict with remaining_issues and validation_passed
    Context: Reads "doctor", "issues_found";
             sets "remaining_issues", "validation_passed"
    """

    name = "validate_repair"
    description = "Validating repair results"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[dict[str, Any]]:
        """Validate repair by re-running diagnostics.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with validation details
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        initial_issues: int = context.get("issues_found", 0) or 0

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Validating repair results") as task:
                        report = await doctor.run_diagnostics()
                        remaining = sum(
                            1 for check in report.checks if check.severity != CheckSeverity.OK
                        )
                        task.complete(f"{remaining} issues remaining")
            else:
                report = await doctor.run_diagnostics()
                remaining = sum(1 for check in report.checks if check.severity != CheckSeverity.OK)

            # Store results in context
            context.set("remaining_issues", remaining)

            # Validation passes if remaining issues are fewer than initial,
            # OR if there were no issues to begin with (0 == 0 means success)
            validation_passed = remaining < initial_issues or (
                initial_issues == 0 and remaining == 0
            )
            context.set("validation_passed", validation_passed)

            result_data = {
                "remaining_issues": remaining,
                "validation_passed": validation_passed,
            }

            return StepResult.ok(result_data)

        except Exception as e:
            # Store exception for potential re-raise by workflow
            context.set("_exception", e)
            return StepResult.fail(f"Validation failed: {e}")
