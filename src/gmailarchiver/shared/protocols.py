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
