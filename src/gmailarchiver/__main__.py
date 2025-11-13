"""Gmail Archiver CLI application."""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .archiver import GmailArchiver
from .auth import GmailAuthenticator
from .gmail_client import GmailClient
from .state import ArchiveState
from .validator import ArchiveValidator

app = typer.Typer(
    help="Archive old Gmail messages to local mbox files",
    no_args_is_help=True
)
console = Console()


@app.command()
def archive(
    age_threshold: str = typer.Argument(
        ...,
        help="Age threshold (e.g., '3y' for 3 years, '6m' for 6 months, '2w' for 2 weeks)"
    ),
    output: str = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: archive_YYYYMMDD.mbox[.gz])"
    ),
    compress: str | None = typer.Option(
        None,
        "--compress", "-c",
        help="Compression format: 'gzip', 'lzma', or 'zstd' (fastest, recommended)"
    ),
    incremental: bool = typer.Option(
        True,
        "--incremental/--no-incremental",
        help="Skip already-archived messages"
    ),
    trash: bool = typer.Option(
        False,
        "--trash",
        help="Move archived messages to trash (30-day recovery)"
    ),
    delete: bool = typer.Option(
        False,
        "--delete",
        help="Permanently delete archived messages (IRREVERSIBLE!)"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview without making changes"
    ),
    credentials: str = typer.Option(
        "credentials.json",
        "--credentials",
        help="Path to OAuth2 credentials file"
    ),
) -> None:
    """
    Archive Gmail messages older than the specified threshold.

    Examples:

        Archive emails older than 3 years:
        $ gmailarchiver archive 3y

        Archive with zstd compression (fastest, recommended):
        $ gmailarchiver archive 3y --compress zstd

        Archive with gzip compression:
        $ gmailarchiver archive 3y --compress gzip

        Archive and move to trash:
        $ gmailarchiver archive 3y --trash

        Dry run to preview:
        $ gmailarchiver archive 6m --dry-run
    """
    # Generate default output filename if not provided
    if not output:
        timestamp = datetime.now().strftime('%Y%m%d')
        extension = '.mbox'
        if compress == 'gzip':
            extension = '.mbox.gz'
        elif compress == 'lzma':
            extension = '.mbox.xz'
        elif compress == 'zstd':
            extension = '.mbox.zst'
        output = f"archive_{timestamp}{extension}"

    # Authenticate
    console.print("\n[bold blue]Gmail Archiver[/bold blue]\n")
    console.print("Authenticating...")

    try:
        authenticator = GmailAuthenticator(credentials_file=credentials)
        creds = authenticator.authenticate()
        console.print("✓ Authenticated successfully\n")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}", style="red")
        raise typer.Exit(1)

    # Initialize clients
    gmail_client = GmailClient(creds)
    archiver = GmailArchiver(gmail_client)

    # Perform archiving
    try:
        result = archiver.archive(
            age_threshold=age_threshold,
            output_file=output,
            compress=compress,
            incremental=incremental,
            dry_run=dry_run
        )

        if dry_run:
            console.print("\n[yellow]DRY RUN completed - no changes made[/yellow]")
            return

        if result['messages_archived'] == 0:
            console.print("\n[yellow]No messages to archive[/yellow]")
            return

        # Validate archive
        console.print("\n[bold]Validating archive...[/bold]")

        # Get the actual message IDs that were archived
        with ArchiveState() as state:
            # Get recently archived messages for this file
            archived_ids = state.get_archived_message_ids_for_file(output)

        validation_passed = archiver.validate_archive(output, archived_ids)

        if not validation_passed:
            console.print("\n[red]⚠ Archive validation failed![/red]")
            console.print("Archive may be incomplete. Deletion cancelled for safety.")
            raise typer.Exit(1)

        # Handle deletion if requested
        if trash or delete:
            if not validation_passed:
                console.print("\n[red]Cannot delete: Archive validation failed[/red]")
                raise typer.Exit(1)

            if delete:
                # Permanent deletion requires explicit confirmation
                console.print("\n[bold red]⚠ WARNING: PERMANENT DELETION[/bold red]")
                msg_count = result['messages_archived']
                console.print(f"This will permanently delete {msg_count} messages.")
                console.print("This action CANNOT be undone!\n")

                confirmation = typer.prompt(
                    f"Type 'DELETE {result['messages_archived']} MESSAGES' to confirm"
                )

                if confirmation != f"DELETE {result['messages_archived']} MESSAGES":
                    console.print("[yellow]Deletion cancelled[/yellow]")
                    return

                # Perform permanent deletion
                archiver.delete_archived_messages(
                    list(archived_ids),
                    permanent=True
                )

            elif trash:
                # Move to trash with confirmation
                if not typer.confirm(
                    f"\nMove {result['messages_archived']} messages to trash? "
                    "(30-day recovery period)"
                ):
                    console.print("[yellow]Cancelled[/yellow]")
                    return

                archiver.delete_archived_messages(
                    list(archived_ids),
                    permanent=False
                )

        console.print("\n[bold green]✓ Archive completed successfully![/bold green]\n")

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def validate(
    archive_file: str = typer.Argument(..., help="Path to archive file to validate")
) -> None:
    """
    Validate an existing archive file.

    Example:
        $ gmailarchiver validate archive_20250113.mbox.gz
    """
    console.print(f"\n[bold]Validating archive:[/bold] {archive_file}\n")

    archive_path = Path(archive_file)
    if not archive_path.exists():
        console.print(f"[red]Error:[/red] Archive file not found: {archive_file}")
        raise typer.Exit(1)

    # Get expected message IDs from state database for this specific archive
    with ArchiveState() as state:
        expected_ids = state.get_archived_message_ids_for_file(archive_file)

    validator = ArchiveValidator(archive_file)
    results = validator.validate_comprehensive(expected_ids)
    validator.report(results)

    if not results['passed']:
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """
    Show archiving status and statistics.

    Example:
        $ gmailarchiver status
    """
    console.print("\n[bold blue]Archive Status[/bold blue]\n")

    with ArchiveState() as state:
        # Overall stats
        total_archived = state.get_archived_count()
        console.print(f"Total messages archived: [bold]{total_archived:,}[/bold]\n")

        # Recent runs
        recent_runs = state.get_archive_runs(limit=10)

        if recent_runs:
            table = Table(title="Recent Archive Runs")
            table.add_column("Run ID", style="cyan")
            table.add_column("Timestamp", style="magenta")
            table.add_column("Query", style="yellow")
            table.add_column("Messages", style="green")
            table.add_column("Archive File", style="blue")

            for run in recent_runs:
                table.add_row(
                    str(run['run_id']),
                    run['timestamp'][:19],  # Truncate timestamp
                    run['query'],
                    str(run['messages_archived']),
                    run['archive_file']
                )

            console.print(table)
        else:
            console.print("[yellow]No archive runs found[/yellow]")

    console.print()


@app.command()
def auth_reset() -> None:
    """
    Reset authentication (revoke and delete token).

    Example:
        $ gmailarchiver auth-reset
    """
    console.print("\n[bold]Resetting authentication...[/bold]\n")

    authenticator = GmailAuthenticator()
    authenticator.revoke()

    console.print("✓ Authentication token deleted")
    console.print("Run any command to re-authenticate\n")


@app.callback()
def main() -> None:
    """
    Gmail Archiver - Archive old Gmail messages to local mbox files.

    Safely archive emails older than a specified threshold with validation,
    compression, and incremental archiving support.
    """
    pass


if __name__ == "__main__":
    app()
