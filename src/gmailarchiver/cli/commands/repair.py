"""Repair command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.repair import repair_command


@with_context(requires_storage=True, has_progress=True, operation_name="repair")
def repair(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    backfill: bool = typer.Option(
        False, "--backfill", help="Backfill missing mbox offsets and Message-IDs"
    ),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Preview repairs"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Repair database issues.

    Fixes common database problems including orphaned records and missing offsets.
    Use --backfill to scan mbox files and update missing offsets.

    Examples:
        $ gmailarchiver utilities repair
        $ gmailarchiver utilities repair --backfill --no-dry-run
        $ gmailarchiver utilities repair --json
    """
    asyncio.run(repair_command(ctx, state_db, backfill, dry_run, json_output))
