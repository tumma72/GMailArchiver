"""Tests for command_context module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from gmailarchiver.cli.command_context import (
    CommandContext,
    _StaticOperationHandle,
    with_context,
)
from gmailarchiver.cli.output import OutputManager
from gmailarchiver.data.schema_manager import SchemaVersion, SchemaVersionError


class TestCommandContext:
    """Tests for CommandContext dataclass."""

    def test_creation(self) -> None:
        """CommandContext can be created with minimal args."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        assert ctx.output is output
        assert ctx.db is None
        assert ctx.gmail is None
        assert ctx.json_mode is False
        assert ctx.dry_run is False

    def test_creation_with_all_options(self) -> None:
        """CommandContext can be created with all options."""
        output = MagicMock(spec=OutputManager)
        db = MagicMock()
        gmail = MagicMock()

        ctx = CommandContext(
            output=output,
            db=db,
            gmail=gmail,
            json_mode=True,
            dry_run=True,
            state_db_path="/path/to/db",
        )

        assert ctx.db is db
        assert ctx.gmail is gmail
        assert ctx.json_mode is True
        assert ctx.dry_run is True
        assert ctx.state_db_path == "/path/to/db"

    def test_info_delegates_to_output(self) -> None:
        """info() should delegate to output.info()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.info("test message")

        output.info.assert_called_once_with("test message")

    def test_warning_delegates_to_output(self) -> None:
        """warning() should delegate to output.warning()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.warning("test warning")

        output.warning.assert_called_once_with("test warning")

    def test_success_delegates_to_output(self) -> None:
        """success() should delegate to output.success()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.success("test success")

        output.success.assert_called_once_with("test success")

    def test_error_delegates_to_output(self) -> None:
        """error() should delegate to output.error() with exit_code=0."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.error("test error")

        output.error.assert_called_once_with("test error", exit_code=0)

    def test_show_report_delegates_to_output(self) -> None:
        """show_report() should delegate to output.show_report()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)
        data = {"key": "value"}

        ctx.show_report("Title", data)

        output.show_report.assert_called_once_with("Title", data, None)

    def test_show_table_delegates_to_output(self) -> None:
        """show_table() should delegate to output.show_table()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.show_table("Title", ["A", "B"], [["1", "2"]])

        output.show_table.assert_called_once_with("Title", ["A", "B"], [["1", "2"]])

    def test_suggest_next_steps_delegates_to_output(self) -> None:
        """suggest_next_steps() should delegate to output.suggest_next_steps()."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        ctx.suggest_next_steps(["step1", "step2"])

        output.suggest_next_steps.assert_called_once_with(["step1", "step2"])

    def test_fail_and_exit_raises_typer_exit(self) -> None:
        """fail_and_exit() should show error panel and raise typer.Exit."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        with pytest.raises(typer.Exit) as exc_info:
            ctx.fail_and_exit("Error Title", "Error message")

        assert exc_info.value.exit_code == 1
        output.show_error_panel.assert_called_once()

    def test_fail_and_exit_with_suggestion(self) -> None:
        """fail_and_exit() should include suggestion in error panel."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)

        with pytest.raises(typer.Exit):
            ctx.fail_and_exit(
                "Error Title",
                "Error message",
                suggestion="Try this",
                details=["detail1"],
                exit_code=2,
            )

        output.show_error_panel.assert_called_once_with(
            title="Error Title",
            message="Error message",
            suggestion="Try this",
            details=["detail1"],
            exit_code=0,
        )


class TestStaticOperationHandle:
    """Tests for _StaticOperationHandle."""

    def test_log_info(self) -> None:
        """log() with INFO level should call output.info()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.log("test message", "INFO")

        output.info.assert_called_once_with("test message")

    def test_log_warning(self) -> None:
        """log() with WARNING level should call output.warning()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.log("test message", "WARNING")

        output.warning.assert_called_once_with("test message")

    def test_log_error(self) -> None:
        """log() with ERROR level should call output.error()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.log("test message", "ERROR")

        output.error.assert_called_once_with("test message", exit_code=0)

    def test_log_success(self) -> None:
        """log() with SUCCESS level should call output.success()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.log("test message", "SUCCESS")

        output.success.assert_called_once_with("test message")

    def test_update_progress_with_task(self) -> None:
        """update_progress() should update progress when task exists."""
        output = MagicMock(spec=OutputManager)
        progress = MagicMock()
        progress.add_task.return_value = "task_id"

        handle = _StaticOperationHandle(output, progress, "test", 100)
        handle.update_progress(5)

        progress.update.assert_called_once_with("task_id", advance=5, refresh=True)

    def test_set_status(self) -> None:
        """set_status() should update task description."""
        output = MagicMock(spec=OutputManager)
        progress = MagicMock()
        progress.add_task.return_value = "task_id"

        handle = _StaticOperationHandle(output, progress, "test", 100)
        handle.set_status("new status")

        progress.update.assert_called_with("task_id", description="new status", refresh=True)

    def test_set_total_creates_task(self) -> None:
        """set_total() should create task if none exists."""
        output = MagicMock(spec=OutputManager)
        progress = MagicMock()

        handle = _StaticOperationHandle(output, progress, "test", None)
        handle.set_total(50, "new description")

        progress.add_task.assert_called_once_with("new description", total=50)

    def test_succeed(self) -> None:
        """succeed() should call output.success()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.succeed("done")

        output.success.assert_called_once_with("done")

    def test_fail(self) -> None:
        """fail() should call output.error()."""
        output = MagicMock(spec=OutputManager)
        handle = _StaticOperationHandle(output, None, "test", None)

        handle.fail("failed")

        output.error.assert_called_once_with("failed", exit_code=0)


