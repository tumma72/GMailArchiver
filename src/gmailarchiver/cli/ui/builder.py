"""UI Builder for live progress components.

This module provides the UIBuilder and TaskSequence implementations for
creating live, updating UI components like spinners and progress bars.

Design: See docs/UI_UX_CLI.md for complete UI/UX guidelines.

Example usage:
    with ctx.ui.task_sequence() as seq:
        with seq.task("Counting messages") as t:
            count = importer.count_messages(file)
            t.complete(f"Found {count:,} messages")

        with seq.task("Importing messages", total=count) as t:
            for msg in messages:
                process(msg)
                t.advance()
            t.complete(f"Imported {count:,} messages")

REFACTORED: Now uses composable widgets from gmailarchiver.cli.ui.widgets.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from rich.console import Console, Group
from rich.live import Live

# Import widgets - now the source of truth for task and log rendering
from gmailarchiver.cli.ui.widgets.log_window import LogLevel, LogWindowWidget
from gmailarchiver.cli.ui.widgets.task import (
    SPINNER_FRAMES,
    TaskStatus,
    TaskWidget,
)

# Default max visible logs in the log window
DEFAULT_MAX_LOGS = 10


# =============================================================================
# Implementation Classes
# =============================================================================


class TaskHandleImpl:
    """Implementation of TaskHandle for controlling a single task.

    REFACTORED: Now wraps a TaskWidget for state management and rendering.
    """

    def __init__(
        self,
        widget: TaskWidget,
        sequence: TaskSequenceImpl,
    ) -> None:
        """Initialize with a TaskWidget and parent sequence.

        Args:
            widget: The TaskWidget managing task state and rendering
            sequence: Parent TaskSequenceImpl for refresh coordination
        """
        self._widget = widget
        self._sequence = sequence

    def complete(self, message: str) -> None:
        """Mark task as successfully completed."""
        self._widget.complete(message)
        self._sequence._refresh()

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed."""
        self._widget.fail(message, reason)
        self._sequence._refresh()

    def advance(self, n: int = 1) -> None:
        """Advance progress counter."""
        self._widget.advance(n)
        self._sequence._refresh()

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking.

        Args:
            total: Total number of items to process
            description: Optional new description for the task
        """
        self._widget.total = total
        if description:
            self._widget.description = description
        self._sequence._refresh()

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context."""
        self._sequence._log(message, level)

    def warn(self, message: str) -> None:
        """Mark task as completed with warning status."""
        self._widget.warn(message)
        self._sequence._refresh()

    # OperationHandle compatibility methods (for archiver.py integration)

    def update_progress(self, advance: int = 1) -> None:
        """Advance progress counter (OperationHandle compatibility)."""
        self.advance(advance)

    def set_status(self, status: str) -> None:
        """Update task description (OperationHandle compatibility)."""
        self._widget.description = status
        self._sequence._refresh()

    def succeed(self, message: str) -> None:
        """Mark task as successful (OperationHandle compatibility)."""
        self.complete(message)

    def complete_pending(self, final_message: str, level: str = "SUCCESS") -> None:
        """Complete a pending log entry (OperationHandle compatibility)."""
        self.log(final_message, level)


