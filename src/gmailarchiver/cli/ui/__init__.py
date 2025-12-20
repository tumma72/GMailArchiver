"""CLI UI module - composable widgets and progress builders.

This module provides the user interface components for CLI commands:

**Widgets** (static display):
- ReportCard: Key-value reports with optional emoji
- SuggestionList: Next-step suggestions with context
- ErrorPanel: Error messages with details and suggestions
- ValidationPanel: Multi-check validation results with pass/fail/skip states
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
# Adapters
from gmailarchiver.cli.ui.adapters import CLIProgressAdapter

# Builders
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
    Widget,
)

# Widgets
from gmailarchiver.cli.ui.widgets import (
    CheckStatus,
    ErrorPanel,
    LogLevel,
    LogWindowWidget,
    ProgressBarWidget,
    ProgressSummary,
    ReportCard,
    SuggestionList,
    TaskWidget,
    ValidationPanel,
    WorkflowProgressWidget,
)

# Import LogEntry from log_window widget
from gmailarchiver.cli.ui.widgets.log_window import LogEntry

# Import SPINNER_FRAMES, TaskStatus, and SYMBOLS from widgets (source of truth)
from gmailarchiver.cli.ui.widgets.task import (
    SPINNER_FRAMES,
    TaskStatus,
)
from gmailarchiver.cli.ui.widgets.task import (
    STATUS_SYMBOLS as SYMBOLS,
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
    "LogEntry",
    # Builder constants
    "SPINNER_FRAMES",
    "SYMBOLS",
    "DEFAULT_MAX_LOGS",
    # Adapters
    "CLIProgressAdapter",
    # Widgets
    "ReportCard",
    "SuggestionList",
    "ErrorPanel",
    "ValidationPanel",
    "CheckStatus",
    "ProgressSummary",
    "TaskWidget",
    "ProgressBarWidget",
    "LogWindowWidget",
    "LogLevel",
    "WorkflowProgressWidget",
]
