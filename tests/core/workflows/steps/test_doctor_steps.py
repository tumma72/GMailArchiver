"""Tests for diagnostic steps - TDD Red Phase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.core.workflows.steps.doctor import (
    DatabaseDiagnosticStep,
    EnvironmentDiagnosticStep,
    SystemDiagnosticStep,
)

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test: DatabaseDiagnosticStep
# ============================================================================


class TestDatabaseDiagnosticStep:
    """Test DatabaseDiagnosticStep execution."""

    async def test_step_has_correct_name_and_description(self) -> None:
        """Test that step has proper name and description attributes."""
        step = DatabaseDiagnosticStep()

        assert step.name == "database_diagnostics"
        assert step.description == "Running database diagnostics"

    async def test_executes_check_archive_health(self) -> None:
        """Test that step calls doctor.check_archive_health()."""
        # Setup
        step = DatabaseDiagnosticStep()
        context = StepContext()

        # Mock doctor with return value
        mock_doctor = AsyncMock()
        checks = [
            CheckResult("schema", CheckSeverity.OK, "Schema OK", False),
            CheckResult("integrity", CheckSeverity.OK, "Integrity OK", False),
        ]
        mock_doctor.check_archive_health.return_value = checks
        context.set("doctor", mock_doctor)

        # Execute
        result = await step.execute(context, None)

        # Assert
        assert result.success is True
        mock_doctor.check_archive_health.assert_called_once()
        assert context.get("database_checks") == checks

    async def test_handles_no_progress_reporter(self) -> None:
        """Test step works without progress reporter."""
        step = DatabaseDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_archive_health.return_value = []
        context.set("doctor", mock_doctor)

        # Execute with progress=None
        result = await step.execute(context, None, progress=None)

        assert result.success is True
        mock_doctor.check_archive_health.assert_called_once()

    async def test_handles_with_progress_reporter(self) -> None:
        """Test step reports progress when provided."""
        step = DatabaseDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_archive_health.return_value = []
        context.set("doctor", mock_doctor)

        # Create mock progress reporter with proper context manager
        mock_progress = MagicMock()
        mock_sequence = MagicMock()
        mock_task = MagicMock()

        # Setup context manager chain
        mock_progress.task_sequence.return_value.__enter__ = MagicMock(return_value=mock_sequence)
        mock_progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)
        mock_sequence.task.return_value.__enter__ = MagicMock(return_value=mock_task)
        mock_sequence.task.return_value.__exit__ = MagicMock(return_value=None)

        # Execute with progress
        result = await step.execute(context, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_returns_error_when_doctor_missing(self) -> None:
        """Test step fails when doctor not in context."""
        step = DatabaseDiagnosticStep()
        context = StepContext()
        # Intentionally don't set doctor in context

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_writes_checks_to_context(self) -> None:
        """Test that step writes check results to context with correct key."""
        step = DatabaseDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        checks = [
            CheckResult("check1", CheckSeverity.OK, "Message 1", False),
            CheckResult("check2", CheckSeverity.WARNING, "Message 2", True),
        ]
        mock_doctor.check_archive_health.return_value = checks
        context.set("doctor", mock_doctor)

        await step.execute(context, None)

        # Verify results stored in context
        stored_checks = context.get("database_checks")
        assert stored_checks == checks
        assert len(stored_checks) == 2
        assert stored_checks[0].name == "check1"
        assert stored_checks[1].severity == CheckSeverity.WARNING

    async def test_handles_doctor_exception(self) -> None:
        """Test step handles exceptions from doctor gracefully."""
        step = DatabaseDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_archive_health.side_effect = Exception("Database error")
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None)

        assert result.success is False
        assert "Database diagnostics failed" in result.error
        assert "Database error" in result.error


# ============================================================================
# Test: EnvironmentDiagnosticStep
# ============================================================================


class TestEnvironmentDiagnosticStep:
    """Test EnvironmentDiagnosticStep execution."""

    async def test_step_has_correct_name_and_description(self) -> None:
        """Test that step has proper name and description attributes."""
        step = EnvironmentDiagnosticStep()

        assert step.name == "environment_diagnostics"
        assert step.description == "Running environment diagnostics"

    async def test_executes_check_environment_health(self) -> None:
        """Test that step calls doctor.check_environment_health()."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        checks = [
            CheckResult("python", CheckSeverity.OK, "Python 3.14+", False),
        ]
        mock_doctor.check_environment_health.return_value = checks
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None)

        assert result.success is True
        mock_doctor.check_environment_health.assert_called_once()
        assert context.get("environment_checks") == checks

    async def test_handles_no_progress_reporter(self) -> None:
        """Test step works without progress reporter."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_environment_health.return_value = []
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None, progress=None)

        assert result.success is True
        mock_doctor.check_environment_health.assert_called_once()

    async def test_handles_with_progress_reporter(self) -> None:
        """Test step reports progress when provided."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_environment_health.return_value = []
        context.set("doctor", mock_doctor)

        mock_progress = MagicMock()
        mock_sequence = MagicMock()
        mock_task = MagicMock()

        mock_progress.task_sequence.return_value.__enter__ = MagicMock(return_value=mock_sequence)
        mock_progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)
        mock_sequence.task.return_value.__enter__ = MagicMock(return_value=mock_task)
        mock_sequence.task.return_value.__exit__ = MagicMock(return_value=None)

        result = await step.execute(context, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_returns_error_when_doctor_missing(self) -> None:
        """Test step fails when doctor not in context."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_writes_checks_to_context(self) -> None:
        """Test that step writes check results to context with correct key."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        checks = [
            CheckResult("python", CheckSeverity.OK, "Python OK", False),
            CheckResult("deps", CheckSeverity.WARNING, "Missing dep", True),
        ]
        mock_doctor.check_environment_health.return_value = checks
        context.set("doctor", mock_doctor)

        await step.execute(context, None)

        stored_checks = context.get("environment_checks")
        assert stored_checks == checks
        assert len(stored_checks) == 2

    async def test_handles_doctor_exception(self) -> None:
        """Test step handles exceptions from doctor gracefully."""
        step = EnvironmentDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_environment_health.side_effect = Exception("Env error")
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None)

        assert result.success is False
        assert "Environment diagnostics failed" in result.error
        assert "Env error" in result.error


