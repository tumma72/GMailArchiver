"""Tests for repair CLI command implementation.

This module tests the repair_command function in cli/repair.py, focusing on:
- Database existence validation (line 21)
- Workflow exception handling (lines 39-46)
- Successful repair workflow
- UI task sequence integration

Tests ensure all code paths are covered including error paths that were
previously uncovered (87% -> 100% coverage).

Fixtures used from conftest.py:
- v11_db: v1.1 database path
- temp_dir: Temporary directory for test files
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.repair import repair_command
from gmailarchiver.core.workflows.repair import RepairConfig, RepairResult

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_ctx() -> CommandContext:
    """Create a mock CommandContext for testing.

    Returns:
        MagicMock instance mimicking CommandContext with all required methods.
    """
    ctx = MagicMock(spec=CommandContext)
    ctx.storage = MagicMock()
    ctx.ui = MagicMock()
    ctx.warning = MagicMock()
    ctx.success = MagicMock()
    # Set up output mock for widget rendering
    ctx.output = MagicMock()
    ctx.output.show_report = MagicMock()
    ctx.output.suggest_next_steps = MagicMock()
    ctx.output.json_mode = False
    ctx.output.quiet = False
    ctx.output.console = MagicMock()
    ctx.fail_and_exit = MagicMock(side_effect=SystemExit(1))
    return ctx


# ============================================================================
# Database Existence Tests (Line 21)
# ============================================================================


class TestDatabaseValidation:
    """Tests for database path validation.

    Tests line 21: Database not found error path.
    """

    @pytest.mark.asyncio
    async def test_missing_database_fails_with_clear_error(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should show clear error when database doesn't exist.

        Tests line 21: ctx.fail_and_exit when database not found.
        """
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await repair_command(
                ctx=mock_ctx,
                state_db=nonexistent_db,
                backfill=False,
                dry_run=False,
                json_output=False,
            )

        # Verify fail_and_exit was called with appropriate error
        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Database Not Found" in call_args.kwargs["title"]
        assert nonexistent_db in call_args.kwargs["message"]
        assert "Check database path" in call_args.kwargs["suggestion"]

    @pytest.mark.asyncio
    async def test_missing_database_provides_helpful_suggestion(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should suggest checking database path or archiving emails."""
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await repair_command(
                ctx=mock_ctx,
                state_db=nonexistent_db,
                backfill=False,
                dry_run=False,
                json_output=False,
            )

        call_args = mock_ctx.fail_and_exit.call_args
        suggestion = call_args.kwargs["suggestion"]
        assert "archive" in suggestion.lower() or "check" in suggestion.lower()


# ============================================================================
# Workflow Exception Handling Tests (Lines 39-46)
# ============================================================================


class TestWorkflowExceptionHandling:
    """Tests for workflow exception handling.

    Tests lines 39-46: Exception handling path when workflow.run() fails.
    """

    @pytest.mark.asyncio
    async def test_workflow_exception_fails_with_error_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle workflow exceptions with clear error messages.

        Tests lines 39-46: Exception caught, task.fail() called, then
        ctx.fail_and_exit() called.
        """
        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=PermissionError("Access denied"))
            MockWorkflow.return_value = mock_workflow

            # Mock UI task sequence
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.fail = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            with pytest.raises(SystemExit):
                await repair_command(
                    ctx=mock_ctx,
                    state_db=v11_db,
                    backfill=False,
                    dry_run=False,
                    json_output=False,
                )

        # Should mark task as failed with error message
        mock_task.fail.assert_called_once()
        fail_call = mock_task.fail.call_args
        assert "Repair failed" in fail_call[0][0]
        assert "Access denied" in fail_call.kwargs["reason"]

        # Should call fail_and_exit with helpful error
        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Repair Failed" in call_args.kwargs["title"]
        assert "Access denied" in call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_workflow_exception_suggests_permissions_check(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest checking permissions when repair fails."""
        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=RuntimeError("Repair failed"))
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.fail = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            with pytest.raises(SystemExit):
                await repair_command(
                    ctx=mock_ctx,
                    state_db=v11_db,
                    backfill=False,
                    dry_run=False,
                    json_output=False,
                )

        # Should suggest permissions check and backup restoration
        call_args = mock_ctx.fail_and_exit.call_args
        suggestion = call_args.kwargs["suggestion"]
        assert "permissions" in suggestion.lower()
        assert "backup" in suggestion.lower()

    @pytest.mark.asyncio
    async def test_workflow_exception_includes_original_error_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should include original exception message in error output."""
        original_error = "Database is locked by another process"

        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=OSError(original_error))
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.fail = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            with pytest.raises(SystemExit):
                await repair_command(
                    ctx=mock_ctx,
                    state_db=v11_db,
                    backfill=False,
                    dry_run=False,
                    json_output=False,
                )

        # Error message should contain original exception
        call_args = mock_ctx.fail_and_exit.call_args
        error_msg = call_args.kwargs["message"]
        assert original_error in error_msg

    @pytest.mark.asyncio
    async def test_workflow_exception_returns_early(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should return after fail_and_exit call, not execute further code.

        Line 46: return statement after fail_and_exit.
        """
        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=Exception("Test error"))
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.fail = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            with pytest.raises(SystemExit):
                await repair_command(
                    ctx=mock_ctx,
                    state_db=v11_db,
                    backfill=False,
                    dry_run=False,
                    json_output=False,
                )

        # Should not call success, warning, or show_report after exception
        mock_ctx.success.assert_not_called()
        mock_ctx.warning.assert_not_called()
        # output.show_report and suggest_next_steps should also not be called
        # (they are called later in the success path)


# ============================================================================
# Successful Repair Tests
# ============================================================================


class TestSuccessfulRepair:
    """Tests for successful repair workflow."""

    @pytest.mark.asyncio
    async def test_successful_repair_in_dry_run_mode(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display issues found in dry-run mode without fixing."""
        result = RepairResult(
            issues_found=3,
            issues_fixed=0,
            dry_run=True,
            details=["Issue 1", "Issue 2", "Issue 3"],
        )

        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.complete = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            await repair_command(
                ctx=mock_ctx,
                state_db=v11_db,
                backfill=False,
                dry_run=True,
                json_output=False,
            )

        # Should complete task with issues found
        mock_task.complete.assert_called_once()
        complete_msg = mock_task.complete.call_args[0][0]
        assert "3" in complete_msg
        assert "issues" in complete_msg.lower()

        # Should show dry-run warning
        mock_ctx.warning.assert_called_once()
        warning_msg = mock_ctx.warning.call_args[0][0]
        assert "DRY RUN" in warning_msg

    @pytest.mark.asyncio
    async def test_successful_repair_actually_fixes_issues(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display issues fixed when not in dry-run mode."""
        result = RepairResult(
            issues_found=5,
            issues_fixed=5,
            dry_run=False,
            details=["Fixed issue 1", "Fixed issue 2"],
        )

        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.complete = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            await repair_command(
                ctx=mock_ctx,
                state_db=v11_db,
                backfill=False,
                dry_run=False,
                json_output=False,
            )

        # Should complete task with issues repaired
        mock_task.complete.assert_called_once()
        complete_msg = mock_task.complete.call_args[0][0]
        assert "5" in complete_msg
        assert "issues" in complete_msg.lower()

        # Should show success message
        mock_ctx.success.assert_called_once()
        success_msg = mock_ctx.success.call_args[0][0]
        assert "5" in success_msg
        assert "repaired" in success_msg.lower()

    @pytest.mark.asyncio
    async def test_repair_passes_correct_config_to_workflow(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should pass correct RepairConfig to workflow.run()."""
        result = RepairResult(
            issues_found=0,
            issues_fixed=0,
            dry_run=True,
            details=[],
        )

        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.complete = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            await repair_command(
                ctx=mock_ctx,
                state_db=v11_db,
                backfill=True,
                dry_run=True,
                json_output=False,
            )

        # Check config passed to workflow.run
        mock_workflow.run.assert_called_once()
        config = mock_workflow.run.call_args[0][0]
        assert isinstance(config, RepairConfig)
        assert config.state_db == v11_db
        assert config.backfill is True
        assert config.dry_run is True


# ============================================================================
# Storage Context Tests
# ============================================================================


class TestSuggestions:
    """Tests for next-step suggestions."""

    @pytest.mark.asyncio
    async def test_dry_run_with_backfill_suggests_both_options(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest both repair and backfill when dry-run with backfill flag.

        Tests line 71: backfill suggestion added when backfill=True.
        """
        result = RepairResult(
            issues_found=2,
            issues_fixed=0,
            dry_run=True,
            details=["Issue 1", "Issue 2"],
        )

        with patch("gmailarchiver.cli.repair.RepairWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Mock UI
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.complete = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            await repair_command(
                ctx=mock_ctx,
                state_db=v11_db,
                backfill=True,
                dry_run=True,
                json_output=False,
            )

        # Should suggest next steps - SuggestionList widget calls ctx.output.suggest_next_steps
        mock_ctx.output.suggest_next_steps.assert_called_once()
        suggestions = mock_ctx.output.suggest_next_steps.call_args[0][0]
        assert len(suggestions) == 2
        assert any("--no-dry-run" in s for s in suggestions)
        assert any("--backfill" in s for s in suggestions)


# ============================================================================
# Storage Context Tests
# ============================================================================


class TestStorageContextRequirement:
    """Tests that repair command requires storage context."""

    @pytest.mark.asyncio
    async def test_asserts_storage_is_not_none(self, mock_ctx: CommandContext, v11_db: str) -> None:
        """Should assert that storage is not None (guaranteed by requires_storage=True).

        Line 27: assert ctx.storage is not None
        """
        # Set storage to None to test assertion
        mock_ctx.storage = None

        with pytest.raises(AssertionError):
            await repair_command(
                ctx=mock_ctx,
                state_db=v11_db,
                backfill=False,
                dry_run=False,
                json_output=False,
            )
