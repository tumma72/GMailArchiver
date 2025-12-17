"""Search command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.search import search_command


@with_context(requires_storage=True, operation_name="search")
def search(
    ctx: CommandContext,
    query: str = typer.Argument(..., help="Search query (Gmail syntax supported)"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of results"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    with_preview: bool = typer.Option(
        False, "--with-preview", help="Include message body preview in results"
    ),
    interactive: bool = typer.Option(
        False, "--interactive", help="Interactive mode for message selection and extraction"
    ),
) -> None:
    """
    Search archived messages.

    Supports Gmail-style query syntax with full-text search via BM25 ranking.

    Examples:
        $ gmailarchiver search "from:sender@example.com"
        $ gmailarchiver search "subject:invoice" --limit 20
        $ gmailarchiver search "body:urgent" --json
        $ gmailarchiver search "meeting" --with-preview
        $ gmailarchiver search "project" --interactive
    """
    asyncio.run(search_command(ctx, query, state_db, limit, json_output, with_preview, interactive))
