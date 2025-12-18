"""CLI adapters bridging workflows to UI components.

This module provides adapters that implement the ProgressReporter protocol,
allowing workflows in the core layer to report progress without depending
on CLI-specific types.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from gmailarchiver.shared.protocols import (
    NoOpTaskSequence,
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

    Example:
        adapter = CLIProgressAdapter(ctx.output, ctx.ui)
        workflow = ImportWorkflow(storage, progress=adapter)
        result = await workflow.run(config)
    """

    def __init__(self, output: OutputManager, ui: UIBuilder | None = None) -> None:
        """Initialize the adapter.

        Args:
            output: OutputManager for message output
            ui: Optional UIBuilder for task sequences
        """
        self._output = output
        self._ui = ui

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
    def task_sequence(self) -> Generator[TaskSequence]:
        """Create a task sequence for multi-step operations.

        Delegates to UIBuilder if available, otherwise returns
        a no-op sequence.
        """
        if self._ui:
            with self._ui.task_sequence() as seq:
                yield seq
        else:
            yield NoOpTaskSequence()
