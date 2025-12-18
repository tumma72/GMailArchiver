"""CLI UI module - composable widgets and progress builders.

This module provides the user interface components for CLI commands:

**Widgets** (static display):
- ReportCard: Key-value reports with optional emoji
- SuggestionList: Next-step suggestions with context
- ErrorPanel: Error messages with details and suggestions
- ProgressSummary: Operation statistics display

**Builders** (live progress):
- UIBuilder: Entry point for live UI components
- TaskSequence: Multi-step operation sequences
- TaskHandle: Individual task control

**Adapters** (protocol bridges):
- CLIProgressAdapter: Bridges workflows to UI

Usage:
    from gmailarchiver.cli.ui import ReportCard, SuggestionList, UIBuilderImpl

    # Display a report
    ReportCard("Results")
        .with_emoji("📦")
        .add_field("Count", 42)
        .render(ctx.output)

    # Create live progress
    with ctx.ui.task_sequence() as seq:
        with seq.task("Processing") as t:
            do_work()
            t.complete("Done")

See cli/ui/ARCHITECTURE.md for complete design documentation.
"""

# Protocols
from gmailarchiver.cli.ui.protocols import (
    TaskHandle,
    TaskSequence,
    UIBuilder,
    Widget,
)

# Builders
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

# Adapters
from gmailarchiver.cli.ui.adapters import CLIProgressAdapter

# Widgets
from gmailarchiver.cli.ui.widgets import (
    ErrorPanel,
    ProgressSummary,
    ReportCard,
    SuggestionList,
)

__all__ = [
    # Protocols
    "Widget",
    "UIBuilder",
    "TaskSequence",
    "TaskHandle",
    # Builder implementations
    "UIBuilderImpl",
    "TaskSequenceImpl",
    "TaskHandleImpl",
    "TaskStatus",
    "TaskState",
    "LogEntry",
    # Builder constants
    "SPINNER_FRAMES",
    "SYMBOLS",
    "LOG_SYMBOLS",
    "DEFAULT_MAX_LOGS",
    # Adapters
    "CLIProgressAdapter",
    # Widgets
    "ReportCard",
    "SuggestionList",
    "ErrorPanel",
    "ProgressSummary",
]
