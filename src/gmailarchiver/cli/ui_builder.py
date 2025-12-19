"""Fluent builder for CLI output components.

DEPRECATED: Import from gmailarchiver.cli.ui instead.

This module re-exports from the new location for backward compatibility.
"""

# Re-export from new location
from gmailarchiver.cli.ui.builder import (
    DEFAULT_MAX_LOGS,
    TaskHandleImpl,
    TaskSequenceImpl,
    UIBuilderImpl,
)
from gmailarchiver.cli.ui.protocols import (
    TaskHandle,
    TaskSequence,
    UIBuilder,
)
from gmailarchiver.cli.ui.widgets.log_window import LogEntry
from gmailarchiver.cli.ui.widgets.task import (
    SPINNER_FRAMES,
    TaskStatus,
)
from gmailarchiver.cli.ui.widgets.task import (
    STATUS_SYMBOLS as SYMBOLS,
)

__all__ = [
    # Protocols
    "TaskHandle",
    "TaskSequence",
    "UIBuilder",
    # Implementations
    "UIBuilderImpl",
    "TaskSequenceImpl",
    "TaskHandleImpl",
    "TaskStatus",
    "LogEntry",
    # Constants
    "SPINNER_FRAMES",
    "SYMBOLS",
    "DEFAULT_MAX_LOGS",
]
