"""Import command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import CLIProgressAdapter
from gmailarchiver.core.workflows.import_ import ImportConfig, ImportWorkflow


async def import_command(
    ctx: CommandContext,
    archive_pattern: str,
    state_db: str,
    deduplicate: bool,
    json_output: bool,
) -> None:
    """Async implementation of import command."""
    # Check database exists
    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Database will be created automatically if using default path",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Create progress adapter to provide step-by-step feedback
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = ImportWorkflow(ctx.storage, progress=progress)
    config = ImportConfig(archive_patterns=[archive_pattern], state_db=state_db, dedupe=deduplicate)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Importing archives") as t:
            try:
                result = await workflow.run(config)
                t.complete(f"Imported {result.imported_count:,} messages")
            except FileNotFoundError as e:
                t.fail("Archive not found", reason=str(e))
                ctx.fail_and_exit(
                    title="Archive Not Found",
                    message=str(e),
                    suggestion="Check archive file path or glob pattern",
                )
                return
            except Exception as e:
                t.fail("Import failed", reason=str(e))
                ctx.fail_and_exit(
                    title="Import Failed",
                    message=f"Failed to import archives: {e}",
                    suggestion="Check file permissions and archive format",
                )
                return

    # Display import results
    report_data = {
        "Files Processed": str(len(result.files_processed)),
        "Messages Imported": f"{result.imported_count:,}",
        "Duplicates Skipped": f"{result.duplicate_count:,}" if deduplicate else "N/A",
    }
    ctx.show_report("Import Results", report_data)

    # Success message
    ctx.success(
        f"Successfully imported {result.imported_count:,} messages "
        f"from {len(result.files_processed)} file(s)"
    )

    # Suggest next steps
    ctx.suggest_next_steps(
        [
            "Search messages: gmailarchiver search 'query'",
            "View status: gmailarchiver status",
        ]
    )
