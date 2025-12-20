"""Diagnostic steps for system health checks.

This module provides steps for running diagnostic checks:
- DatabaseDiagnosticStep: Run archive and database health diagnostics
- EnvironmentDiagnosticStep: Run Python environment health diagnostics
- SystemDiagnosticStep: Run system health diagnostics
"""

from dataclasses import dataclass
from typing import Any

from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class DiagnosticInput:
    """Input for diagnostic steps (currently no specific input needed)."""

    pass


class DatabaseDiagnosticStep:
    """Step that runs archive and database health diagnostics.

    Runs 4 database-related health checks:
    - Database schema version
    - Database integrity
    - Orphaned FTS records
    - Archive files existence

    Input: None (uses doctor from context)
    Output: None (writes CheckResult list to context["database_checks"])
    Context: Reads DOCTOR, sets "database_checks"
    """

    name = "database_diagnostics"
    description = "Running database diagnostics"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[None]:
        """Run database health diagnostics.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with None data (results stored in context)
        """
        # Get doctor from context (injected by workflow)
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Running database checks") as task:
                        checks = await doctor.check_archive_health()
                        task.complete(f"Completed {len(checks)} checks")
            else:
                checks = await doctor.check_archive_health()

            # Write results to context
            context.set("database_checks", checks)

            return StepResult.ok(None)

        except Exception as e:
            return StepResult.fail(f"Database diagnostics failed: {e}")


class EnvironmentDiagnosticStep:
    """Step that runs Python environment health diagnostics.

    Runs 4 environment-related health checks:
    - Python version
    - Dependencies installed
    - OAuth token validity
    - Credentials file existence

    Input: None (uses doctor from context)
    Output: None (writes CheckResult list to context["environment_checks"])
    Context: Reads DOCTOR, sets "environment_checks"
    """

    name = "environment_diagnostics"
    description = "Running environment diagnostics"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[None]:
        """Run environment health diagnostics.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with None data (results stored in context)
        """
        # Get doctor from context (injected by workflow)
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Running environment checks") as task:
                        checks = await doctor.check_environment_health()
                        task.complete(f"Completed {len(checks)} checks")
            else:
                checks = await doctor.check_environment_health()

            # Write results to context
            context.set("environment_checks", checks)

            return StepResult.ok(None)

        except Exception as e:
            return StepResult.fail(f"Environment diagnostics failed: {e}")


class SystemDiagnosticStep:
    """Step that runs system health diagnostics.

    Runs 4 system-related health checks:
    - Disk space availability
    - Write permissions
    - Stale lock files
    - Temp directory accessibility

    Input: None (uses doctor from context)
    Output: None (writes CheckResult list to context["system_checks"])
    Context: Reads DOCTOR, sets "system_checks"
    """

    name = "system_diagnostics"
    description = "Running system diagnostics"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[None]:
        """Run system health diagnostics.

        Args:
            context: Shared step context (expects "doctor" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with None data (results stored in context)
        """
        # Get doctor from context (injected by workflow)
        doctor: Doctor | None = context.get("doctor")
        if not doctor:
            return StepResult.fail("Doctor not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Running system checks") as task:
                        checks = await doctor.check_system_health()
                        task.complete(f"Completed {len(checks)} checks")
            else:
                checks = await doctor.check_system_health()

            # Write results to context
            context.set("system_checks", checks)

            return StepResult.ok(None)

        except Exception as e:
            return StepResult.fail(f"System diagnostics failed: {e}")
