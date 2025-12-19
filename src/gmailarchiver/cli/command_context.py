"""Command infrastructure for unified CLI command structure.

Provides:
- CommandContext: Unified context dataclass for all commands
- @with_context: Decorator that handles command boilerplate

This module standardizes CLI command structure, eliminating boilerplate
and ensuring consistent user experience across all 34 commands.

Example:
    @app.command()
    @with_context(requires_db=True, has_progress=True)
    def validate(ctx: CommandContext, archive_file: str) -> None:
        if not Path(archive_file).exists():
            ctx.fail_and_exit("File Not Found", f"Archive not found: {archive_file}")

        with ctx.operation("Validating archive"):
            ctx.set_progress_total(4)
            # ... validation steps ...
            ctx.advance_progress(1)

        ctx.success("Validation complete")
"""

import asyncio
import functools
import inspect
import logging
import sys
import traceback
from collections.abc import AsyncIterator, Callable, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, ParamSpec, TypeVar

import typer

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.data.schema_manager import (
    SchemaManager,
    SchemaVersion,
    SchemaVersionError,
)

from .output import OperationHandle, OutputManager
from .ui import UIBuilder, UIBuilderImpl

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class CommandContext:
    """Unified context for all CLI commands.

    Provides a consistent interface for:
    - Output (info, warning, success, error messages)
    - Progress tracking (operations, progress bars)
    - Data access (storage layer, Gmail client)
    - Error handling (fail_and_exit with suggestions)

    Attributes:
        output: OutputManager instance for all output operations
        operation_handle: Current operation handle (if has_progress=True)
        storage: HybridStorage instance (if requires_storage=True)
        gmail: GmailClient instance (if requires_gmail=True)
        json_mode: Whether JSON output is enabled
        dry_run: Whether dry-run mode is enabled
        state_db_path: Path to the state database
    """

    output: OutputManager
    operation_handle: OperationHandle | None = None
    storage: HybridStorage | None = None
    gmail: GmailClient | None = None
    json_mode: bool = False
    dry_run: bool = False
    state_db_path: str = "archive_state.db"
    _operation_name: str | None = field(default=None, repr=False)
    _live_context: Any = field(default=None, repr=False)
    _ui_builder: UIBuilder | None = field(default=None, repr=False)
    _gmail_credentials: Any = field(default=None, repr=False)

    # ==================== OUTPUT METHODS ====================

    def info(self, message: str) -> None:
        """Show informational message.

        Args:
            message: Info message to display
        """
        self.output.info(message)

    def warning(self, message: str) -> None:
        """Show warning message.

        Args:
            message: Warning message to display
        """
        self.output.warning(message)

    def success(self, message: str) -> None:
        """Show success message.

        Args:
            message: Success message to display
        """
        self.output.success(message)

    def error(self, message: str) -> None:
        """Show non-fatal error message.

        For fatal errors that should exit, use fail_and_exit().

        Args:
            message: Error message to display
        """
        self.output.error(message, exit_code=0)

    # ==================== UI BUILDER ====================

    @property
    def ui(self) -> UIBuilder:
        """Access the fluent UI builder for task sequences and spinners.

        Returns lazily-initialized UIBuilder for declarative UI construction.

        Example:
            with ctx.ui.task_sequence() as seq:
                with seq.task("Counting messages") as t:
                    count = count_messages(file)
                    t.complete(f"Found {count:,} messages")

                with seq.task("Importing messages", total=count) as t:
                    for msg in messages:
                        process(msg)
                        t.advance()
                    t.complete(f"Imported {count:,} messages")

        Returns:
            UIBuilder instance for fluent UI construction
        """
        if self._ui_builder is None:
            self._ui_builder = UIBuilderImpl(
                console=self.output.console,
                json_mode=self.json_mode,
            )
        return self._ui_builder

    # ==================== AUTHENTICATION ====================

    def authenticate_gmail(
        self,
        credentials: str | None = None,
        required: bool = True,
        validate_deletion_scope: bool = False,
    ) -> GmailClient | None:
        """Authenticate with Gmail using GmailClient.create() factory.

        Uses the GmailClient.create() factory method which handles OAuth2
        authentication automatically. Shows spinner UI during auth.

        Note: This is a sync wrapper for use in sync command contexts. For async
        code, use authenticate_gmail_async() or gmail_session() instead.

        Args:
            credentials: Optional custom OAuth2 credentials file path.
                        If None (default), uses bundled app credentials.
            required: If True (default), calls fail_and_exit on auth failure.
                     If False, returns None on failure.
            validate_deletion_scope: If True, validates that credentials have
                                    deletion permission (https://mail.google.com/).
                                    Used by delete/trash operations.

        Returns:
            GmailClient instance on success, None on failure (if required=False)

        Raises:
            typer.Exit: If required=True and authentication/validation fails

        Example:
            # Required auth (exits on failure)
            gmail = ctx.authenticate_gmail()

            # Optional auth (returns None on failure)
            gmail = ctx.authenticate_gmail(required=False)
            if gmail is None:
                ctx.warning("Continuing without Gmail access")

            # Auth with deletion permission validation
            gmail = ctx.authenticate_gmail(validate_deletion_scope=True)
        """
        with self.ui.spinner("Authenticating with Gmail") as task:
            try:
                gmail = asyncio.run(GmailClient.create(credentials_file=credentials))

                # Validate deletion scope if requested
                if validate_deletion_scope and gmail._authenticator:
                    if not gmail._authenticator.validate_scopes(["https://mail.google.com/"]):
                        task.fail("Missing deletion permission")
                        asyncio.run(gmail.close())
                        if required:
                            self.fail_and_exit(
                                "Missing deletion permission",
                                "Your current authorization doesn't include "
                                "permission to delete messages",
                                details=[
                                    "This was likely caused by using an older version of the app",
                                ],
                                suggestion="Run 'gmailarchiver auth-reset' then retry",
                            )
                        return None

                self.gmail = gmail
                self._gmail_credentials = gmail._credentials
                task.complete("Connected")
                return gmail
            except FileNotFoundError as e:
                task.fail("Credentials not found")
                if required:
                    self.fail_and_exit(
                        "Credentials Not Found",
                        str(e),
                        suggestion="Reinstall the application or provide --credentials",
                    )
                return None
            except Exception as e:
                task.fail("Authentication failed")
                if required:
                    self.fail_and_exit(
                        "Authentication Failed",
                        f"Failed to authenticate with Gmail: {e}",
                        suggestion="Run 'gmailarchiver auth-reset' and try again",
                    )
                return None

    async def authenticate_gmail_async(
        self,
        credentials: str | None = None,
        required: bool = True,
        validate_deletion_scope: bool = False,
    ) -> GmailClient | None:
        """Async version of authenticate_gmail for use inside async workflows.

        Uses GmailClient.create() factory method which handles authentication
        automatically. Use this instead of authenticate_gmail() when calling
        from within an async function that's already running in an event loop.

        Args:
            credentials: Optional custom OAuth2 credentials file path.
            required: If True (default), calls fail_and_exit on auth failure.
            validate_deletion_scope: If True, validates deletion permission.

        Returns:
            GmailClient instance on success, None on failure (if required=False)
        """
        with self.ui.spinner("Authenticating with Gmail") as task:
            try:
                gmail = await GmailClient.create(credentials_file=credentials)

                # Validate deletion scope if requested
                if validate_deletion_scope and gmail._authenticator:
                    if not gmail._authenticator.validate_scopes(["https://mail.google.com/"]):
                        task.fail("Missing deletion permission")
                        await gmail.close()
                        if required:
                            self.fail_and_exit(
                                "Missing deletion permission",
                                "Your current authorization doesn't include "
                                "permission to delete messages",
                                details=[
                                    "This was likely caused by using an older version of the app",
                                ],
                                suggestion="Run 'gmailarchiver auth-reset' then retry",
                            )
                        return None

                self.gmail = gmail
                self._gmail_credentials = gmail._credentials
                task.complete("Connected")
                return gmail
            except FileNotFoundError as e:
                task.fail("Credentials not found")
                if required:
                    self.fail_and_exit(
                        "Credentials Not Found",
                        str(e),
                        suggestion="Reinstall the application or provide --credentials",
                    )
                return None
            except Exception as e:
                task.fail("Authentication failed")
                if required:
                    self.fail_and_exit(
                        "Authentication Failed",
                        f"Failed to authenticate with Gmail: {e}",
                        suggestion="Run 'gmailarchiver auth-reset' and try again",
                    )
                return None

    @asynccontextmanager
    async def gmail_session(
        self,
        credentials: str | None = None,
        validate_deletion_scope: bool = False,
    ) -> AsyncIterator[GmailClient]:
        """Async context manager for Gmail client with proper lifecycle management.

        This is the preferred way to use GmailClient - it ensures proper
        initialization and cleanup of the HTTP client using async with.

        Uses GmailClient.create() factory method which handles authentication
        automatically.

        Args:
            credentials: Path to credentials file (uses bundled if None)
            validate_deletion_scope: Require deletion permission

        Yields:
            Initialized GmailClient ready for API calls

        Raises:
            typer.Exit: If authentication fails

        Example:
            async with ctx.gmail_session() as gmail:
                async for msg in gmail.list_messages("before:2022/01/01"):
                    print(msg["id"])
        """
        with self.ui.spinner("Authenticating with Gmail") as task:
            try:
                client = await GmailClient.create(credentials_file=credentials)
                task.complete("Connected")
            except FileNotFoundError as e:
                task.fail("Credentials not found")
                self.fail_and_exit(
                    "Credentials Not Found",
                    str(e),
                    suggestion="Reinstall the application or provide --credentials",
                )
            except Exception as e:
                task.fail("Authentication failed")
                self.fail_and_exit(
                    "Authentication Failed",
                    f"Failed to authenticate with Gmail: {e}",
                    suggestion="Run 'gmailarchiver auth-reset' and try again",
                )

        # Validate deletion scope if requested
        if validate_deletion_scope and client._authenticator:
            if not client._authenticator.validate_scopes(["https://mail.google.com/"]):
                await client.close()
                self.fail_and_exit(
                    "Missing deletion permission",
                    "Your current authorization doesn't include permission to delete messages",
                    details=["This was likely caused by using an older version of the app"],
                    suggestion="Run 'gmailarchiver auth-reset' then retry",
                )

        # Store for potential reuse
        self.gmail = client
        self._gmail_credentials = client._credentials

        async with client:
            yield client

    # ==================== PROGRESS METHODS ====================

    @contextmanager
    def operation(
        self, description: str, total: int | None = None
    ) -> Generator[OperationHandle | _StaticOperationHandle]:
        """Context manager for tracked operations with progress.

        Use this to wrap long-running operations that benefit from
        progress tracking.

        Args:
            description: Description of the operation
            total: Total number of items (if known)

        Yields:
            OperationHandle for progress updates

        Example:
            with ctx.operation("Processing files", total=100) as op:
                for i, file in enumerate(files):
                    process(file)
                    ctx.advance_progress(1)
        """
        if self._live_context is not None:
            # Use live output handler
            handle = self._live_context.start_operation(description, total=total)
            self.operation_handle = handle
            try:
                yield handle
            finally:
                self.operation_handle = None
        else:
            # Fallback to static output
            self.output.start_operation(self._operation_name or "operation", description)
            with self.output.progress_context(description, total=total) as progress:
                # Create a simple handle wrapper
                handle = _StaticOperationHandle(self.output, progress, description, total)
                self.operation_handle = handle
                try:
                    yield handle
                finally:
                    self.operation_handle = None

    def set_progress_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking.

        Call this when the total becomes known after starting an operation.

        Args:
            total: Total number of items to process
            description: Optional new description for progress bar
        """
        if self.operation_handle is not None:
            self.operation_handle.set_total(total, description)

    def advance_progress(self, n: int = 1) -> None:
        """Advance progress counter.

        Args:
            n: Number of units to advance (default: 1)
        """
        if self.operation_handle is not None:
            self.operation_handle.update_progress(n)

    def log_progress(self, message: str, level: str = "INFO") -> None:
        """Log a message within the current operation.

        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        if self.operation_handle is not None:
            self.operation_handle.log(message, level)
        else:
            # Fallback to output
            if level == "WARNING":
                self.warning(message)
            elif level == "ERROR":
                self.error(message)
            elif level == "SUCCESS":
                self.success(message)
            else:
                self.info(message)

    # ==================== DISPLAY METHODS ====================

    def show_report(
        self,
        title: str,
        data: dict[str, Any] | Sequence[dict[str, Any]],
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Display a report table or summary.

        Args:
            title: Report title
            data: Data to display (dict for key-value, list for table)
            summary: Optional summary data shown below table
        """
        self.output.show_report(title, data, summary)

    def show_table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        """Display tabular data.

        Args:
            title: Table title
            headers: Column headers
            rows: Table rows
        """
        self.output.show_table(title, headers, rows)

    def suggest_next_steps(self, suggestions: Sequence[str]) -> None:
        """Show actionable next steps.

        Args:
            suggestions: List of suggested commands or actions
        """
        self.output.suggest_next_steps(suggestions)

    # ==================== ERROR HANDLING ====================

    def fail_and_exit(
        self,
        title: str,
        message: str,
        suggestion: str | None = None,
        details: Sequence[str] | None = None,
        exit_code: int = 1,
    ) -> NoReturn:
        """Show error panel and exit.

        Use this for fatal errors that should stop execution.

        Args:
            title: Error panel title
            message: Main error message
            suggestion: Optional suggested fix
            details: Optional list of detail lines
            exit_code: Exit code (default: 1)

        Raises:
            typer.Exit: Always raises to exit the command
        """
        self.output.show_error_panel(
            title=title,
            message=message,
            suggestion=suggestion,
            details=details,
            exit_code=0,  # Don't let OutputManager exit
        )
        raise typer.Exit(exit_code)


class _StaticOperationHandle:
    """Simple operation handle for static output mode."""

    def __init__(
        self,
        output: OutputManager,
        progress: Any,
        description: str,
        total: int | None,
    ) -> None:
        self._output = output
        self._progress = progress
        self._description = description
        self._total = total
        self._task_id: Any = None
        if progress and total:
            self._task_id = progress.add_task(description, total=total)

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message."""
        if level == "WARNING":
            self._output.warning(message)
        elif level == "ERROR":
            self._output.error(message, exit_code=0)
        elif level == "SUCCESS":
            self._output.success(message)
        else:
            self._output.info(message)

    def update_progress(self, advance: int = 1) -> None:
        """Advance progress."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, advance=advance, refresh=True)

    def set_status(self, status: str) -> None:
        """Update status text."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=status, refresh=True)

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking."""
        self._total = total
        if self._progress:
            if self._task_id is None:
                self._task_id = self._progress.add_task(
                    description or self._description, total=total
                )
            else:
                self._progress.update(
                    self._task_id,
                    total=total,
                    description=description or self._description,
                    refresh=True,
                )

    def succeed(self, message: str) -> None:
        """Mark operation as successful."""
        self._output.success(message)

    def fail(self, message: str) -> None:
        """Mark operation as failed."""
        self._output.error(message, exit_code=0)

    def complete_pending(self, final_message: str, level: str = "SUCCESS") -> None:
        """Complete a pending log entry."""
        self.log(final_message, level)


def with_context(
    requires_storage: bool = False,
    requires_gmail: bool = False,
    requires_schema: str | None = None,
    has_progress: bool = False,
    operation_name: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that provides CommandContext to commands.

    Handles all common boilerplate:
    - TTY detection for output mode selection
    - OutputManager initialization
    - HybridStorage initialization (if requires_storage=True)
    - GmailClient initialization (if requires_gmail=True)
    - Schema version checking (if requires_schema is set)
    - Exception handling with user-friendly messages
    - Resource cleanup

    Args:
        requires_storage: Initialize HybridStorage and inject as ctx.storage
        requires_gmail: Initialize GmailClient and inject as ctx.gmail
        requires_schema: Minimum schema version required (e.g., "1.2")
        has_progress: Enable progress tracking via live output
        operation_name: Default operation name for progress tracking

    Returns:
        Decorator function

    Example:
        @app.command()
        @with_context(requires_storage=True, has_progress=True)
        def validate(ctx: CommandContext, archive_file: str) -> None:
            ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        # Get the original function's signature and remove 'ctx' parameter
        # This is necessary because Typer introspects the function signature
        # to determine CLI parameters, and we inject 'ctx' programmatically
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        param_names = {p.name for p in params}
        new_params = [p for p in params if p.name != "ctx"]
        new_sig = sig.replace(parameters=new_params)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Extract common options from kwargs with explicit types
            # Pop these values as we handle them in the decorator
            json_output: bool = bool(kwargs.pop("json_output", False))
            dry_run: bool = bool(kwargs.pop("dry_run", False))
            state_db: str = str(kwargs.pop("state_db", "archive_state.db"))
            credentials: str | None = kwargs.pop("credentials", None)  # type: ignore[assignment]

            # Re-add options that the function expects in its signature
            if "json_output" in param_names:
                kwargs["json_output"] = json_output
            if "dry_run" in param_names:
                kwargs["dry_run"] = dry_run
            if "state_db" in param_names:
                kwargs["state_db"] = state_db
            if "credentials" in param_names:
                kwargs["credentials"] = credentials

            # Detect TTY mode for output
            use_live_mode = has_progress and not json_output and sys.stdout.isatty()

            # Initialize OutputManager
            output = OutputManager(
                json_mode=json_output,
                live_mode=use_live_mode,
            )

            # Create context
            ctx = CommandContext(
                output=output,
                json_mode=json_output,
                dry_run=dry_run,
                state_db_path=str(state_db),
                _operation_name=operation_name or func.__name__,
            )

            db: DBManager | None = None
            storage: HybridStorage | None = None

            try:
                # Initialize storage if required
                if requires_storage:
                    db_path = Path(state_db)
                    if not db_path.exists():
                        ctx.fail_and_exit(
                            "Database Not Found",
                            f"State database not found: {state_db}",
                            suggestion="Run 'gmailarchiver archive' or 'import' first",
                        )
                    # Use SchemaManager for version checking
                    schema_mgr = SchemaManager(db_path)

                    # Check schema version if required
                    if requires_schema:
                        required_version = SchemaVersion.from_string(requires_schema)
                        try:
                            asyncio.run(schema_mgr.require_version(required_version))
                        except SchemaVersionError as e:
                            ctx.fail_and_exit(
                                "Schema Version Mismatch",
                                str(e),
                                suggestion=e.suggestion,
                            )

                    # Initialize DBManager (skip validation since SchemaManager already checked)
                    db = DBManager(str(db_path), validate_schema=False)
                    asyncio.run(db.initialize())

                    # Pass the detected schema version to DBManager
                    # (since validate_schema=False means it won't detect itself)
                    if schema_mgr._cached_version is not None:
                        db.schema_version = schema_mgr._cached_version.value

                    # Wrap DBManager with HybridStorage
                    # Only preload RFC IDs if we've validated the schema supports it (v1.1+)
                    # This prevents failures when schema check hasn't run yet
                    preload_rfc_ids = requires_schema is not None
                    storage = HybridStorage(db, preload_rfc_ids=preload_rfc_ids)
                    ctx.storage = storage

                # Initialize Gmail client if required (uses spinner UI)
                if requires_gmail:
                    ctx.authenticate_gmail(credentials=credentials)

                # Set up live context if using progress
                if use_live_mode:
                    with output.live_layout_context() as live_ctx:
                        ctx._live_context = live_ctx
                        return func(ctx, *args, **kwargs)  # type: ignore[arg-type]
                else:
                    return func(ctx, *args, **kwargs)  # type: ignore[arg-type]

            except typer.Exit:
                # Re-raise typer exits (from fail_and_exit)
                raise
            except KeyboardInterrupt:
                ctx.warning("\nOperation cancelled by user")
                raise typer.Exit(130)
            except Exception as e:
                # Log full traceback for debugging
                logger.exception("Unexpected error in command")
                ctx.fail_and_exit(
                    "Unexpected Error",
                    str(e),
                    suggestion="Check the logs for more details or report this issue",
                    details=[traceback.format_exc().split("\n")[-2]],
                )
            finally:
                # Flush JSON output if in JSON mode
                if json_output:
                    output.end_operation(success=True)

                # Cleanup Gmail client if initialized
                if ctx.gmail is not None:
                    try:
                        asyncio.run(ctx.gmail.close())
                    except Exception:
                        pass

                # Cleanup resources
                # Note: HybridStorage doesn't own the DBManager connection,
                # so we close the underlying DBManager directly
                if db is not None:
                    try:
                        asyncio.run(db.close())
                    except Exception:
                        pass

        # Apply the new signature (without ctx) to the wrapper
        # This prevents Typer from seeing 'ctx' as a CLI parameter
        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]

        # Also remove 'ctx' from annotations so Typer doesn't try to parse it
        if hasattr(wrapper, "__annotations__"):
            wrapper.__annotations__ = {k: v for k, v in func.__annotations__.items() if k != "ctx"}

        return wrapper

    return decorator
