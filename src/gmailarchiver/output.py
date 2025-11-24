"""Unified output system for all Gmail Archiver commands.

Provides consistent Rich-formatted terminal output and optional JSON output for scripting.
Supports progress tracking, task status, and actionable next-steps suggestions.
"""

import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text


@dataclass
class SearchResultEntry:
    """A single search result entry."""
    gmail_id: str
    rfc_message_id: str
    subject: str
    from_addr: str
    to_addr: str | None
    date: str
    body_preview: str | None
    archive_file: str
    mbox_offset: int
    relevance_score: float | None


@dataclass
class LogEntry:
    """A single log entry with metadata for deduplication and display."""
    timestamp: float
    level: str  # INFO, WARNING, ERROR, SUCCESS
    message: str
    count: int = 1  # Number of times this message appeared (for deduplication)


class LogBuffer:
    """Ring buffer for log messages with deduplication and Rich rendering.

    Used by LiveLayoutContext to display scrolling log messages in a fixed-size
    window. Supports:
    - FIFO ring buffer (fixed max_visible size)
    - Message deduplication (by message text)
    - Severity symbols (ℹ, ⚠, ✗, ✓)
    - Duplicate count display (x2, x3, etc.)
    - Separate storage for all logs (for session logging)

    This is part of v1.3.1's live layout system for flicker-free progress display.
    """

    SEVERITY_MAP = {
        "INFO": ("ℹ", "blue"),
        "WARNING": ("⚠", "yellow"),
        "ERROR": ("✗", "red"),
        "SUCCESS": ("✓", "green"),
    }

    def __init__(self, max_visible: int = 10) -> None:
        """Initialize LogBuffer.

        Args:
            max_visible: Maximum number of log entries to show in UI.
                         Set to 0 to disable visible buffer (store all in all_logs only).

        Raises:
            ValueError: If max_visible is negative.
        """
        if max_visible < 0:
            raise ValueError("max_visible must be non-negative")

        self._max_visible = max_visible
        self._visible: deque[LogEntry] = deque(maxlen=max_visible if max_visible > 0 else None)
        self._all_logs: list[LogEntry] = []
        self._entry_map: dict[str, LogEntry] = {}  # Message text -> LogEntry

    def add(self, message: str, level: str = "INFO") -> None:
        """Add a log entry with deduplication.

        If the message already exists:
        - Increment its count
        - Update its timestamp
        - Re-add to visible buffer if it was evicted

        Args:
            message: Log message text.
            level: Severity level (INFO, WARNING, ERROR, SUCCESS).
        """
        if message in self._entry_map:
            # Duplicate: update existing entry
            entry = self._entry_map[message]
            entry.count += 1
            entry.timestamp = time.time()

            # If evicted from visible buffer, re-add it
            if self._max_visible > 0 and entry not in self._visible:
                self._visible.append(entry)
        else:
            # New entry
            entry = LogEntry(timestamp=time.time(), level=level, message=message)
            self._entry_map[message] = entry
            self._all_logs.append(entry)

            # Add to visible buffer if enabled
            if self._max_visible > 0:
                self._visible.append(entry)

    def render(self) -> Group:
        """Render visible logs as Rich Group with severity symbols.

        Returns:
            Rich Group containing formatted log entries.
        """
        renderables = []
        for entry in self._visible:
            symbol, color = self.SEVERITY_MAP.get(entry.level, ("?", "white"))
            count_str = f" [dim](x{entry.count})[/dim]" if entry.count > 1 else ""
            text = Text.from_markup(f"[{color}]{symbol}[/{color}] {entry.message}{count_str}")
            renderables.append(text)
        return Group(*renderables)

    def get_all_logs(self) -> list[LogEntry]:
        """Get a copy of all log entries (for session logging).

        Returns:
            Copy of all log entries (not just visible ones).
        """
        return self._all_logs.copy()

    def clear(self) -> None:
        """Clear all log entries."""
        self._visible.clear()
        self._all_logs.clear()
        self._entry_map.clear()


