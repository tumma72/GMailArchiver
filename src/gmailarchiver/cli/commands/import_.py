"""Import command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import CLIProgressAdapter, ReportCard, SuggestionList
from gmailarchiver.core.workflows.import_ import ImportConfig, ImportResult, ImportWorkflow


@with_context(requires_storage=True, has_progress=True, operation_name="import")
def import_(
    ctx: CommandContext,
    archive_pattern: str = typer.Argument(
        ..., help="Archive file path or glob pattern (e.g., 'archives/*.mbox.gz')"
    ),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    deduplicate: bool = typer.Option(
        True, "--deduplicate/--no-deduplicate", help="Skip duplicate messages"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Import existing mbox files into database.

    Supports glob patterns and all compression formats (gzip, lzma, zstd).
    Automatically deduplicates messages based on Message-ID.

    Examples:
        $ gmailarchiver utilities import archive.mbox
        $ gmailarchiver utilities import "archives/*.mbox.gz"
        $ gmailarchiver utilities import archive.mbox --no-deduplicate
        $ gmailarchiver utilities import archive.mbox --json
    """
    asyncio.run(
        _run_import(
            ctx=ctx,
            archive_pattern=archive_pattern,
            state_db=state_db,
            deduplicate=deduplicate,
        )
    )


async def _run_import(
    ctx: CommandContext,
    archive_pattern: str,
    state_db: str,
    deduplicate: bool,
) -> None:
    """Async implementation of import command following thin client pattern."""
    # Phase 1: Validate inputs
    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Database will be created automatically if using default path",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Phase 2: Create workflow and config
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = ImportWorkflow(ctx.storage, progress=progress)
    config = ImportConfig(
        archive_patterns=[archive_pattern],
        state_db=state_db,
        dedupe=deduplicate,
    )

    # Phase 3: Execute workflow with shared task sequence (Log Window pattern)
    try:
        with progress.workflow_sequence(show_logs=True, max_logs=5):
            result = await workflow.run(config)
    except FileNotFoundError as e:
        ctx.fail_and_exit(
            title="Archive Not Found",
            message=str(e),
            suggestion="Check archive file path or glob pattern",
        )
    except Exception as e:
        ctx.fail_and_exit(
            title="Import Failed",
            message=f"Failed to import archives: {e}",
            suggestion="Check file permissions and archive format",
        )

    # Phase 4: Handle results
    if not result.files_processed:
        _handle_no_files(ctx, archive_pattern)
        return

    if result.errors:
        _handle_errors(ctx, result)

    # Phase 5: Show summary
    _show_final_summary(ctx, result, deduplicate)


def _handle_no_files(ctx: CommandContext, pattern: str) -> None:
    """Handle case where no files matched the pattern."""
    ctx.warning(f"No files found matching: {pattern}")
    SuggestionList().add("Check your file path or glob pattern").add(
        "Use quotes around patterns with wildcards: 'archives/*.mbox'"
    ).render(ctx.output)


def _handle_errors(ctx: CommandContext, result: ImportResult) -> None:
    """Handle import errors (but continue with summary)."""
    for error in result.errors[:5]:  # Show first 5 errors
        ctx.error(error)
    if len(result.errors) > 5:
        ctx.error(f"... and {len(result.errors) - 5} more errors")


def _show_final_summary(
    ctx: CommandContext,
    result: ImportResult,
    deduplicate: bool,
) -> None:
    """Show final summary report."""
    card = (
        ReportCard("Import Results")
        .add_field("Files Processed", str(len(result.files_processed)))
        .add_field("Messages Imported", f"{result.imported_count:,}")
    )

    if deduplicate:
        card.add_field("Duplicates Skipped", f"{result.duplicate_count:,}")

    if result.errors:
        card.add_field("Errors", str(len(result.errors)), style="red")

    card.render(ctx.output)

    # Success message
    if result.imported_count > 0:
        ctx.success(
            f"Successfully imported {result.imported_count:,} messages "
            f"from {len(result.files_processed)} file(s)"
        )
    else:
        ctx.info("No new messages imported (all duplicates)")

    # Suggest next steps
    SuggestionList().add("Search messages: gmailarchiver search 'query'").add(
        "View status: gmailarchiver status"
    ).render(ctx.output)
