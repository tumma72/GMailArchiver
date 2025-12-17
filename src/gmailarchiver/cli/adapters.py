"""CLI adapters implementing shared protocols."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from gmailarchiver.shared.protocols import (
    NoOpTaskSequence,
    TaskSequence,
)

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager
    from gmailarchiver.cli.ui_builder import UIBuilder


class CLIProgressAdapter:
    """Adapts OutputManager/UIBuilder to ProgressReporter protocol.

    This adapter allows workflows to report progress without
    depending on CLI-specific types.
    """

    def __init__(self, output: OutputManager, ui: UIBuilder | None = None) -> None:
        self._output = output
        self._ui = ui

    def info(self, message: str) -> None:
        self._output.info(message)

    def warning(self, message: str) -> None:
        self._output.warning(message)

    def error(self, message: str) -> None:
        self._output.error(message)

    @contextmanager
    def task_sequence(self) -> Generator[TaskSequence]:
        if self._ui:
            with self._ui.task_sequence() as seq:
                yield seq
        else:
            yield NoOpTaskSequence()
