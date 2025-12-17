"""Import command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.import_ import import_command


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
    asyncio.run(import_command(ctx, archive_pattern, state_db, deduplicate, json_output))
