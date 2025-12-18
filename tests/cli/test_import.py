"""Tests for CLI import command implementation.

This module tests the import_command function in cli/import_.py, focusing on:
- Command behavior and argument handling
- Integration with ImportWorkflow
- Error handling and user feedback
- Progress reporting via CommandContext

Fixtures used from conftest.py:
- v11_db: v1.1 database path
- hybrid_storage: HybridStorage instance with db_manager
- tmp_path: pytest temporary directory
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.import_ import import_command
from gmailarchiver.cli.output import OutputManager
from gmailarchiver.core.workflows.import_ import ImportConfig, ImportResult

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_output():
    """Create mock OutputManager for testing."""
    output = MagicMock(spec=OutputManager)
    output.console = MagicMock()
    return output


@pytest.fixture
def command_context(mock_output, hybrid_storage):
    """Create CommandContext with mocked output and real storage."""
    ctx = CommandContext(
        output=mock_output,
        storage=hybrid_storage,
        json_mode=False,
        dry_run=False,
    )
    # Mock the UI builder to avoid Rich console interactions
    ctx._ui_builder = MagicMock()
    ctx._ui_builder.task_sequence.return_value.__enter__ = MagicMock()
    ctx._ui_builder.task_sequence.return_value.__exit__ = MagicMock()
    return ctx


@pytest.fixture
def sample_mbox_file(tmp_path: Path) -> Path:
    """Create a sample mbox file for testing."""
    mbox_path = tmp_path / "test_archive.mbox"
    mbox_content = b"""From alice@example.com Mon Jan 01 00:00:00 2024
From: alice@example.com
To: bob@example.com
Subject: Test Message
Message-ID: <test001@example.com>
Date: Mon, 01 Jan 2024 00:00:00 +0000

