"""Tests for command_context module."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        assert ctx.storage is None
        assert ctx.gmail is None
        assert ctx.json_mode is False
        assert ctx.dry_run is False

    def test_creation_with_all_options(self) -> None:
        """CommandContext can be created with all options."""
        output = MagicMock(spec=OutputManager)
        storage = MagicMock()
        gmail = MagicMock()

        ctx = CommandContext(
            output=output,
            storage=storage,
            gmail=gmail,
            json_mode=True,
            dry_run=True,
            state_db_path="/path/to/db",
        )

        assert ctx.storage is storage
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
        """@with_context with requires_storage should fail if DB doesn't exist."""

        @with_context(requires_storage=True)
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
        """@with_context with requires_storage should inject HybridStorage."""
        # Create a minimal database
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")  # Create empty file

        captured_ctx = None

        @with_context(requires_storage=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
            patch("gmailarchiver.cli.command_context.HybridStorage") as MockStorage,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            mock_db.initialize = AsyncMock()  # initialize is async
            mock_db.close = AsyncMock()  # close is async
            MockDB.return_value = mock_db
            mock_storage = MagicMock()
            MockStorage.return_value = mock_storage

            test_cmd(state_db=str(db_path))

        assert captured_ctx is not None
        assert captured_ctx.storage is mock_storage

    def test_requires_schema_version_check(self, tmp_path: Path) -> None:
        """@with_context with requires_schema should check version."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")

        @with_context(requires_storage=True, requires_schema="1.2")
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.SchemaManager") as MockSchemaManager,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
            patch("gmailarchiver.cli.command_context.HybridStorage") as MockStorage,
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
            patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail,
        ):
            mock_output = MagicMock(spec=OutputManager)
            # Add console attribute for UIBuilder (used by authenticate_gmail)
            mock_output.console = MagicMock()
            MockOutput.return_value = mock_output
            mock_gmail = MagicMock()
            mock_gmail._credentials = MagicMock()
            mock_gmail._authenticator = None
            MockGmail.create = AsyncMock(return_value=mock_gmail)

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
            patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail,
        ):
            mock_output = MagicMock(spec=OutputManager)
            # Add console attribute for UIBuilder (used by authenticate_gmail)
            mock_output.console = MagicMock()
            MockOutput.return_value = mock_output
            MockGmail.create = AsyncMock(side_effect=Exception("Auth failed"))

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

        @with_context(requires_storage=True)
        def test_cmd(ctx: CommandContext) -> None:
            pass

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
            patch("gmailarchiver.cli.command_context.HybridStorage") as MockStorage,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            mock_db.initialize = AsyncMock()  # initialize is async
            mock_db.close = AsyncMock()  # close is async
            MockDB.return_value = mock_db
            mock_storage = MagicMock()
            MockStorage.return_value = mock_storage

            test_cmd(state_db=str(db_path))

            mock_db.close.assert_called_once()

    def test_db_cleanup_on_exception(self, tmp_path: Path) -> None:
        """@with_context should close DB even on exception."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")

        @with_context(requires_storage=True)
        def test_cmd(ctx: CommandContext) -> None:
            raise ValueError("test error")

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("gmailarchiver.cli.command_context.DBManager") as MockDB,
            patch("gmailarchiver.cli.command_context.HybridStorage") as MockStorage,
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output
            mock_db = MagicMock()
            mock_db.initialize = AsyncMock()  # initialize is async
            mock_db.close = AsyncMock()  # close is async
            MockDB.return_value = mock_db
            mock_storage = MagicMock()
            MockStorage.return_value = mock_storage

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


# ============================================================================
# Coverage Improvement Tests - Authentication and Progress Methods
# ============================================================================


