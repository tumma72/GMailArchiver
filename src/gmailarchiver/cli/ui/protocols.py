"""UI protocols for widgets and builders.

This module defines the protocol interfaces that all UI components implement.
Protocols enable type checking while keeping implementations decoupled.

Note: Protocol classes contain only abstract method signatures (`...` bodies)
and are excluded from coverage measurement since they define interfaces only.
"""

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager


class Widget(Protocol):  # pragma: no cover
    """Protocol for renderable UI widgets.

    All widgets implement this protocol, enabling consistent rendering
    and JSON serialization for both interactive and automated use.
    """

    def render(self, output: OutputManager) -> None:
        """Render the widget to output.

        Args:
            output: OutputManager for rendering
        """
        ...

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Used when --json flag is set for automation.

        Returns:
            Dictionary suitable for JSON serialization
        """
        ...


class TaskHandle(Protocol):  # pragma: no cover
    """Protocol for controlling a single task within a sequence.

    Provides methods for updating task state, progress, and completion.
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
            reason: Optional detailed reason (shown after "->")
        """
        ...

    def advance(self, n: int = 1) -> None:
        """Advance progress counter.

        Args:
            n: Number of items to advance (default: 1)
        """
        ...

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking (for late-bound totals).

        Args:
            total: Total number of items to process
            description: Optional new description for the task
        """
        ...

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context.

        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        ...

    def warn(self, message: str) -> None:
        """Mark task as completed with warning status.

        Use when task completed but with caveats or non-fatal issues.
        Displays yellow warning symbol instead of green checkmark.

        Args:
            message: Warning message to display
        """
        ...


class TaskSequence(Protocol):  # pragma: no cover
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


class UIBuilder(Protocol):  # pragma: no cover
    """Protocol for UI builder entry point.

    Commands access this via ctx.ui to build declarative UI.
    """

    def task_sequence(
        self,
        title: str | None = None,
        show_logs: bool = False,
        max_logs: int = 10,
    ) -> AbstractContextManager[TaskSequence]:
        """Create a task sequence for multi-step operations.

        Args:
            title: Optional title for the sequence
            show_logs: If True, shows a scrolling log window below tasks
            max_logs: Maximum number of visible log entries

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
