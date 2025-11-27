"""Fluent builder for CLI output components.

This module provides a declarative API for CLI output that commands use
without knowing Rich implementation details. Commands describe WHAT to
display, this module handles HOW.

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
"""

import time
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

# =============================================================================
# Enums and Data Classes
# =============================================================================


class TaskStatus(Enum):
    """Task execution states."""

    PENDING = auto()  # Not started (○)
    RUNNING = auto()  # In progress (spinner)
    SUCCESS = auto()  # Completed successfully (✓)
    FAILED = auto()  # Completed with error (✗)


@dataclass
class TaskState:
    """Internal state for a single task."""

    description: str
    status: TaskStatus = TaskStatus.PENDING
    total: int | None = None
    completed: int = 0
    result_message: str | None = None
    failure_reason: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None


# =============================================================================
# Protocols
# =============================================================================


class TaskHandle(Protocol):
    """Handle for controlling a single task within a sequence.

    Methods:
        complete: Mark task as successful (shows ✓)
        fail: Mark task as failed (shows ✗)
        advance: Advance progress counter (if total was set)
        set_total: Set total for late-bound progress
        log: Log a message within the task context
    """

    def complete(self, message: str) -> None:
        """Mark task as successfully completed.

        Args:
            message: Success message (e.g., "Found 4,269 messages")
        """
        ...

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed.

        Args:
            message: Failure message
            reason: Optional detailed reason (shown after "→")
        """
        ...

    def advance(self, n: int = 1) -> None:
        """Advance progress counter.

        Args:
            n: Number of items to advance (default: 1)
        """
        ...

    def set_total(self, total: int) -> None:
        """Set total for progress tracking (for late-bound totals).

        Args:
            total: Total number of items to process
        """
        ...

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context.

        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR)
        """
        ...


class TaskSequence(Protocol):
    """Protocol for task sequence builders.

    A task sequence manages multiple sequential tasks with a single
    Rich Live context, preventing flickering and ensuring consistent
    display updates.
    """

    def task(
        self, description: str, total: int | None = None
    ) -> AbstractContextManager[TaskHandle]:
        """Create a task within the sequence.

        Args:
            description: Task description (e.g., "Importing messages")
            total: Optional total for progress tracking

        Returns:
            Context manager yielding a TaskHandle
        """
        ...


class UIBuilder(Protocol):
    """Protocol for UI builder entry point.

    Commands access this via ctx.ui to build declarative UI.
    """

    def task_sequence(self, title: str | None = None) -> AbstractContextManager[TaskSequence]:
        """Create a task sequence for multi-step operations.

        Args:
            title: Optional title for the sequence

        Returns:
            Context manager yielding a TaskSequence
        """
        ...

    def spinner(self, description: str) -> AbstractContextManager[TaskHandle]:
        """Create a simple spinner for single operations.

        Shorthand for a task sequence with one task.

        Args:
            description: Spinner description

        Returns:
            Context manager yielding a TaskHandle
        """
        ...


# =============================================================================
# Implementation Classes
# =============================================================================

# Spinner animation frames (braille pattern)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Status symbols
SYMBOLS = {
    TaskStatus.PENDING: ("○", "dim"),
    TaskStatus.RUNNING: (SPINNER_FRAMES[0], "cyan"),  # Will be animated
    TaskStatus.SUCCESS: ("✓", "green"),
    TaskStatus.FAILED: ("✗", "red"),
}


class TaskHandleImpl:
    """Implementation of TaskHandle for controlling a single task."""

    def __init__(
        self,
        state: TaskState,
        sequence: TaskSequenceImpl,
    ) -> None:
        self._state = state
        self._sequence = sequence

    def complete(self, message: str) -> None:
        """Mark task as successfully completed."""
        self._state.status = TaskStatus.SUCCESS
        self._state.result_message = message
        self._state.end_time = time.time()
        self._sequence._refresh()

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed."""
        self._state.status = TaskStatus.FAILED
        self._state.result_message = message
        self._state.failure_reason = reason
        self._state.end_time = time.time()
        self._sequence._refresh()

    def advance(self, n: int = 1) -> None:
        """Advance progress counter."""
        self._state.completed += n
        self._sequence._refresh()

    def set_total(self, total: int) -> None:
        """Set total for progress tracking."""
        self._state.total = total
        self._sequence._refresh()

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context."""
        # For now, we just store logs in the sequence
        # Future: could display in a log buffer below tasks
        self._sequence._log(message, level)