class TestCommandContextAuthenticateGmail:
    """Test CommandContext.authenticate_gmail() method."""

    def test_authenticate_gmail_success(self) -> None:
        """Test authenticate_gmail with successful authentication."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()  # UIBuilder needs console
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = ctx.authenticate_gmail()

        assert result is mock_gmail
        assert ctx.gmail is mock_gmail
        assert ctx._gmail_credentials is mock_gmail._credentials

    def test_authenticate_gmail_file_not_found_required(self) -> None:
        """Test authenticate_gmail raises when credentials not found (required=True)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=FileNotFoundError("Credentials not found"))
            with pytest.raises(typer.Exit) as exc_info:
                ctx.authenticate_gmail(required=True)

            assert exc_info.value.exit_code == 1

    def test_authenticate_gmail_file_not_found_optional(self) -> None:
        """Test authenticate_gmail returns None when credentials not found (required=False)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=FileNotFoundError("Credentials not found"))
            result = ctx.authenticate_gmail(required=False)

        assert result is None

    def test_authenticate_gmail_exception_required(self) -> None:
        """Test authenticate_gmail raises on auth exception (required=True)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=Exception("Auth error"))
            with pytest.raises(typer.Exit) as exc_info:
                ctx.authenticate_gmail(required=True)

            assert exc_info.value.exit_code == 1

    def test_authenticate_gmail_exception_optional(self) -> None:
        """Test authenticate_gmail returns None on exception (required=False)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=Exception("Auth error"))
            result = ctx.authenticate_gmail(required=False)

        assert result is None

    def test_authenticate_gmail_validate_deletion_scope_missing(self) -> None:
        """Test authenticate_gmail fails when deletion scope is missing."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_authenticator = MagicMock()
        mock_authenticator.validate_scopes.return_value = False
        mock_gmail._authenticator = mock_authenticator
        mock_gmail.close = AsyncMock()

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            with pytest.raises(typer.Exit) as exc_info:
                ctx.authenticate_gmail(validate_deletion_scope=True, required=True)

            assert exc_info.value.exit_code == 1

    def test_authenticate_gmail_validate_deletion_scope_optional(self) -> None:
        """Test authenticate_gmail returns None when deletion scope missing (required=False)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_authenticator = MagicMock()
        mock_authenticator.validate_scopes.return_value = False
        mock_gmail._authenticator = mock_authenticator
        mock_gmail.close = AsyncMock()

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = ctx.authenticate_gmail(validate_deletion_scope=True, required=False)

        assert result is None

    def test_authenticate_gmail_with_custom_credentials(self) -> None:
        """Test authenticate_gmail accepts custom credentials path."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = ctx.authenticate_gmail(credentials="/custom/path.json")

            MockGmail.create.assert_called_once_with(credentials_file="/custom/path.json")
            assert result is mock_gmail


class TestCommandContextAuthenticateGmailAsync:
    """Test CommandContext.authenticate_gmail_async() method."""

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_success(self) -> None:
        """Test authenticate_gmail_async with successful authentication."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = await ctx.authenticate_gmail_async()

        assert result is mock_gmail
        assert ctx.gmail is mock_gmail

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_file_not_found_required(self) -> None:
        """Test authenticate_gmail_async raises when credentials not found (required=True)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=FileNotFoundError("Not found"))
            with pytest.raises(typer.Exit) as exc_info:
                await ctx.authenticate_gmail_async(required=True)

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_file_not_found_optional(self) -> None:
        """Test authenticate_gmail_async returns None when creds not found."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=FileNotFoundError("Not found"))
            result = await ctx.authenticate_gmail_async(required=False)

        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_exception_required(self) -> None:
        """Test authenticate_gmail_async raises on exception (required=True)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=Exception("Auth error"))
            with pytest.raises(typer.Exit) as exc_info:
                await ctx.authenticate_gmail_async(required=True)

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_exception_optional(self) -> None:
        """Test authenticate_gmail_async returns None on exception (required=False)."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=Exception("Auth error"))
            result = await ctx.authenticate_gmail_async(required=False)

        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_validate_deletion_scope_missing(self) -> None:
        """Test authenticate_gmail_async fails when deletion scope is missing."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_authenticator = MagicMock()
        mock_authenticator.validate_scopes.return_value = False
        mock_gmail._authenticator = mock_authenticator
        mock_gmail.close = AsyncMock()

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            with pytest.raises(typer.Exit) as exc_info:
                await ctx.authenticate_gmail_async(validate_deletion_scope=True, required=True)

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_validate_deletion_scope_optional(self) -> None:
        """Test authenticate_gmail_async returns None when deletion scope missing."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_authenticator = MagicMock()
        mock_authenticator.validate_scopes.return_value = False
        mock_gmail._authenticator = mock_authenticator
        mock_gmail.close = AsyncMock()

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = await ctx.authenticate_gmail_async(
                validate_deletion_scope=True, required=False
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_gmail_async_with_custom_credentials(self) -> None:
        """Test authenticate_gmail_async accepts custom credentials path."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            result = await ctx.authenticate_gmail_async(credentials="/custom/path.json")

            MockGmail.create.assert_called_once_with(credentials_file="/custom/path.json")
            assert result is mock_gmail


