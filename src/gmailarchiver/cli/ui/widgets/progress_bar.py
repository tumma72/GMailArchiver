"""ProgressBarWidget - Workflow progress bar display."""

import time
from dataclasses import dataclass, field
from typing import Any, Self

from rich.text import Text

# Spinner frames (braille pattern)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@dataclass
class ProgressBarWidget:
    """Widget for displaying workflow progress bar.

    Supports both determinate (known total) and indeterminate progress.

    For determinate progress (known total):
        Shows: ⠹ Description [████████░░░░] 67% • 1,234/2,000 • 2m remaining

    For indeterminate progress (unknown total):
        Shows: ⠹ Description... (5s elapsed)

    Example (determinate):
        bar = ProgressBarWidget("Archiving messages", total=100)
        bar.advance(10)  # Shows progress bar
        text = bar.render(animation_frame=0)

    Example (indeterminate):
        bar = ProgressBarWidget("Authenticating with Gmail")
        text = bar.render(animation_frame=0)  # Shows spinner + elapsed time
    """

    description: str
    total: int | None = None
    completed: int = 0
    start_time: float = field(default_factory=time.time)
    bar_width: int = 12
    _is_complete: bool = False
    _complete_message: str | None = None
    _is_failed: bool = False
    _fail_message: str | None = None

    def set_total(self, total: int) -> Self:
        """Set total for determinate progress.

        Args:
            total: Total number of items to process

        Returns:
            Self for fluent chaining
        """
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

    def set_progress(self, completed: int, total: int | None = None) -> Self:
        """Set current progress.

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

    def complete(self, message: str | None = None) -> Self:
        """Mark progress as complete.

        Args:
            message: Optional completion message

        Returns:
            Self for fluent chaining
        """
        self._is_complete = True
        self._complete_message = message
        if self.total is not None:
            self.completed = self.total
        return self

    def fail(self, message: str | None = None) -> Self:
        """Mark progress as failed.

        Args:
            message: Optional failure message

        Returns:
            Self for fluent chaining
        """
        self._is_failed = True
        self._fail_message = message
        return self

    @property
    def is_running(self) -> bool:
        """Check if progress is still running.

        Returns:
            True if still running, False if complete or failed
        """
        return not self._is_complete and not self._is_failed

    def render(self, animation_frame: int = 0) -> Text:
        """Render progress bar to Rich Text.

        Args:
            animation_frame: Current animation frame for spinner (0-9)

        Returns:
            Rich Text object ready for display
        """
        text = Text()

        # Status symbol
        if self._is_complete:
            text.append("✓ ", style="green")
        elif self._is_failed:
            text.append("✗ ", style="red")
        else:
            spinner = SPINNER_FRAMES[animation_frame % len(SPINNER_FRAMES)]
            text.append(f"{spinner} ", style="cyan")

        # Description
        if self._is_complete:
            text.append(self.description)
            if self._complete_message:
                text.append(f": {self._complete_message}", style="green")
            return text

        if self._is_failed:
            text.append(self.description)
            if self._fail_message:
                text.append(f": {self._fail_message}", style="red")
            return text

        # Running state
        text.append(self.description, style="bold")

        if self.total is not None and self.total > 0:
            # Determinate progress bar
            self._render_bar(text)
        else:
            # Indeterminate - show elapsed time
            text.append("...", style="dim")
            elapsed = time.time() - self.start_time
            text.append(f" ({self._format_elapsed(elapsed)})", style="dim")

        return text

    def _render_bar(self, text: Text) -> None:
        """Render the progress bar portion.

        Args:
            text: Rich Text object to append bar to
        """
        if self.total is None or self.total == 0:
            return

        pct = min((self.completed / self.total) * 100, 100)  # Cap at 100%

        # Progress bar
        filled = int(self.bar_width * pct / 100)
        bar_filled = "━" * filled
        bar_empty = "─" * (self.bar_width - filled)

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

        if rate > 0 and remaining > 0:
            eta_seconds = remaining / rate
            return self._format_time(eta_seconds) + " remaining"
        return None

    def _format_elapsed(self, seconds: float) -> str:
        """Format elapsed time.

        Args:
            seconds: Number of seconds elapsed

        Returns:
            Human-readable elapsed time string
        """
        return self._format_time(seconds) + " elapsed"

    def _format_time(self, seconds: float) -> str:
        """Format time in human-readable form.

        Args:
            seconds: Number of seconds

        Returns:
            Formatted time string (e.g., "2m 30s", "1h 15m")
        """
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with progress information
        """
        return {
            "type": "progress_bar",
            "description": self.description,
            "completed": self.completed,
            "total": self.total,
            "percent": (self.completed / self.total * 100) if self.total else None,
            "is_complete": self._is_complete,
            "is_failed": self._is_failed,
            "complete_message": self._complete_message,
            "fail_message": self._fail_message,
        }
