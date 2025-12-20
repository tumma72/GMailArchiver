"""Migrate command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import ReportCard, SuggestionList
from gmailarchiver.core.workflows.migrate import MigrateConfig, MigrateWorkflow


async def migrate_command(
    ctx: CommandContext,
    state_db: str,
    json_output: bool,
) -> None:
    """Async implementation of migrate command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check database path or archive emails first",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    workflow = MigrateWorkflow(ctx.storage)
    config = MigrateConfig(state_db=state_db)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Checking schema version") as t:
            try:
                result = await workflow.run(config)

                if result.from_version == result.to_version:
                    t.complete("Already at latest version")
                    ctx.info(f"Database schema is already at version {result.to_version}")
                    return

                t.complete(f"Migrated from v{result.from_version} to v{result.to_version}")

            except Exception as e:
                t.fail("Migration failed", reason=str(e))
                ctx.fail_and_exit(
                    title="Migration Failed",
                    message=f"Failed to migrate database: {e}",
                    suggestion=(
                        "Restore from backup: gmailarchiver utilities rollback\n"
                        "Or check database file permissions"
                    ),
                )
                return

    # Display migration results
    (
        ReportCard("Schema Migration")
        .add_field("Old Version", result.from_version)
        .add_field("New Version", result.to_version)
        .add_field("Backup Created", result.backup_path or "N/A")
        .add_field("Details", "\n".join(result.details) if result.details else "None")
        .render(ctx.output)
    )

    # Success message and next steps
    ctx.success(f"Successfully migrated database to v{result.to_version}")
    SuggestionList().add("Verify integrity: gmailarchiver utilities verify-integrity").add(
        "Verify consistency: gmailarchiver utilities verify-consistency"
    ).render(ctx.output)
