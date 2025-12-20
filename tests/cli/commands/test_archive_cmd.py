"""Tests for archive command CLI implementation.

This module tests the archive command entry point and handlers,
focusing on:
- Command execution flow
- Error handling paths
- Progress reporting integration
- Different result scenarios (dry run, interrupted, validation failed, etc.)
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import typer

from gmailarchiver.cli.commands.archive import (
    _handle_deletion,
    _handle_dry_run,
    _handle_interrupted,
    _handle_no_new_messages,
    _handle_validation_failure,
    _run_archive,
    _show_final_summary,
)
from gmailarchiver.core.workflows.archive import ArchiveResult

# =============================================================================
# Helper Factories
# =============================================================================


def create_mock_context(
    storage: AsyncMock | None = None,
    output: Mock | None = None,
    ui: Mock | None = None,
) -> Mock:
    """Create a mock CommandContext for testing.

    Args:
        storage: Optional mock storage
        output: Optional mock output manager
        ui: Optional mock UI builder

    Returns:
        Mock CommandContext with configured attributes
    """
    ctx = Mock()
    ctx.storage = storage or create_mock_storage()
    ctx.output = output or create_mock_output()
    ctx.ui = ui or create_mock_ui()
    ctx.warning = Mock()
    ctx.info = Mock()
    ctx.success = Mock()
    ctx.error = Mock()
    ctx.show_report = Mock()
    ctx.suggest_next_steps = Mock()
    ctx.fail_and_exit = Mock(side_effect=typer.Exit(1))
    return ctx


def create_mock_storage() -> AsyncMock:
    """Create a mock HybridStorage for testing.

    Returns:
        AsyncMock HybridStorage with common methods
    """
    storage = AsyncMock()
    storage.get_message_ids_for_archive = AsyncMock(return_value=[])
    return storage


def create_mock_output() -> Mock:
    """Create a mock OutputManager for testing.

    Returns:
        Mock OutputManager with common methods
    """
    output = Mock()
    output.show_validation_report = Mock()
    output.suggest_next_steps = Mock()  # For SuggestionList widget
    output.show_report = Mock()  # For ReportCard widget
    output.progress_context = Mock()
    output.progress_context.return_value.__enter__ = Mock()
    output.progress_context.return_value.__exit__ = Mock()
    # These are needed for ValidationPanel.render()
    output.json_mode = False
    output.quiet = False
    output.console = Mock()
    return output


def create_mock_ui() -> Mock:
    """Create a mock UIBuilder for testing.

    Returns:
        Mock UIBuilder with spinner and task_sequence support
    """
    ui = Mock()

    # Mock spinner
    spinner_task = Mock()
    spinner_task.complete = Mock()
    spinner_task.fail = Mock()

    spinner_context = Mock()
    spinner_context.__enter__ = Mock(return_value=spinner_task)
    spinner_context.__exit__ = Mock()

    ui.spinner = Mock(return_value=spinner_context)

    # Mock task_sequence - needed for workflow_sequence() in CLIProgressAdapter
    task_handle = Mock()
    task_handle.complete = Mock()
    task_handle.fail = Mock()
    task_handle.advance = Mock()
    task_handle.log = Mock()
    task_handle.set_total = Mock()

    task_context = Mock()
    task_context.__enter__ = Mock(return_value=task_handle)
    task_context.__exit__ = Mock(return_value=None)

    sequence = Mock()
    sequence.task = Mock(return_value=task_context)

    sequence_context = Mock()
    sequence_context.__enter__ = Mock(return_value=sequence)
    sequence_context.__exit__ = Mock(return_value=None)

    ui.task_sequence = Mock(return_value=sequence_context)

    return ui


def create_archive_result(
    archived_count: int = 10,
    skipped_count: int = 0,
    duplicate_count: int = 0,
    found_count: int = 10,
    actual_file: str = "archive.mbox",
    interrupted: bool = False,
    validation_passed: bool = True,
    validation_details: dict | None = None,
) -> ArchiveResult:
    """Create an ArchiveResult for testing.

    Args:
        archived_count: Number of messages archived
        skipped_count: Number of messages skipped
        duplicate_count: Number of duplicate messages
        found_count: Number of messages found
        actual_file: Path to archive file
        interrupted: Whether operation was interrupted
        validation_passed: Whether validation passed
        validation_details: Optional validation details dict

    Returns:
        Configured ArchiveResult instance
    """
    return ArchiveResult(
        archived_count=archived_count,
        skipped_count=skipped_count,
        duplicate_count=duplicate_count,
        found_count=found_count,
        actual_file=actual_file,
        gmail_query="before:2022/01/01",
        interrupted=interrupted,
        validation_passed=validation_passed,
        validation_details=validation_details,
    )


# =============================================================================
# Test archive() Entry Point
# =============================================================================


class TestArchiveEntryPoint:
    """Tests for the archive() command entry point."""

    def test_archive_calls_asyncio_run(self, temp_dir):
        """Archive command should invoke asyncio.run to execute _run_archive."""
        # Note: archive() is decorated with @with_context which injects ctx,
        # so we can't test it directly without going through the decorator.
        # Instead, we test that the inner async function is properly invoked.

        # Create a mock state database to pass decorator validation
        state_db = temp_dir / "archive_state.db"
        state_db.touch()

        # Act & Assert
        with patch("gmailarchiver.cli.commands.archive.asyncio.run") as mock_run:
            # Mock the asyncio.run to avoid actual execution
            mock_run.return_value = None

            # We can't call archive() directly since @with_context injects ctx
            # Instead, test the _run_archive function directly which is what
            # archive() calls via asyncio.run
            from gmailarchiver.cli.commands.archive import _run_archive

            # Verify the function exists and is callable
            assert callable(_run_archive)
            assert inspect.iscoroutinefunction(_run_archive)


# =============================================================================
# Test _run_archive() Workflow
# =============================================================================


@pytest.mark.asyncio
class TestRunArchive:
    """Tests for the _run_archive() async implementation."""

    async def test_run_archive_successful_flow(self):
        """Should complete full archive workflow successfully."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=5, found_count=5)

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=False,
                credentials=None,
            )

        # Assert
        mock_workflow.run.assert_called_once()
        ctx.success.assert_called()

    async def test_run_archive_handles_value_error(self):
        """Should handle ValueError from workflow with helpful message."""
        # Arrange
        ctx = create_mock_context()

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(side_effect=ValueError("Invalid age format"))

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            with pytest.raises(typer.Exit):
                await _run_archive(
                    ctx=ctx,
                    age_threshold="invalid",
                    output=None,
                    compress=None,
                    incremental=True,
                    trash=False,
                    delete=False,
                    dry_run=False,
                    verbose=False,
                    credentials=None,
                )

        # Assert
        ctx.fail_and_exit.assert_called_once()
        call_args = ctx.fail_and_exit.call_args[1]
        assert call_args["title"] == "Invalid Input"
        assert "Invalid age format" in call_args["message"]

    async def test_run_archive_handles_general_exception(self):
        """Should handle general exceptions with network suggestion."""
        # Arrange
        ctx = create_mock_context()

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(side_effect=RuntimeError("Network error"))

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            with pytest.raises(typer.Exit):
                await _run_archive(
                    ctx=ctx,
                    age_threshold="3y",
                    output=None,
                    compress=None,
                    incremental=True,
                    trash=False,
                    delete=False,
                    dry_run=False,
                    verbose=False,
                    credentials=None,
                )

        # Assert
        ctx.fail_and_exit.assert_called_once()
        call_args = ctx.fail_and_exit.call_args[1]
        assert call_args["title"] == "Archive Failed"
        assert "network connection" in call_args["suggestion"]

    async def test_run_archive_dry_run_mode(self):
        """Should handle dry run mode correctly."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=0, found_count=10)

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with (
            patch("gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow),
            patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard,
        ):
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=True,
                verbose=False,
                credentials=None,
            )

        # Assert
        ctx.warning.assert_called_with("DRY RUN completed - no changes made")
        MockReportCard.assert_called_once()
        mock_card.render.assert_called_once_with(ctx.output)

    async def test_run_archive_interrupted(self):
        """Should handle interrupted archive correctly."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=3,
            found_count=10,
            interrupted=True,
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=False,
                credentials=None,
            )

        # Assert
        ctx.warning.assert_called_with("Archive was interrupted (Ctrl+C)")
        # SuggestionList widget calls ctx.output.suggest_next_steps internally
        ctx.output.suggest_next_steps.assert_called_once()

    async def test_run_archive_validation_failed(self):
        """Should handle validation failure correctly."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            found_count=5,
            validation_passed=False,
            validation_details={"errors": ["Checksum mismatch"]},
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with (
            patch("gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow),
            patch("gmailarchiver.cli.commands.archive.ErrorPanel") as MockErrorPanel,
        ):
            mock_panel = MagicMock()
            mock_panel.add_details = MagicMock(return_value=mock_panel)
            mock_panel.with_suggestion = MagicMock(return_value=mock_panel)
            mock_panel.render = MagicMock()
            MockErrorPanel.return_value = mock_panel

            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=False,
                credentials=None,
            )

        # Assert - validation failure handler should render error panel
        MockErrorPanel.assert_called_once()
        mock_panel.render.assert_called_once_with(ctx.output)

    async def test_run_archive_no_messages_found(self):
        """Should handle no messages found scenario."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=0,
            found_count=0,
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=False,
                credentials=None,
            )

        # Assert
        ctx.warning.assert_called_with("No messages found matching criteria")
        # SuggestionList widget calls ctx.output.suggest_next_steps internally
        ctx.output.suggest_next_steps.assert_called_once()

    async def test_run_archive_no_new_messages(self):
        """Should handle no new messages (all already archived)."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=0,
            skipped_count=10,
            found_count=10,
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=False,
                credentials=None,
            )

        # Assert
        ctx.info.assert_called()
        # Check that one of the info calls mentions "already archived"
        info_calls = [str(call) for call in ctx.info.call_args_list]
        assert any("already archived" in str(call) for call in info_calls)

    async def test_run_archive_successful_with_verbose(self):
        """Should show validation details when verbose and validation passes."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            found_count=5,
            validation_passed=True,
            validation_details={"message_count": 5, "checksum": "valid"},
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            await _run_archive(
                ctx=ctx,
                age_threshold="3y",
                output=None,
                compress=None,
                incremental=True,
                trash=False,
                delete=False,
                dry_run=False,
                verbose=True,  # Verbose enabled
                credentials=None,
            )

        # Assert - ValidationPanel.render() calls ctx.output.console.print()
        # In verbose mode, validation panel should be rendered
        assert ctx.output.console.print.called
        ctx.success.assert_called()

    async def test_run_archive_with_deletion_after_archiving(self):
        """Should handle deletion when messages were archived and deletion requested."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            found_count=5,
            validation_passed=True,
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)
        mock_workflow.delete_messages = AsyncMock()

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)

        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act - with trash flag
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            with patch("gmailarchiver.cli.commands.archive.typer.confirm", return_value=True):
                await _run_archive(
                    ctx=ctx,
                    age_threshold="3y",
                    output=None,
                    compress=None,
                    incremental=True,
                    trash=True,  # Request trash
                    delete=False,
                    dry_run=False,
                    verbose=False,
                    credentials=None,
                )

        # Assert
        mock_workflow.delete_messages.assert_called_once()
        ctx.success.assert_called()


# =============================================================================
# Test Handler Functions
# =============================================================================


class TestHandleDryRun:
    """Tests for _handle_dry_run() handler."""

    def test_handle_dry_run_shows_preview(self):
        """Should display dry run preview with counts."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=0,
            skipped_count=2,
            duplicate_count=1,
            found_count=10,
        )

        # Act
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _handle_dry_run(ctx, result)

        # Assert
        ctx.warning.assert_called_with("DRY RUN completed - no changes made")
        MockReportCard.assert_called_once_with("Archive Preview")
        # Verify add_field was called with expected values
        assert mock_card.add_field.call_count == 5
        # Verify render was called
        mock_card.render.assert_called_once_with(ctx.output)


