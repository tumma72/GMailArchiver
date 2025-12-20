"""CLI UI Widgets - composable display components.

This package provides reusable widgets for CLI output:
- ReportCard: Key-value reports with optional emoji
- SuggestionList: Next-step suggestions with context
- ErrorPanel: Error messages with details and suggestions
- ValidationPanel: Multi-check validation results with pass/fail/skip states
- ProgressSummary: Operation statistics display
- TaskWidget: Single task display with spinner/status transitions
- ProgressBarWidget: Workflow progress bar with ETA and count display
- LogWindowWidget: Scrolling log window for task entries
- WorkflowProgressWidget: Composer for multi-step workflow progress display
- TableWidget: Flexible table with intelligent column sizing

All widgets use the fluent builder pattern for easy composition.

Usage:
    from gmailarchiver.cli.ui.widgets import (
        ReportCard, SuggestionList, TaskWidget, ProgressBarWidget,
        LogWindowWidget, WorkflowProgressWidget, TableWidget, ColumnSpec,
    )

    ReportCard("Results")
        .with_emoji("📦")
        .add_field("Count", 42)
        .render(ctx.output)

    task = TaskWidget("Processing")
    task.start().set_progress(50, 100)
    text = task.render(animation_frame=0)

    bar = ProgressBarWidget("Archiving messages", total=100)
    bar.advance(10)
    text = bar.render(animation_frame=0)

    log = LogWindowWidget(max_size=5)
    log.success("Archived: Email subject")
    log.warning("Skipped (duplicate): Another subject")

    wf = WorkflowProgressWidget()
    wf.add_task("Scan").start()
    wf.log_success("Found items")
    group = wf.render()

    table = TableWidget("Search Results")
    table.add_column("Subject", content="cut", ratio=2)
    table.add_column("Message-ID", content="full")
    table.add_row("Meeting notes", "<msg123@example.com>")
    table.render_to_output(output)
"""

from gmailarchiver.cli.ui.widgets.errors import ErrorPanel
from gmailarchiver.cli.ui.widgets.log_window import LogLevel, LogWindowWidget
from gmailarchiver.cli.ui.widgets.progress import ProgressSummary
from gmailarchiver.cli.ui.widgets.progress_bar import ProgressBarWidget
from gmailarchiver.cli.ui.widgets.report_card import ReportCard
from gmailarchiver.cli.ui.widgets.suggestions import SuggestionList
from gmailarchiver.cli.ui.widgets.table import ColumnSpec, TableWidget
from gmailarchiver.cli.ui.widgets.task import TaskWidget
from gmailarchiver.cli.ui.widgets.validation import CheckStatus, ValidationPanel
from gmailarchiver.cli.ui.widgets.workflow_progress import WorkflowProgressWidget

__all__ = [
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
    "TableWidget",
    "ColumnSpec",
]
