"""Status command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import CLIProgressAdapter
from gmailarchiver.cli.ui.widgets import ReportCard, TableWidget
from gmailarchiver.core.workflows.status import StatusConfig, StatusWorkflow
from gmailarchiver.shared.utils import format_bytes


@with_context(requires_storage=True, requires_schema="1.1", operation_name="status")
def status(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show more detail"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Show archiving status and statistics.

    Displays database size, schema version, message counts, and recent archive runs.
    Use --verbose for more detail about recent runs.

    Examples:
        $ gmailarchiver status
        $ gmailarchiver status --verbose
        $ gmailarchiver status --json
    """
    asyncio.run(_run_status(ctx=ctx, verbose=verbose, json_output=json_output))


async def _run_status(
    ctx: CommandContext,
    verbose: bool,
    json_output: bool,
) -> None:
    """Async implementation of status command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Create workflow and config
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = StatusWorkflow(ctx.storage, progress=progress)
    config = StatusConfig(verbose=verbose, runs_limit=5)

    # Execute workflow
    try:
        with progress.workflow_sequence(show_logs=False):
            result = await workflow.run(config)
    except Exception as e:
        ctx.fail_and_exit(
            title="Status Error",
            message=f"Failed to retrieve status: {e}",
            suggestion="Check database file integrity or run 'gmailarchiver doctor'",
        )

    # Handle JSON output
    if json_output:
        ctx.output.set_json_payload(
            {
                "schema_version": result.schema_version,
                "database_size_bytes": result.database_size_bytes,
                "total_messages": result.total_messages,
                "archive_files_count": result.archive_files_count,
                "archive_files": result.archive_files,
                "recent_runs": result.recent_runs,
            }
        )
        return

    # Display report card with main statistics
    report = ReportCard("Archive Status")
    report.add_field("Schema Version", result.schema_version)
    report.add_field("Database Size", format_bytes(result.database_size_bytes))
    report.add_field("Total Messages", f"{result.total_messages:,}")

    # Show archive files with detail based on verbosity
    if result.archive_files:
        if verbose:
            files_display = f"{result.archive_files_count} (latest: {result.archive_files[-1]})"
        elif result.archive_files_count == 1:
            files_display = f"1 ({result.archive_files[0]})"
        else:
            files_display = str(result.archive_files_count)
    else:
        files_display = "0"
    report.add_field("Archive Files", files_display)

    report.render(ctx.output)

    # Display recent runs table
    if result.recent_runs:
        _display_recent_runs_table(ctx, result.recent_runs, verbose)
    else:
        ctx.warning("No archive runs found")


def _display_recent_runs_table(
    ctx: CommandContext,
    runs: list[dict[str, object]],
    verbose: bool,
) -> None:
    """Display recent archive runs in a table.

    Column order: Timestamp, Messages, Archive, [Query in verbose mode]
    """
    limit = 10 if verbose else 5
    runs_to_show = runs[:limit]

    table = TableWidget(title=f"Recent Archive Runs (Last {len(runs_to_show)})")

    # Add columns in order: Timestamp, Messages, Archive, [Query]
    table.add_column("Timestamp", content="cut", max_width=19)
    table.add_column("Messages", content="cut", max_width=10)
    table.add_column("Archive", content="cut", ratio=2)

    if verbose:
        table.add_column("Query", content="cut", ratio=1)

    # Add rows
    for run in runs_to_show:
        timestamp = str(run.get("run_timestamp", ""))[:19]
        messages = str(run.get("messages_archived", 0))
        archive = str(run.get("archive_file", ""))

        if verbose:
            query = str(run.get("query", ""))[:30] if run.get("query") else ""
            table.add_row(timestamp, messages, archive, query)
        else:
            table.add_row(timestamp, messages, archive)

    table.render_to_output(ctx.output)