class TaskSequenceImpl:
    """Implementation of TaskSequence that manages Rich Live context.

    This class owns a single Rich Live context and manages all task
    rendering within it. This solves the flickering bug by having
    a single point of refresh control.
    """

    def __init__(
        self,
        console: Console | None,
        json_mode: bool = False,
        title: str | None = None,
    ) -> None:
        self._console = console
        self._json_mode = json_mode
        self._title = title
        self._tasks: list[TaskState] = []
        self._logs: list[tuple[str, str]] = []
        self._json_events: list[dict[str, Any]] = []
        self._live: Live | None = None
        self._animation_frame: int = 0
        self._last_refresh: float = 0

    def __enter__(self) -> TaskSequenceImpl:
        """Enter the task sequence context."""
        if not self._json_mode and self._console:
            self._live = Live(
                self._render(),
                console=self._console,
                auto_refresh=False,  # Manual control - prevents flickering
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
            for task in self._tasks:
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.FAILED
                    task.result_message = "Interrupted"
                    task.failure_reason = str(exc_val) if exc_val else None
                    task.end_time = time.time()

        # Final refresh to show final state
        if self._live:
            self._refresh()
            self._live.__exit__(exc_type, exc_val, exc_tb)

    @contextmanager
    def task(
        self, description: str, total: int | None = None
    ) -> Generator[TaskHandleImpl]:
        """Create a task within the sequence."""
        # Create task state
        state = TaskState(
            description=description,
            status=TaskStatus.RUNNING,
            total=total,
            start_time=time.time(),
        )
        self._tasks.append(state)

        # Emit JSON event
        if self._json_mode:
            event: dict[str, Any] = {
                "event": "task_start",
                "description": description,
                "timestamp": state.start_time,
            }
            if total is not None:
                event["total"] = total
            self._json_events.append(event)

        # Create handle
        handle = TaskHandleImpl(state, self)

        # Refresh to show new task
        self._refresh()

        try:
            yield handle
        except Exception:
            # Auto-fail on uncaught exception if not already completed
            if state.status == TaskStatus.RUNNING:
                state.status = TaskStatus.FAILED
                state.result_message = "Exception"
                state.end_time = time.time()
                self._refresh()
            raise
        finally:
            # Emit JSON completion event
            if self._json_mode:
                self._json_events.append(
                    {
                        "event": "task_complete",
                        "description": description,
                        "success": state.status == TaskStatus.SUCCESS,
                        "result": state.result_message,
                        "reason": state.failure_reason,
                        "elapsed": (state.end_time or time.time()) - state.start_time,
                    }
                )

    def _refresh(self) -> None:
        """Refresh the display. Single point of control."""
        if self._live:
            # Update animation frame (throttled)
            now = time.time()
            if now - self._last_refresh >= 0.1:  # 10 fps max
                self._animation_frame = (self._animation_frame + 1) % len(
                    SPINNER_FRAMES
                )
                self._last_refresh = now

            self._live.update(self._render())
            self._live.refresh()

    def _render(self) -> Group:
        """Render all tasks to a Rich Group."""
        lines: list[Text] = []

        for task in self._tasks:
            line = self._render_task(task)
            lines.append(line)

        return Group(*lines) if lines else Group(Text(""))

    def _render_task(self, task: TaskState) -> Text:
        """Render a single task line."""
        text = Text()

        # Symbol with animation for running tasks
        if task.status == TaskStatus.RUNNING:
            symbol = SPINNER_FRAMES[self._animation_frame]
            color = "cyan"
        else:
            symbol, color = SYMBOLS[task.status]

        text.append(f"{symbol} ", style=color)

        # Description
        if task.status == TaskStatus.RUNNING:
            text.append(task.description, style="bold")
            # Show progress if total is known
            if task.total is not None and task.total > 0:
                pct = (task.completed / task.total) * 100
                text.append(f" [{task.completed:,}/{task.total:,}]", style="dim")
                text.append(f" ({pct:.0f}%)", style="cyan")
            else:
                text.append("...", style="dim")
        elif task.status == TaskStatus.SUCCESS:
            text.append(task.description)
            if task.result_message:
                text.append(f": {task.result_message}", style="green")
        elif task.status == TaskStatus.FAILED:
            text.append(task.description)
            text.append(": FAILED", style="red bold")
            if task.failure_reason:
                text.append(f' → "{task.failure_reason}"', style="dim red")
        else:  # PENDING
            text.append(task.description, style="dim")

        return text

    def _log(self, message: str, level: str) -> None:
        """Store a log message."""
        self._logs.append((level, message))
        if self._json_mode:
            self._json_events.append(
                {
                    "event": "log",
                    "level": level,
                    "message": message,
                    "timestamp": time.time(),
                }
            )

    def get_json_events(self) -> list[dict[str, Any]]:
        """Get all JSON events emitted during the sequence."""
        return self._json_events


class UIBuilderImpl:
    """Implementation of UIBuilder - the entry point for commands."""

    def __init__(
        self,
        console: Console | None,
        json_mode: bool = False,
    ) -> None:
        self._console = console
        self._json_mode = json_mode

    @contextmanager
    def task_sequence(
        self, title: str | None = None
    ) -> Generator[TaskSequenceImpl]:
        """Create a task sequence for multi-step operations."""
        seq = TaskSequenceImpl(
            console=self._console,
            json_mode=self._json_mode,
            title=title,
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
