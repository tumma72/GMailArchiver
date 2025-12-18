"""TaskWidget - Single task display with status transitions."""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Self

from rich.text import Text


class TaskStatus(Enum):
    """Task execution states."""

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    WARNING = auto()


# Spinner frames (braille pattern)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Status symbols and colors
STATUS_SYMBOLS = {
    TaskStatus.PENDING: ("○", "dim"),
    TaskStatus.RUNNING: (SPINNER_FRAMES[0], "cyan"),  # Will animate
    TaskStatus.SUCCESS: ("✓", "green"),
    TaskStatus.FAILED: ("✗", "red"),
    TaskStatus.WARNING: ("⚠", "yellow"),
}


@dataclass
class TaskWidget:
    """Widget for displaying a single task with status transitions.

    Follows fluent builder pattern for configuration.

    Example:
        task = TaskWidget("Processing messages")
        task.start()  # Shows spinner
        task.set_progress(50, 100)  # Shows progress bar
        task.complete("Processed 100 messages")  # Shows ✓

        # Render to Rich Text
        text = task.render(animation_frame=0)
    """

    description: str
    status: TaskStatus = TaskStatus.PENDING
    total: int | None = None
    completed: int = 0
    result_message: str | None = None
    failure_reason: str | None = None
    start_time: float = field(default_factory=time.time)

    def start(self) -> Self:
        """Mark task as running.

        Returns:
            Self for fluent chaining
        """
        self.status = TaskStatus.RUNNING
        self.start_time = time.time()
        return self

    def complete(self, message: str) -> Self:
        """Mark task as successfully completed.

        Args:
            message: Success message to display

        Returns:
            Self for fluent chaining
        """
        self.status = TaskStatus.SUCCESS
        self.result_message = message
        return self

    def fail(self, message: str, reason: str | None = None) -> Self:
        """Mark task as failed.

        Args:
            message: Failure message to display
            reason: Optional detailed reason for failure

        Returns:
            Self for fluent chaining
        """
        self.status = TaskStatus.FAILED
        self.result_message = message
        self.failure_reason = reason
        return self

    def warn(self, message: str) -> Self:
        """Mark task with warning status.

        Args:
            message: Warning message to display

        Returns:
            Self for fluent chaining
        """
        self.status = TaskStatus.WARNING
        self.result_message = message
        return self

    def set_progress(self, completed: int, total: int | None = None) -> Self:
        """Update progress counters.

        Args:
            completed: Number of items completed
            total: Total number of items (optional, updates if provided)

        Returns:
            Self for fluent chaining
        """
        self.completed = completed
        if total is not None:
            self.total = total
        return self

    def advance(self, n: int = 1) -> Self:
        """Advance progress by n items.

        Args:
            n: Number of items to advance (default: 1)

        Returns:
            Self for fluent chaining
        """
        self.completed += n
        return self

    def render(self, animation_frame: int = 0) -> Text:
        """Render task to Rich Text.

        Args:
            animation_frame: Current animation frame for spinner (0-9)

        Returns:
            Rich Text object ready for display
        """
        text = Text()

        # Get symbol and color based on status
        if self.status == TaskStatus.RUNNING:
            symbol = SPINNER_FRAMES[animation_frame % len(SPINNER_FRAMES)]
            color = "cyan"
        else:
            symbol, color = STATUS_SYMBOLS[self.status]

        text.append(f"{symbol} ", style=color)

        # Description
        if self.status == TaskStatus.RUNNING:
            text.append(self.description, style="bold")
            # Show progress if available
            if self.total is not None and self.total > 0:
                self._render_progress(text)
            else:
                text.append("...", style="dim")
        elif self.status == TaskStatus.SUCCESS:
            text.append(self.description)
            if self.result_message:
                text.append(f": {self.result_message}", style="green")
        elif self.status == TaskStatus.FAILED:
            text.append(self.description)
            text.append(": FAILED", style="red bold")
            if self.failure_reason:
                text.append(f' → "{self.failure_reason}"', style="dim red")
        elif self.status == TaskStatus.WARNING:
            text.append(self.description)
            if self.result_message:
                text.append(f": {self.result_message}", style="yellow")
        else:  # PENDING
            text.append(self.description, style="dim")

        return text

    def _render_progress(self, text: Text) -> None:
        """Render progress bar inline.

        Args:
            text: Rich Text object to append progress to
        """
        if self.total is None or self.total == 0:
            return

        pct = (self.completed / self.total) * 100

        # Progress bar
        bar_width = 20
        filled = int(bar_width * pct / 100)
        bar_filled = "━" * filled
        bar_empty = "─" * (bar_width - filled)

        text.append(" [", style="dim")
        text.append(bar_filled, style="green")
        text.append(bar_empty, style="dim")
        text.append("]", style="dim")
        text.append(f" {pct:.0f}%", style="cyan")
        text.append(" • ", style="dim")
        text.append(f"{self.completed:,}/{self.total:,}", style="dim")

        # ETA
        eta = self._calculate_eta()
        if eta:
            text.append(" • ", style="dim")
            text.append(eta, style="dim")

    def _calculate_eta(self) -> str | None:
        """Calculate estimated time remaining.

        Returns:
            Formatted ETA string or None if unavailable
        """
        if self.total is None or self.completed == 0:
            return None

        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return None

        rate = self.completed / elapsed
        remaining = self.total - self.completed

        if rate > 0:
            eta_seconds = remaining / rate
            if eta_seconds < 60:
                return f"{eta_seconds:.0f}s remaining"
            if eta_seconds < 3600:
                minutes = int(eta_seconds // 60)
                seconds = int(eta_seconds % 60)
                return f"{minutes}m {seconds}s remaining"
            hours = int(eta_seconds // 3600)
            minutes = int((eta_seconds % 3600) // 60)
            return f"{hours}h {minutes}m remaining"
        return None

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, description, status, and progress info
        """
        return {
            "type": "task",
            "description": self.description,
            "status": self.status.name.lower(),
            "completed": self.completed,
            "total": self.total,
            "result": self.result_message,
            "reason": self.failure_reason,
        }
