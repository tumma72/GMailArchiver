"""Tests for verify CLI commands.

This module tests the CLI layer for verification commands:
- verify-integrity: Database integrity checks
- verify-consistency: Database/mbox consistency checks
- verify-offsets: Mbox offset verification

Tests focus on behavioral outcomes (error handling, argument parsing, workflow integration)
rather than internal implementation details.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.verify import (
    verify_consistency_command,
    verify_integrity_command,
    verify_offsets_command,
)
from gmailarchiver.core.workflows.verify import VerifyConfig, VerifyResult, VerifyType


@pytest.fixture
def mock_ctx() -> CommandContext:
    """Create a mock CommandContext for testing."""
    ctx = MagicMock(spec=CommandContext)
    ctx.storage = MagicMock()
    ctx.ui = MagicMock()
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
# verify-integrity Command Tests
# ============================================================================


class TestVerifyIntegrityCommand:
    """Tests for verify_integrity_command behavior."""

    @pytest.mark.asyncio
    async def test_missing_database_fails_with_clear_error(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should show clear error when database doesn't exist."""
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await verify_integrity_command(ctx=mock_ctx, state_db=nonexistent_db, json_output=False)

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Database Not Found" in call_args.kwargs["title"]
        assert nonexistent_db in call_args.kwargs["message"]
        assert "Check database path" in call_args.kwargs["suggestion"]

    @pytest.mark.asyncio
    async def test_successful_integrity_check_shows_report(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display success report when integrity check passes."""
        result = VerifyResult(
            passed=True,
            issues_found=0,
            issues=[],
            verify_type=VerifyType.INTEGRITY.value,
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Should not raise
            await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should show report with passed=True
        mock_ctx.output.show_report.assert_called_once()
        call_args = mock_ctx.output.show_report.call_args
        assert call_args[0][0] == "Database Integrity"
        report_data = call_args[0][1]
        assert report_data["Passed"] == "Yes"
        assert report_data["Issues Found"] == "0"

        # Should not suggest next steps on success
        mock_ctx.output.suggest_next_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_integrity_check_shows_issues_and_suggestions(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display issues and suggest fixes when integrity check fails."""
        result = VerifyResult(
            passed=False,
            issues_found=2,
            issues=[{"name": "foreign_key_check", "severity": "ERROR", "message": "FK violation"}],
            verify_type=VerifyType.INTEGRITY.value,
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should show report with passed=False
        mock_ctx.output.show_report.assert_called_once()
        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Passed"] == "No"
        assert report_data["Issues Found"] == "2"

        # Should suggest repair actions
        mock_ctx.output.suggest_next_steps.assert_called_once()
        suggestions = mock_ctx.output.suggest_next_steps.call_args[0][0]
        assert len(suggestions) == 2
        assert "repair" in suggestions[0].lower()
        assert "rollback" in suggestions[1].lower()

    @pytest.mark.asyncio
    async def test_workflow_exception_fails_with_error_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle workflow exceptions with clear error messages."""
        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=PermissionError("Access denied"))
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Verification Failed" in call_args.kwargs["title"]
        assert "Access denied" in call_args.kwargs["message"]
        assert "permissions" in call_args.kwargs["suggestion"]

    @pytest.mark.asyncio
    async def test_creates_verify_config_with_correct_type(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should create VerifyConfig with INTEGRITY type."""
        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="integrity")

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Check that workflow.run was called with correct config
        mock_workflow.run.assert_called_once()
        config = mock_workflow.run.call_args[0][0]
        assert isinstance(config, VerifyConfig)
        assert config.verify_type == VerifyType.INTEGRITY
        assert config.state_db == v11_db


# ============================================================================
# verify-consistency Command Tests
# ============================================================================


class TestVerifyConsistencyCommand:
    """Tests for verify_consistency_command behavior."""

    @pytest.mark.asyncio
    async def test_missing_database_fails_with_clear_error(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should show clear error when database doesn't exist."""
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await verify_consistency_command(
                ctx=mock_ctx, state_db=nonexistent_db, json_output=False
            )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Database Not Found" in call_args.kwargs["title"]
        assert nonexistent_db in call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_successful_consistency_check_shows_task_completion(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show task completion when consistency check passes."""
        result = VerifyResult(
            passed=True, issues_found=0, issues=[], verify_type=VerifyType.CONSISTENCY.value
        )

        # Mock UI task sequence
        mock_task = MagicMock()
        mock_task.__enter__ = MagicMock(return_value=mock_task)
        mock_task.__exit__ = MagicMock(return_value=False)
        mock_task.complete = MagicMock()
        mock_task.fail = MagicMock()

        mock_seq = MagicMock()
        mock_seq.__enter__ = MagicMock(return_value=mock_seq)
        mock_seq.__exit__ = MagicMock(return_value=False)
        mock_seq.task = MagicMock(return_value=mock_task)

        mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should call task.complete with success message
        mock_task.complete.assert_called_once()
        assert "consistent" in mock_task.complete.call_args[0][0].lower()

        # Should show report
        mock_ctx.output.show_report.assert_called_once()
        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Passed"] == "Yes"

    @pytest.mark.asyncio
    async def test_failed_consistency_check_shows_task_failure(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show task failure when consistency check fails."""
        result = VerifyResult(
            passed=False,
            issues_found=3,
            issues=[{"name": "orphaned_fts", "severity": "WARNING", "message": "Orphaned FTS"}],
            verify_type=VerifyType.CONSISTENCY.value,
        )

        # Mock UI task sequence
        mock_task = MagicMock()
        mock_task.__enter__ = MagicMock(return_value=mock_task)
        mock_task.__exit__ = MagicMock(return_value=False)
        mock_task.complete = MagicMock()
        mock_task.fail = MagicMock()

        mock_seq = MagicMock()
        mock_seq.__enter__ = MagicMock(return_value=mock_seq)
        mock_seq.__exit__ = MagicMock(return_value=False)
        mock_seq.task = MagicMock(return_value=mock_task)

        mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should call task.fail
        mock_task.fail.assert_called_once()

        # Should suggest repair with --backfill option
        mock_ctx.output.suggest_next_steps.assert_called_once()
        suggestions = mock_ctx.output.suggest_next_steps.call_args[0][0]
        assert any("--backfill" in s for s in suggestions)
        assert any("re-import" in s.lower() for s in suggestions)

    @pytest.mark.asyncio
    async def test_workflow_exception_shows_task_failure_and_exits(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle workflow exceptions with task failure and error exit."""
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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=RuntimeError("Workflow error"))
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should call task.fail with error
        mock_task.fail.assert_called_once()
        assert "error" in mock_task.fail.call_args.kwargs.get("reason", "").lower()

        # Should call fail_and_exit
        mock_ctx.fail_and_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_verify_config_with_consistency_type(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should create VerifyConfig with CONSISTENCY type."""
        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="consistency")

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Check config
        config = mock_workflow.run.call_args[0][0]
        assert config.verify_type == VerifyType.CONSISTENCY
        assert config.state_db == v11_db


# ============================================================================
# verify-offsets Command Tests
# ============================================================================


class TestVerifyOffsetsCommand:
    """Tests for verify_offsets_command behavior."""

    @pytest.mark.asyncio
    async def test_missing_database_fails_with_clear_error(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should show clear error when database doesn't exist."""
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await verify_offsets_command(ctx=mock_ctx, state_db=nonexistent_db, json_output=False)

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Database Not Found" in call_args.kwargs["title"]

    @pytest.mark.asyncio
    async def test_successful_offset_check_shows_task_completion(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show task completion when offset check passes."""
        result = VerifyResult(
            passed=True, issues_found=0, issues=[], verify_type=VerifyType.OFFSETS.value
        )

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should complete task with success message
        mock_task.complete.assert_called_once()
        assert "valid" in mock_task.complete.call_args[0][0].lower()

        # Should show report
        mock_ctx.output.show_report.assert_called_once()
        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Passed"] == "Yes"

    @pytest.mark.asyncio
    async def test_failed_offset_check_suggests_repair(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest repair actions when offset check fails."""
        result = VerifyResult(
            passed=False,
            issues_found=5,
            issues=[{"name": "invalid_offset", "severity": "ERROR", "message": "Invalid offset"}],
            verify_type=VerifyType.OFFSETS.value,
        )

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should suggest repair with backfill
        mock_ctx.output.suggest_next_steps.assert_called_once()
        suggestions = mock_ctx.output.suggest_next_steps.call_args[0][0]
        assert any("--backfill" in s for s in suggestions)

    @pytest.mark.asyncio
    async def test_workflow_exception_suggests_mbox_accessibility_check(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest checking mbox file accessibility on workflow error."""
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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=FileNotFoundError("Mbox not found"))
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should suggest checking mbox accessibility
        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "mbox" in call_args.kwargs["suggestion"].lower()

    @pytest.mark.asyncio
    async def test_creates_verify_config_with_offsets_type(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should create VerifyConfig with OFFSETS type."""
        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="offsets")

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Check config
        config = mock_workflow.run.call_args[0][0]
        assert config.verify_type == VerifyType.OFFSETS
        assert config.state_db == v11_db


# ============================================================================
# Integration Tests - Storage Assertion
# ============================================================================


class TestVerifyCommandsStorageRequirement:
    """Tests that verify commands require storage context."""

    @pytest.mark.asyncio
    async def test_verify_integrity_asserts_storage_exists(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should assert storage is not None (guaranteed by requires_storage=True)."""
        # Set storage to None to test assertion
        mock_ctx.storage = None

        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="integrity")

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Should raise AssertionError
            with pytest.raises(AssertionError):
                await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

    @pytest.mark.asyncio
    async def test_verify_consistency_asserts_storage_exists(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should assert storage is not None."""
        mock_ctx.storage = None

        with pytest.raises(AssertionError):
            await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

    @pytest.mark.asyncio
    async def test_verify_offsets_asserts_storage_exists(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should assert storage is not None."""
        mock_ctx.storage = None

        with pytest.raises(AssertionError):
            await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestVerifyCommandsEdgeCases:
    """Edge case tests for verify commands."""

    @pytest.mark.asyncio
    async def test_integrity_with_zero_issues_shows_zero_in_report(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display '0' for issues when none found."""
        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="integrity")

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_integrity_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Issues Found"] == "0"

    @pytest.mark.asyncio
    async def test_consistency_with_empty_issues_list_shows_passed(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show passed when issues list is empty even if issues_found > 0."""
        # Edge case: issues_found > 0 but issues list is empty (shouldn't happen)
        result = VerifyResult(passed=True, issues_found=0, issues=[], verify_type="consistency")

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_consistency_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should not raise SystemExit
        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Passed"] == "Yes"

    @pytest.mark.asyncio
    async def test_offsets_verification_handles_large_issue_count(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle and display large numbers of issues."""
        result = VerifyResult(passed=False, issues_found=1000, issues=[], verify_type="offsets")

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

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            with pytest.raises(SystemExit):
                await verify_offsets_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        report_data = mock_ctx.output.show_report.call_args[0][1]
        assert report_data["Issues Found"] == "1000"