class TestCommandContextGmailSessionContextManager:
    """Test CommandContext.gmail_session() async context manager."""

    @pytest.mark.asyncio
    async def test_gmail_session_success(self) -> None:
        """Test gmail_session context manager authenticates and yields client."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None
        mock_gmail.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail.__aexit__ = AsyncMock(return_value=None)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            async with ctx.gmail_session() as gmail:
                assert gmail is mock_gmail

    @pytest.mark.asyncio
    async def test_gmail_session_file_not_found(self) -> None:
        """Test gmail_session fails if credentials not found."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=FileNotFoundError("Not found"))
            with pytest.raises(typer.Exit) as exc_info:
                async with ctx.gmail_session():
                    pass

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_gmail_session_auth_exception(self) -> None:
        """Test gmail_session fails on auth exception."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(side_effect=Exception("Auth error"))
            with pytest.raises(typer.Exit) as exc_info:
                async with ctx.gmail_session():
                    pass

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_gmail_session_validate_deletion_scope_missing(self) -> None:
        """Test gmail_session fails when deletion scope is missing."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_authenticator = MagicMock()
        mock_authenticator.validate_scopes.return_value = False
        mock_gmail._authenticator = mock_authenticator
        mock_gmail.close = AsyncMock()

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            with pytest.raises(typer.Exit) as exc_info:
                async with ctx.gmail_session(validate_deletion_scope=True):
                    pass

            assert exc_info.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_gmail_session_with_custom_credentials(self) -> None:
        """Test gmail_session accepts custom credentials path."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_gmail._credentials = MagicMock()
        mock_gmail._authenticator = None
        mock_gmail.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail.__aexit__ = AsyncMock(return_value=None)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            async with ctx.gmail_session(credentials="/custom/path.json") as gmail:
                assert gmail is mock_gmail
                MockGmail.create.assert_called_once_with(credentials_file="/custom/path.json")

    @pytest.mark.asyncio
    async def test_gmail_session_stores_credentials_and_client(self) -> None:
        """Test gmail_session stores credentials in context."""
        output = MagicMock(spec=OutputManager)
        output.console = MagicMock()
        ctx = CommandContext(output=output)

        mock_gmail = MagicMock()
        mock_credentials = MagicMock()
        mock_gmail._credentials = mock_credentials
        mock_gmail._authenticator = None
        mock_gmail.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail.__aexit__ = AsyncMock(return_value=None)

        with patch("gmailarchiver.cli.command_context.GmailClient") as MockGmail:
            MockGmail.create = AsyncMock(return_value=mock_gmail)
            async with ctx.gmail_session():
                assert ctx.gmail is mock_gmail
                assert ctx._gmail_credentials is mock_credentials


class TestCommandContextProgressMethods:
    """Test CommandContext progress tracking methods."""

    def test_set_progress_total_with_handle(self) -> None:
        """Test set_progress_total updates operation handle."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.set_progress_total(100, "new description")

        mock_handle.set_total.assert_called_once_with(100, "new description")

    def test_set_progress_total_without_handle(self) -> None:
        """Test set_progress_total does nothing without operation handle."""
        output = OutputManager()
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        # Should not raise
        ctx.set_progress_total(100)

    def test_advance_progress_with_handle(self) -> None:
        """Test advance_progress updates operation handle."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.advance_progress(5)

        mock_handle.update_progress.assert_called_once_with(5)

    def test_advance_progress_without_handle(self) -> None:
        """Test advance_progress does nothing without operation handle."""
        output = OutputManager()
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        # Should not raise
        ctx.advance_progress(5)

    def test_advance_progress_default(self) -> None:
        """Test advance_progress defaults to 1."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.advance_progress()

        mock_handle.update_progress.assert_called_once_with(1)

    def test_log_progress_with_handle(self) -> None:
        """Test log_progress logs to operation handle."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.log_progress("Processing item", "INFO")

        mock_handle.log.assert_called_once_with("Processing item", "INFO")

    def test_log_progress_without_handle_info(self) -> None:
        """Test log_progress falls back to output.info when no handle."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        ctx.log_progress("message", "INFO")

        output.info.assert_called_once_with("message")

    def test_log_progress_without_handle_warning(self) -> None:
        """Test log_progress falls back to output.warning."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        ctx.log_progress("warning", "WARNING")

        output.warning.assert_called_once_with("warning")

    def test_log_progress_without_handle_error(self) -> None:
        """Test log_progress falls back to output.error."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        ctx.log_progress("error", "ERROR")

        output.error.assert_called_once_with("error", exit_code=0)

    def test_log_progress_without_handle_success(self) -> None:
        """Test log_progress falls back to output.success."""
        output = MagicMock(spec=OutputManager)
        ctx = CommandContext(output=output)
        ctx.operation_handle = None

        ctx.log_progress("success", "SUCCESS")

        output.success.assert_called_once_with("success")


