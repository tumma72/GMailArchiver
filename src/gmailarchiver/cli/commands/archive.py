"""Archive command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.adapters import CLIProgressAdapter
from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.core.workflows.archive import (
    ArchiveConfig,
    ArchiveResult,
    ArchiveWorkflow,
)


@with_context(requires_storage=True, has_progress=True, operation_name="archive")
def archive(
    ctx: CommandContext,
    age_threshold: str = typer.Argument(
        ...,
        help="Age threshold or exact date. "
        "Relative: '3y' (3 years), '6m' (6 months), '2w' (2 weeks), '30d' (30 days). "
        "Exact: '2024-01-01' (ISO format YYYY-MM-DD)",
    ),
    output: str = typer.Option(
        None, "--output", "-o", help="Output file path (default: archive_YYYYMMDD.mbox[.gz])"
    ),
    compress: str | None = typer.Option(
        None,
        "--compress",
        "-c",
        help="Compression format: 'gzip', 'lzma', or 'zstd' (fastest, recommended)",
    ),
    incremental: bool = typer.Option(
        True, "--incremental/--no-incremental", help="Skip already-archived messages"
    ),
    trash: bool = typer.Option(
        False, "--trash", help="Move archived messages to trash (30-day recovery)"
    ),
    delete: bool = typer.Option(
        False, "--delete", help="Permanently delete archived messages (IRREVERSIBLE!)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed validation output"),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Archive Gmail messages older than the specified threshold.

    Examples:

    \b
    $ gmailarchiver archive 3y
    $ gmailarchiver archive 6m --dry-run
    $ gmailarchiver archive 2024-01-01
    $ gmailarchiver archive 2023-06-15 --compress zstd
    $ gmailarchiver archive 3y --trash
    $ gmailarchiver archive 3y --json
    """
    asyncio.run(
        _run_archive(
            ctx=ctx,
            age_threshold=age_threshold,
            output=output,
            compress=compress,
            incremental=incremental,
            trash=trash,
            delete=delete,
            dry_run=dry_run,
            verbose=verbose,
            credentials=credentials,
        )
    )


async def _run_archive(
    ctx: CommandContext,
    age_threshold: str,
    output: str | None,
    compress: str | None,
    incremental: bool,
    trash: bool,
    delete: bool,
    dry_run: bool,
    verbose: bool,
    credentials: str | None,
) -> None:
    """Async implementation of the archive command following thin client pattern."""
    # Phase 1: Create dependencies
    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    progress = CLIProgressAdapter(ctx.output, ctx.ui)

    # Phase 2: Authenticate with Gmail
    async with ctx.gmail_session(credentials) as gmail:
        # Phase 3: Create workflow and config
        workflow = ArchiveWorkflow(gmail, ctx.storage, progress)
        config = ArchiveConfig(
            age_threshold=age_threshold,
            output_file=output,
            compress=compress,
            incremental=incremental,
            dry_run=dry_run,
            trash=trash,
            delete=delete,
        )

        # Phase 4: Execute workflow
        try:
            result = await workflow.run(config)
        except ValueError as e:
            ctx.fail_and_exit(
                title="Invalid Input",
                message=str(e),
                suggestion="Check your age threshold format",
            )
        except Exception as e:
            ctx.fail_and_exit(
                title="Archive Failed",
                message=str(e),
                suggestion="Check your network connection and Gmail API access",
            )

        # Phase 5: Handle different result scenarios
        # 5.1 Dry run mode
        if dry_run:
            _handle_dry_run(ctx, result)
            return

        # 5.2 Interrupted
        if result.interrupted:
            _handle_interrupted(ctx, result, age_threshold)
            return

        # 5.3 Validation failed
        if not result.validation_passed and result.archived_count > 0:
            _handle_validation_failure(ctx, result, verbose)
            return

        # 5.4 Show verbose validation if requested
        if verbose and result.validation_details:
            ctx.output.show_validation_report(result.validation_details, title="Archive Validation")

        # 5.5 No messages found
        if result.found_count == 0:
            ctx.warning("No messages found matching criteria")
            ctx.suggest_next_steps(
                [
                    "Check your age threshold",
                    "Verify messages exist in Gmail matching the criteria",
                ]
            )
            return

        # 5.6 Nothing new to archive (but may offer deletion)
        if result.archived_count == 0:
            await _handle_no_new_messages(ctx, result, workflow, trash, delete, age_threshold)
            return

        # 5.7 Handle deletion for newly archived messages
        if (trash or delete) and result.archived_count > 0:
            await _handle_deletion(ctx, workflow, result, trash, delete)

        # Phase 6: Final summary
        _show_final_summary(ctx, result, output, compress, trash, delete, age_threshold)


def _handle_dry_run(ctx: CommandContext, result: ArchiveResult) -> None:
    """Handle dry run output."""
    ctx.warning("DRY RUN completed - no changes made")
    report_data = {
        "Messages Found": result.found_count,
        "Messages to Archive": (result.found_count - result.skipped_count - result.duplicate_count),
        "Already Archived": result.skipped_count + result.duplicate_count,
        "Output File": result.actual_file,
        "Mode": "Dry Run (no changes made)",
    }
    ctx.show_report("Archive Preview", report_data)


def _handle_interrupted(ctx: CommandContext, result: ArchiveResult, age_threshold: str) -> None:
    """Handle interrupted archive."""
    ctx.warning("Archive was interrupted (Ctrl+C)")
    ctx.info(f"Partial archive saved: {result.actual_file}")
    ctx.info(f"Progress: {result.archived_count} messages archived")
    ctx.suggest_next_steps(
        [
            f"Resume: gmailarchiver archive {age_threshold}",
            "Cleanup: gmailarchiver cleanup --list",
        ]
    )


