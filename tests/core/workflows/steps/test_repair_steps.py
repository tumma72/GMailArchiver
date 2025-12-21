"""Tests for repair steps - TDD Red Phase.

These tests define the expected behavior for:
- DiagnoseStep: Runs full diagnostics and identifies issues
- AutoFixStep: Attempts to auto-fix fixable issues (with optional backfill)
- ValidateRepairStep: Re-validates after repair to confirm fixes

All tests should FAIL initially because the steps don't exist yet.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.doctor._repair import FixResult
from gmailarchiver.core.doctor.facade import DoctorReport
from gmailarchiver.core.workflows.step import StepContext

# Import the steps that don't exist yet - these imports will fail
# until implementation is complete. We use try/except to allow
# tests to be collected, but they will fail when the module doesn't exist.
try:
    from gmailarchiver.core.workflows.steps.repair import (
        AutoFixStep,
        DiagnoseStep,
        ValidateRepairStep,
    )
except ImportError:
    # Mark module as missing for pytest.skip
    DiagnoseStep = None
    AutoFixStep = None
    ValidateRepairStep = None

# Skip all tests in this module if the repair steps module doesn't exist
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        DiagnoseStep is None,
        reason="repair steps module not implemented yet (TDD Red Phase)",
    ),
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_doctor() -> AsyncMock:
    """Create a mock Doctor facade for testing."""
    doctor = AsyncMock()

    # Default to no issues found
    doctor.run_diagnostics.return_value = DoctorReport(
        overall_status=CheckSeverity.OK,
        checks=[
            CheckResult(
                name="database_schema",
                severity=CheckSeverity.OK,
                message="Schema version is valid",
                fixable=False,
            )
        ],
        checks_passed=1,
        warnings=0,
        errors=0,
        fixable_issues=[],
    )

    doctor.run_auto_fix.return_value = []
    doctor.close.return_value = None

    return doctor


@pytest.fixture
def mock_doctor_with_issues() -> AsyncMock:
    """Create a mock Doctor with fixable issues."""
    doctor = AsyncMock()

    doctor.run_diagnostics.return_value = DoctorReport(
        overall_status=CheckSeverity.ERROR,
        checks=[
            CheckResult(
                name="orphaned_fts",
                severity=CheckSeverity.ERROR,
                message="FTS table is missing",
                fixable=True,
            ),
            CheckResult(
                name="stale_locks",
                severity=CheckSeverity.WARNING,
                message="Stale lock files found",
                fixable=True,
            ),
            CheckResult(
                name="disk_space",
                severity=CheckSeverity.OK,
                message="Disk space OK",
                fixable=False,
            ),
        ],
        checks_passed=1,
        warnings=1,
        errors=1,
        fixable_issues=["orphaned_fts", "stale_locks"],
    )

    doctor.run_auto_fix.return_value = [
        FixResult(check_name="orphaned_fts", success=True, message="FTS table rebuilt"),
        FixResult(check_name="stale_locks", success=True, message="Lock files removed"),
    ]

    doctor.close.return_value = None

    return doctor


@pytest.fixture
def mock_migration_manager() -> AsyncMock:
    """Create a mock MigrationManager for backfill testing."""
    manager = AsyncMock()
    manager.backfill_offsets_from_mbox.return_value = 5
    manager._close.return_value = None
    return manager


@pytest.fixture
def mock_progress() -> MagicMock:
    """Create a mock progress reporter for testing."""
    progress = MagicMock()

    # Create mock task sequence with proper context manager
    task_seq = MagicMock()
    progress.task_sequence.return_value.__enter__ = MagicMock(return_value=task_seq)
    progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)

    # Create mock task handle
    task_handle = MagicMock()
    task_handle.advance = MagicMock()
    task_handle.complete = MagicMock()
    task_seq.task.return_value.__enter__ = MagicMock(return_value=task_handle)
    task_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    return progress


@pytest.fixture
def context_with_doctor(mock_doctor: AsyncMock) -> StepContext:
    """Create a StepContext with mock doctor injected."""
    context = StepContext()
    context.set("doctor", mock_doctor)
    return context


@pytest.fixture
def context_with_doctor_and_issues(mock_doctor_with_issues: AsyncMock) -> StepContext:
    """Create a StepContext with mock doctor that has issues."""
    context = StepContext()
    context.set("doctor", mock_doctor_with_issues)
    return context


@pytest.fixture
def repair_config() -> dict:
    """Create a sample repair configuration."""
    return {
        "state_db": "/path/to/test.db",
        "dry_run": False,
        "backfill": False,
    }


# ============================================================================
# Test: DiagnoseStep
# ============================================================================


class TestDiagnoseStep:
    """Test DiagnoseStep execution."""

    async def test_can_instantiate(self) -> None:
        """DiagnoseStep can be instantiated."""
        step = DiagnoseStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """DiagnoseStep has the correct name attribute."""
        step = DiagnoseStep()
        assert step.name == "diagnose"

    async def test_has_correct_description(self) -> None:
        """DiagnoseStep has the correct description attribute."""
        step = DiagnoseStep()
        assert step.description == "Running diagnostics"

    async def test_execute_calls_doctor_run_diagnostics(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute calls doctor.run_diagnostics()."""
        step = DiagnoseStep()

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        mock_doctor.run_diagnostics.assert_called_once()

    async def test_stores_diagnosis_report_in_context(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute stores diagnosis_report in context."""
        step = DiagnoseStep()

        await step.execute(context_with_doctor, None)

        stored_report = context_with_doctor.get("diagnosis_report")
        assert stored_report is not None
        assert isinstance(stored_report, DoctorReport)

    async def test_stores_fixable_issues_in_context(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute stores fixable_issues list in context."""
        step = DiagnoseStep()

        await step.execute(context_with_doctor_and_issues, None)

        fixable_issues = context_with_doctor_and_issues.get("fixable_issues")
        assert fixable_issues is not None
        assert isinstance(fixable_issues, list)
        assert "orphaned_fts" in fixable_issues
        assert "stale_locks" in fixable_issues

    async def test_stores_issues_found_count_in_context(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute stores issues_found count in context."""
        step = DiagnoseStep()

        await step.execute(context_with_doctor_and_issues, None)

        issues_found = context_with_doctor_and_issues.get("issues_found")
        assert issues_found is not None
        assert issues_found == 2  # 1 error + 1 warning

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = DiagnoseStep()
        context = StepContext()  # No doctor injected

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = DiagnoseStep()

        mock_doctor.run_diagnostics.side_effect = Exception("Database error")

        result = await step.execute(context_with_doctor, None)

        assert result.success is False
        assert "Diagnostics failed" in result.error
        assert "Database error" in result.error

    async def test_handles_no_progress_reporter(self, context_with_doctor: StepContext) -> None:
        """Step works without progress reporter."""
        step = DiagnoseStep()

        result = await step.execute(context_with_doctor, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_doctor: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = DiagnoseStep()

        result = await step.execute(context_with_doctor, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_doctor_report(
        self, context_with_doctor: StepContext
    ) -> None:
        """Execute result data contains the DoctorReport."""
        step = DiagnoseStep()

        result = await step.execute(context_with_doctor, None)

        assert result.data is not None
        assert isinstance(result.data, DoctorReport)
        assert result.data.overall_status == CheckSeverity.OK

    async def test_counts_only_non_ok_checks_as_issues(
        self, context_with_doctor_and_issues: StepContext
    ) -> None:
        """Only non-OK checks are counted as issues_found."""
        step = DiagnoseStep()

        await step.execute(context_with_doctor_and_issues, None)

        # Should be 2 (1 error + 1 warning), not 3 (which includes OK)
        assert context_with_doctor_and_issues.get("issues_found") == 2


# ============================================================================
# Test: AutoFixStep
# ============================================================================


class TestAutoFixStep:
    """Test AutoFixStep execution."""

    async def test_can_instantiate(self) -> None:
        """AutoFixStep can be instantiated."""
        step = AutoFixStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """AutoFixStep has the correct name attribute."""
        step = AutoFixStep()
        assert step.name == "auto_fix"

    async def test_has_correct_description(self) -> None:
        """AutoFixStep has the correct description attribute."""
        step = AutoFixStep()
        assert step.description == "Attempting auto-fix"

    async def test_execute_calls_doctor_run_auto_fix(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute calls doctor.run_auto_fix()."""
        step = AutoFixStep()

        # Setup context with fixable issues from previous step
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        result = await step.execute(context_with_doctor_and_issues, None)

        assert result.success is True
        mock_doctor_with_issues.run_auto_fix.assert_called_once()

    async def test_stores_fix_results_in_context(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute stores fix_results in context."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        await step.execute(context_with_doctor_and_issues, None)

        fix_results = context_with_doctor_and_issues.get("fix_results")
        assert fix_results is not None
        assert isinstance(fix_results, list)
        assert len(fix_results) == 2

    async def test_stores_issues_fixed_count_in_context(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute stores issues_fixed count in context."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        await step.execute(context_with_doctor_and_issues, None)

        issues_fixed = context_with_doctor_and_issues.get("issues_fixed")
        assert issues_fixed == 2

    async def test_handles_partial_failures(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute handles when some fixes succeed and others fail."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        # Configure mixed results
        mock_doctor_with_issues.run_auto_fix.return_value = [
            FixResult(check_name="orphaned_fts", success=True, message="FTS rebuilt"),
            FixResult(check_name="stale_locks", success=False, message="Permission denied"),
        ]

        result = await step.execute(context_with_doctor_and_issues, None)

        assert result.success is True  # Step succeeds even with partial failures
        assert context_with_doctor_and_issues.get("issues_fixed") == 1

    async def test_skips_when_no_fixable_issues(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute skips auto-fix when no fixable issues exist."""
        step = AutoFixStep()
        context_with_doctor.set("fixable_issues", [])

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        mock_doctor.run_auto_fix.assert_not_called()
        assert context_with_doctor.get("issues_fixed") == 0

    async def test_runs_backfill_when_config_backfill_true(
        self,
        context_with_doctor_and_issues: StepContext,
        mock_doctor_with_issues: AsyncMock,
        mock_migration_manager: AsyncMock,
    ) -> None:
        """Execute runs backfill via migration_manager when config.backfill=True."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", [])
        context_with_doctor_and_issues.set("config", {"backfill": True, "state_db": "/test.db"})
        context_with_doctor_and_issues.set("migration_manager", mock_migration_manager)

        # Mock db_manager for getting invalid offsets
        mock_db_manager = AsyncMock()
        mock_db_manager.get_messages_with_invalid_offsets.return_value = [
            {"gmail_id": "msg1", "rfc_message_id": "<msg1@example.com>"}
        ]
        mock_doctor_with_issues._get_db_manager.return_value = mock_db_manager

        result = await step.execute(context_with_doctor_and_issues, None)

        assert result.success is True
        mock_migration_manager.backfill_offsets_from_mbox.assert_called_once()

    async def test_backfill_adds_to_issues_fixed_count(
        self,
        context_with_doctor_and_issues: StepContext,
        mock_doctor_with_issues: AsyncMock,
        mock_migration_manager: AsyncMock,
    ) -> None:
        """Backfill count is added to issues_fixed."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts"])
        context_with_doctor_and_issues.set("config", {"backfill": True, "state_db": "/test.db"})
        context_with_doctor_and_issues.set("migration_manager", mock_migration_manager)

        # Mock 1 fix + 5 backfill = 6 total
        mock_doctor_with_issues.run_auto_fix.return_value = [
            FixResult(check_name="orphaned_fts", success=True, message="FTS rebuilt")
        ]
        mock_migration_manager.backfill_offsets_from_mbox.return_value = 5

        mock_db_manager = AsyncMock()
        mock_db_manager.get_messages_with_invalid_offsets.return_value = [
            {"gmail_id": "msg1"} for _ in range(5)
        ]
        mock_doctor_with_issues._get_db_manager.return_value = mock_db_manager

        await step.execute(context_with_doctor_and_issues, None)

        assert context_with_doctor_and_issues.get("issues_fixed") == 6

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = AutoFixStep()
        context = StepContext()
        context.set("fixable_issues", ["something"])

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts"])

        mock_doctor_with_issues.run_auto_fix.side_effect = Exception("Repair failed")

        result = await step.execute(context_with_doctor_and_issues, None)

        assert result.success is False
        assert "Auto-fix failed" in result.error
        assert "Repair failed" in result.error

    async def test_handles_no_progress_reporter(
        self, context_with_doctor_and_issues: StepContext
    ) -> None:
        """Step works without progress reporter."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", [])

        result = await step.execute(context_with_doctor_and_issues, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self,
        context_with_doctor_and_issues: StepContext,
        mock_doctor_with_issues: AsyncMock,
        mock_progress: MagicMock,
    ) -> None:
        """Step reports progress when provided."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        result = await step.execute(context_with_doctor_and_issues, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_fix_results(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """Execute result data contains the FixResult list."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", ["orphaned_fts", "stale_locks"])

        result = await step.execute(context_with_doctor_and_issues, None)

        assert result.data is not None
        assert isinstance(result.data, list)
        assert all(isinstance(r, FixResult) for r in result.data)

    async def test_closes_migration_manager_after_backfill(
        self,
        context_with_doctor_and_issues: StepContext,
        mock_doctor_with_issues: AsyncMock,
        mock_migration_manager: AsyncMock,
    ) -> None:
        """Execute closes migration_manager after backfill."""
        step = AutoFixStep()
        context_with_doctor_and_issues.set("fixable_issues", [])
        context_with_doctor_and_issues.set("config", {"backfill": True, "state_db": "/test.db"})
        context_with_doctor_and_issues.set("migration_manager", mock_migration_manager)

        mock_db_manager = AsyncMock()
        mock_db_manager.get_messages_with_invalid_offsets.return_value = [{"gmail_id": "msg1"}]
        mock_doctor_with_issues._get_db_manager.return_value = mock_db_manager

        await step.execute(context_with_doctor_and_issues, None)

        mock_migration_manager._close.assert_called_once()


# ============================================================================
# Test: ValidateRepairStep
# ============================================================================


class TestValidateRepairStep:
    """Test ValidateRepairStep execution."""

    async def test_can_instantiate(self) -> None:
        """ValidateRepairStep can be instantiated."""
        step = ValidateRepairStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """ValidateRepairStep has the correct name attribute."""
        step = ValidateRepairStep()
        assert step.name == "validate_repair"

    async def test_has_correct_description(self) -> None:
        """ValidateRepairStep has the correct description attribute."""
        step = ValidateRepairStep()
        assert step.description == "Validating repair results"

    async def test_execute_calls_doctor_run_diagnostics_again(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute calls doctor.run_diagnostics() to re-validate."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        mock_doctor.run_diagnostics.assert_called_once()

    async def test_stores_remaining_issues_in_context(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute stores remaining_issues count in context."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        await step.execute(context_with_doctor, None)

        remaining = context_with_doctor.get("remaining_issues")
        assert remaining is not None
        assert remaining == 0  # Mock doctor returns OK report

    async def test_stores_validation_passed_true_when_issues_reduced(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """validation_passed=True when remaining_issues < initial issues."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 5)  # Initially had 5 issues

        # Mock doctor now returns 0 issues
        await step.execute(context_with_doctor, None)

        assert context_with_doctor.get("validation_passed") is True

    async def test_stores_validation_passed_false_when_issues_same(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """validation_passed=False when remaining_issues same or more."""
        step = ValidateRepairStep()
        context_with_doctor_and_issues.set("issues_found", 2)  # Initially had 2 issues

        # Mock doctor still returns 2 issues (same as before)
        await step.execute(context_with_doctor_and_issues, None)

        assert context_with_doctor_and_issues.get("validation_passed") is False

    async def test_validation_passed_true_even_with_remaining_issues(
        self, context_with_doctor_and_issues: StepContext, mock_doctor_with_issues: AsyncMock
    ) -> None:
        """validation_passed=True when remaining < initial even if not zero."""
        step = ValidateRepairStep()
        context_with_doctor_and_issues.set("issues_found", 5)  # Initially had 5 issues

        # Mock doctor now returns 2 issues (less than initial)
        await step.execute(context_with_doctor_and_issues, None)

        assert context_with_doctor_and_issues.get("remaining_issues") == 2
        assert context_with_doctor_and_issues.get("validation_passed") is True

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = ValidateRepairStep()
        context = StepContext()
        context.set("issues_found", 2)

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        mock_doctor.run_diagnostics.side_effect = Exception("Validation error")

        result = await step.execute(context_with_doctor, None)

        assert result.success is False
        assert "Validation failed" in result.error
        assert "Validation error" in result.error

    async def test_handles_no_progress_reporter(self, context_with_doctor: StepContext) -> None:
        """Step works without progress reporter."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        result = await step.execute(context_with_doctor, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_doctor: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        result = await step.execute(context_with_doctor, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_validation_details(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute result data contains validation details."""
        step = ValidateRepairStep()
        context_with_doctor.set("issues_found", 2)

        result = await step.execute(context_with_doctor, None)

        assert result.data is not None
        assert "remaining_issues" in result.data
        assert "validation_passed" in result.data

    async def test_defaults_issues_found_to_zero_if_missing(
        self, context_with_doctor: StepContext
    ) -> None:
        """Execute defaults issues_found to 0 if not in context."""
        step = ValidateRepairStep()
        # Don't set issues_found

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        # With 0 initial issues and 0 remaining, validation should pass
        assert context_with_doctor.get("validation_passed") is True


# ============================================================================
# Test: Step Integration
# ============================================================================


class TestRepairStepsIntegration:
    """Test repair steps work correctly together."""

    async def test_all_steps_share_doctor_from_context(self, mock_doctor: AsyncMock) -> None:
        """All repair steps can share the same doctor from context."""
        context = StepContext()
        context.set("doctor", mock_doctor)

        diagnose_step = DiagnoseStep()
        fix_step = AutoFixStep()
        validate_step = ValidateRepairStep()

        r1 = await diagnose_step.execute(context, None)
        r2 = await fix_step.execute(context, None)
        r3 = await validate_step.execute(context, None)

        assert r1.success is True
        assert r2.success is True
        assert r3.success is True

        # All results stored in context
        assert context.get("diagnosis_report") is not None
        assert context.get("issues_found") is not None
        assert context.get("issues_fixed") is not None
        assert context.get("remaining_issues") is not None
        assert context.get("validation_passed") is not None

    async def test_steps_follow_protocol(self) -> None:
        """All repair steps follow the Step protocol."""
        diagnose_step = DiagnoseStep()
        fix_step = AutoFixStep()
        validate_step = ValidateRepairStep()

        for step in [diagnose_step, fix_step, validate_step]:
            # Should have name property
            assert hasattr(step, "name")
            assert isinstance(step.name, str)

            # Should have description property
            assert hasattr(step, "description")
            assert isinstance(step.description, str)

            # Should have execute method
            assert hasattr(step, "execute")
            assert callable(step.execute)

    async def test_data_flows_through_context(self, mock_doctor_with_issues: AsyncMock) -> None:
        """Data from diagnose flows to fix and validate steps."""
        context = StepContext()
        context.set("doctor", mock_doctor_with_issues)

        # After diagnose, fixable_issues should be set
        diagnose_step = DiagnoseStep()
        await diagnose_step.execute(context, None)

        assert context.get("fixable_issues") == ["orphaned_fts", "stale_locks"]
        assert context.get("issues_found") == 2

        # AutoFix uses fixable_issues from context
        fix_step = AutoFixStep()
        await fix_step.execute(context, None)

        assert context.get("issues_fixed") == 2

        # Reset doctor to return OK after fixes
        mock_doctor_with_issues.run_diagnostics.return_value = DoctorReport(
            overall_status=CheckSeverity.OK,
            checks=[
                CheckResult(
                    name="disk_space",
                    severity=CheckSeverity.OK,
                    message="Disk space OK",
                    fixable=False,
                )
            ],
            checks_passed=1,
            warnings=0,
            errors=0,
            fixable_issues=[],
        )

        # Validate uses issues_found from diagnose to compare
        validate_step = ValidateRepairStep()
        await validate_step.execute(context, None)

        assert context.get("remaining_issues") == 0
        assert context.get("validation_passed") is True