class LiveLayoutContext:
    """Flicker-free live layout for progress tracking with integrated logging.

    Combines Rich Live display with LogBuffer and SessionLogger for a clean,
    professional output experience. Used as a context manager to ensure proper
    cleanup.

    Features:
    - Flicker-free updates via Rich Live
    - Integrated log display (LogBuffer) + session logging (SessionLogger)
    - Automatic component initialization
    - Context manager support

    This is part of v1.3.1's live layout system to fix flickering progress bars.
    """

    def __init__(
        self,
        log_buffer: LogBuffer | None = None,
        session_logger: SessionLogger | None = None,
        max_visible: int = 10,
        log_dir: Path | None = None,
    ) -> None:
        """Initialize LiveLayoutContext.

        Args:
            log_buffer: LogBuffer instance (creates default if None)
            session_logger: SessionLogger instance (creates default if None)
            max_visible: Max visible log lines (if creating default LogBuffer)
            log_dir: Log directory for SessionLogger (if creating default)
        """
        # Create or use provided components
        if log_buffer is not None:
            self.log_buffer = log_buffer
        else:
            self.log_buffer = LogBuffer(max_visible=max_visible)

        if session_logger is not None:
            self.session_logger = session_logger
        else:
            self.session_logger = SessionLogger(log_dir=log_dir)

    def add_log(self, message: str, level: str = "INFO") -> None:
        """Add log entry to both LogBuffer (UI) and SessionLogger (file).

        Args:
            message: Log message text
            level: Severity level (INFO, WARNING, ERROR, SUCCESS, DEBUG)
        """
        # Add to visible log buffer (for UI)
        self.log_buffer.add(message, level)

        # Write to session log file (for debugging)
        self.session_logger.write(message, level)

    def __enter__(self) -> LiveLayoutContext:
        """Context manager entry - starts live layout."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures SessionLogger is closed."""
        self.session_logger.close()