def _handle_validation_failure(ctx: CommandContext, result: ArchiveResult, verbose: bool) -> None:
    """Handle validation failure."""
    if verbose and result.validation_details:
        ctx.output.show_validation_report(result.validation_details, title="Archive Validation")

    ctx.fail_and_exit(
        title="Validation Failed",
        message="Archive validation did not pass all checks",
        details=result.validation_details.get("errors", []) if result.validation_details else [],
        suggestion="Check disk space and file permissions. DO NOT delete Gmail messages yet.",
    )


async def _handle_no_new_messages(
    ctx: CommandContext,
    result: ArchiveResult,
    workflow: ArchiveWorkflow,
    trash: bool,
    delete: bool,
    age_threshold: str,
) -> None:
    """Handle case where no new messages need archiving."""
    assert ctx.storage is not None  # Required by decorator

    # Show contextual message
    if result.duplicate_count > 0 and result.skipped_count > 0:
        ctx.info(
            f"Nothing new to archive: {result.skipped_count:,} already archived, "
            f"{result.duplicate_count:,} duplicates"
        )
    elif result.duplicate_count > 0:
        ctx.info(f"Nothing new to archive: all {result.duplicate_count:,} messages are duplicates")
    else:
        ctx.info(f"Nothing new to archive: all {result.skipped_count:,} messages already archived")

    # Offer deletion for existing messages (if user requested trash/delete)
    if (trash or delete) and Path(result.actual_file).exists():
        archived_ids = await ctx.storage.get_message_ids_for_archive(result.actual_file)
        if archived_ids:
            count = len(archived_ids)
            ctx.info(f"\nFound {count:,} messages in {result.actual_file}")

            if delete:
                ctx.warning("WARNING: PERMANENT DELETION")
                ctx.warning("This action CANNOT be undone!")
                if (
                    typer.prompt(f"\nType 'DELETE {count} MESSAGES' to confirm")
                    == f"DELETE {count} MESSAGES"
                ):
                    with ctx.output.progress_context("Permanently deleting messages", total=None):
                        await workflow.delete_messages(result.actual_file, permanent=True)
                    ctx.success(f"Permanently deleted {count:,} messages from Gmail")
                else:
                    ctx.info("Deletion cancelled")
            elif trash:
                if typer.confirm(f"Move {count:,} messages to trash? (30-day recovery period)"):
                    with ctx.output.progress_context("Moving messages to trash", total=None):
                        await workflow.delete_messages(result.actual_file, permanent=False)
                    ctx.success(f"Moved {count:,} messages to trash")
                else:
                    ctx.info("Cancelled")


async def _handle_deletion(
    ctx: CommandContext,
    workflow: ArchiveWorkflow,
    result: ArchiveResult,
    trash: bool,
    delete: bool,
) -> None:
    """Handle deletion confirmation and execution for newly archived messages."""
    if delete:
        ctx.warning("WARNING: PERMANENT DELETION")
        ctx.warning(f"This will permanently delete {result.archived_count} messages.")
        ctx.warning("This action CANNOT be undone!")
        if (
            typer.prompt(f"\nType 'DELETE {result.archived_count} MESSAGES' to confirm")
            == f"DELETE {result.archived_count} MESSAGES"
        ):
            with ctx.output.progress_context("Permanently deleting messages", total=None):
                await workflow.delete_messages(result.actual_file, permanent=True)
            ctx.success("Messages permanently deleted")
        else:
            ctx.info("Deletion cancelled")

    elif trash:
        if not typer.confirm(
            f"\nMove {result.archived_count} messages to trash? (30-day recovery period)"
        ):
            ctx.info("Cancelled")
            return

        with ctx.output.progress_context("Moving messages to trash", total=None):
            await workflow.delete_messages(result.actual_file, permanent=False)

        ctx.success("Messages moved to trash")


def _show_final_summary(
    ctx: CommandContext,
    result: ArchiveResult,
    output: str | None,
    compress: str | None,
    trash: bool,
    delete: bool,
    age_threshold: str,
) -> None:
    """Show final summary report."""
    report_data = {
        "Archived": f"{result.archived_count:,} messages",
        "File": output or result.actual_file,
    }

    if result.skipped_count > 0 or result.duplicate_count > 0:
        skipped_parts = []
        if result.skipped_count > 0:
            skipped_parts.append(f"{result.skipped_count:,} already archived")
        if result.duplicate_count > 0:
            skipped_parts.append(f"{result.duplicate_count:,} duplicates")
        report_data["Skipped"] = ", ".join(skipped_parts)

    if compress:
        report_data["Compression"] = compress

    if trash:
        report_data["Gmail"] = "Moved to trash (30-day recovery)"
    elif delete:
        report_data["Gmail"] = "Permanently deleted"

    ctx.show_report("Archive Summary", report_data)
    ctx.success("Archive completed!")

    # Contextual suggestions based on what happened
    suggestions: list[str] = []

    if result.archived_count > 0 and not trash and not delete:
        # Suggest deletion options if messages were archived but not deleted
        suggestions.append(
            f"Move to trash (recoverable): gmailarchiver archive {age_threshold} --trash"
        )

    if result.duplicate_count > 0:
        # Suggest dedupe review when duplicates were found
        suggestions.append("Review duplicates: gmailarchiver dedupe --dry-run")

    if suggestions:
        ctx.suggest_next_steps(suggestions)
