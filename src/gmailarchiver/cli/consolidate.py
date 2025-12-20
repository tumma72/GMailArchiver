"""Consolidate command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import ReportCard, SuggestionList
from gmailarchiver.core.workflows.consolidate import ConsolidateConfig, ConsolidateWorkflow


async def consolidate_command(
    ctx: CommandContext,
    output_file: str,
    state_db: str,
    deduplicate: bool,
    sort_by_date: bool,
    compress: str | None,
    json_output: bool,
) -> None:
    """Async implementation of consolidate command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Archive emails first or import existing archives",
        )

    # Check if output file already exists
    output_path = Path(output_file)
    if output_path.exists():
        ctx.fail_and_exit(
            title="Output File Exists",
            message=f"Output file already exists: {output_file}",
            suggestion="Choose a different output file name or delete the existing file",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Get all archive files from database
    cursor = await ctx.storage.db._conn.execute("SELECT DISTINCT archive_file FROM messages")
    rows = await cursor.fetchall()
    archives = [row[0] for row in rows]

    if not archives:
        ctx.fail_and_exit(
            title="No Archives Found",
            message="No archives found in database",
            suggestion="Archive emails first or import existing archives",
        )
        return

    workflow = ConsolidateWorkflow(ctx.storage)
    config = ConsolidateConfig(
        source_files=archives,
        output_file=output_file,
        dedupe=deduplicate,
        sort_by_date=sort_by_date,
        compress=compress,
    )

    with ctx.ui.task_sequence() as seq:
        with seq.task("Consolidating archives") as t:
            try:
                result = await workflow.run(config)
                t.complete(f"Consolidated {result.messages_count:,} messages")
            except Exception as e:
                t.fail("Consolidation failed", reason=str(e))
                ctx.fail_and_exit(
                    title="Consolidation Failed",
                    message=f"Failed to consolidate archives: {e}",
                    suggestion="Check disk space and file permissions",
                )
                return

    # Display consolidation results
    (
        ReportCard("Consolidation Results")
        .add_field("Input Archives", str(result.source_files_count))
        .add_field("Messages Processed", f"{result.messages_count:,}")
        .add_field("Duplicates Removed", f"{result.duplicates_removed:,}" if deduplicate else "N/A")
        .add_field("Output File", result.output_file)
        .add_field("Sorted By Date", "Yes" if result.sort_applied else "No")
        .render(ctx.output)
    )

    # Success message
    ctx.success(
        f"Successfully consolidated {result.source_files_count} archives into {result.output_file}"
    )

    # Suggest next steps
    SuggestionList().add(
        f"Validate consolidated archive: gmailarchiver validate {result.output_file}"
    ).add("View updated status: gmailarchiver status").render(ctx.output)
