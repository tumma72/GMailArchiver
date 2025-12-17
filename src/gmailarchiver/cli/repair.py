"""Repair command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.core.workflows.repair import RepairConfig, RepairWorkflow


async def repair_command(
    ctx: CommandContext,
    state_db: str,
    backfill: bool,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Async implementation of repair command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check database path or archive emails first",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    workflow = RepairWorkflow(ctx.storage)
    config = RepairConfig(state_db=state_db, backfill=backfill, dry_run=dry_run)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Analyzing database") as t:
            try:
                result = await workflow.run(config)
                if dry_run:
                    t.complete(f"Found {result.issues_found} issues")
                else:
                    t.complete(f"Repaired {result.issues_fixed} issues")
            except Exception as e:
                t.fail("Repair failed", reason=str(e))
                ctx.fail_and_exit(
                    title="Repair Failed",
                    message=f"Failed to repair database: {e}",
                    suggestion="Check database file permissions or restore from backup",
                )
                return

    # Display detailed results
    if dry_run:
        ctx.warning("DRY RUN - no changes made")
        report_data = {
            "Issues Found": str(result.issues_found),
            "Details": "\n".join(result.details) if result.details else "None",
        }
    else:
        report_data = {
            "Issues Fixed": str(result.issues_fixed),
            "Details": "\n".join(result.details) if result.details else "None",
        }

    ctx.show_report("Database Repair", report_data)

    # Suggest next steps
    if dry_run and result.issues_found > 0:
        suggestions = ["Apply repairs: gmailarchiver utilities repair --no-dry-run"]
        if backfill:
            suggestions.append(
                "Backfill offsets: gmailarchiver utilities repair --backfill --no-dry-run"
            )
        ctx.suggest_next_steps(suggestions)
    elif not dry_run and result.issues_fixed > 0:
        ctx.success(f"Successfully repaired {result.issues_fixed} issues")
        ctx.suggest_next_steps(
            [
                "Verify integrity: gmailarchiver utilities verify-integrity",
                "Verify consistency: gmailarchiver utilities verify-consistency",
            ]
        )
