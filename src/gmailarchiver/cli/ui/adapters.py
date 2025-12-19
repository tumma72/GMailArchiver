"""CLI adapters bridging workflows to UI components.

This module provides adapters that implement the ProgressReporter protocol,
allowing workflows in the core layer to report progress without depending
on CLI-specific types.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from gmailarchiver.shared.protocols import (
    NoOpTaskHandle,
    NoOpTaskSequence,
    TaskHandle,
    TaskSequence,
)

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager
    from gmailarchiver.cli.ui.protocols import UIBuilder


class CLIProgressAdapter:
    """Adapts OutputManager/UIBuilder to ProgressReporter protocol.

    This adapter allows workflows to report progress without
    depending on CLI-specific types. It bridges the protocol-based
    workflow layer with the Rich-based UI layer.

    Supports two modes:
    1. Standard mode: Each task_sequence() call creates a new Live context
    2. Workflow mode: A shared sequence for multi-step workflows with log window

    Example (standard):
        adapter = CLIProgressAdapter(ctx.output, ctx.ui)
        workflow = ImportWorkflow(storage, progress=adapter)
        result = await workflow.run(config)

    Example (workflow mode with log window):
        with adapter.workflow_sequence(show_logs=True) as progress:
            # All tasks share the same sequence
            with progress.task("Scanning") as t:
                ...
                t.complete("Found 100 messages")
            with progress.task("Archiving", total=100) as t:
                for msg in messages:
                    t.advance()
                    t.log(f"Archived: {msg.subject}")
    """

    def __init__(self, output: OutputManager, ui: UIBuilder | None = None) -> None:
        """Initialize the adapter.

        Args:
            output: OutputManager for message output
            ui: Optional UIBuilder for task sequences
        """
        self._output = output
        self._ui = ui
        self._shared_sequence: TaskSequence | None = None

    def info(self, message: str) -> None:
        """Log an informational message."""
        self._output.info(message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self._output.warning(message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self._output.error(message)

    @contextmanager
    def task_sequence(self, show_logs: bool = False) -> Generator[TaskSequence]:
        """Create a task sequence for multi-step operations.

        If a shared workflow sequence is active, returns that instead
        of creating a new one.

        Args:
            show_logs: If True and creating new sequence, show log window

        Yields:
            TaskSequence for managing tasks
        """
        # If we have a shared sequence, use it (don't create nested Live contexts)
        if self._shared_sequence is not None:
            yield self._shared_sequence
            return

        if self._ui:
            with self._ui.task_sequence(show_logs=show_logs) as seq:
                yield seq  # type: ignore[misc]
        else:
            yield NoOpTaskSequence()

    @contextmanager
    def workflow_sequence(
        self, show_logs: bool = False, max_logs: int = 5
    ) -> Generator[WorkflowProgressContext]:
        """Create a shared task sequence for workflow-level operations.

        This creates a single Live context that all tasks share, following
        the Log Window pattern from UI_UX_CLI.md Section 7.4.

        Args:
            show_logs: If True, show scrolling log window below tasks
            max_logs: Maximum number of visible log entries

        Yields:
            WorkflowProgressContext for creating tasks within the shared sequence

        Example:
            with adapter.workflow_sequence(show_logs=True) as progress:
                with progress.task("Step 1") as t:
                    t.complete("Done")
                with progress.task("Step 2", total=100) as t:
                    for i in range(100):
                        t.advance()
                        t.log(f"Processed item {i}")
        """
        if self._ui:
            with self._ui.task_sequence(show_logs=show_logs, max_logs=max_logs) as seq:
                self._shared_sequence = seq  # type: ignore[assignment]
                try:
                    yield WorkflowProgressContext(seq, self._output)  # type: ignore[arg-type]
                finally:
                    self._shared_sequence = None
        else:
            yield WorkflowProgressContext(NoOpTaskSequence(), self._output)


class WorkflowProgressContext:
    """Context for workflow-level progress with shared task sequence.

    Provides a convenient API for creating tasks within a shared sequence
    and logging messages.
    """

    def __init__(self, sequence: TaskSequence, output: Any) -> None:
        """Initialize with shared sequence and output manager.

        Args:
            sequence: Shared TaskSequence
            output: OutputManager for fallback output
        """
        self._sequence = sequence
        self._output = output

    @contextmanager
    def task(self, description: str, total: int | None = None) -> Generator[TaskHandle]:
        """Create a task within the shared sequence.

        Args:
            description: Task description
            total: Optional total for progress bar

        Yields:
            TaskHandle for controlling the task
        """
        if hasattr(self._sequence, "task"):
            with self._sequence.task(description, total) as handle:
                yield handle
        else:
            yield NoOpTaskHandle()

    def info(self, message: str) -> None:
        """Log an informational message."""
        self._output.info(message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self._output.warning(message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self._output.error(message)
