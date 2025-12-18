"""CLI UI Widgets - composable display components.

This package provides reusable widgets for CLI output:
- ReportCard: Key-value reports with optional emoji
- SuggestionList: Next-step suggestions with context
- ErrorPanel: Error messages with details and suggestions
- ProgressSummary: Operation statistics display

All widgets use the fluent builder pattern for easy composition.

Usage:
    from gmailarchiver.cli.ui.widgets import ReportCard, SuggestionList

    ReportCard("Results")
        .with_emoji("📦")
        .add_field("Count", 42)
        .render(ctx.output)
"""

from gmailarchiver.cli.ui.widgets.errors import ErrorPanel
from gmailarchiver.cli.ui.widgets.progress import ProgressSummary
from gmailarchiver.cli.ui.widgets.report_card import ReportCard
from gmailarchiver.cli.ui.widgets.suggestions import SuggestionList

__all__ = [
    "ReportCard",
    "SuggestionList",
    "ErrorPanel",
    "ProgressSummary",
]
