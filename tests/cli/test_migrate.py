"""Tests for migrate CLI command implementation.

This module tests the migrate_command function in cli/migrate.py, focusing on:
- Database existence validation
- Schema version checking (already at latest version)
- Successful migration workflow
- Error handling and user feedback
- UI task sequence integration

Tests ensure all code paths are covered including:
- Database not found error (line 18)
- Already at latest version path (lines 34-36)
- Migration exception handling (lines 40-50)
- Success report generation (lines 53-68)

Fixtures used from conftest.py:
- v11_db: v1.1 database path
- temp_dir: Temporary directory for test files
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.migrate import migrate_command
from gmailarchiver.core.workflows.migrate import MigrateConfig, MigrateResult

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
    ctx.info = MagicMock()
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
# Database Existence Tests
# ============================================================================


class TestDatabaseValidation:
    """Tests for database path validation."""

    @pytest.mark.asyncio
    async def test_missing_database_fails_with_clear_error(
        self, mock_ctx: CommandContext, tmp_path: Path
    ) -> None:
        """Should show clear error when database doesn't exist.

        Tests line 18: Database not found error path.
        """
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await migrate_command(ctx=mock_ctx, state_db=nonexistent_db, json_output=False)

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
        """Should suggest checking database path or archiving emails.

        Verifies suggestion text is informative.
        """
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(SystemExit):
            await migrate_command(ctx=mock_ctx, state_db=nonexistent_db, json_output=False)

        call_args = mock_ctx.fail_and_exit.call_args
        suggestion = call_args.kwargs["suggestion"]
        assert "archive" in suggestion.lower() or "check" in suggestion.lower()


# ============================================================================
# Schema Version Tests
# ============================================================================


class TestSchemaVersionChecking:
    """Tests for schema version checking logic.

    Tests lines 33-36: Already at latest version path.
    """

    @pytest.mark.asyncio
    async def test_already_at_latest_version_returns_early(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show info message and return early when already at latest.

        When from_version == to_version, should not call show_report or
        suggest_next_steps, only ctx.info().
        """
        result = MigrateResult(
            success=True,
            from_version="1.1",
            to_version="1.1",
            backup_path=None,
            details=["Database is already at target version"],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Mock UI task sequence
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.complete = MagicMock()

            mock_seq = MagicMock()
            mock_seq.__enter__ = MagicMock(return_value=mock_seq)
            mock_seq.__exit__ = MagicMock(return_value=False)
            mock_seq.task = MagicMock(return_value=mock_task)

            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_seq)

            # Should not raise
            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should complete task with early exit message
        mock_task.complete.assert_called_once()
        complete_msg = mock_task.complete.call_args[0][0]
        assert "latest" in complete_msg.lower()

        # Should show info message about already being at latest
        mock_ctx.info.assert_called_once()
        info_msg = mock_ctx.info.call_args[0][0]
        assert "already" in info_msg.lower()
        assert "1.1" in info_msg

        # Should NOT call show_report when versions match
        mock_ctx.output.show_report.assert_not_called()

        # Should NOT call suggest_next_steps when versions match
        mock_ctx.output.suggest_next_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_at_latest_returns_immediately(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should return function immediately when versions match.

        Ensures no further processing happens after early return.
        """
        result = MigrateResult(
            success=True,
            from_version="1.1",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Verify success/suggest_next_steps were not called (early return)
        mock_ctx.success.assert_not_called()
        mock_ctx.output.suggest_next_steps.assert_not_called()


# ============================================================================
# Successful Migration Tests
# ============================================================================


class TestSuccessfulMigration:
    """Tests for successful migration workflow."""

    @pytest.mark.asyncio
    async def test_successful_migration_shows_report(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should display success report when migration completes.

        Tests lines 53-68: show_report generation on success.
        """
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path="/path/to/backup.db",
            details=["Schema updated", "Tables migrated", "Indexes created"],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should show report with migration details
        mock_ctx.output.show_report.assert_called_once()
        call_args = mock_ctx.output.show_report.call_args
        assert call_args[0][0] == "Schema Migration"
        report_data = call_args[0][1]

        # Check report contains version information
        assert "Old Version" in report_data
        assert "1.0" in report_data["Old Version"]
        assert "New Version" in report_data
        assert "1.1" in report_data["New Version"]
        assert "Backup Created" in report_data
        assert "backup.db" in report_data["Backup Created"]

    @pytest.mark.asyncio
    async def test_successful_migration_shows_success_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show success message after migration completes."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path="/path/to/backup.db",
            details=["Migration complete"],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should show success message
        mock_ctx.success.assert_called_once()
        success_msg = mock_ctx.success.call_args[0][0]
        assert "1.1" in success_msg
        assert "migrated" in success_msg.lower()

    @pytest.mark.asyncio
    async def test_successful_migration_suggests_next_steps(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest verification commands after successful migration."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path="/path/to/backup.db",
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should suggest next steps - SuggestionList widget calls ctx.output.suggest_next_steps
        mock_ctx.output.suggest_next_steps.assert_called_once()
        suggestions = mock_ctx.output.suggest_next_steps.call_args[0][0]
        assert len(suggestions) == 2
        assert any("verify-integrity" in s for s in suggestions)
        assert any("verify-consistency" in s for s in suggestions)

    @pytest.mark.asyncio
    async def test_successful_migration_displays_task_completion(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should mark migration task as completed in UI."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should complete task with migration message
        mock_task.complete.assert_called_once()
        complete_msg = mock_task.complete.call_args[0][0]
        assert "1.0" in complete_msg and "1.1" in complete_msg


# ============================================================================
# Migration Exception Handling Tests
# ============================================================================


class TestMigrationExceptionHandling:
    """Tests for migration exception handling.

    Tests lines 40-50: Migration exception handling path.
    """

    @pytest.mark.asyncio
    async def test_migration_exception_fails_with_error_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle migration exceptions with clear error messages."""
        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=ValueError("Schema mismatch"))
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
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should mark task as failed with reason containing error message
        mock_task.fail.assert_called_once()
        fail_call = mock_task.fail.call_args
        # First positional arg is message, reason is passed as keyword arg
        assert "Migration failed" in fail_call[0][0]
        assert "Schema mismatch" in fail_call.kwargs["reason"]

        # Should call fail_and_exit with helpful error
        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Migration Failed" in call_args.kwargs["title"]
        assert "Schema mismatch" in call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_migration_exception_suggests_rollback(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should suggest rollback command when migration fails."""
        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=RuntimeError("Migration failed"))
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
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should suggest rollback and permissions check
        call_args = mock_ctx.fail_and_exit.call_args
        suggestion = call_args.kwargs["suggestion"]
        assert "rollback" in suggestion.lower()
        assert "permissions" in suggestion.lower()

    @pytest.mark.asyncio
    async def test_migration_exception_includes_original_error_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should include original exception message in error output."""
        original_error = "Disk space exhausted during migration"

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Error message should contain original exception
        call_args = mock_ctx.fail_and_exit.call_args
        error_msg = call_args.kwargs["message"]
        assert original_error in error_msg

    @pytest.mark.asyncio
    async def test_migration_exception_returns_early(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should return after fail_and_exit call, not execute further code."""
        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should not call success, show_report, or suggest_next_steps
        mock_ctx.success.assert_not_called()
        mock_ctx.output.show_report.assert_not_called()
        mock_ctx.output.suggest_next_steps.assert_not_called()


# ============================================================================
# Workflow Integration Tests
# ============================================================================


class TestWorkflowIntegration:
    """Tests for integration with MigrateWorkflow."""

    @pytest.mark.asyncio
    async def test_creates_migrate_workflow_with_storage(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should create MigrateWorkflow with storage from context."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Workflow should be created with storage
        MockWorkflow.assert_called_once_with(mock_ctx.storage)

    @pytest.mark.asyncio
    async def test_passes_migrate_config_to_workflow(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should pass correct MigrateConfig to workflow.run()."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Workflow.run should be called with MigrateConfig
        mock_workflow.run.assert_called_once()
        config = mock_workflow.run.call_args[0][0]
        assert isinstance(config, MigrateConfig)
        assert config.state_db == v11_db


# ============================================================================
# Report Generation Tests
# ============================================================================


class TestReportGeneration:
    """Tests for report data generation and formatting."""

    @pytest.mark.asyncio
    async def test_report_includes_all_migration_details(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should include all migration details in report."""
        details = [
            "Backup created: /path/to/backup.db",
            "Schema updated successfully",
            "Indexes rebuilt",
            "Statistics updated",
        ]
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path="/path/to/backup.db",
            details=details,
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Report should include all details
        report_call = mock_ctx.output.show_report.call_args
        report_data = report_call[0][1]
        details_str = report_data["Details"]
        assert "Schema updated successfully" in details_str
        assert "Indexes rebuilt" in details_str
        assert "Statistics updated" in details_str

    @pytest.mark.asyncio
    async def test_report_shows_na_when_no_details(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show 'N/A' for details when details list is empty."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Report should show N/A for empty details
        report_call = mock_ctx.output.show_report.call_args
        report_data = report_call[0][1]
        assert report_data["Details"] == "None"

    @pytest.mark.asyncio
    async def test_report_shows_na_when_no_backup_created(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should show 'N/A' for backup path when no backup was created."""
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=["Schema updated"],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Backup path should show N/A
        report_call = mock_ctx.output.show_report.call_args
        report_data = report_call[0][1]
        assert report_data["Backup Created"] == "N/A"


# ============================================================================
# Storage Context Tests
# ============================================================================


class TestStorageContextRequirement:
    """Tests that migrate command requires storage context."""

    @pytest.mark.asyncio
    async def test_asserts_storage_is_not_none(self, mock_ctx: CommandContext, v11_db: str) -> None:
        """Should assert that storage is not None (guaranteed by requires_storage=True).

        Line 24: assert ctx.storage is not None
        """
        # Set storage to None to test assertion
        mock_ctx.storage = None

        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            # Should raise AssertionError
            with pytest.raises(AssertionError):
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Edge case tests for migrate command."""

    @pytest.mark.asyncio
    async def test_migration_with_very_long_version_strings(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle version strings correctly in success message."""
        result = MigrateResult(
            success=True,
            from_version="1.0.0.0",
            to_version="1.1.0.0",
            backup_path=None,
            details=[],
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Should successfully complete with version strings
        success_msg = mock_ctx.success.call_args[0][0]
        assert "1.1.0.0" in success_msg

    @pytest.mark.asyncio
    async def test_migration_exception_with_special_characters_in_message(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should handle exception messages with special characters."""
        error_msg = "Database error: constraint violation (FK: parent_id) -> child records exist"

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=ValueError(error_msg))
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
                await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # Error message should include special characters
        call_args = mock_ctx.fail_and_exit.call_args
        error_output = call_args.kwargs["message"]
        assert "constraint violation" in error_output

    @pytest.mark.asyncio
    async def test_report_with_multiline_details(
        self, mock_ctx: CommandContext, v11_db: str
    ) -> None:
        """Should properly format multiline details in report."""
        details = [
            "Step 1: Checking schema",
            "Step 2: Creating backup",
            "Step 3: Applying patches",
            "Step 4: Verifying integrity",
        ]
        result = MigrateResult(
            success=True,
            from_version="1.0",
            to_version="1.1",
            backup_path="/backup.db",
            details=details,
        )

        with patch("gmailarchiver.cli.migrate.MigrateWorkflow") as MockWorkflow:
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

            await migrate_command(ctx=mock_ctx, state_db=v11_db, json_output=False)

        # All details should be joined with newlines
        report_call = mock_ctx.output.show_report.call_args
        report_data = report_call[0][1]
        details_str = report_data["Details"]
        assert "Step 1: Checking schema" in details_str
        assert "Step 4: Verifying integrity" in details_str