class TestWithContextDecorator:
    """Tests for @with_context decorator."""

    def test_basic_decorator(self) -> None:
        """@with_context should inject CommandContext as first parameter."""
        captured_ctx = None

        @with_context()
        def test_cmd(ctx: CommandContext) -> str:
            nonlocal captured_ctx
            captured_ctx = ctx
            return "result"

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            result = test_cmd()

        assert result == "result"
        assert captured_ctx is not None
        assert isinstance(captured_ctx, CommandContext)

    def test_json_output_option(self) -> None:
        """@with_context should handle json_output kwarg."""
        captured_ctx = None

        @with_context()
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(json_output=True)

        assert captured_ctx is not None
        assert captured_ctx.json_mode is True
        MockOutput.assert_called_once_with(json_mode=True, live_mode=False)

    def test_dry_run_option(self) -> None:
        """@with_context should handle dry_run kwarg."""
        captured_ctx = None

        @with_context()
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(dry_run=True)

        assert captured_ctx is not None
        assert captured_ctx.dry_run is True

    def test_requires_db_missing_file(self, tmp_path: Path) -> None:
        """@with_context with requires_db should fail if DB doesn't exist."""

        @with_context(requires_db=True)
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            with pytest.raises(typer.Exit) as exc_info:
                test_cmd(state_db=str(tmp_path / "nonexistent.db"))

            assert exc_info.value.exit_code == 1
            mock_output.show_error_panel.assert_called_once()

    def test_requires_db_success(self, tmp_path: Path) -> None:
        """@with_context with requires_db should inject DBManager."""
        # Create a minimal database
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")  # Create empty file

        captured_ctx = None

        @with_context(requires_db=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            MockDB.return_value = mock_db

            test_cmd(state_db=str(db_path))

        assert captured_ctx is not None
        assert captured_ctx.db is mock_db

    def test_requires_schema_version_check(self, tmp_path: Path) -> None:
        """@with_context with requires_schema should check version."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")

        @with_context(requires_db=True, requires_schema="1.2")
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.SchemaManager") as MockSchemaManager,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            # Mock SchemaManager to detect v1.1 and fail version requirement
            mock_schema_mgr = MagicMock()
            mock_schema_mgr.detect_version.return_value = SchemaVersion.V1_1
            mock_schema_mgr.require_version.side_effect = SchemaVersionError(
                "Schema version 1.2+ required, got 1.1",
                current_version=SchemaVersion.V1_1,
                required_version=SchemaVersion.V1_2,
            )
            MockSchemaManager.return_value = mock_schema_mgr

            with pytest.raises(typer.Exit) as exc_info:
                test_cmd(state_db=str(db_path))

            assert exc_info.value.exit_code == 1
            # Should show schema mismatch error
            call_args = mock_output.show_error_panel.call_args
            assert "Schema" in call_args.kwargs.get("title", "")

    def test_requires_gmail_success(self, tmp_path: Path) -> None:
        """@with_context with requires_gmail should inject GmailClient."""
        captured_ctx = None

        @with_context(requires_gmail=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.GmailAuthenticator") as MockAuth,
            patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail,
        ):
            mock_output = MagicMock(spec=OutputManager)
            # Add console attribute for UIBuilder (used by authenticate_gmail)
            mock_output.console = MagicMock()
            MockOutput.return_value = mock_output
            mock_auth = MagicMock()
            MockAuth.return_value = mock_auth
            mock_gmail = MagicMock()
            MockGmail.return_value = mock_gmail

            test_cmd()

        assert captured_ctx is not None
        assert captured_ctx.gmail is mock_gmail

    def test_requires_gmail_auth_failure(self) -> None:
        """@with_context should fail gracefully on auth error."""

        @with_context(requires_gmail=True)
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.GmailAuthenticator") as MockAuth,
        ):
            mock_output = MagicMock(spec=OutputManager)
            # Add console attribute for UIBuilder (used by authenticate_gmail)
            mock_output.console = MagicMock()
            MockOutput.return_value = mock_output
            MockAuth.return_value.authenticate.side_effect = Exception("Auth failed")

            with pytest.raises(typer.Exit) as exc_info:
                test_cmd()

            assert exc_info.value.exit_code == 1
            call_args = mock_output.show_error_panel.call_args
            assert "Authentication" in call_args.kwargs.get("title", "")

    def test_keyboard_interrupt_handling(self) -> None:
        """@with_context should handle KeyboardInterrupt gracefully."""

        @with_context()
        def test_cmd(ctx: CommandContext) -> None:
            raise KeyboardInterrupt()

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            with pytest.raises(typer.Exit) as exc_info:
                test_cmd()

            assert exc_info.value.exit_code == 130
            mock_output.warning.assert_called_once()

    def test_unexpected_exception_handling(self) -> None:
        """@with_context should handle unexpected exceptions gracefully."""

        @with_context()
        def test_cmd(ctx: CommandContext) -> None:
            raise ValueError("unexpected error")

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            with pytest.raises(typer.Exit) as exc_info:
                test_cmd()

            assert exc_info.value.exit_code == 1
            call_args = mock_output.show_error_panel.call_args
            assert "Unexpected" in call_args.kwargs.get("title", "")

    def test_db_cleanup_on_success(self, tmp_path: Path) -> None:
        """@with_context should close DB on success."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")

        @with_context(requires_db=True)
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            MockDB.return_value = mock_db

            test_cmd(state_db=str(db_path))

            mock_db.close.assert_called_once()

    def test_db_cleanup_on_exception(self, tmp_path: Path) -> None:
        """@with_context should close DB even on exception."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")

        @with_context(requires_db=True)
        def test_cmd(ctx: CommandContext) -> None:
            raise ValueError("test error")

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            MockDB.return_value = mock_db

            with pytest.raises(typer.Exit):
                test_cmd(state_db=str(db_path))

            mock_db.close.assert_called_once()

    def test_preserves_function_metadata(self) -> None:
        """@with_context should preserve function name and docstring."""

        @with_context()
        def my_command(ctx: CommandContext) -> None:
            """This is my command."""
            pass

        assert my_command.__name__ == "my_command"
        assert my_command.__doc__ == "This is my command."

    def test_passes_additional_args(self) -> None:
        """@with_context should pass additional args to the function."""
        captured_args = None

        @with_context()
        def test_cmd(ctx: CommandContext, arg1: str, arg2: int) -> None:
            nonlocal captured_args
            captured_args = (arg1, arg2)

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd("hello", 42)

        assert captured_args == ("hello", 42)

    def test_passes_additional_kwargs(self) -> None:
        """@with_context should pass additional kwargs to the function."""
        captured_kwargs = None

        @with_context()
        def test_cmd(ctx: CommandContext, name: str = "default") -> None:
            nonlocal captured_kwargs
            captured_kwargs = {"name": name}

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(name="custom")

        assert captured_kwargs == {"name": "custom"}


# ============================================================================
# Coverage Improvement Tests - CommandContext.operation() context manager
# ============================================================================


class TestCommandContextOperationContextManager:
    """Test CommandContext.operation() context manager behavior."""

    def test_operation_with_static_context(self) -> None:
        """Test operation() uses static handler when no live context."""
        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        # No live context
        ctx._live_context = None

        with ctx.operation("Processing", total=10) as handle:
            # Should get a handle
            assert handle is not None
            # Context should have operation_handle set
            assert ctx.operation_handle is handle

        # After context exits, operation_handle should be cleared
        assert ctx.operation_handle is None

    def test_operation_with_live_context(self) -> None:
        """Test operation() uses live handler when live context is set."""
        from gmailarchiver.cli.output import LiveOutputHandler

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a live output handler (which manages LiveLayoutContext)
            live_handler = LiveOutputHandler(output, log_dir=Path(tmpdir))
            with live_handler:
                # The live handler creates a LiveLayoutContext internally
                ctx._live_context = live_handler

                with ctx.operation("Processing", total=10) as handle:
                    # Should get a handle
                    assert handle is not None
                    assert ctx.operation_handle is handle

                # After context exits, operation_handle should be cleared
                assert ctx.operation_handle is None


class TestStaticOperationHandleCompletePending:
    """Test _StaticOperationHandle.complete_pending() behavior."""

    def test_complete_pending_logs_message(self) -> None:
        """Test complete_pending() calls log() with the message and level."""
        output = OutputManager()

        with output.progress_context("Testing", total=10) as progress:
            if progress:
                handle = _StaticOperationHandle(output, progress, "Initial", total=10)

                # Use patch to verify log is called
                with patch.object(handle, "log") as mock_log:
                    handle.complete_pending("Done!", "SUCCESS")
                    mock_log.assert_called_once_with("Done!", "SUCCESS")

    def test_complete_pending_default_level(self) -> None:
        """Test complete_pending() defaults to SUCCESS level."""
        output = OutputManager()

        with output.progress_context("Testing", total=10) as progress:
            if progress:
                handle = _StaticOperationHandle(output, progress, "Initial", total=10)

                with patch.object(handle, "log") as mock_log:
                    handle.complete_pending("Finished!")
                    mock_log.assert_called_once_with("Finished!", "SUCCESS")
