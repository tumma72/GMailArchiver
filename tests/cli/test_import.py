"""Tests for CLI import command implementation.

This module tests the import command in cli/commands/import_.py, focusing on:
- Command behavior and argument handling
- Integration with ImportWorkflow
- Error handling and user feedback
- Progress reporting via CLIProgressAdapter

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
from gmailarchiver.cli.commands.import_ import _run_import
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
            await _run_import(
                ctx,
                archive_pattern=str(sample_mbox_file),
                state_db=nonexistent_db,
                deduplicate=True,
            )

        # Should exit with error code
        assert exc_info.value.exit_code == 1

        # Verify error message was shown
        ctx.output.show_error_panel.assert_called_once()
        error_call = ctx.output.show_error_panel.call_args
        assert "Database Not Found" in error_call[1]["title"]
        assert nonexistent_db in error_call[1]["message"]


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

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern=str(sample_mbox_file),
                    state_db=v11_db,
                    deduplicate=True,
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

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern="*.mbox",
                    state_db=v11_db,
                    deduplicate=False,
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
        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(side_effect=FileNotFoundError("Archive file not found"))

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                # Should call fail_and_exit (raises typer.Exit)
                with pytest.raises(typer.Exit) as exc_info:
                    await _run_import(
                        command_context,
                        archive_pattern="nonexistent.mbox",
                        state_db=v11_db,
                        deduplicate=True,
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
        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(side_effect=ValueError("Unexpected error"))

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                # Should call fail_and_exit (raises typer.Exit)
                with pytest.raises(typer.Exit) as exc_info:
                    await _run_import(
                        command_context,
                        archive_pattern="test.mbox",
                        state_db=v11_db,
                        deduplicate=True,
                    )

                # Should exit with error code
                assert exc_info.value.exit_code == 1

                # Should show error with suggestion
                command_context.output.show_error_panel.assert_called_once()
                error_call = command_context.output.show_error_panel.call_args
                assert "Import Failed" in error_call[1]["title"]
                assert "Unexpected error" in error_call[1]["message"]
                assert "permissions" in error_call[1]["suggestion"].lower()


# ============================================================================
# Result Handling Tests
# ============================================================================


class TestResultHandling:
    """Tests for result handling and summary display."""

    @pytest.mark.asyncio
    async def test_import_handles_no_files_found(self, command_context, v11_db):
        """Import should warn when no files match the pattern."""
        mock_result = ImportResult(
            imported_count=0,
            skipped_count=0,
            duplicate_count=0,
            files_processed=[],  # No files processed
        )

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern="nonexistent*.mbox",
                    state_db=v11_db,
                    deduplicate=True,
                )

                # Should show warning
                command_context.output.warning.assert_called()

    @pytest.mark.asyncio
    async def test_import_displays_results_via_report_card(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should display summary via ReportCard widget."""
        mock_result = ImportResult(
            imported_count=10,
            skipped_count=2,
            duplicate_count=3,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                with patch("gmailarchiver.cli.commands.import_.ReportCard") as MockReportCard:
                    mock_card = MagicMock()
                    mock_card.add_field.return_value = mock_card
                    MockReportCard.return_value = mock_card

                    await _run_import(
                        command_context,
                        archive_pattern=str(sample_mbox_file),
                        state_db=v11_db,
                        deduplicate=True,
                    )

                    # ReportCard should be created with "Import Results"
                    MockReportCard.assert_called_once_with("Import Results")

                    # Should have added fields
                    assert mock_card.add_field.call_count >= 2

                    # Should have been rendered
                    mock_card.render.assert_called_once()

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

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern="*.mbox",
                    state_db=v11_db,
                    deduplicate=True,
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

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern=str(sample_mbox_file),
                    state_db=v11_db,
                    deduplicate=True,
                )

                # Should suggest next steps
                command_context.output.suggest_next_steps.assert_called_once()
                suggestions = command_context.output.suggest_next_steps.call_args[0][0]
                assert len(suggestions) > 0
                assert any("search" in s.lower() for s in suggestions)
                assert any("status" in s.lower() for s in suggestions)

    @pytest.mark.asyncio
    async def test_import_shows_info_when_all_duplicates(
        self, command_context, v11_db, sample_mbox_file
    ):
        """Import should show info message when no new messages (all duplicates)."""
        mock_result = ImportResult(
            imported_count=0,
            skipped_count=0,
            duplicate_count=5,
            files_processed=[str(sample_mbox_file)],
        )

        with patch("gmailarchiver.cli.commands.import_.ImportWorkflow") as MockWorkflow:
            mock_workflow = MockWorkflow.return_value
            mock_workflow.run = AsyncMock(return_value=mock_result)

            with patch("gmailarchiver.cli.commands.import_.CLIProgressAdapter") as MockAdapter:
                mock_adapter = MockAdapter.return_value
                mock_adapter.workflow_sequence.return_value.__enter__ = MagicMock()
                mock_adapter.workflow_sequence.return_value.__exit__ = MagicMock(return_value=False)

                await _run_import(
                    command_context,
                    archive_pattern=str(sample_mbox_file),
                    state_db=v11_db,
                    deduplicate=True,
                )

                # Should show info message (not success)
                command_context.output.info.assert_called()
                info_msg = command_context.output.info.call_args[0][0]
                assert "duplicate" in info_msg.lower() or "no new" in info_msg.lower()
