"""Fluent builder for CLI output components.

DEPRECATED: Import from gmailarchiver.cli.ui instead.

This module re-exports from the new location for backward compatibility.
"""

# Re-export from new location
from gmailarchiver.cli.ui.builder import (
    DEFAULT_MAX_LOGS,
    LOG_SYMBOLS,
    SPINNER_FRAMES,
    SYMBOLS,
    LogEntry,
    TaskHandleImpl,
    TaskSequenceImpl,
    TaskState,
    TaskStatus,
    UIBuilderImpl,
)
from gmailarchiver.cli.ui.protocols import (
    TaskHandle,
    TaskSequence,
    UIBuilder,
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
    "TaskState",
    "LogEntry",
    # Constants
    "SPINNER_FRAMES",
    "SYMBOLS",
    "LOG_SYMBOLS",
    "DEFAULT_MAX_LOGS",
]
