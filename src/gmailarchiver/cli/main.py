"""Main CLI application entry point."""

import typer

from gmailarchiver._version import __version__


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"Gmail Archiver version {__version__}")
        raise typer.Exit()


# Create the main Typer app
app = typer.Typer(help="Archive old Gmail messages to local mbox files", no_args_is_help=True)

# Sub-application for advanced/low-level utilities
utilities_app = typer.Typer(help="Advanced utility and maintenance commands")
app.add_typer(
    utilities_app,
    name="utilities",
    help="Low-level utilities (verification, DB maintenance, migration, cleanup)",
)

# Schedule sub-application
schedule_app = typer.Typer(help="Manage automated maintenance schedules", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Gmail Archiver - Archive old Gmail messages to local mbox files."""
    pass


# Import and register commands
def _register_commands() -> None:
    """Register all CLI commands."""

    # Import main commands
    from gmailarchiver.cli.commands.archive import archive

    # Import utilities subcommands
    from gmailarchiver.cli.commands.consolidate import consolidate
    from gmailarchiver.cli.commands.dedupe import dedupe
    from gmailarchiver.cli.commands.doctor import doctor
    from gmailarchiver.cli.commands.import_ import import_
    from gmailarchiver.cli.commands.migrate import migrate
    from gmailarchiver.cli.commands.repair import repair

    # Import schedule subcommands
    from gmailarchiver.cli.commands.schedule import add, disable, enable, list_, remove
    from gmailarchiver.cli.commands.search import search
    from gmailarchiver.cli.commands.status import status
    from gmailarchiver.cli.commands.validate import validate
    from gmailarchiver.cli.commands.verify import (
        verify_consistency,
        verify_integrity,
        verify_offsets,
    )

    # Register main commands
    app.command()(archive)
    app.command()(search)
    app.command()(status)
    app.command()(validate)

    # Register utilities subcommands
    utilities_app.command(name="verify-integrity")(verify_integrity)
    utilities_app.command(name="verify-consistency")(verify_consistency)
    utilities_app.command(name="verify-offsets")(verify_offsets)
    utilities_app.command()(repair)
    utilities_app.command()(migrate)
    utilities_app.command(name="import")(import_)
    utilities_app.command()(consolidate)
    utilities_app.command()(dedupe)
    utilities_app.command()(doctor)

    # Register schedule subcommands
    schedule_app.command()(add)
    schedule_app.command(name="list")(list_)
    schedule_app.command()(remove)
    schedule_app.command()(enable)
    schedule_app.command()(disable)


# Register commands when module is imported
_register_commands()
