"""Tests for verify steps - TDD Red Phase.

These tests define the expected behavior for:
- VerifyIntegrityStep: Runs database integrity checks
- VerifyConsistencyStep: Runs database-archive consistency checks
- VerifyOffsetsStep: Runs mbox offset accuracy checks

All tests should FAIL initially because the steps don't exist yet.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.workflows.step import StepContext

# Import the steps that don't exist yet - these imports will fail
# until implementation is complete. We use pytest.importorskip to allow
# tests to be collected, but they will fail when the module doesn't exist.
try:
    from gmailarchiver.core.workflows.steps.verify import (
        VerifyConsistencyStep,
        VerifyIntegrityStep,
        VerifyOffsetsStep,
    )
except ImportError:
    # Mark module as missing for pytest.skip
    VerifyIntegrityStep = None
    VerifyConsistencyStep = None
    VerifyOffsetsStep = None

# Skip all tests in this module if the verify module doesn't exist
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        VerifyIntegrityStep is None,
        reason="verify module not implemented yet (TDD Red Phase)",
    ),
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_doctor() -> AsyncMock:
    """Create a mock Doctor facade for testing."""
    doctor = AsyncMock()
    # Default to passing all checks
    doctor.check_database_integrity.return_value = CheckResult(
        name="Database integrity",
        severity=CheckSeverity.OK,
        message="All integrity checks passed",
        fixable=False,
    )
    doctor.check_database_schema.return_value = CheckResult(
        name="Database schema",
        severity=CheckSeverity.OK,
        message="Schema version 1.1",
        fixable=False,
    )
    doctor.check_orphaned_fts.return_value = CheckResult(
        name="Orphaned FTS records",
        severity=CheckSeverity.OK,
        message="No orphaned FTS records",
        fixable=False,
    )
    doctor.check_archive_files_exist.return_value = CheckResult(
        name="Archive files",
        severity=CheckSeverity.OK,
        message="All archive files exist",
        fixable=False,
    )
    doctor.check_mbox_offsets.return_value = CheckResult(
        name="Mbox offsets",
        severity=CheckSeverity.OK,
        message="All offsets are valid",
        fixable=False,
    )
    return doctor


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
    task_seq.task.return_value.__enter__ = MagicMock(return_value=task_handle)
    task_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    return progress


@pytest.fixture
def context_with_doctor(mock_doctor: AsyncMock) -> StepContext:
    """Create a StepContext with mock doctor injected."""
    context = StepContext()
    context.set("doctor", mock_doctor)
    return context


# ============================================================================
# Test: VerifyIntegrityStep
# ============================================================================


class TestVerifyIntegrityStep:
    """Test VerifyIntegrityStep execution."""

    async def test_can_instantiate(self) -> None:
        """VerifyIntegrityStep can be instantiated."""
        step = VerifyIntegrityStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """VerifyIntegrityStep has the correct name attribute."""
        step = VerifyIntegrityStep()
        assert step.name == "verify_integrity"

    async def test_has_correct_description(self) -> None:
        """VerifyIntegrityStep has the correct description attribute."""
        step = VerifyIntegrityStep()
        assert step.description == "Verifying database integrity"

    async def test_execute_with_passing_check(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns success when integrity check passes."""
        step = VerifyIntegrityStep()

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        mock_doctor.check_database_integrity.assert_called_once()

    async def test_execute_with_failing_check(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns failure details when integrity check fails."""
        step = VerifyIntegrityStep()

        # Configure doctor to return failing check
        mock_doctor.check_database_integrity.return_value = CheckResult(
            name="Database corruption",
            severity=CheckSeverity.ERROR,
            message="Database file is corrupted",
            fixable=True,
            details="Run PRAGMA integrity_check",
        )

        result = await step.execute(context_with_doctor, None)

        assert result.success is True  # Step succeeds, but result contains issue
        # Result data should contain the check result
        assert result.data is not None
        assert result.data.severity == CheckSeverity.ERROR

    async def test_stores_result_in_context(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute stores result in context at 'integrity_result' key."""
        step = VerifyIntegrityStep()

        await step.execute(context_with_doctor, None)

        stored_result = context_with_doctor.get("integrity_result")
        assert stored_result is not None
        assert isinstance(stored_result, CheckResult)

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = VerifyIntegrityStep()
        context = StepContext()  # No doctor injected

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = VerifyIntegrityStep()

        mock_doctor.check_database_integrity.side_effect = Exception("Database error")

        result = await step.execute(context_with_doctor, None)

        assert result.success is False
        assert "Integrity check failed" in result.error
        assert "Database error" in result.error

    async def test_handles_no_progress_reporter(self, context_with_doctor: StepContext) -> None:
        """Step works without progress reporter."""
        step = VerifyIntegrityStep()

        result = await step.execute(context_with_doctor, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_doctor: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = VerifyIntegrityStep()

        result = await step.execute(context_with_doctor, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_check_result(
        self, context_with_doctor: StepContext
    ) -> None:
        """Execute result data contains the CheckResult."""
        step = VerifyIntegrityStep()

        result = await step.execute(context_with_doctor, None)

        assert result.data is not None
        assert isinstance(result.data, CheckResult)
        assert result.data.name == "Database integrity"


# ============================================================================
# Test: VerifyConsistencyStep
# ============================================================================


class TestVerifyConsistencyStep:
    """Test VerifyConsistencyStep execution."""

    async def test_can_instantiate(self) -> None:
        """VerifyConsistencyStep can be instantiated."""
        step = VerifyConsistencyStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """VerifyConsistencyStep has the correct name attribute."""
        step = VerifyConsistencyStep()
        assert step.name == "verify_consistency"

    async def test_has_correct_description(self) -> None:
        """VerifyConsistencyStep has the correct description attribute."""
        step = VerifyConsistencyStep()
        assert step.description == "Verifying database-archive consistency"

    async def test_execute_with_all_checks_passing(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns success when all consistency checks pass."""
        step = VerifyConsistencyStep()

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        # Should call multiple checks
        mock_doctor.check_database_schema.assert_called_once()
        mock_doctor.check_orphaned_fts.assert_called_once()
        mock_doctor.check_archive_files_exist.assert_called_once()

    async def test_execute_with_some_checks_failing(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns check results when some consistency checks fail."""
        step = VerifyConsistencyStep()

        # Configure doctor to return mixed results
        mock_doctor.check_database_schema.return_value = CheckResult(
            name="Database schema",
            severity=CheckSeverity.WARNING,
            message="Schema version mismatch",
            fixable=True,
            details="Run migration",
        )
        mock_doctor.check_orphaned_fts.return_value = CheckResult(
            name="Orphaned FTS records",
            severity=CheckSeverity.ERROR,
            message="Found 5 orphaned FTS records",
            fixable=True,
            details="Run repair",
        )

        result = await step.execute(context_with_doctor, None)

        assert result.success is True  # Step succeeds, but results contain issues
        assert result.data is not None
        # Result data should be a list of CheckResult
        assert isinstance(result.data, list)
        assert len(result.data) == 3  # All three checks

    async def test_stores_results_in_context(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute stores results in context at 'consistency_results' key."""
        step = VerifyConsistencyStep()

        await step.execute(context_with_doctor, None)

        stored_results = context_with_doctor.get("consistency_results")
        assert stored_results is not None
        assert isinstance(stored_results, list)
        assert len(stored_results) == 3  # Three consistency checks

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = VerifyConsistencyStep()
        context = StepContext()  # No doctor injected

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = VerifyConsistencyStep()

        mock_doctor.check_database_schema.side_effect = Exception("Schema check error")

        result = await step.execute(context_with_doctor, None)

        assert result.success is False
        assert "Consistency check failed" in result.error
        assert "Schema check error" in result.error

    async def test_handles_no_progress_reporter(self, context_with_doctor: StepContext) -> None:
        """Step works without progress reporter."""
        step = VerifyConsistencyStep()

        result = await step.execute(context_with_doctor, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_doctor: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = VerifyConsistencyStep()

        result = await step.execute(context_with_doctor, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_all_check_results(
        self, context_with_doctor: StepContext
    ) -> None:
        """Execute result data contains all CheckResult objects."""
        step = VerifyConsistencyStep()

        result = await step.execute(context_with_doctor, None)

        assert result.data is not None
        assert isinstance(result.data, list)
        # Should have results from schema, FTS, and archive file checks
        check_names = [c.name for c in result.data]
        assert "Database schema" in check_names
        assert "Orphaned FTS records" in check_names
        assert "Archive files" in check_names


# ============================================================================
# Test: VerifyOffsetsStep
# ============================================================================


class TestVerifyOffsetsStep:
    """Test VerifyOffsetsStep execution."""

    async def test_can_instantiate(self) -> None:
        """VerifyOffsetsStep can be instantiated."""
        step = VerifyOffsetsStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """VerifyOffsetsStep has the correct name attribute."""
        step = VerifyOffsetsStep()
        assert step.name == "verify_offsets"

    async def test_has_correct_description(self) -> None:
        """VerifyOffsetsStep has the correct description attribute."""
        step = VerifyOffsetsStep()
        assert step.description == "Verifying mbox offset accuracy"

    async def test_execute_with_passing_check(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns success when offset check passes."""
        step = VerifyOffsetsStep()

        result = await step.execute(context_with_doctor, None)

        assert result.success is True
        mock_doctor.check_mbox_offsets.assert_called_once()

    async def test_execute_with_failing_check(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute returns failure details when offset check fails."""
        step = VerifyOffsetsStep()

        # Configure doctor to return failing check
        mock_doctor.check_mbox_offsets.return_value = CheckResult(
            name="Mbox offsets",
            severity=CheckSeverity.ERROR,
            message="Found 3 invalid offsets",
            fixable=True,
            details="Run repair --backfill",
        )

        result = await step.execute(context_with_doctor, None)

        assert result.success is True  # Step succeeds, but result contains issue
        assert result.data is not None
        assert result.data.severity == CheckSeverity.ERROR

    async def test_stores_result_in_context(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute stores result in context at 'offsets_result' key."""
        step = VerifyOffsetsStep()

        await step.execute(context_with_doctor, None)

        stored_result = context_with_doctor.get("offsets_result")
        assert stored_result is not None
        assert isinstance(stored_result, CheckResult)

    async def test_fails_without_doctor_in_context(self) -> None:
        """Execute fails gracefully when Doctor not in context."""
        step = VerifyOffsetsStep()
        context = StepContext()  # No doctor injected

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_handles_doctor_exception(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute handles exceptions from Doctor facade."""
        step = VerifyOffsetsStep()

        mock_doctor.check_mbox_offsets.side_effect = Exception("Offset check error")

        result = await step.execute(context_with_doctor, None)

        assert result.success is False
        assert "Offset check failed" in result.error
        assert "Offset check error" in result.error

    async def test_handles_no_progress_reporter(self, context_with_doctor: StepContext) -> None:
        """Step works without progress reporter."""
        step = VerifyOffsetsStep()

        result = await step.execute(context_with_doctor, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_doctor: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = VerifyOffsetsStep()

        result = await step.execute(context_with_doctor, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_check_result(
        self, context_with_doctor: StepContext
    ) -> None:
        """Execute result data contains the CheckResult."""
        step = VerifyOffsetsStep()

        result = await step.execute(context_with_doctor, None)

        assert result.data is not None
        assert isinstance(result.data, CheckResult)
        assert result.data.name == "Mbox offsets"

    async def test_uses_archive_file_from_input(
        self, context_with_doctor: StepContext, mock_doctor: AsyncMock
    ) -> None:
        """Execute uses archive_file from input_data if provided."""
        step = VerifyOffsetsStep()

        # Provide archive file as input
        result = await step.execute(context_with_doctor, "/path/to/archive.mbox")

        assert result.success is True
        # Should pass archive file to doctor method
        mock_doctor.check_mbox_offsets.assert_called_once_with(archive_file="/path/to/archive.mbox")


# ============================================================================
# Test: Step Integration
# ============================================================================


class TestVerifyStepsIntegration:
    """Test verify steps work correctly together."""

    async def test_all_steps_share_doctor_from_context(self, mock_doctor: AsyncMock) -> None:
        """All verify steps can share the same doctor from context."""
        context = StepContext()
        context.set("doctor", mock_doctor)

        integrity_step = VerifyIntegrityStep()
        consistency_step = VerifyConsistencyStep()
        offsets_step = VerifyOffsetsStep()

        r1 = await integrity_step.execute(context, None)
        r2 = await consistency_step.execute(context, None)
        r3 = await offsets_step.execute(context, None)

        assert r1.success is True
        assert r2.success is True
        assert r3.success is True

        # All results stored in context
        assert context.get("integrity_result") is not None
        assert context.get("consistency_results") is not None
        assert context.get("offsets_result") is not None

    async def test_steps_follow_protocol(self) -> None:
        """All verify steps follow the Step protocol."""
        integrity_step = VerifyIntegrityStep()
        consistency_step = VerifyConsistencyStep()
        offsets_step = VerifyOffsetsStep()

        for step in [integrity_step, consistency_step, offsets_step]:
            # Should have name property
            assert hasattr(step, "name")
            assert isinstance(step.name, str)

            # Should have description property
            assert hasattr(step, "description")
            assert isinstance(step.description, str)

            # Should have execute method
            assert hasattr(step, "execute")
            assert callable(step.execute)
