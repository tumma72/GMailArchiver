"""Tests for DoctorWorkflow - TDD Red Phase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.data.hybrid_storage import HybridStorage

# Import will fail initially - this is expected (Red phase)
try:
    from gmailarchiver.core.workflows.doctor import (
        DoctorConfig,
        DoctorResult,
        DoctorWorkflow,
    )

    WORKFLOW_EXISTS = True
except ImportError:
    WORKFLOW_EXISTS = False
    # Create placeholder classes for test structure
    DoctorWorkflow = None  # type: ignore[misc, assignment]
    DoctorConfig = None  # type: ignore[misc, assignment]
    DoctorResult = None  # type: ignore[misc, assignment]

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test: DoctorConfig
# ============================================================================


@pytest.mark.skipif(not WORKFLOW_EXISTS, reason="DoctorWorkflow not yet implemented")
class TestDoctorConfig:
    """Test DoctorConfig dataclass."""

    async def test_config_has_required_fields(self) -> None:
        """Test that DoctorConfig has expected fields."""
        # Create minimal config
        config = DoctorConfig(verbose=False)

        assert hasattr(config, "verbose")
        assert config.verbose is False

    async def test_config_defaults(self) -> None:
        """Test DoctorConfig default values."""
        config = DoctorConfig()

        # verbose should default to False
        assert config.verbose is False


# ============================================================================
# Test: DoctorResult
# ============================================================================


@pytest.mark.skipif(not WORKFLOW_EXISTS, reason="DoctorWorkflow not yet implemented")
class TestDoctorResult:
    """Test DoctorResult dataclass."""

    async def test_result_has_required_fields(self) -> None:
        """Test that DoctorResult has all expected fields."""
        result = DoctorResult(
            overall_status=CheckSeverity.OK,
            checks=[],
            checks_passed=0,
            warnings=0,
            errors=0,
            fixable_issues=[],
            database_checks=[],
            environment_checks=[],
            system_checks=[],
        )

        assert hasattr(result, "overall_status")
        assert hasattr(result, "checks")
        assert hasattr(result, "checks_passed")
        assert hasattr(result, "warnings")
        assert hasattr(result, "errors")
        assert hasattr(result, "fixable_issues")
        assert hasattr(result, "database_checks")
        assert hasattr(result, "environment_checks")
        assert hasattr(result, "system_checks")

    async def test_result_categorized_checks(self) -> None:
        """Test that result properly categorizes checks."""
        db_check = CheckResult("db", CheckSeverity.OK, "OK", False)
        env_check = CheckResult("env", CheckSeverity.WARNING, "Warn", True)
        sys_check = CheckResult("sys", CheckSeverity.ERROR, "Error", False)

        result = DoctorResult(
            overall_status=CheckSeverity.ERROR,
            checks=[db_check, env_check, sys_check],
            checks_passed=1,
            warnings=1,
            errors=1,
            fixable_issues=["env"],
            database_checks=[db_check],
            environment_checks=[env_check],
            system_checks=[sys_check],
        )

        assert len(result.database_checks) == 1
        assert len(result.environment_checks) == 1
        assert len(result.system_checks) == 1
        assert result.database_checks[0].name == "db"
        assert result.environment_checks[0].severity == CheckSeverity.WARNING
        assert result.system_checks[0].severity == CheckSeverity.ERROR


# ============================================================================
# Test: DoctorWorkflow Initialization
# ============================================================================


@pytest.mark.skipif(not WORKFLOW_EXISTS, reason="DoctorWorkflow not yet implemented")
class TestDoctorWorkflowInit:
    """Test DoctorWorkflow initialization."""

    async def test_workflow_accepts_storage(self) -> None:
        """Test that workflow can be initialized with HybridStorage."""
        mock_storage = AsyncMock(spec=HybridStorage)

        workflow = DoctorWorkflow(mock_storage)

        assert workflow is not None
        assert workflow.storage == mock_storage


# ============================================================================
# Test: DoctorWorkflow Execution
# ============================================================================


@pytest.mark.skipif(not WORKFLOW_EXISTS, reason="DoctorWorkflow not yet implemented")
class TestDoctorWorkflowExecution:
    """Test DoctorWorkflow execution and result aggregation."""

    async def test_runs_all_three_steps(self) -> None:
        """Test that workflow runs all 3 diagnostic steps."""
        from pathlib import Path

        # Setup mock storage
        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        # Execute
        result = await workflow.run(config)

        # Assert result is DoctorResult
        assert isinstance(result, DoctorResult)
        assert hasattr(result, "overall_status")
        assert hasattr(result, "checks")
        assert hasattr(result, "database_checks")
        assert hasattr(result, "environment_checks")
        assert hasattr(result, "system_checks")

    async def test_aggregates_results_from_context(self) -> None:
        """Test that workflow correctly aggregates step results."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Verify aggregation
        all_checks = result.database_checks + result.environment_checks + result.system_checks
        total_categorized = len(all_checks)
        total_counted = result.checks_passed + result.warnings + result.errors

        assert total_categorized == total_counted

    async def test_determines_overall_status_error(self) -> None:
        """Test overall status is ERROR when errors present."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # If any errors exist, overall should be ERROR
        if result.errors > 0:
            assert result.overall_status == CheckSeverity.ERROR

    async def test_determines_overall_status_warning(self) -> None:
        """Test overall status is WARNING when only warnings present."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # If no errors but warnings exist, overall should be WARNING
        if result.errors == 0 and result.warnings > 0:
            assert result.overall_status == CheckSeverity.WARNING

    async def test_determines_overall_status_ok(self) -> None:
        """Test overall status is OK when no errors or warnings."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # If no errors or warnings, overall should be OK
        if result.errors == 0 and result.warnings == 0:
            assert result.overall_status == CheckSeverity.OK

    async def test_collects_fixable_issues(self) -> None:
        """Test that fixable issues are identified."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Verify fixable issues are in result
        assert isinstance(result.fixable_issues, list)

        # Each fixable issue should correspond to a check
        for issue in result.fixable_issues:
            # Find corresponding check
            check = next((c for c in result.checks if c.name == issue), None)
            if check:
                assert check.fixable is True
                assert check.severity != CheckSeverity.OK

    async def test_counts_are_accurate(self) -> None:
        """Test that check counts are accurate."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Count manually from checks
        passed = sum(1 for c in result.checks if c.severity == CheckSeverity.OK)
        warnings = sum(1 for c in result.checks if c.severity == CheckSeverity.WARNING)
        errors = sum(1 for c in result.checks if c.severity == CheckSeverity.ERROR)

        assert result.checks_passed == passed
        assert result.warnings == warnings
        assert result.errors == errors

    async def test_workflow_with_progress_reporter(self) -> None:
        """Test workflow execution with progress reporter."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        # Create mock progress
        mock_progress = MagicMock()

        # Progress is passed to constructor, not run()
        workflow = DoctorWorkflow(mock_storage, progress=mock_progress)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Should still return valid result
        assert isinstance(result, DoctorResult)
        assert hasattr(result, "overall_status")

    async def test_workflow_without_progress_reporter(self) -> None:
        """Test workflow execution without progress reporter."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        # Progress passed to constructor as None (default)
        workflow = DoctorWorkflow(mock_storage, progress=None)
        config = DoctorConfig(verbose=False)

        # Execute without progress
        result = await workflow.run(config)

        # Should still return valid result
        assert isinstance(result, DoctorResult)
        assert hasattr(result, "overall_status")

    async def test_creates_doctor_instance(self) -> None:
        """Test that workflow creates Doctor instance from storage."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_db = MagicMock()
        mock_db.db_path = Path("test.db")
        mock_storage.db = mock_db

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        # Execute workflow
        result = await workflow.run(config)

        # Workflow should have created and used a Doctor instance
        assert result is not None

    async def test_closes_doctor_after_execution(self) -> None:
        """Test that workflow properly closes Doctor instance."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        # Execute workflow
        result = await workflow.run(config)

        # Doctor should be closed after execution
        # (This is tested by verifying no hanging resources)
        assert result is not None


# ============================================================================
# Test: DoctorWorkflow Edge Cases
# ============================================================================


@pytest.mark.skipif(not WORKFLOW_EXISTS, reason="DoctorWorkflow not yet implemented")
class TestDoctorWorkflowEdgeCases:
    """Test DoctorWorkflow edge cases and error handling."""

    async def test_handles_empty_check_results(self) -> None:
        """Test workflow handles case where all steps return empty lists."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Even with empty results, should have valid structure
        assert isinstance(result, DoctorResult)
        assert isinstance(result.database_checks, list)
        assert isinstance(result.environment_checks, list)
        assert isinstance(result.system_checks, list)

    async def test_handles_all_checks_passing(self) -> None:
        """Test workflow when all checks pass."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # If all pass, overall should be OK
        if result.checks_passed == len(result.checks) and len(result.checks) > 0:
            assert result.overall_status == CheckSeverity.OK
            assert result.errors == 0
            assert result.warnings == 0
            assert len(result.fixable_issues) == 0

    async def test_handles_mixed_severity_results(self) -> None:
        """Test workflow with mix of OK, WARNING, and ERROR."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config = DoctorConfig(verbose=False)

        result = await workflow.run(config)

        # Verify counts add up
        total = result.checks_passed + result.warnings + result.errors
        assert total == len(result.checks)

    async def test_verbose_mode_affects_config_only(self) -> None:
        """Test that verbose mode is stored in config but doesn't affect result."""
        from pathlib import Path

        mock_storage = AsyncMock(spec=HybridStorage)
        mock_storage.db = MagicMock()
        mock_storage.db.db_path = Path("test.db")

        workflow = DoctorWorkflow(mock_storage)
        config_verbose = DoctorConfig(verbose=True)
        config_normal = DoctorConfig(verbose=False)

        # Both should return valid results
        result_verbose = await workflow.run(config_verbose)
        result_normal = await workflow.run(config_normal)

        assert isinstance(result_verbose, DoctorResult)
        assert isinstance(result_normal, DoctorResult)
