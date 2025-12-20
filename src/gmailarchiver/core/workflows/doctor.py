"""Workflow for running system diagnostics.

This workflow coordinates running diagnostic checks using composable Steps:
1. DatabaseDiagnosticStep - Database health checks (schema, integrity, FTS, files)
2. EnvironmentDiagnosticStep - Environment checks (Python, deps, OAuth, credentials)
3. SystemDiagnosticStep - System checks (disk space, permissions, locks, temp)
"""

from dataclasses import dataclass

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class DoctorConfig:
    """Configuration for doctor operation."""

    verbose: bool = False


@dataclass
class DoctorResult:
    """Aggregated diagnostic results."""

    overall_status: CheckSeverity
    checks: list[CheckResult]
    checks_passed: int
    warnings: int
    errors: int
    fixable_issues: list[str]

    # Categorized for UI display
    database_checks: list[CheckResult]
    environment_checks: list[CheckResult]
    system_checks: list[CheckResult]


class DoctorWorkflow:
    """Workflow for running system diagnostics.

    Uses Step composition for reusable diagnostic operations:
    - DatabaseDiagnosticStep for database/archive health
    - EnvironmentDiagnosticStep for Python environment health
    - SystemDiagnosticStep for system resource health
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize workflow with storage layer.

        Args:
            storage: HybridStorage instance for database access
            progress: Optional progress reporter
        """
        self.storage = storage
        self.progress = progress

        # Import here to avoid circular imports
        from gmailarchiver.core.workflows.steps.doctor import (
            DatabaseDiagnosticStep,
            EnvironmentDiagnosticStep,
            SystemDiagnosticStep,
        )

        self._db_step = DatabaseDiagnosticStep()
        self._env_step = EnvironmentDiagnosticStep()
        self._sys_step = SystemDiagnosticStep()

    async def run(self, config: DoctorConfig) -> DoctorResult:
        """Run diagnostic workflow with all 3 category checks.

        Args:
            config: Configuration with verbose flag

        Returns:
            DoctorResult with categorized check results
        """
        # Create Doctor facade (managed internally by workflow)
        # storage.db.db_path is already a Path object
        doctor = Doctor(
            db_path=self.storage.db.db_path,
            storage=self.storage,
            validate_schema=False,  # Doctor needs to inspect any schema version
            auto_create=False,  # Don't create DB if missing - that's a diagnostic
        )

        # Create context and inject doctor
        context = StepContext()
        context.set("doctor", doctor)

        # Build workflow
        workflow = (
            WorkflowComposer("doctor")
            .add_step(self._db_step)
            .add_step(self._env_step)
            .add_step(self._sys_step)
        )

        # Execute all steps (no input_data needed - doctor in context)
        try:
            await workflow.run(None, progress=self.progress, context=context)
        except Exception:
            pass  # Diagnostics never fail, always show what we found

        # Aggregate results from context
        db_checks: list[CheckResult] = context.get("database_checks", []) or []
        env_checks: list[CheckResult] = context.get("environment_checks", []) or []
        sys_checks: list[CheckResult] = context.get("system_checks", []) or []
        all_checks: list[CheckResult] = db_checks + env_checks + sys_checks

        # Calculate statistics
        passed = sum(1 for c in all_checks if c.severity == CheckSeverity.OK)
        warnings = sum(1 for c in all_checks if c.severity == CheckSeverity.WARNING)
        errors = sum(1 for c in all_checks if c.severity == CheckSeverity.ERROR)

        # Determine overall status
        overall = (
            CheckSeverity.ERROR
            if errors > 0
            else (CheckSeverity.WARNING if warnings > 0 else CheckSeverity.OK)
        )

        # Collect fixable issues
        fixable = [c.name for c in all_checks if c.fixable and c.severity != CheckSeverity.OK]

        return DoctorResult(
            overall_status=overall,
            checks=all_checks,
            checks_passed=passed,
            warnings=warnings,
            errors=errors,
            fixable_issues=fixable,
            database_checks=db_checks,
            environment_checks=env_checks,
            system_checks=sys_checks,
        )
