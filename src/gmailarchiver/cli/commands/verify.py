"""Verify commands implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.verify import (
    verify_consistency_command,
    verify_integrity_command,
    verify_offsets_command,
)


@with_context(requires_storage=True, operation_name="verify-integrity")
def verify_integrity(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Verify database integrity.

    Checks database health including foreign keys, indexes, and SQLite integrity.

    Examples:
        $ gmailarchiver utilities verify-integrity
        $ gmailarchiver utilities verify-integrity --json
    """
    asyncio.run(verify_integrity_command(ctx, state_db, json_output))


@with_context(requires_storage=True, operation_name="verify-consistency")
def verify_consistency(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Verify database/mbox consistency.

    Deep consistency check ensuring database records match actual mbox files.

    Examples:
        $ gmailarchiver utilities verify-consistency
        $ gmailarchiver utilities verify-consistency --json
    """
    asyncio.run(verify_consistency_command(ctx, state_db, json_output))


@with_context(requires_storage=True, operation_name="verify-offsets")
def verify_offsets(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Verify mbox offset accuracy.

    Validates that stored mbox offsets correctly point to message locations.

    Examples:
        $ gmailarchiver utilities verify-offsets
        $ gmailarchiver utilities verify-offsets --json
    """
    asyncio.run(verify_offsets_command(ctx, state_db, json_output))