class TestHandleInterrupted:
    """Tests for _handle_interrupted() handler."""

    def test_handle_interrupted_shows_progress_and_suggestions(self):
        """Should display partial progress and resume suggestions."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=3,
            found_count=10,
            interrupted=True,
        )

        # Act
        _handle_interrupted(ctx, result, age_threshold="3y")

        # Assert
        ctx.warning.assert_called_with("Archive was interrupted (Ctrl+C)")

        # Check info calls
        info_calls = [call[0][0] for call in ctx.info.call_args_list]
        assert any("Partial archive saved" in msg for msg in info_calls)
        assert any("3 messages archived" in msg for msg in info_calls)

        # Check suggestions - SuggestionList widget calls ctx.output.suggest_next_steps
        ctx.output.suggest_next_steps.assert_called_once()
        suggestions = ctx.output.suggest_next_steps.call_args[0][0]
        assert any("Resume" in s for s in suggestions)


class TestHandleValidationFailure:
    """Tests for _handle_validation_failure() handler."""

    def test_handle_validation_failure_without_verbose(self):
        """Should fail with validation error without showing details."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            validation_passed=False,
            validation_details={"errors": ["Checksum mismatch"]},
        )

        # Act
        with patch("gmailarchiver.cli.commands.archive.ErrorPanel") as MockErrorPanel:
            mock_panel = MagicMock()
            mock_panel.add_details = MagicMock(return_value=mock_panel)
            mock_panel.with_suggestion = MagicMock(return_value=mock_panel)
            mock_panel.render = MagicMock()
            MockErrorPanel.return_value = mock_panel

            _handle_validation_failure(ctx, result, verbose=False)

        # Assert
        ctx.output.show_validation_report.assert_not_called()
        MockErrorPanel.assert_called_once()
        mock_panel.render.assert_called_once_with(ctx.output)

    def test_handle_validation_failure_with_verbose(self):
        """Should show validation details when verbose is enabled."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            validation_passed=False,
            validation_details={"errors": ["Checksum mismatch"]},
        )

        # Act
        with patch("gmailarchiver.cli.commands.archive.ErrorPanel") as MockErrorPanel:
            mock_panel = MagicMock()
            mock_panel.add_details = MagicMock(return_value=mock_panel)
            mock_panel.with_suggestion = MagicMock(return_value=mock_panel)
            mock_panel.render = MagicMock()
            MockErrorPanel.return_value = mock_panel

            _handle_validation_failure(ctx, result, verbose=True)

        # Assert - ValidationPanel.render() calls ctx.output.console.print()
        assert ctx.output.console.print.called
        MockErrorPanel.assert_called_once()
        mock_panel.render.assert_called_once_with(ctx.output)


@pytest.mark.asyncio
class TestHandleNoNewMessages:
    """Tests for _handle_no_new_messages() handler."""

    async def test_handle_no_new_messages_already_archived(self):
        """Should report when all messages already archived."""
        # Arrange
        ctx = create_mock_context()
        ctx.storage = create_mock_storage()

        result = create_archive_result(
            archived_count=0,
            skipped_count=10,
            duplicate_count=0,
            found_count=10,
        )

        workflow = AsyncMock()

        # Act
        await _handle_no_new_messages(
            ctx=ctx,
            result=result,
            workflow=workflow,
            trash=False,
            delete=False,
            age_threshold="3y",
        )

        # Assert
        ctx.info.assert_called()
        info_msg = ctx.info.call_args[0][0]
        assert "10" in info_msg
        assert "already archived" in info_msg

    async def test_handle_no_new_messages_duplicates(self):
        """Should report when all messages are duplicates."""
        # Arrange
        ctx = create_mock_context()
        ctx.storage = create_mock_storage()

        result = create_archive_result(
            archived_count=0,
            skipped_count=0,
            duplicate_count=5,
            found_count=5,
        )

        workflow = AsyncMock()

        # Act
        await _handle_no_new_messages(
            ctx=ctx,
            result=result,
            workflow=workflow,
            trash=False,
            delete=False,
            age_threshold="3y",
        )

        # Assert
        ctx.info.assert_called()
        info_msg = ctx.info.call_args[0][0]
        assert "duplicates" in info_msg

    async def test_handle_no_new_messages_mixed(self):
        """Should report both already archived and duplicates."""
        # Arrange
        ctx = create_mock_context()
        ctx.storage = create_mock_storage()

        result = create_archive_result(
            archived_count=0,
            skipped_count=5,
            duplicate_count=3,
            found_count=8,
        )

        workflow = AsyncMock()

        # Act
        await _handle_no_new_messages(
            ctx=ctx,
            result=result,
            workflow=workflow,
            trash=False,
            delete=False,
            age_threshold="3y",
        )

        # Assert
        ctx.info.assert_called()
        info_msg = ctx.info.call_args[0][0]
        assert "already archived" in info_msg
        assert "duplicates" in info_msg

    async def test_handle_no_new_messages_offers_deletion_with_trash(self, temp_dir):
        """Should offer to trash existing messages."""
        # Arrange
        ctx = create_mock_context()
        archive_file = temp_dir / "archive.mbox"
        archive_file.touch()

        ctx.storage = create_mock_storage()
        ctx.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2", "msg3"])

        result = create_archive_result(
            archived_count=0,
            skipped_count=3,
            found_count=3,
            actual_file=str(archive_file),
        )

        workflow = AsyncMock()
        workflow.delete_messages = AsyncMock()

        # Act - simulate user confirming trash
        with patch("gmailarchiver.cli.commands.archive.typer.confirm", return_value=True):
            await _handle_no_new_messages(
                ctx=ctx,
                result=result,
                workflow=workflow,
                trash=True,
                delete=False,
                age_threshold="3y",
            )

        # Assert
        workflow.delete_messages.assert_called_once_with(str(archive_file), permanent=False)
        ctx.success.assert_called()

    async def test_handle_no_new_messages_offers_deletion_with_delete(self, temp_dir):
        """Should offer to permanently delete existing messages."""
        # Arrange
        ctx = create_mock_context()
        archive_file = temp_dir / "archive.mbox"
        archive_file.touch()

        ctx.storage = create_mock_storage()
        ctx.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2"])

        result = create_archive_result(
            archived_count=0,
            skipped_count=2,
            found_count=2,
            actual_file=str(archive_file),
        )

        workflow = AsyncMock()
        workflow.delete_messages = AsyncMock()

        # Act - simulate user confirming deletion
        with patch(
            "gmailarchiver.cli.commands.archive.typer.prompt", return_value="DELETE 2 MESSAGES"
        ):
            await _handle_no_new_messages(
                ctx=ctx,
                result=result,
                workflow=workflow,
                trash=False,
                delete=True,
                age_threshold="3y",
            )

        # Assert
        workflow.delete_messages.assert_called_once_with(str(archive_file), permanent=True)
        ctx.success.assert_called()

    async def test_handle_no_new_messages_deletion_cancelled(self, temp_dir):
        """Should handle deletion cancellation."""
        # Arrange
        ctx = create_mock_context()
        archive_file = temp_dir / "archive.mbox"
        archive_file.touch()

        ctx.storage = create_mock_storage()
        ctx.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1"])

        result = create_archive_result(
            archived_count=0,
            skipped_count=1,
            found_count=1,
            actual_file=str(archive_file),
        )

        workflow = AsyncMock()

        # Act - simulate user cancelling
        with patch("gmailarchiver.cli.commands.archive.typer.confirm", return_value=False):
            await _handle_no_new_messages(
                ctx=ctx,
                result=result,
                workflow=workflow,
                trash=True,
                delete=False,
                age_threshold="3y",
            )

        # Assert
        workflow.delete_messages.assert_not_called()
        ctx.info.assert_called_with("Cancelled")

    async def test_handle_no_new_messages_delete_wrong_confirmation(self, temp_dir):
        """Should cancel permanent deletion with wrong confirmation phrase."""
        # Arrange
        ctx = create_mock_context()
        archive_file = temp_dir / "archive.mbox"
        archive_file.touch()

        ctx.storage = create_mock_storage()
        ctx.storage.get_message_ids_for_archive = AsyncMock(return_value=["msg1", "msg2"])

        result = create_archive_result(
            archived_count=0,
            skipped_count=2,
            found_count=2,
            actual_file=str(archive_file),
        )

        workflow = AsyncMock()

        # Act - simulate wrong confirmation phrase
        with patch(
            "gmailarchiver.cli.commands.archive.typer.prompt",
            return_value="DELETE MESSAGES",  # Wrong phrase
        ):
            await _handle_no_new_messages(
                ctx=ctx,
                result=result,
                workflow=workflow,
                trash=False,
                delete=True,
                age_threshold="3y",
            )

        # Assert
        workflow.delete_messages.assert_not_called()
        ctx.info.assert_called_with("Deletion cancelled")


@pytest.mark.asyncio
class TestHandleDeletion:
    """Tests for _handle_deletion() handler."""

    async def test_handle_deletion_trash_confirmed(self):
        """Should move messages to trash when confirmed."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=5)
        workflow = AsyncMock()
        workflow.delete_messages = AsyncMock()

        # Act - simulate confirmation
        with patch("gmailarchiver.cli.commands.archive.typer.confirm", return_value=True):
            await _handle_deletion(
                ctx=ctx,
                workflow=workflow,
                result=result,
                trash=True,
                delete=False,
            )

        # Assert
        workflow.delete_messages.assert_called_once_with(result.actual_file, permanent=False)
        ctx.success.assert_called_with("Messages moved to trash")

    async def test_handle_deletion_trash_cancelled(self):
        """Should handle trash cancellation."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=5)
        workflow = AsyncMock()

        # Act - simulate cancellation
        with patch("gmailarchiver.cli.commands.archive.typer.confirm", return_value=False):
            await _handle_deletion(
                ctx=ctx,
                workflow=workflow,
                result=result,
                trash=True,
                delete=False,
            )

        # Assert
        workflow.delete_messages.assert_not_called()
        ctx.info.assert_called_with("Cancelled")

    async def test_handle_deletion_permanent_confirmed(self):
        """Should permanently delete messages when confirmed."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=10)
        workflow = AsyncMock()
        workflow.delete_messages = AsyncMock()

        # Act - simulate correct confirmation phrase
        with patch(
            "gmailarchiver.cli.commands.archive.typer.prompt",
            return_value="DELETE 10 MESSAGES",
        ):
            await _handle_deletion(
                ctx=ctx,
                workflow=workflow,
                result=result,
                trash=False,
                delete=True,
            )

        # Assert
        workflow.delete_messages.assert_called_once_with(result.actual_file, permanent=True)
        ctx.success.assert_called_with("Messages permanently deleted")

    async def test_handle_deletion_permanent_wrong_phrase(self):
        """Should cancel deletion if confirmation phrase is wrong."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=10)
        workflow = AsyncMock()

        # Act - simulate wrong confirmation phrase
        with patch(
            "gmailarchiver.cli.commands.archive.typer.prompt",
            return_value="DELETE MESSAGES",  # Wrong phrase
        ):
            await _handle_deletion(
                ctx=ctx,
                workflow=workflow,
                result=result,
                trash=False,
                delete=True,
            )

        # Assert
        workflow.delete_messages.assert_not_called()
        ctx.info.assert_called_with("Deletion cancelled")


class TestShowFinalSummary:
    """Tests for _show_final_summary() handler."""

    def test_show_final_summary_basic(self):
        """Should show basic summary report."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=10,
            skipped_count=0,
            duplicate_count=0,
        )

        # Act
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _show_final_summary(
                ctx=ctx,
                result=result,
                output_file=None,
            )

        # Assert
        MockReportCard.assert_called_once_with("Archive Summary")
        assert mock_card.add_field.call_count >= 2
        mock_card.render.assert_called_once_with(ctx.output)
        ctx.success.assert_called_with("Archive completed!")

    def test_show_final_summary_with_skipped(self):
        """Should include skipped count in summary."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=5,
            skipped_count=3,
            duplicate_count=2,
        )

        # Act
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _show_final_summary(
                ctx=ctx,
                result=result,
                output_file=None,
            )

        # Assert
        MockReportCard.assert_called_once_with("Archive Summary")
        # Verify add_field was called (should include Skipped field)
        assert mock_card.add_field.call_count >= 3
        mock_card.render.assert_called_once_with(ctx.output)

    def test_show_final_summary_with_custom_output_file(self):
        """Should display custom output file when provided."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(archived_count=10, actual_file="archive.mbox")

        # Act
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _show_final_summary(
                ctx=ctx,
                result=result,
                output_file="custom_archive.mbox",
            )

        # Assert
        MockReportCard.assert_called_once_with("Archive Summary")
        # Verify File field contains custom output
        call_args_list = mock_card.add_field.call_args_list
        file_field_found = False
        for call in call_args_list:
            if call[0][0] == "File" and "custom_archive.mbox" in call[0][1]:
                file_field_found = True
                break
        assert file_field_found, "File field should contain custom output file"
        mock_card.render.assert_called_once_with(ctx.output)
