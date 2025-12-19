"""Shared protocols for cross-layer communication.

This module defines protocol interfaces that allow layers to communicate
without tight coupling. Implementations live in their respective layers.
"""

from contextlib import AbstractContextManager
from typing import Protocol


class ProgressReporter(Protocol):
    """Protocol for reporting progress and messages during operations.

    This protocol allows workflows to report progress without depending
    on CLI-specific types like OutputManager or UIBuilder.
    """

    def info(self, message: str) -> None:
        """Log an informational message.

        Args:
            message: Info message text
        """
        ...  # pragma: no cover

    def warning(self, message: str) -> None:
        """Log a warning message.

        Args:
            message: Warning message text
        """
        ...  # pragma: no cover

    def error(self, message: str) -> None:
        """Log an error message.

        Args:
            message: Error message text
        """
        ...  # pragma: no cover

    def task_sequence(self) -> AbstractContextManager[TaskSequence]:
        """Create a task sequence for multi-step operations.

        Returns:
            Context manager yielding a TaskSequence
        """
        ...  # pragma: no cover


class TaskSequence(Protocol):
    """Protocol for task sequence builders.

    A task sequence manages multiple sequential tasks with a single
    live context, preventing flickering and ensuring consistent display.
    """

    def task(
        self, description: str, total: int | None = None
    ) -> AbstractContextManager[TaskHandle]:
        """Create a task within the sequence.

        Args:
            description: Task description
            total: Optional total for progress tracking

        Returns:
            Context manager yielding a TaskHandle
        """
        ...  # pragma: no cover


class TaskHandle(Protocol):
    """Handle for controlling a single task within a sequence."""

    def complete(self, message: str) -> None:
        """Mark task as successfully completed.

        Args:
            message: Success message
        """
        ...  # pragma: no cover

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed.

        Args:
            message: Failure message
            reason: Optional detailed reason
        """
        ...  # pragma: no cover

    def advance(self, n: int = 1) -> None:
        """Advance progress counter.

        Args:
            n: Number of items to advance
        """
        ...  # pragma: no cover

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context.

        For Log Window pattern (UI_UX_CLI.md Section 7.4).

        Args:
            message: Log message
            level: Log level (INFO, SUCCESS, WARNING, ERROR)
        """
        ...  # pragma: no cover

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking (late binding).

        Args:
            total: Total number of items
            description: Optional new description
        """
        ...  # pragma: no cover

    def set_status(self, status: str) -> None:
        """Update task description/status message.

        For live progress updates during operations.

        Args:
            status: New status message to display
        """
        ...  # pragma: no cover

    def warn(self, message: str) -> None:
        """Mark task as completed with warning status.

        Use when task completed but with caveats or non-fatal issues.
        Displays yellow warning symbol instead of green checkmark.

        Args:
            message: Warning message to display
        """
        ...  # pragma: no cover


class NoOpTaskSequence:
    """No-op implementation of TaskSequence for when UI is not available."""

    def task(
        self, description: str, total: int | None = None
    ) -> AbstractContextManager[NoOpTaskHandle]:
        """Create a no-op task."""
        from contextlib import contextmanager

        @contextmanager
        def _task():
            yield NoOpTaskHandle()

        return _task()


class NoOpTaskHandle:
    """No-op implementation of TaskHandle."""

    def complete(self, message: str) -> None:
        """No-op completion."""
        pass

    def fail(self, message: str, reason: str | None = None) -> None:
        """No-op failure."""
        pass

    def advance(self, n: int = 1) -> None:
        """No-op advance."""
        pass

    def log(self, message: str, level: str = "INFO") -> None:
        """No-op log."""
        pass

    def set_total(self, total: int, description: str | None = None) -> None:
        """No-op set_total."""
        pass

    def set_status(self, status: str) -> None:
        """No-op set_status."""
        pass

    def warn(self, message: str) -> None:
        """No-op warn."""
        pass


class NoOpProgressReporter:
    """No-op implementation of ProgressReporter for testing."""

    def info(self, message: str) -> None:
        """No-op info message."""
        pass

    def warning(self, message: str) -> None:
        """No-op warning message."""
        pass

    def error(self, message: str) -> None:
        """No-op error message."""
        pass

    def task_sequence(self) -> AbstractContextManager[TaskSequence]:
        """Create a no-op task sequence."""
        from contextlib import contextmanager

        @contextmanager
        def _sequence():
            yield NoOpTaskSequence()

        return _sequence()
