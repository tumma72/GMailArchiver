"""Dedupe command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.dedupe import dedupe_command


@with_context(requires_storage=True, has_progress=True, operation_name="dedupe")
def dedupe(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Preview duplicates"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Find and remove duplicate messages.

    Identifies duplicates based on Message-ID (100% precision) and optionally
    removes them, keeping the newest copy. Always use --dry-run first to preview.

    Examples:
        $ gmailarchiver utilities dedupe
        $ gmailarchiver utilities dedupe --no-dry-run
        $ gmailarchiver utilities dedupe --json
    """
    asyncio.run(dedupe_command(ctx, state_db, dry_run, json_output))
