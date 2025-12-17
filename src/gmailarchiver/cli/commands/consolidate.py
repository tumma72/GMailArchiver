"""Consolidate command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.consolidate import consolidate_command


@with_context(requires_storage=True, has_progress=True, operation_name="consolidate")
def consolidate(
    ctx: CommandContext,
    output_file: str = typer.Argument(..., help="Output archive file path"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    deduplicate: bool = typer.Option(
        True, "--deduplicate/--no-deduplicate", help="Remove duplicate messages"
    ),
    sort_by_date: bool = typer.Option(True, "--sort/--no-sort", help="Sort messages by date"),
    compress: str | None = typer.Option(
        None, "--compress", "-c", help="Compression format: 'gzip', 'lzma', or 'zstd'"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Consolidate multiple archives into one.

    Merges all archived messages into a single archive file with optional
    deduplication and sorting. Updates database offsets transactionally.

    Examples:
        $ gmailarchiver utilities consolidate consolidated.mbox
        $ gmailarchiver utilities consolidate output.mbox.gz --compress gzip
        $ gmailarchiver utilities consolidate output.mbox --no-deduplicate --no-sort
        $ gmailarchiver utilities consolidate output.mbox --json
    """
    asyncio.run(
        consolidate_command(
            ctx, output_file, state_db, deduplicate, sort_by_date, compress, json_output
        )
    )
