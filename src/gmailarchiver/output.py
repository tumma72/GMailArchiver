"""Unified output system for all Gmail Archiver commands.

Provides consistent Rich-formatted terminal output and optional JSON output for scripting.
Supports progress tracking, task status, and actionable next-steps suggestions.
"""

import json
import sys
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich.console import Console
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
    ) -> Generator[Progress | None, None, None]:
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

        if self.quiet:
            return

        if not self.console:
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

        # Tabular report
        elif isinstance(data, Sequence) and data:
            # Get columns from first row
            first_row = data[0]
            table = Table(title=title)

            for col in first_row.keys():
                table.add_column(col, style="cyan")

            for row in data:
                table.add_row(*[str(v) for v in row.values()])

            self.console.print(table)

        # Show summary if provided
        if summary:
            self.console.print()
            for key, value in summary.items():
                self.console.print(f"[bold]{key}:[/bold] {value}")

        self.console.print()

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
            self._flush_json()
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

    def _flush_json(self) -> None:
        """Flush accumulated JSON events to stdout."""
        if self.json_mode:
            output = {"events": self._json_events, "timestamp": time.time()}
            print(json.dumps(output, indent=2))
            self._json_events = []