class TestCommandContextUIBuilder:
    """Test CommandContext.ui property."""

    def test_ui_builder_lazy_initialization(self) -> None:
        """Test ui builder is lazily initialized."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        assert ctx._ui_builder is None
        ui = ctx.ui
        assert ui is not None
        assert ctx._ui_builder is not None

    def test_ui_builder_returns_same_instance(self) -> None:
        """Test ui property returns same instance on subsequent calls."""
        output = OutputManager()
        ctx = CommandContext(output=output)

        ui1 = ctx.ui
        ui2 = ctx.ui

        assert ui1 is ui2

    def test_ui_builder_respects_json_mode(self) -> None:
        """Test ui builder is created with json_mode from context."""
        output = OutputManager(json_mode=True)
        ctx = CommandContext(output=output, json_mode=True)

        ui = ctx.ui
        assert ui is not None


class TestStaticOperationHandleSetTotalWithExistingTask:
    """Test _StaticOperationHandle.set_total() when task already exists."""

    def test_set_total_updates_existing_task(self) -> None:
        """Test set_total updates existing task when task_id is set."""
        output = MagicMock(spec=OutputManager)
        progress = MagicMock()
        progress.add_task.return_value = "task123"

        # Create handle with initial total
        handle = _StaticOperationHandle(output, progress, "test", 10)
        # This should create a task
        assert handle._task_id == "task123"

        # Now update with new total
        handle.set_total(50, "new description")

        # Should call update, not add_task again
        progress.update.assert_called_once_with(
            "task123",
            total=50,
            description="new description",
            refresh=True,
        )

    def test_set_total_updates_description_only(self) -> None:
        """Test set_total updates task with new description."""
        output = MagicMock(spec=OutputManager)
        progress = MagicMock()
        progress.add_task.return_value = "task_id"

        handle = _StaticOperationHandle(output, progress, "initial", 100)
        handle.set_total(100, "updated description")

        progress.update.assert_called_once_with(
            "task_id",
            total=100,
            description="updated description",
            refresh=True,
        )


class TestWithContextDecoratorOptionsReinjection:
    """Test @with_context decorator re-injecting options to function signature."""

    def test_reinjection_of_json_output_parameter(self) -> None:
        """Test json_output is re-added to kwargs when function expects it."""
        captured_kwargs = {}

        @with_context()
        def test_cmd(ctx: CommandContext, json_output: bool = False) -> None:
            nonlocal captured_kwargs
            captured_kwargs = {"json_output": json_output}

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(json_output=True)

        assert captured_kwargs["json_output"] is True

    def test_reinjection_of_dry_run_parameter(self) -> None:
        """Test dry_run is re-added to kwargs when function expects it."""
        captured_kwargs = {}

        @with_context()
        def test_cmd(ctx: CommandContext, dry_run: bool = False) -> None:
            nonlocal captured_kwargs
            captured_kwargs = {"dry_run": dry_run}

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(dry_run=True)

        assert captured_kwargs["dry_run"] is True

    def test_reinjection_of_state_db_parameter(self) -> None:
        """Test state_db is re-added to kwargs when function expects it."""
        captured_kwargs = {}

        @with_context()
        def test_cmd(ctx: CommandContext, state_db: str = "default.db") -> None:
            nonlocal captured_kwargs
            captured_kwargs = {"state_db": state_db}

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(state_db="/custom/db.db")

        assert captured_kwargs["state_db"] == "/custom/db.db"

    def test_reinjection_of_credentials_parameter(self) -> None:
        """Test credentials is re-added to kwargs when function expects it."""
        captured_kwargs = {}

        @with_context()
        def test_cmd(ctx: CommandContext, credentials: str | None = None) -> None:
            nonlocal captured_kwargs
            captured_kwargs = {"credentials": credentials}

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(credentials="/path/to/creds.json")

        assert captured_kwargs["credentials"] == "/path/to/creds.json"

    def test_reinjection_of_all_options(self) -> None:
        """Test all options are re-added when function expects them."""
        captured_kwargs = {}

        @with_context()
        def test_cmd(
            ctx: CommandContext,
            json_output: bool = False,
            dry_run: bool = False,
            state_db: str = "default.db",
            credentials: str | None = None,
        ) -> None:
            nonlocal captured_kwargs
            captured_kwargs = {
                "json_output": json_output,
                "dry_run": dry_run,
                "state_db": state_db,
                "credentials": credentials,
            }

        with patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput:
            MockOutput.return_value = MagicMock(spec=OutputManager)
            test_cmd(
                json_output=True,
                dry_run=True,
                state_db="/custom.db",
                credentials="/custom_creds.json",
            )

        assert captured_kwargs["json_output"] is True
        assert captured_kwargs["dry_run"] is True
        assert captured_kwargs["state_db"] == "/custom.db"
        assert captured_kwargs["credentials"] == "/custom_creds.json"


class TestWithContextDecoratorLiveMode:
    """Test @with_context decorator with live progress mode."""

    def test_live_mode_with_progress_and_tty(self) -> None:
        """Test decorator uses live mode when has_progress=True and isatty()=True."""
        captured_ctx = None

        @with_context(has_progress=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("sys.stdout.isatty", return_value=True) as mock_isatty,
        ):
            mock_output = MagicMock(spec=OutputManager)
            mock_output.live_layout_context = MagicMock()
            mock_output.live_layout_context.return_value.__enter__ = MagicMock(
                return_value=MagicMock()
            )
            mock_output.live_layout_context.return_value.__exit__ = MagicMock(return_value=None)
            MockOutput.return_value = mock_output

            test_cmd()

        # live_layout_context should have been called
        mock_output.live_layout_context.assert_called_once()
        assert captured_ctx is not None
        assert captured_ctx._live_context is not None

    def test_live_mode_not_used_without_tty(self) -> None:
        """Test decorator does not use live mode when isatty()=False."""
        captured_ctx = None

        @with_context(has_progress=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("sys.stdout.isatty", return_value=False),
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            test_cmd()

        # live_layout_context should NOT have been called
        mock_output.live_layout_context.assert_not_called()
        assert captured_ctx is not None
        assert captured_ctx._live_context is None

    def test_live_mode_not_used_with_json_output(self) -> None:
        """Test decorator does not use live mode when json_output=True."""
        captured_ctx = None

        @with_context(has_progress=True)
        def test_cmd(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        with (
            patch("gmailarchiver.cli.command_context.OutputManager") as MockOutput,
            patch("sys.stdout.isatty", return_value=True),
        ):
            mock_output = MagicMock(spec=OutputManager)
            MockOutput.return_value = mock_output

            test_cmd(json_output=True)

        # live_layout_context should NOT have been called (json_output takes priority)
        mock_output.live_layout_context.assert_not_called()
        assert captured_ctx is not None
        # JSON mode should still be enabled
        assert captured_ctx.json_mode is True
