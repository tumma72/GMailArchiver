"""Dedupe command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.core.workflows.dedupe import DedupeConfig, DedupeWorkflow


async def dedupe_command(
    ctx: CommandContext,
    state_db: str,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Async implementation of dedupe command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Archive emails first or import existing archives",
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

    workflow = DedupeWorkflow(ctx.storage)
    config = DedupeConfig(archive_files=archives, dry_run=dry_run)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Scanning for duplicates") as t:
            try:
                result = await workflow.run(config)

                if result.duplicates_found == 0:
                    t.complete("No duplicates found")
                elif dry_run:
                    t.complete(f"Found {result.duplicates_found:,} duplicates")
                else:
                    t.complete(f"Removed {result.duplicates_removed:,} duplicates")

            except Exception as e:
                t.fail("Deduplication failed", reason=str(e))
                ctx.fail_and_exit(
                    title="Deduplication Failed",
                    message=f"Failed to deduplicate messages: {e}",
                    suggestion="Check database integrity or restore from backup",
                )
                return

    # Early exit if no duplicates
    if result.duplicates_found == 0:
        ctx.info("No duplicate messages found")
        return

    # Display deduplication results
    if dry_run:
        ctx.warning("DRY RUN - no changes made")
        report_data = {
            "Duplicates Found": f"{result.duplicates_found:,}",
            "Messages Kept": f"{result.messages_kept:,}",
        }
        ctx.show_report("Duplicate Messages Preview", report_data)

        ctx.suggest_next_steps(
            [
                "Remove duplicates: gmailarchiver utilities dedupe --no-dry-run",
                "Verify integrity first: gmailarchiver utilities verify-integrity",
            ]
        )
    else:
        report_data = {
            "Duplicates Removed": f"{result.duplicates_removed:,}",
            "Messages Kept": f"{result.messages_kept:,}",
        }
        ctx.show_report("Deduplication Results", report_data)

        ctx.success(f"Successfully removed {result.duplicates_removed:,} duplicate messages")
        ctx.suggest_next_steps(
            [
                "Verify consistency: gmailarchiver utilities verify-consistency",
                "View updated status: gmailarchiver status",
            ]
        )