This is a test message body.
"""
    mbox_path.write_bytes(mbox_content)
    return mbox_path


# ============================================================================
# Database Validation Tests
# ============================================================================


class TestDatabaseValidation:
    """Tests for database path validation."""

    @pytest.mark.asyncio
    async def test_import_fails_when_database_not_found(
        self, mock_output, tmp_path, sample_mbox_file
    ):
        """Import should fail with clear error when database doesn't exist."""
        # Create context with non-existent database
        nonexistent_db = str(tmp_path / "nonexistent.db")
        ctx = CommandContext(
            output=mock_output,
            storage=None,
            state_db_path=nonexistent_db,
        )
        ctx._ui_builder = MagicMock()

        # Should call fail_and_exit (raises typer.Exit)
        with pytest.raises(typer.Exit) as exc_info:
            await import_command(
                ctx,
                archive_pattern=str(sample_mbox_file),
                state_db=nonexistent_db,
                deduplicate=True,
                json_output=False,
            )

        # Should exit with error code
        assert exc_info.value.exit_code == 1

        # Verify error message was shown
        ctx.output.show_error_panel.assert_called_once()
        error_call = ctx.output.show_error_panel.call_args
        assert "Database Not Found" in error_call[1]["title"]
        assert nonexistent_db in error_call[1]["message"]

    @pytest.mark.asyncio
    async def test_import_succeeds_when_database_exists(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should proceed when database exists."""
        # Mock ImportWorkflow to avoid actual import
        mock_result = ImportResult(
            imported_count=1,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder task sequence
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)

            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            # Should not raise
            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Workflow should have been called
            mock_workflow.run.assert_called_once()


# ============================================================================
# Workflow Integration Tests
# ============================================================================


class TestWorkflowIntegration:
    """Tests for integration with ImportWorkflow."""

    @pytest.mark.asyncio
    async def test_import_creates_workflow_with_storage(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should create ImportWorkflow with storage from context."""
        mock_result = ImportResult(
            imported_count=1,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Workflow should be created with storage from context
            MockWorkflow.assert_called_once()
            call_args = MockWorkflow.call_args
            assert call_args[0][0] == command_context.storage

    @pytest.mark.asyncio
    async def test_import_passes_config_to_workflow(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should pass correct ImportConfig to workflow."""
        mock_result = ImportResult(
            imported_count=1,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern="*.mbox",
                state_db=v11_db,
                deduplicate=False,
                json_output=False,
            )

            # Workflow.run should be called with correct config
            mock_workflow.run.assert_called_once()
            config = mock_workflow.run.call_args[0][0]
            assert isinstance(config, ImportConfig)
            assert config.archive_patterns == ["*.mbox"]
            assert config.state_db == v11_db
            assert config.dedupe is False


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling during import."""

    @pytest.mark.asyncio
    async def test_import_handles_file_not_found_error(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should handle FileNotFoundError with helpful message."""
        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(side_effect=FileNotFoundError("Archive file not found"))

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.fail = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            # Should call fail_and_exit (raises typer.Exit)
            with pytest.raises(typer.Exit) as exc_info:
                await import_command(
                    command_context,
                    archive_pattern="nonexistent.mbox",
                    state_db=v11_db,
                    deduplicate=True,
                    json_output=False,
                )

            # Should exit with error code
            assert exc_info.value.exit_code == 1

            # Should show helpful error
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert "Archive Not Found" in error_call[1]["title"]
            assert "Archive file not found" in error_call[1]["message"]
            assert "glob pattern" in error_call[1]["suggestion"]

    @pytest.mark.asyncio
    async def test_import_handles_generic_exception(self, command_context, v11_db):
        """Import should handle unexpected exceptions with error message."""
        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(side_effect=ValueError("Unexpected error"))

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.fail = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            # Should call fail_and_exit (raises typer.Exit)
            with pytest.raises(typer.Exit) as exc_info:
                await import_command(
                    command_context,
                    archive_pattern="test.mbox",
                    state_db=v11_db,
                    deduplicate=True,
                    json_output=False,
                )

            # Should exit with error code
            assert exc_info.value.exit_code == 1

            # Should show error with suggestion
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert "Import Failed" in error_call[1]["title"]
            assert "Unexpected error" in error_call[1]["message"]
            assert "permissions" in error_call[1]["suggestion"].lower()

    @pytest.mark.asyncio
    async def test_import_marks_task_as_failed_on_error(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should mark task as failed when error occurs."""
        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(side_effect=ValueError("Test error"))

            # Mock UI builder with task that tracks fail() calls
            mock_task_item = MagicMock()
            mock_task_item.fail = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)

            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)

            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            # Should fail (raises typer.Exit)
            with pytest.raises(typer.Exit):
                await import_command(
                    command_context,
                    archive_pattern=str(sample_mbox_file),
                    state_db=v11_db,
                    deduplicate=True,
                    json_output=False,
                )

            # Task should be marked as failed
            mock_task_item.fail.assert_called()
            fail_call = mock_task_item.fail.call_args
            assert "Import failed" in fail_call[0][0]


# ============================================================================
# Progress Reporting Tests
# ============================================================================


class TestProgressReporting:
    """Tests for progress reporting behavior."""

    @pytest.mark.asyncio
    async def test_import_shows_task_progress(self, command_context, v11_db, sample_mbox_file):
        """Import should show task progress during operation."""
        mock_result = ImportResult(
            imported_count=5,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task_item = MagicMock()
            mock_task_item.complete = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)

            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)

            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Task should be completed with count
            mock_task_item.complete.assert_called_once()
            complete_call = mock_task_item.complete.call_args
            assert "5" in complete_call[0][0]
            assert "message" in complete_call[0][0].lower()

    @pytest.mark.asyncio
    async def test_import_displays_results_report(self, command_context, v11_db, sample_mbox_file):
        """Import should display summary report after completion."""
        mock_result = ImportResult(
            imported_count=10,
            skipped_count=2,
            duplicate_count=3,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Should show report with statistics
            command_context.output.show_report.assert_called_once()
            report_call = command_context.output.show_report.call_args
            assert report_call[0][0] == "Import Results"
            report_data = report_call[0][1]
            assert "Messages Imported" in report_data
            assert "10" in report_data["Messages Imported"]

    @pytest.mark.asyncio
    async def test_import_shows_duplicate_count_when_deduplication_enabled(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import report should show duplicates skipped when dedupe=True."""
        mock_result = ImportResult(
            imported_count=5,
            skipped_count=0,
            duplicate_count=3,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Report should include duplicate count
            report_call = command_context.output.show_report.call_args
            report_data = report_call[0][1]
            assert "Duplicates Skipped" in report_data
            assert "3" in report_data["Duplicates Skipped"]

    @pytest.mark.asyncio
    async def test_import_shows_na_for_duplicates_when_deduplication_disabled(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import report should show N/A for duplicates when dedupe=False."""
        mock_result = ImportResult(
            imported_count=5,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=False,
                json_output=False,
            )

            # Report should show N/A for duplicates
            report_call = command_context.output.show_report.call_args
            report_data = report_call[0][1]
            assert "Duplicates Skipped" in report_data
            assert report_data["Duplicates Skipped"] == "N/A"


# ============================================================================
# Success Message Tests
# ============================================================================


class TestSuccessMessages:
    """Tests for success message formatting."""

    @pytest.mark.asyncio
    async def test_import_shows_success_message_with_counts(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should show success message with message and file counts."""
        mock_result = ImportResult(
            imported_count=15,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file), "another.mbox"],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern="*.mbox",
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Should show success with counts
            command_context.output.success.assert_called_once()
            success_msg = command_context.output.success.call_args[0][0]
            assert "15" in success_msg
            assert "2" in success_msg  # 2 files
            assert "message" in success_msg.lower()

    @pytest.mark.asyncio
    async def test_import_suggests_next_steps(self, command_context, v11_db, sample_mbox_file):
        """Import should suggest next steps after completion."""
        mock_result = ImportResult(
            imported_count=5,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock UI builder
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=False)
            mock_task_item = MagicMock()
            mock_task_item.__enter__ = MagicMock(return_value=mock_task_item)
            mock_task_item.__exit__ = MagicMock(return_value=False)
            mock_task.task = MagicMock(return_value=mock_task_item)
            command_context._ui_builder.task_sequence = MagicMock(return_value=mock_task)

            await import_command(
                command_context,
                archive_pattern=str(sample_mbox_file),
                state_db=v11_db,
                deduplicate=True,
                json_output=False,
            )

            # Should suggest next steps
            command_context.output.suggest_next_steps.assert_called_once()
            suggestions = command_context.output.suggest_next_steps.call_args[0][0]
            assert len(suggestions) > 0
            assert any("search" in s.lower() for s in suggestions)
            assert any("status" in s.lower() for s in suggestions)