class TaskSequenceImpl:
    """Implementation of TaskSequence that manages Rich Live context.

    REFACTORED: Now uses TaskWidget and LogWindowWidget for rendering.

    This class owns a single Rich Live context and manages all task
    rendering within it. This solves the flickering bug by having
    a single point of refresh control.

    Supports an optional log window that shows recent activity messages
    below the task list (for operations like archive that stream updates).

    IMPORTANT: Implements __rich__() so Rich Live re-evaluates the renderable
    on each auto-refresh cycle, enabling spinner animation during async waits.
    """

    def __init__(
        self,
        console: Console | None,
        json_mode: bool = False,
        title: str | None = None,
        show_logs: bool = False,
        max_logs: int = DEFAULT_MAX_LOGS,
    ) -> None:
        self._console = console
        self._json_mode = json_mode
        self._title = title
        self._show_logs = show_logs
        self._max_logs = max_logs

        # Task widgets (replaces _tasks list of TaskState)
        self._task_widgets: list[TaskWidget] = []

        # Log window widget (replaces _visible_logs deque)
        self._log_window = LogWindowWidget(max_size=max_logs, show_separator=True)

        # All logs for JSON mode
        self._logs: list[tuple[str, str]] = []
        self._json_events: list[dict[str, Any]] = []

        # Live display state
        self._live: Live | None = None
        self._animation_frame: int = 0
        self._last_refresh: float = 0

    def __rich__(self) -> Group:
        """Rich protocol: Return renderable for Live auto-refresh.

        This method is called by Rich Live on each refresh cycle (10fps),
        allowing spinner animation to update even during async waits.
        """
        return self._render()

    def __enter__(self) -> TaskSequenceImpl:
        """Enter the task sequence context."""
        if not self._json_mode and self._console:
            # Pass self (implements __rich__) so Rich re-evaluates on each refresh
            self._live = Live(
                self,  # TaskSequenceImpl.__rich__() called on each refresh
                console=self._console,
                refresh_per_second=10,  # Animate spinner at 10fps
                transient=False,  # Keep output visible after exit
            )
            self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the task sequence context."""
        # Auto-fail any running tasks on exception
        if exc_type is not None:
            for widget in self._task_widgets:
                if widget.status == TaskStatus.RUNNING:
                    widget.fail("Interrupted", str(exc_val) if exc_val else None)

        # Final refresh to show final state
        if self._live:
            self._refresh()
            self._live.__exit__(exc_type, exc_val, exc_tb)

    @contextmanager
    def task(self, description: str, total: int | None = None) -> Generator[TaskHandleImpl]:
        """Create a task within the sequence."""
        # Create task widget (already started)
        widget = TaskWidget(description)
        widget.start()
        if total is not None:
            widget.total = total
        self._task_widgets.append(widget)

        # Emit JSON event
        if self._json_mode:
            event: dict[str, Any] = {
                "event": "task_start",
                "description": description,
                "timestamp": widget.start_time,
            }
            if total is not None:
                event["total"] = total
            self._json_events.append(event)

        # Create handle
        handle = TaskHandleImpl(widget, self)

        # Refresh to show new task
        self._refresh()

        try:
            yield handle
        except Exception:
            # Auto-fail on uncaught exception if not already completed
            if widget.status == TaskStatus.RUNNING:
                widget.fail("Exception")
                self._refresh()
            raise
        finally:
            # Emit JSON completion event
            if self._json_mode:
                self._json_events.append(
                    {
                        "event": "task_complete",
                        "description": description,
                        "success": widget.status == TaskStatus.SUCCESS,
                        "result": widget.result_message,
                        "reason": widget.failure_reason,
                        "elapsed": time.time() - widget.start_time,
                    }
                )

    def _refresh(self) -> None:
        """Refresh the display. Single point of control.

        Note: We only call refresh(), not update(). The Live was initialized
        with `self` as the renderable, so Rich will call __rich__() on each
        refresh cycle, which returns _render() with updated animation frame.
        Calling update() would replace the renderable with a static Group.
        """
        if self._live:
            self._live.refresh()

    def _render(self) -> Group:
        """Render all tasks and optional log window to a Rich Group.

        Uses TaskWidget.render() and LogWindowWidget.render() for consistent
        rendering with the composable widget system.
        """
        # Update animation frame on each render for smooth spinner
        now = time.time()
        if now - self._last_refresh >= 0.1:  # 10 fps
            self._animation_frame = (self._animation_frame + 1) % len(SPINNER_FRAMES)
            self._last_refresh = now

        renderables: list[Any] = []

        # Render task widgets
        for widget in self._task_widgets:
            renderables.append(widget.render(self._animation_frame))

        # Render log window if enabled and has logs
        if self._show_logs and self._log_window.has_entries:
            renderables.append(self._log_window.render())

        return Group(*renderables) if renderables else Group()

    def _log(self, message: str, level: str) -> None:
        """Store a log message and optionally display it in the log window."""
        timestamp = time.time()
        self._logs.append((level, message))

        # Add to log window widget
        if self._show_logs:
            # Map string level to LogLevel enum
            log_level = {
                "INFO": LogLevel.INFO,
                "SUCCESS": LogLevel.SUCCESS,
                "WARNING": LogLevel.WARNING,
                "ERROR": LogLevel.ERROR,
            }.get(level, LogLevel.INFO)

            self._log_window.log(message, log_level)
            self._refresh()

        # Emit JSON event
        if self._json_mode:
            self._json_events.append(
                {
                    "event": "log",
                    "level": level,
                    "message": message,
                    "timestamp": timestamp,
                }
            )

    def get_json_events(self) -> list[dict[str, Any]]:
        """Get all JSON events emitted during the sequence."""
        return self._json_events


class UIBuilderImpl:
    """Implementation of UIBuilder - the entry point for commands.

    Creates task sequences and spinners for live progress display.
    """

    def __init__(
        self,
        console: Console | None,
        json_mode: bool = False,
    ) -> None:
        self._console = console
        self._json_mode = json_mode

    @contextmanager
    def task_sequence(
        self,
        title: str | None = None,
        show_logs: bool = False,
        max_logs: int = DEFAULT_MAX_LOGS,
    ) -> Generator[TaskSequenceImpl]:
        """Create a task sequence for multi-step operations.

        Args:
            title: Optional title for the sequence
            show_logs: If True, shows a scrolling log window below tasks
            max_logs: Maximum number of visible log entries (default: 10)
        """
        seq = TaskSequenceImpl(
            console=self._console,
            json_mode=self._json_mode,
            title=title,
            show_logs=show_logs,
            max_logs=max_logs,
        )
        with seq:
            yield seq

    @contextmanager
    def spinner(self, description: str) -> Generator[TaskHandleImpl]:
        """Create a simple spinner for single operations.

        Shorthand for a task sequence with one task.
        """
        with self.task_sequence() as seq:
            with seq.task(description) as task:
                yield task
