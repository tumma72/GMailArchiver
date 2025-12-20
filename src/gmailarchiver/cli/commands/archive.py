"""Archive command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import (
    CLIProgressAdapter,
    ErrorPanel,
    ReportCard,
    SuggestionList,
    ValidationPanel,
)
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

        # Phase 4: Execute workflow with shared task sequence (Log Window pattern)
        # This creates a single Live context that all workflow steps share
        try:
            with progress.workflow_sequence(show_logs=True, max_logs=5):
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
            _build_validation_panel(result.validation_details).render(ctx.output)

        # 5.5 No messages found
        if result.found_count == 0:
            ctx.warning("No messages found matching criteria")
            SuggestionList().add("Check your age threshold").add(
                "Verify messages exist in Gmail matching the criteria"
            ).render(ctx.output)
            return

        # 5.6 Nothing new to archive (but may offer deletion)
        if result.archived_count == 0:
            await _handle_no_new_messages(ctx, result, workflow, trash, delete, age_threshold)
            return

        # 5.7 Handle deletion for newly archived messages
        if (trash or delete) and result.archived_count > 0:
            await _handle_deletion(ctx, workflow, result, trash, delete)

        # Phase 6: Final summary
        _show_final_summary(ctx, result, output)


def _handle_dry_run(ctx: CommandContext, result: ArchiveResult) -> None:
    """Handle dry run output."""
    ctx.warning("DRY RUN completed - no changes made")
    ReportCard("Archive Preview").add_field("Messages Found", result.found_count).add_field(
        "Messages to Archive",
        result.found_count - result.skipped_count - result.duplicate_count,
    ).add_field("Already Archived", result.skipped_count + result.duplicate_count).add_field(
        "Output File", result.actual_file
    ).add_field("Mode", "Dry Run (no changes made)").render(ctx.output)


def _handle_interrupted(ctx: CommandContext, result: ArchiveResult, age_threshold: str) -> None:
    """Handle interrupted archive."""
    ctx.warning("Archive was interrupted (Ctrl+C)")
    ctx.info(f"Partial archive saved: {result.actual_file}")
    ctx.info(f"Progress: {result.archived_count} messages archived")
    SuggestionList().add(f"Resume: gmailarchiver archive {age_threshold}").add(
        "Cleanup: gmailarchiver cleanup --list"
    ).render(ctx.output)


def _handle_validation_failure(ctx: CommandContext, result: ArchiveResult, verbose: bool) -> None:
    """Handle validation failure."""
    if result.validation_details:
        # Always show ValidationPanel on failure (per UI_UX_CLI.md guideline)
        _build_validation_panel(result.validation_details).render(ctx.output)

    ErrorPanel("Validation Failed", "Archive validation did not pass all checks").add_details(
        result.validation_details.get("errors", []) if result.validation_details else []
    ).with_suggestion(
        "Check disk space and file permissions. DO NOT delete Gmail messages yet."
    ).render(ctx.output)


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
    output_file: str | None,
) -> None:
    """Show final summary report."""
    card = (
        ReportCard("Archive Summary")
        .add_field("Archived", f"{result.archived_count:,} messages")
        .add_field("File", output_file or result.actual_file)
    )

    if result.skipped_count > 0 or result.duplicate_count > 0:
        skipped_parts = []
        if result.skipped_count > 0:
            skipped_parts.append(f"{result.skipped_count:,} already archived")
        if result.duplicate_count > 0:
            skipped_parts.append(f"{result.duplicate_count:,} duplicates")
        card.add_field("Skipped", ", ".join(skipped_parts))

    card.render(ctx.output)
    ctx.success("Archive completed!")


def _build_validation_panel(details: dict[str, object]) -> ValidationPanel:
    """Build a ValidationPanel from validation details dict.

    Args:
        details: Dict with count_check, database_check, integrity_check,
                 spot_check (bools) and errors (list[str])

    Returns:
        ValidationPanel configured with the check results
    """
    panel = ValidationPanel("Archive Validation")

    # Add checks in order
    panel.add_check("Count check", passed=bool(details.get("count_check", False)))
    panel.add_check("Database check", passed=bool(details.get("database_check", False)))
    panel.add_check("Integrity check", passed=bool(details.get("integrity_check", False)))
    panel.add_check("Spot check", passed=bool(details.get("spot_check", False)))

    # Add errors if any
    errors = details.get("errors", [])
    if errors and isinstance(errors, list):
        panel.add_errors([str(e) for e in errors])

    return panel
