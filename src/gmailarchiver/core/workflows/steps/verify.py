"""Verification steps for database and archive checks.

This module provides steps for running verification checks:
- VerifyIntegrityStep: Run database integrity checks
- VerifyConsistencyStep: Run database-archive consistency checks
- VerifyOffsetsStep: Run mbox offset accuracy checks
"""

from typing import Any

from gmailarchiver.core.doctor._diagnostics import CheckResult
from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


class VerifyIntegrityStep:
    """Step that runs database integrity checks.

    Runs database integrity check using PRAGMA integrity_check.

    Input: None (uses doctor from context)
    Output: CheckResult (stored in context["integrity_result"])
    Context: Reads "doctor", sets "integrity_result"
    """

    name = "verify_integrity"
    description = "Verifying database integrity"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[CheckResult]:
        """Run database integrity check.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with CheckResult data
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Checking database integrity") as task:
                        check = await doctor.check_database_integrity()
                        if check.severity.value == "OK":
                            task.complete("Database integrity check passed")
                        else:
                            task.fail("Database integrity check failed")
            else:
                check = await doctor.check_database_integrity()

            context.set("integrity_result", check)

            return StepResult.ok(check)

        except Exception as e:
            return StepResult.fail(f"Integrity check failed: {e}")


class VerifyConsistencyStep:
    """Step that runs database-archive consistency checks.

    Runs multiple consistency checks:
    - Database schema version
    - Orphaned FTS records
    - Archive files existence

    Input: None (uses doctor from context)
    Output: list[CheckResult] (stored in context["consistency_results"])
    Context: Reads "doctor", sets "consistency_results"
    """

    name = "verify_consistency"
    description = "Verifying database-archive consistency"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[list[CheckResult]]:
        """Run database-archive consistency checks.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with list of CheckResult data
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Checking database-archive consistency") as task:
                        checks = [
                            await doctor.check_database_schema(),
                            await doctor.check_orphaned_fts(),
                            await doctor.check_archive_files_exist(),
                        ]
                        passed = all(c.severity.value == "OK" for c in checks)
                        if passed:
                            task.complete("All consistency checks passed")
                        else:
                            issues = sum(1 for c in checks if c.severity.value != "OK")
                            task.fail(f"Found {issues} consistency issues")
            else:
                checks = [
                    await doctor.check_database_schema(),
                    await doctor.check_orphaned_fts(),
                    await doctor.check_archive_files_exist(),
                ]

            context.set("consistency_results", checks)

            return StepResult.ok(checks)

        except Exception as e:
            return StepResult.fail(f"Consistency check failed: {e}")


class VerifyOffsetsStep:
    """Step that runs mbox offset accuracy checks.

    Verifies that mbox offsets in the database are accurate.

    Input: Optional archive file path (string) to check specific file
    Output: CheckResult (stored in context["offsets_result"])
    Context: Reads "doctor", sets "offsets_result"
    """

    name = "verify_offsets"
    description = "Verifying mbox offset accuracy"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[CheckResult]:
        """Run mbox offset verification.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Optional archive file path to check
            progress: Optional progress reporter

        Returns:
            StepResult with CheckResult data
        """
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Checking mbox offsets") as task:
                        if input_data:
                            check = await doctor.check_mbox_offsets(archive_file=input_data)
                        else:
                            check = await doctor.check_mbox_offsets()
                        if check.severity.value == "OK":
                            task.complete("Offset verification passed")
                        else:
                            task.fail("Offset verification failed")
            else:
                if input_data:
                    check = await doctor.check_mbox_offsets(archive_file=input_data)
                else:
                    check = await doctor.check_mbox_offsets()

            context.set("offsets_result", check)

            return StepResult.ok(check)

        except Exception as e:
            return StepResult.fail(f"Offset check failed: {e}")
