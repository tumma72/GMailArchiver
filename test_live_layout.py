#!/usr/bin/env python3
"""Test script for live layout display with dummy data.

This demonstrates what the user should see during archiving:
- Progress bar showing overall progress
- 10-row scrolling log buffer with message processing
- Severity icons (ℹ ⚠ ✗ ✓)
- Message deduplication with counts (x2, x3, etc.)
"""

import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.layout import Layout

# Import from gmailarchiver
from gmailarchiver.output import LogBuffer, SessionLogger, LiveLayoutContext


def create_live_display(log_buffer: LogBuffer, progress: Progress, task_id: int) -> Layout:
    """Create Rich layout with progress bar + scrolling log.

    Returns:
        Layout with two sections:
        - Top: Progress bar
        - Bottom: Log table (10 rows)
    """
    layout = Layout()
    layout.split_column(
        Layout(name="progress", size=3),
        Layout(name="logs", size=12)
    )

    # Top section: Progress bar
    layout["progress"].update(Panel(progress, title="Archive Progress", border_style="blue"))

    # Bottom section: Use LogBuffer's render() method
    log_display = log_buffer.render()
    layout["logs"].update(Panel(log_display, title="Processing Log", border_style="green"))

    return layout


def simulate_archiving():
    """Simulate the archiving process with dummy data."""
    console = Console()

    # Create components
    log_buffer = LogBuffer(max_visible=10)
    session_logger = SessionLogger(log_dir=Path("/tmp/gmailarchiver_test"))

    # Create progress bar
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False
    )
    task_id = progress.add_task("Archiving messages", total=20)

    # Simulate archiving with live display
    with Live(create_live_display(log_buffer, progress, task_id), refresh_per_second=4, console=console) as live:
        # Simulate initial messages
        log_buffer.add("Starting archiving process...", "INFO")
        session_logger.write("Starting archiving process...", "INFO")
        time.sleep(0.5)

        log_buffer.add("Connecting to Gmail API...", "INFO")
        session_logger.write("Connecting to Gmail API...", "INFO")
        live.update(create_live_display(log_buffer, progress, task_id))
        time.sleep(0.5)

        log_buffer.add("Found 20 messages to archive", "INFO")
        session_logger.write("Found 20 messages to archive", "INFO")
        live.update(create_live_display(log_buffer, progress, task_id))
        time.sleep(0.5)

        # Simulate processing 20 messages
        for i in range(1, 21):
            # Random message subjects
            subjects = [
                "Important Meeting Notes",
                "Project Update Q3",
                "Budget Review",
                "Team Sync",
                "Weekly Report",
                "Action Items",
                "Follow-up Discussion",
                "Quarterly Review",
                "Design Proposal",
                "Code Review Request"
            ]
            subject = subjects[i % len(subjects)]

            # Simulate different outcomes
            if i % 7 == 0:
                # Simulate error
                log_buffer.add(f"✗ Failed to archive message {i}: Network timeout", "ERROR")
                session_logger.write(f"Failed to archive message {i}: Network timeout", "ERROR")
            elif i % 5 == 0:
                # Simulate warning (duplicate)
                log_buffer.add(f"⚠ Skipping duplicate: {subject}", "WARNING")
                session_logger.write(f"Skipping duplicate: {subject}", "WARNING")
            else:
                # Success
                log_buffer.add(f"✓ Archived: {subject}", "SUCCESS")
                session_logger.write(f"Archived: {subject}", "SUCCESS")

            progress.update(task_id, advance=1)
            live.update(create_live_display(log_buffer, progress, task_id))
            time.sleep(0.3)  # Simulate processing time

        # Final message
        log_buffer.add("Archiving complete!", "SUCCESS")
        session_logger.write("Archiving complete!", "SUCCESS")
        live.update(create_live_display(log_buffer, progress, task_id))
        time.sleep(1)

    session_logger.close()
    console.print("\n✓ Live layout test complete!", style="bold green")
    console.print(f"Session log written to: {session_logger.log_file}")


if __name__ == "__main__":
    simulate_archiving()
