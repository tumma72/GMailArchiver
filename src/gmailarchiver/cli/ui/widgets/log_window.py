"""LogWindowWidget - Scrolling log window for task entries."""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Self

from rich.console import Group
from rich.rule import Rule
from rich.text import Text


class LogLevel(Enum):
    """Log entry severity levels."""

    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()


# Log level symbols and colors (matching UI_UX_CLI.md)
LOG_SYMBOLS = {
    LogLevel.INFO: ("ℹ", "blue"),
    LogLevel.SUCCESS: ("✓", "green"),
    LogLevel.WARNING: ("⚠", "yellow"),
    LogLevel.ERROR: ("✗", "red"),
}


@dataclass
class LogEntry:
    """A single log entry with level, message, and timestamp."""

    level: LogLevel
    message: str
    timestamp: float = field(default_factory=time.time)

    def render(self) -> Text:
        """Render entry to Rich Text.

        Returns:
            Rich Text object with styled log entry
        """
        text = Text()
        symbol, color = LOG_SYMBOLS[self.level]
        text.append(f"{symbol} ", style=color)
        text.append(self.message)
        return text

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with level, message, and timestamp
        """
        return {
            "level": self.level.name.lower(),
            "message": self.message,
            "timestamp": self.timestamp,
        }


class LogWindowWidget:
    """Widget for displaying a scrolling log window.

    Uses a ring buffer to maintain recent log entries.
    New entries appear at bottom, old entries scroll out at top.

    Example:
        log = LogWindowWidget(max_size=5)
        log.success("Archived: Email subject")
        log.warning("Skipped (duplicate): Another subject")
        log.error("Failed: Error message")

        # Render to Rich Group
        group = log.render()
    """

    def __init__(self, max_size: int = 5, show_separator: bool = True) -> None:
        """Initialize log window.

        Args:
            max_size: Maximum number of visible entries
            show_separator: Whether to show separator line at top
        """
        self.max_size = max_size
        self.show_separator = show_separator
        self._entries: deque[LogEntry] = deque(maxlen=max_size)
        self._all_entries: list[LogEntry] = []  # Keep all for JSON output

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> Self:
        """Add a log entry.

        Args:
            message: Log message
            level: Log severity level

        Returns:
            Self for fluent chaining
        """
        entry = LogEntry(level=level, message=message)
        self._entries.append(entry)
        self._all_entries.append(entry)
        return self

    def info(self, message: str) -> Self:
        """Add an info log entry.

        Args:
            message: Log message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.INFO)

    def success(self, message: str) -> Self:
        """Add a success log entry.

        Args:
            message: Log message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.SUCCESS)

    def warning(self, message: str) -> Self:
        """Add a warning log entry.

        Args:
            message: Log message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.WARNING)

    def error(self, message: str) -> Self:
        """Add an error log entry.

        Args:
            message: Log message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.ERROR)

    def clear(self) -> Self:
        """Clear all entries.

        Returns:
            Self for fluent chaining
        """
        self._entries.clear()
        self._all_entries.clear()
        return self

    @property
    def visible_count(self) -> int:
        """Number of currently visible entries."""
        return len(self._entries)

    @property
    def total_count(self) -> int:
        """Total number of entries (including scrolled out)."""
        return len(self._all_entries)

    @property
    def has_entries(self) -> bool:
        """Check if there are any visible entries."""
        return len(self._entries) > 0

    def render(self) -> Group:
        """Render log window to Rich Group.

        Returns:
            Rich Group with separator and log entries
        """
        renderables: list[Any] = []

        # Add separator if enabled and has entries
        if self.show_separator and self.has_entries:
            renderables.append(Rule(style="dim"))

        # Add visible entries
        for entry in self._entries:
            renderables.append(entry.render())

        return Group(*renderables) if renderables else Group(Text(""))

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with widget metadata and entries
        """
        return {
            "type": "log_window",
            "max_size": self.max_size,
            "visible_count": self.visible_count,
            "total_count": self.total_count,
            "visible_entries": [e.to_json() for e in self._entries],
            "all_entries": [e.to_json() for e in self._all_entries],
        }
