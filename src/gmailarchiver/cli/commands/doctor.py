"""Doctor command implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.doctor import _run_doctor


@with_context(requires_storage=True, has_progress=True, operation_name="doctor")
def doctor(
    ctx: CommandContext,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed diagnostics"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """Run comprehensive system diagnostics.

    Checks:
    - Archive and database health (schema, integrity, orphaned FTS, file existence)
    - Python environment (version, dependencies, OAuth token, credentials)
    - System resources (disk space, permissions, stale locks, temp directory)

    Examples:

    \b
    $ gmailarchiver utilities doctor
    $ gmailarchiver utilities doctor --verbose
    $ gmailarchiver utilities doctor --json
    """
    asyncio.run(_run_doctor(ctx, verbose, json_output))
