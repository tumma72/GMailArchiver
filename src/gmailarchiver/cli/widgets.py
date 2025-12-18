"""Reusable CLI widgets for consistent output.

DEPRECATED: Import from gmailarchiver.cli.ui instead.

This module re-exports from the new location for backward compatibility.
"""

# Re-export from new location
from gmailarchiver.cli.ui.widgets import (
    ErrorPanel,
    ProgressSummary,
    ReportCard,
    SuggestionList,
)

__all__ = [
    "ReportCard",
    "SuggestionList",
    "ErrorPanel",
    "ProgressSummary",
]