# ============================================================================
# Test: SystemDiagnosticStep
# ============================================================================


class TestSystemDiagnosticStep:
    """Test SystemDiagnosticStep execution."""

    async def test_step_has_correct_name_and_description(self) -> None:
        """Test that step has proper name and description attributes."""
        step = SystemDiagnosticStep()

        assert step.name == "system_diagnostics"
        assert step.description == "Running system diagnostics"

    async def test_executes_check_system_health(self) -> None:
        """Test that step calls doctor.check_system_health()."""
        step = SystemDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        checks = [
            CheckResult("disk", CheckSeverity.WARNING, "Low disk space", False),
        ]
        mock_doctor.check_system_health.return_value = checks
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None)

        assert result.success is True
        mock_doctor.check_system_health.assert_called_once()
        assert context.get("system_checks") == checks

    async def test_handles_no_progress_reporter(self) -> None:
        """Test step works without progress reporter."""
        step = SystemDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_system_health.return_value = []
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None, progress=None)

        assert result.success is True
        mock_doctor.check_system_health.assert_called_once()

    async def test_handles_with_progress_reporter(self) -> None:
        """Test step reports progress when provided."""
        step = SystemDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_system_health.return_value = []
        context.set("doctor", mock_doctor)

        mock_progress = MagicMock()
        mock_sequence = MagicMock()
        mock_task = MagicMock()

        mock_progress.task_sequence.return_value.__enter__ = MagicMock(return_value=mock_sequence)
        mock_progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)
        mock_sequence.task.return_value.__enter__ = MagicMock(return_value=mock_task)
        mock_sequence.task.return_value.__exit__ = MagicMock(return_value=None)

        result = await step.execute(context, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_returns_error_when_doctor_missing(self) -> None:
        """Test step fails when doctor not in context."""
        step = SystemDiagnosticStep()
        context = StepContext()

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Doctor not found in context"

    async def test_writes_checks_to_context(self) -> None:
        """Test that step writes check results to context with correct key."""
        step = SystemDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        checks = [
            CheckResult("disk", CheckSeverity.OK, "Disk OK", False),
            CheckResult("perms", CheckSeverity.ERROR, "No write access", False),
        ]
        mock_doctor.check_system_health.return_value = checks
        context.set("doctor", mock_doctor)

        await step.execute(context, None)

        stored_checks = context.get("system_checks")
        assert stored_checks == checks
        assert len(stored_checks) == 2

    async def test_handles_doctor_exception(self) -> None:
        """Test step handles exceptions from doctor gracefully."""
        step = SystemDiagnosticStep()
        context = StepContext()

        mock_doctor = AsyncMock()
        mock_doctor.check_system_health.side_effect = Exception("System error")
        context.set("doctor", mock_doctor)

        result = await step.execute(context, None)

        assert result.success is False
        assert "System diagnostics failed" in result.error
        assert "System error" in result.error
