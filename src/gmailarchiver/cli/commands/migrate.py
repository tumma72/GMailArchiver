"""Migrate command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.migrate import migrate_command


@with_context(requires_storage=True, has_progress=True, operation_name="migrate")
def migrate(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Migrate database schema to latest version.

    Automatically upgrades database schema from v1.0 to v1.1+ with backfilling
    of missing mbox offsets and Message-IDs.

    Examples:
        $ gmailarchiver utilities migrate
        $ gmailarchiver utilities migrate --json
    """
    asyncio.run(migrate_command(ctx, state_db, json_output))