class SessionLogger:
    """Persistent file logger for debugging and audit trail.

    Writes ALL log entries (including DEBUG) to a timestamped file for
    post-session analysis. Complements LogBuffer which only shows last N
    visible logs in the UI.

    Features:
    - XDG-compliant log directory (~/.config/gmailarchiver/logs)
    - Timestamped session files (session_YYYY-MM-DD_HHMMSS.log)
    - Automatic cleanup of old log files
    - Immediate flush for real-time debugging
    - Context manager support

    This is part of v1.3.1's live layout system for comprehensive debugging.
    """

    @staticmethod
    def _get_default_log_dir() -> Path:
        """Get default log directory following XDG Base Directory standard.

        Returns:
            Path to log directory:
            - Linux/macOS: ~/.config/gmailarchiver/logs
            - Windows: %APPDATA%/gmailarchiver/logs
        """
        # Respect XDG_CONFIG_HOME if set (Linux/macOS)
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home:
            config_dir = Path(config_home)
        elif os.name == "nt":  # Windows
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:  # macOS/Linux
            config_dir = Path.home() / ".config"

        # Create gmailarchiver/logs subdirectory
        log_dir = config_dir / "gmailarchiver" / "logs"
        return log_dir

    def __init__(self, log_dir: Path | None = None, keep_last: int = 10) -> None:
        """Initialize SessionLogger.

        Args:
            log_dir: Directory for log files (None = use XDG default)
            keep_last: Number of old log files to keep (0 = keep all)

        Raises:
            PermissionError: If directory cannot be created
            OSError: If directory path is invalid
        """
        # Determine log directory
        if log_dir is None:
            self.log_dir = self._get_default_log_dir()
        else:
            self.log_dir = log_dir

        # Create directory if needed
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}.log"

        # Open file handle
        self._file_handle: TextIO = self.log_file.open("w", encoding="utf-8")
        self._closed = False

        # Cleanup old logs if requested
        if keep_last > 0:
            self._cleanup_old_logs(keep_last)

    def write(self, message: str, level: str = "INFO") -> None:
        """Write a log entry with timestamp and severity.

        Args:
            message: Log message text
            level: Severity level (DEBUG, INFO, WARNING, ERROR, SUCCESS)

        Raises:
            ValueError: If logger is closed
            OSError: If write fails (disk full, etc.)
        """
        if self._closed:
            raise ValueError("Cannot write to closed SessionLogger")

        # Format: YYYY-MM-DD HH:MM:SS.mmm [LEVEL] message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"{timestamp} [{level}] {message}\n"

        # Write and flush immediately for real-time debugging
        self._file_handle.write(log_line)
        self._file_handle.flush()

    def close(self) -> None:
        """Close the log file handle.

        Safe to call multiple times.
        """
        if not self._closed:
            self._file_handle.close()
            self._closed = True

    def __enter__(self) -> SessionLogger:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures file is closed."""
        self.close()

    def _cleanup_old_logs(self, keep_last: int) -> None:
        """Remove old log files beyond retention limit.

        Args:
            keep_last: Number of old log files to keep (most recent)
        """
        # Find all session log files (exclude current session)
        all_logs = sorted(
            [f for f in self.log_dir.glob("session_*.log") if f != self.log_file],
            key=lambda p: p.stat().st_mtime,
        )

        # Remove oldest files beyond retention limit
        files_to_remove = all_logs[: -keep_last] if len(all_logs) > keep_last else []

        for old_log in files_to_remove:
            try:
                old_log.unlink()
            except OSError:
                # Ignore errors during cleanup (file might be in use, etc.)
                pass


class ProgressTracker:
    """Tracks progress with ETA calculation and rate smoothing.

    Provides:
    - ETA (Estimated Time of Arrival) calculation
    - Elapsed time tracking
    - Rate calculation with exponential moving average
    - Format strings: [elapsed<remaining, rate]
    - Configurable units (msg/s, MB/s, items/s)
    """

    # Minimum number of items before showing ETA
    MIN_SAMPLES = 5

    # Exponential moving average smoothing factor
    SMOOTHING_FACTOR = 0.3

    def __init__(self, total: int | None = None, unit: str = "items") -> None:
        """Initialize progress tracker.

        Args:
            total: Total number of items to process (None if unknown)
            unit: Unit name for rate display (msg, MB, items, etc.)
        """
        self.total = total
        self.unit = unit
        self.completed = 0
        self._start_time: float | None = None
        self._last_update_time: float | None = None
        self._smoothed_rate: float | None = None

    def start(self) -> None:
        """Start tracking progress."""
        self._start_time = time.perf_counter()
        self._last_update_time = self._start_time
        self.completed = 0
        self._smoothed_rate = None

    def update(
        self,
        amount: int | None = None,
        *,
        completed: int | None = None,
        advance: int | None = None,
    ) -> None:
        """Update progress and recalculate rate.

        Args:
            amount: Positional increment value (shorthand for ``advance``).
            completed: Set new total completed count.
            advance: Amount to increment ``completed`` by.

        Exactly one of ``amount``, ``completed``, or ``advance`` should be
        provided. The positional ``amount`` parameter is primarily for
        convenience in tests and simple callers.
        """
        # Resolve which parameter was provided
        provided = [p is not None for p in (amount, completed, advance)]
        if sum(provided) == 0:
            return
        if sum(provided) > 1:
            raise ValueError("Specify only one of amount, completed, or advance")

        if amount is not None:
            # Positional argument behaves like an advance increment
            self.completed += amount
        elif completed is not None:
            self.completed = completed
        elif advance is not None:
            self.completed += advance

        # Update rate calculation
        self._update_rate()

    def _update_rate(self) -> None:
        """Update smoothed rate using exponential moving average."""
        if self._start_time is None or self.completed == 0:
            return

        current_time = time.perf_counter()
        elapsed = current_time - self._start_time

        # Avoid division by zero
        if elapsed <= 0:
            return

        # Calculate current rate
        current_rate = self.completed / elapsed

        # Apply exponential moving average
        if self._smoothed_rate is None:
            # First rate calculation
            self._smoothed_rate = current_rate
        else:
            # Smooth with previous rate
            self._smoothed_rate = (
                self.SMOOTHING_FACTOR * current_rate
                + (1 - self.SMOOTHING_FACTOR) * self._smoothed_rate
            )

        self._last_update_time = current_time

    def get_elapsed(self) -> float:
        """Get elapsed time in seconds.

        Returns:
            Elapsed seconds since start (0 if not started)
        """
        if self._start_time is None:
            return 0.0

        elapsed = time.perf_counter() - self._start_time
        # Never return negative (handle clock adjustments)
        return max(0.0, elapsed)

    def get_elapsed_formatted(self) -> str:
        """Get formatted elapsed time string.

        Returns:
            Time string in format MM:SS or HH:MM:SS
        """
        elapsed = self.get_elapsed()
        return self._format_time(elapsed)

    def calculate_eta(self) -> float | None:
        """Calculate estimated time of arrival (time remaining).

        Returns:
            Estimated seconds remaining, or None if not enough data
        """
        # Need to know total to calculate ETA
        if self.total is None:
            return None

        # Need minimum samples
        if self.completed < self.MIN_SAMPLES:
            return None

        # Need valid rate
        rate = self.get_rate()
        if rate is None or rate <= 0:
            return None

        # Already complete or past total
        if self.completed >= self.total:
            return None

        # Calculate remaining items and time
        remaining_items = self.total - self.completed
        eta = remaining_items / rate

        return max(0.0, eta)

    def get_eta_formatted(self) -> str:
        """Get formatted ETA string.

        Returns:
            Time string in format MM:SS or HH:MM:SS, or empty if no ETA
        """
        eta = self.calculate_eta()
        if eta is None:
            return ""
        return self._format_time(eta)

    def get_rate(self) -> float | None:
        """Get current smoothed processing rate.

        Returns:
            Items per second, or None if not enough data
        """
        if self._start_time is None or self.completed == 0:
            return None

        return self._smoothed_rate

    def get_rate_formatted(self) -> str:
        """Get formatted rate string.

        Returns:
            Rate string like "5.00 msg/s" or empty if no rate
        """
        rate = self.get_rate()
        if rate is None:
            return ""

        return f"{rate:.2f} {self.unit}/s"

    def get_progress_string(self) -> str:
        """Get complete progress string with elapsed, ETA, and rate.

        Returns:
            Format: [elapsed<remaining, rate] or [elapsed] if no ETA
            Example: [00:30<00:30, 5.00 msg/s]
        """
        if self._start_time is None:
            return ""

        elapsed_str = self.get_elapsed_formatted()
        eta_str = self.get_eta_formatted()
        rate_str = self.get_rate_formatted()

        if eta_str and rate_str:
            # Full format: [elapsed<eta, rate]
            return f"[{elapsed_str}<{eta_str}, {rate_str}]"
        elif rate_str:
            # No ETA yet, but have rate: [elapsed, rate]
            return f"[{elapsed_str}, {rate_str}]"
        else:
            # Only elapsed time
            return f"[{elapsed_str}]"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as MM:SS or HH:MM:SS.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"


@dataclass
class TaskResult:
    """Result of a completed task."""

    name: str
    success: bool
    details: str | None = None
    elapsed: float | None = None


class OutputManager:
    """Unified output system for all commands.

    Provides:
    - Rich terminal output with progress bars and status indicators
    - JSON output mode for scripting
    - Structured logging
    - Next-steps suggestions
    - Consistent error formatting
    """

    def __init__(self, json_mode: bool = False, quiet: bool = False) -> None:
        """Initialize output manager.

        Args:
            json_mode: Output structured JSON instead of Rich terminal output
            quiet: Suppress all output except errors
        """
        self.json_mode = json_mode
        self.quiet = quiet
        self.console = Console() if not json_mode else None
        self._completed_tasks: list[TaskResult] = []
        self._json_events: list[dict[str, Any]] = []
        # Optional top-level JSON payload for commands that want to control
        # the exact JSON output shape (e.g., search results as a list).
        self._json_payload: Any | None = None
        self._operation_start_time: float | None = None

    def start_operation(self, name: str, description: str | None = None) -> None:
        """Start a new operation.

        Args:
            name: Operation name (e.g., "validate", "import")
            description: Optional description shown to user
        """
        self._operation_start_time = time.time()
        self._completed_tasks = []

        if self.json_mode:
            self._json_events.append(
                {"event": "operation_start", "operation": name, "description": description}
            )
        elif not self.quiet and self.console:
            msg = f"[bold blue]{name}[/bold blue]"
            if description:
                msg += f": {description}"
            self.console.print(f"\n{msg}\n")

    @contextmanager
    def progress_context(
        self, description: str, total: int | None = None
    ) -> Generator[Progress | None]:
        """Context manager for progress tracking with live updates.

        Shows:
        - Spinner with current operation
        - Progress bar with ETA (if total known)
        - Completed tasks with ✓/✗ status

        Args:
            description: Description of work being done
            total: Total units of work (if known)

        Yields:
            Progress object for tracking

        Example:
            with output.progress_context("Validating messages", total=1000) as progress:
                task = progress.add_task("Checking...", total=1000)
                for i in range(1000):
                    # Do work
                    progress.update(task, advance=1)
        """
        if self.json_mode:
            # In JSON mode, just track events without live display
            self._json_events.append(
                {"event": "progress_start", "description": description, "total": total}
            )
            yield None
            self._json_events.append({"event": "progress_end", "description": description})
            return

        if self.quiet:
            yield None
            return

        # Create progress bar with all components
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn() if total else TextColumn("[progress.percentage]{task.completed}"),
            TimeElapsedColumn(),
            TimeRemainingColumn() if total else TextColumn(""),
            console=self.console,
        )

        # Create panel showing completed tasks
        def make_status_panel() -> Panel:
            """Create panel showing completed task status."""
            if not self._completed_tasks:
                return Panel("", title="Status", border_style="dim")

            table = Table.grid(padding=(0, 2))
            table.add_column(style="green", no_wrap=True)
            table.add_column()

            for task in self._completed_tasks[-10:]:  # Show last 10 tasks
                icon = "✓" if task.success else "✗"
                style = "green" if task.success else "red"
                elapsed_str = f" ({task.elapsed:.1f}s)" if task.elapsed else ""
                table.add_row(
                    f"[{style}]{icon}[/{style}]",
                    f"{task.name}{elapsed_str}",
                )

            return Panel(table, title="Completed Tasks", border_style="dim")

        # Use Live context to update both progress and status panel
        with Live(
            progress, console=self.console, refresh_per_second=10, transient=False
        ) as live:
            # Store live context for task_complete to update panel
            self._live: Live | None = live
            self._progress: Progress | None = progress
            self._make_status_panel: Callable[[], Panel] | None = make_status_panel

            yield progress

            # Clear live context
            self._live = None
            self._progress = None

    @contextmanager
    def live_layout_context(
        self, max_visible: int = 10, log_dir: Path | None = None
    ) -> Generator[LiveLayoutContext]:
        """Context manager for flicker-free live layout with integrated logging.

        Provides:
        - LogBuffer (last N visible log lines)
        - SessionLogger (persistent file logging)
        - Clean automatic cleanup

        Args:
            max_visible: Max visible log lines (default: 10)
            log_dir: Log directory for SessionLogger (default: XDG-compliant)

        Yields:
            LiveLayoutContext instance for logging

        Example:
            with output.live_layout_context() as live:
                live.add_log("Processing started", "INFO")
                # Do work...
                live.add_log("Processing complete", "SUCCESS")
        """
        live_context = LiveLayoutContext(max_visible=max_visible, log_dir=log_dir)
        with live_context:
            yield live_context

    def task_complete(
        self, name: str, success: bool, details: str | None = None, elapsed: float | None = None
    ) -> None:
        """Mark a task as complete.

        Args:
            name: Task name
            success: Whether task succeeded
            details: Optional details (shown on failure)
            elapsed: Optional elapsed time in seconds
        """
        result = TaskResult(name=name, success=success, details=details, elapsed=elapsed)
        self._completed_tasks.append(result)

        if self.json_mode:
            self._json_events.append(
                {
                    "event": "task_complete",
                    "task": name,
                    "success": success,
                    "details": details,
                    "elapsed": elapsed,
                }
            )
        elif not self.quiet:
            # Update live display if in progress context
            if hasattr(self, "_live") and self._live and hasattr(self, "_make_status_panel"):
                # Regenerate status panel to show updated task list
                if hasattr(self, "_progress") and self._progress:
                    self._live.update(self._progress)

    def show_report(
        self,
        title: str,
        data: dict[str, Any] | Sequence[dict[str, Any]],
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Show a report table or summary.

        Args:
            title: Report title
            data: Data to display (dict for key-value, list for table)
            summary: Optional summary data shown below table
        """
        if self.json_mode:
            self._json_events.append(
                {"event": "report", "title": title, "data": data, "summary": summary}
            )
            return

        if self.quiet or not self.console:
            return

        self.console.print()

        # Key-value report
        if isinstance(data, dict):
            table = Table(title=title, show_header=False, box=None)
            table.add_column("Key", style="cyan", no_wrap=True)
            table.add_column("Value")

            for key, value in data.items():
                table.add_row(key, str(value))

            self.console.print(table)

        # Tabular report (list of dicts or rows)
        elif isinstance(data, Sequence) and data:
            first_row = data[0]

            # If we have a list of dicts, use keys from first row as headers
            if isinstance(first_row, dict):
                headers = list(first_row.keys())
                rows: list[list[Any]] = [
                    [row.get(col, "") for col in headers] for row in data
                ]
            else:
                # Fallback: infer column count from first row and use generic headers
                headers = [f"col{i+1}" for i in range(len(first_row))]
                rows = [list(row) for row in data]

            self.show_table(title=title, headers=headers, rows=rows)

        # Show summary if provided
        if summary:
            self.console.print()
            for key, value in summary.items():
                self.console.print(f"[bold]{key}:[/bold] {value}")

        self.console.print()

    def show_table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        """Render a Rich table from structured data.

        This helper centralizes table rendering logic so that commands can
        pass plain headers/rows and let the OutputManager handle both Rich
        output and JSON/quiet modes.

        Args:
            title: Optional table title
            headers: Column headers
            rows: Table rows (each row is a sequence of values)
        """
        if self.json_mode:
            self._json_events.append(
                {
                    "event": "table",
                    "title": title,
                    "headers": list(headers),
                    "rows": [[str(value) for value in row] for row in rows],
                }
            )
            return

        if self.quiet or not self.console:
            return

        table = Table(title=title)
        for header in headers:
            table.add_column(header, style="cyan")

        for row in rows:
            table.add_row(*[str(value) for value in row])

        self.console.print(table)

    def suggest_next_steps(self, suggestions: Sequence[str]) -> None:
        """Show actionable next steps.

        Args:
            suggestions: List of suggested commands or actions
        """
        if self.json_mode:
            self._json_events.append({"event": "next_steps", "suggestions": list(suggestions)})
            return

        if self.quiet or not self.console:
            return

        self.console.print("\n[bold cyan]Next steps:[/bold cyan]")
        for i, suggestion in enumerate(suggestions, 1):
            self.console.print(f"  {i}. {suggestion}")
        self.console.print()

    def set_json_payload(self, payload: Any) -> None:
        """Set explicit JSON payload for this operation.

        When a payload is set, :meth:`end_operation` will flush this payload
        as the top-level JSON value instead of the default "events" wrapper.
        """
        self._json_payload = payload

    def error(self, message: str, suggestion: str | None = None, exit_code: int = 1) -> None:
        """Show error message with optional suggestion.

        Args:
            message: Error message
            suggestion: Optional suggested fix
            exit_code: Exit code (0 = don't exit, >0 = exit with code)
        """
        if self.json_mode:
            self._json_events.append(
                {"event": "error", "message": message, "suggestion": suggestion}
            )
            if exit_code > 0:
                self._flush_json()
                sys.exit(exit_code)
            return

        if self.console:
            self.console.print(f"\n[bold red]Error:[/bold red] {message}")
            if suggestion:
                self.console.print(f"[yellow]Suggestion:[/yellow] {suggestion}\n")

        if exit_code > 0:
            sys.exit(exit_code)

    def success(self, message: str) -> None:
        """Show success message.

        Args:
            message: Success message
        """
        if self.json_mode:
            self._json_events.append({"event": "success", "message": message})
            return

        if self.quiet or not self.console:
            return

        self.console.print(f"\n[bold green]✓[/bold green] {message}\n")

    def warning(self, message: str) -> None:
        """Show warning message.

        Args:
            message: Warning message
        """
        if self.json_mode:
            self._json_events.append({"event": "warning", "message": message})
            return

        if self.quiet or not self.console:
            return

        self.console.print(f"[bold yellow]⚠[/bold yellow]  {message}")

    def info(self, message: str) -> None:
        """Show informational message.

        Args:
            message: Info message
        """
        if self.json_mode:
            self._json_events.append({"event": "info", "message": message})
            return

        if self.quiet or not self.console:
            return

        if self.console:
            self.console.print(message)

    def end_operation(self, success: bool, summary: str | None = None) -> None:
        """End the current operation.

        Args:
            success: Whether operation succeeded overall
            summary: Optional summary message
        """
        if self._operation_start_time:
            elapsed = time.time() - self._operation_start_time
        else:
            elapsed = None

        if self.json_mode:
            self._json_events.append(
                {
                    "event": "operation_end",
                    "success": success,
                    "summary": summary,
                    "elapsed": elapsed,
                }
            )
            self._flush_json(success=success)
            return

        if self.quiet:
            return

        if not self.console:
            return

        # Show final status
        if success:
            icon = "✓"
            style = "green"
            status = "COMPLETED"
        else:
            icon = "✗"
            style = "red"
            status = "FAILED"

        elapsed_str = f" ({elapsed:.1f}s)" if elapsed else ""
        self.console.print(f"\n[bold {style}]{icon} {status}[/bold {style}]{elapsed_str}")

        if summary:
            self.console.print(f"{summary}\n")

    def _flush_json(self, success: bool | None = None) -> None:
        """Flush accumulated JSON events to stdout.

        If a JSON payload has been set via :meth:`set_json_payload`, that
        payload is emitted as the top-level JSON value. Otherwise, a default
        object containing events and status information is emitted.
        """
        if not self.json_mode:
            return

        # If a payload is explicitly provided (e.g. search results), emit it
        # directly so callers can rely on a stable top-level shape.
        if self._json_payload is not None:
            print(json.dumps(self._json_payload, indent=2))
            self._json_payload = None
            self._json_events = []
            return

        # Default: emit structured events with high-level status
        output: dict[str, Any] = {
            "events": self._json_events,
            "timestamp": time.time(),
        }
        if success is not None:
            output["success"] = success
            output["status"] = "ok" if success else "error"

        print(json.dumps(output, indent=2))
        self._json_events = []
