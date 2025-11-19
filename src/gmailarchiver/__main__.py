"""Gmail Archiver CLI application."""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._version import __version__
from .archiver import GmailArchiver
from .auth import GmailAuthenticator
from .deduplicator import MessageDeduplicator
from .gmail_client import GmailClient
from .migration import MigrationManager
from .state import ArchiveState
from .utils import format_bytes
from .validator import ArchiveValidator


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"Gmail Archiver version {__version__}")
        raise typer.Exit()


app = typer.Typer(
    help="Archive old Gmail messages to local mbox files",
    no_args_is_help=True
)
console = Console()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit"
    )
) -> None:
    """Gmail Archiver - Archive old Gmail messages to local mbox files."""
    pass


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
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)"
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

    try:
        # credentials=None uses bundled OAuth credentials
        # token_file=None uses ~/.config/gmailarchiver/token.json
        authenticator = GmailAuthenticator(credentials_file=credentials)
        creds = authenticator.authenticate()
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
    archive_file: str = typer.Argument(..., help="Path to archive file to validate"),
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Validate an existing archive file.

    Example:
        $ gmailarchiver validate archive_20250113.mbox.gz
        $ gmailarchiver validate archive.mbox --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("validate", f"Validating {archive_file}")

    archive_path = Path(archive_file)
    if not archive_path.exists():
        output.error(
            f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion=(
                f"Import the archive first: 'gmailarchiver import {archive_file}' "
                f"or specify database path with --state-db"
            ),
            exit_code=1,
        )

    # Get expected message IDs from state database for this specific archive
    try:
        with ArchiveState(state_db) as state:
            expected_ids = state.get_archived_message_ids_for_file(archive_file)
    except Exception as e:
        output.error(f"Failed to read database: {e}", exit_code=1)

    # Run validation with progress tracking
    validator = ArchiveValidator(archive_file, state_db)

    output.info(f"Validating {len(expected_ids):,} expected messages...")

    with output.progress_context("Running validation checks", total=4) as progress:
        task = progress.add_task("Validation", total=4) if progress else None

        # Run comprehensive validation
        results = validator.validate_comprehensive(expected_ids)

        if progress and task:
            progress.update(task, completed=4)

    # Show results
    checks = [
        ("Count Check", results["count_check"]),
        ("Database Check", results["database_check"]),
        ("Integrity Check", results["integrity_check"]),
        ("Spot Check", results["spot_check"]),
    ]

    # Build report data
    report_data = {
        check_name: "✓ PASSED" if passed else "✗ FAILED" for check_name, passed in checks
    }

    output.show_report("Validation Results", report_data)

    # Show errors if any
    if results["errors"]:
        output.warning(f"Found {len(results['errors'])} error(s):")
        for error in results["errors"]:
            output.info(f"  • {error}")

    # Suggest next steps on failure
    if not results["passed"]:
        suggestions = []

        if not results["database_check"]:
            suggestions.append(
                "Import archive into database: "
                f"gmailarchiver import {archive_file} --state-db {state_db}"
            )

        if not results["integrity_check"]:
            suggestions.append(
                "Check archive file for corruption or try re-downloading"
            )

        if not results["count_check"] or not results["spot_check"]:
            suggestions.append(
                "Verify database integrity: gmailarchiver verify-integrity --state-db "
                f"{state_db}"
            )
            suggestions.append(
                f"Repair database if needed: gmailarchiver repair --no-dry-run --state-db "
                f"{state_db}"
            )

        if suggestions:
            output.suggest_next_steps(suggestions)

        output.end_operation(success=False, summary="Validation failed")
        raise typer.Exit(1)

    output.end_operation(success=True, summary="All validation checks passed")


@app.command("retry-delete")
def retry_delete_cmd(
    archive_file: str = typer.Argument(..., help="Archive file to delete messages from"),
    permanent: bool = typer.Option(False, "--permanent", help="Permanent deletion (vs trash)"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)"
    ),
) -> None:
    """
    Retry deletion for already-archived messages.

    Use this if archiving succeeded but deletion failed due to permission errors.
    This command retrieves message IDs from the database and attempts deletion again.

    IMPORTANT: You must re-authenticate with full Gmail permissions before using this.
    Run 'gmailarchiver auth-reset' first if you see permission errors.

    Examples:
        Trash messages (recoverable for 30 days):
        $ gmailarchiver retry-delete archive_20251114.mbox

        Permanent deletion (IRREVERSIBLE):
        $ gmailarchiver retry-delete archive_20251114.mbox --permanent
    """
    try:
        # 1. Get archived message IDs from database
        with ArchiveState(state_db) as state:
            message_ids = list(state.get_archived_message_ids_for_file(archive_file))

        if not message_ids:
            console.print(f"[red]Error: No archived messages found for: {archive_file}[/red]")
            console.print("\nPossible causes:")
            console.print("  - Archive file name doesn't match database records")
            console.print("  - Wrong state database path")
            console.print(f"  - Using: {state_db}")
            raise typer.Exit(1)

        console.print(f"\n[bold]Found {len(message_ids)} archived messages[/bold]")
        console.print(f"Archive: {archive_file}\n")

        # 2. Authenticate and validate scopes
        authenticator = GmailAuthenticator(credentials_file=credentials)
        console.print("Authenticating with Gmail...")
        creds = authenticator.authenticate()

        # 3. Validate deletion scope
        console.print("Validating permissions...")
        if not authenticator.validate_scopes(['https://mail.google.com/']):
            console.print("\n[red]Error: Missing deletion permission[/red]")
            console.print(
                "\nYour current authorization doesn't include "
                "permission to delete messages."
            )
            console.print("This was likely caused by using an older version of the app.")
            console.print("\n[bold yellow]To fix this:[/bold yellow]")
            console.print("  1. Run: [bold cyan]gmailarchiver auth-reset[/bold cyan]")
            console.print("  2. Run this command again to re-authenticate with full permissions")
            raise typer.Exit(1)

        console.print("[green]✓ Permissions validated[/green]\n")

        # 4. Create Gmail client
        client = GmailClient(creds)

        # 5. Create archiver (for deletion functionality)
        archiver = GmailArchiver(client, state_db)

        # 6. Delete messages with appropriate confirmation
        if permanent:
            console.print("[bold red]⚠ WARNING: PERMANENT DELETION[/bold red]")
            console.print(
                f"This will [bold]permanently delete[/bold] {len(message_ids)} messages."
            )
            console.print("[red]This action CANNOT be undone![/red]")
            console.print(
                "\nDeleted messages will be gone forever - "
                "not in trash, not recoverable.\n"
            )

            confirmation = typer.prompt(
                f"Type 'DELETE {len(message_ids)} MESSAGES' to confirm"
            )
            if confirmation != f"DELETE {len(message_ids)} MESSAGES":
                console.print("[yellow]Deletion cancelled[/yellow]")
                return

            # Perform permanent deletion
            archiver.delete_archived_messages(message_ids, permanent=True)

        else:
            # Trash deletion (default) - still ask for confirmation
            console.print(f"This will move {len(message_ids)} messages to trash.")
            console.print("(Messages can be recovered from trash for 30 days)\n")

            if not typer.confirm(f"Move {len(message_ids)} messages to trash?"):
                console.print("[yellow]Cancelled[/yellow]")
                return

            # Move to trash
            archiver.delete_archived_messages(message_ids, permanent=False)

        console.print("\n[bold green]✓ Deletion completed successfully![/bold green]\n")

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
) -> None:
    """
    Show archiving status and statistics.

    Example:
        $ gmailarchiver status
    """
    console.print("\n[bold blue]Archive Status[/bold blue]\n")

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        console.print("[yellow]No archive database found[/yellow]\n")
        console.print("To get started, run one of:")
        console.print(
            "  • [bold cyan]gmailarchiver archive 3y[/bold cyan] - "
            "Archive emails older than 3 years"
        )
        console.print(
            "  • [bold cyan]gmailarchiver import archive.mbox[/bold cyan] - "
            "Import existing archive\n"
        )
        raise typer.Exit(0)

    with ArchiveState(state_db) as state:
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
def migrate(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
) -> None:
    """
    Migrate database schema to latest version (v1.1.0).

    Automatically detects schema version and migrates from v1.0 to v1.1
    with enhanced features including mbox offset tracking and full-text search.

    Example:
        $ gmailarchiver migrate
        $ gmailarchiver migrate --state-db /path/to/archive_state.db
    """
    console.print("\n[bold blue]Database Migration[/bold blue]\n")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    # Initialize migration manager
    manager = MigrationManager(db_path)

    # Detect current schema version
    current_version = manager.detect_schema_version()
    console.print(f"Current schema version: [cyan]{current_version}[/cyan]")

    # Check if migration is needed
    if current_version == "1.1":
        console.print("\n[green]Database is already at version 1.1 (up to date)[/green]\n")
        return

    if current_version == "none":
        console.print("\n[yellow]Database appears to be empty or invalid[/yellow]")
        raise typer.Exit(1)

    # Show migration info
    console.print("\n[bold]Migration from v1.0 to v1.1 will:[/bold]")
    console.print("  • Create backup of current database")
    console.print("  • Add enhanced schema with mbox offset tracking")
    console.print("  • Enable full-text search capabilities")
    console.print("  • Add multi-account support (future-ready)")
    console.print("  • Preserve all existing message data\n")

    # Confirm migration
    if not typer.confirm("Proceed with migration?"):
        console.print("[yellow]Migration cancelled[/yellow]")
        return

    try:
        # Create backup
        backup_path = manager.create_backup()
        console.print(f"[green]Backup created:[/green] {backup_path}\n")

        # Run migration
        manager.migrate_v1_to_v1_1()

        # Validate migration
        console.print("\n[bold]Validating migration...[/bold]")
        manager.validate_migration()

        console.print("\n[bold green]✓ Migration completed successfully![/bold green]")
        console.print(f"[dim]Backup saved at: {backup_path}[/dim]\n")

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        manager._close()


@app.command(name="db-info")
def db_info(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
) -> None:
    """
    Display database information and statistics.

    Shows schema version, message count, database size, and recent archive runs.

    Example:
        $ gmailarchiver db-info
        $ gmailarchiver db-info --state-db /path/to/archive_state.db
    """
    console.print("\n[bold blue]Database Information[/bold blue]\n")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        console.print(f"[yellow]Database not found:[/yellow] {state_db}")
        console.print("[dim]No archive database exists yet[/dim]\n")
        return

    # Detect schema version
    manager = MigrationManager(db_path)
    version = manager.detect_schema_version()

    console.print(f"Schema version: [cyan]{version}[/cyan]")

    # Show database file size
    db_size = db_path.stat().st_size
    console.print(f"Database size: [cyan]{format_bytes(db_size)}[/cyan]\n")

    # Get message count and recent runs
    try:
        with ArchiveState(db_path=str(db_path), validate_path=False) as state:
            total_messages = state.get_archived_count()
            console.print(f"Total messages archived: [bold]{total_messages:,}[/bold]\n")

            # Show recent archive runs
            recent_runs = state.get_archive_runs(limit=5)

            if recent_runs:
                table = Table(title="Recent Archive Runs (Last 5)")
                table.add_column("Run ID", style="cyan", justify="right")
                table.add_column("Timestamp", style="magenta")
                table.add_column("Messages", style="green", justify="right")
                table.add_column("Archive File", style="blue")

                for run in recent_runs:
                    table.add_row(
                        str(run['run_id']),
                        run['timestamp'][:19],  # Truncate timestamp
                        str(run['messages_archived']),
                        run['archive_file']
                    )

                console.print(table)
            else:
                console.print("[yellow]No archive runs found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error reading database:[/red] {e}")
        raise typer.Exit(1)
    finally:
        manager._close()

    console.print()


@app.command()
def rollback(
    backup_file: str | None = typer.Option(
        None,
        "--backup-file",
        help="Path to backup file for rollback"
    ),
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
) -> None:
    """
    Rollback database to a previous backup.

    If no backup file is specified, lists available backups.

    Example:
        $ gmailarchiver rollback
        $ gmailarchiver rollback --backup-file archive_state.db.backup.20250114_120000
    """
    console.print("\n[bold blue]Database Rollback[/bold blue]\n")

    db_path = Path(state_db)

    # If no backup file specified, list available backups
    if not backup_file:
        # Find backup files
        backup_pattern = f"{db_path.name}.backup.*"
        backups = sorted(db_path.parent.glob(backup_pattern), reverse=True)

        if not backups:
            console.print("[red]No backup files found[/red]")
            console.print(f"[dim]Looking for pattern: {backup_pattern}[/dim]\n")
            raise typer.Exit(1)

        console.print("[bold]Available backup files:[/bold]\n")

        table = Table()
        table.add_column("Backup File", style="cyan")
        table.add_column("Size", style="yellow")
        table.add_column("Created", style="magenta")

        for backup in backups:
            size = format_bytes(backup.stat().st_size)
            # Extract timestamp from filename
            # Format: archive_state.db.backup.20250114_120000
            parts = backup.name.split('.')
            if len(parts) >= 3:
                timestamp_str = parts[-1]
                # Convert YYYYMMDD_HHMMSS to readable format
                if len(timestamp_str) == 15:
                    date_part = timestamp_str[:8]
                    time_part = timestamp_str[9:]
                    timestamp = (
                        f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} "
                        f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
                    )
                else:
                    timestamp = timestamp_str
            else:
                timestamp = "Unknown"

            table.add_row(str(backup), size, timestamp)

        console.print(table)
        console.print("\n[dim]Use --backup-file to specify which backup to restore[/dim]\n")
        return

    # Rollback to specified backup
    backup_path = Path(backup_file)

    if not backup_path.exists():
        console.print(f"[red]Error:[/red] Backup file not found: {backup_file}")
        raise typer.Exit(1)

    console.print(f"Backup file: [cyan]{backup_file}[/cyan]")
    console.print(f"Target database: [cyan]{state_db}[/cyan]\n")

    console.print(
        "[yellow]⚠ WARNING:[/yellow] This will replace the current database with the backup."
    )
    console.print("Any changes made after the backup was created will be lost.\n")

    # Confirm rollback
    if not typer.confirm("Proceed with rollback?"):
        console.print("[yellow]Rollback cancelled[/yellow]")
        return

    try:
        manager = MigrationManager(db_path)
        manager.rollback_migration(backup_path)

        console.print("\n[bold green]✓ Rollback completed successfully![/bold green]\n")

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="dedupe-report")
def dedupe_report(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
) -> None:
    """
    Show deduplication analysis without making changes.

    Analyzes the archive database for duplicate messages (same RFC Message-ID)
    and displays statistics about potential space savings.

    Example:
        $ gmailarchiver dedupe-report
        $ gmailarchiver dedupe-report --state-db /path/to/archive_state.db
    """
    console.print("\n[bold blue]Deduplication Report[/bold blue]\n")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            # Find duplicates
            duplicates = dedup.find_duplicates()

            # Generate report
            report = dedup.generate_report(duplicates)

            # Display results
            if report.duplicate_message_ids == 0:
                console.print("[green]No duplicate messages found![/green]\n")
                return

            # Display summary statistics
            console.print(f"Total messages analyzed: [bold]{report.total_messages:,}[/bold]")
            console.print(
                f"Duplicate Message-IDs found: [cyan]{report.duplicate_message_ids:,}[/cyan]"
            )
            console.print(
                f"Total duplicate messages: [yellow]{report.total_duplicate_messages:,}[/yellow]"
            )
            console.print(
                f"Messages to remove: [red]{report.messages_to_remove:,}[/red]"
            )
            console.print(
                f"Space recoverable: [green]{format_bytes(report.space_recoverable)}[/green]\n"
            )

            # Display breakdown by archive file
            if report.breakdown_by_archive:
                table = Table(title="Breakdown by Archive File")
                table.add_column("Archive File", style="cyan")
                table.add_column("Duplicates to Remove", style="yellow", justify="right")
                table.add_column("Space Recoverable", style="green", justify="right")

                for archive_file, stats in sorted(report.breakdown_by_archive.items()):
                    table.add_row(
                        archive_file,
                        str(stats['messages_to_remove']),
                        format_bytes(stats['space_recoverable'])
                    )

                console.print(table)
                console.print()

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "\n[yellow]Hint:[/yellow] Run 'gmailarchiver migrate' to upgrade your database"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def dedupe(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    strategy: str = typer.Option(
        "newest",
        "--strategy",
        help="Which copy to keep: 'newest', 'largest', or 'first'"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Preview changes without executing"
    ),
) -> None:
    """
    Remove duplicate messages from archive database.

    Identifies duplicate messages (same RFC Message-ID) and removes all but
    one copy based on the selected strategy.

    Strategies:
        - newest: Keep the most recently archived copy (default)
        - largest: Keep the largest copy by size
        - first: Keep copy from first archive file (alphabetically)

    Example:
        $ gmailarchiver dedupe --dry-run
        $ gmailarchiver dedupe --strategy newest --no-dry-run
        $ gmailarchiver dedupe --strategy largest --no-dry-run
    """
    console.print("\n[bold blue]Deduplication[/bold blue]\n")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    # Validate strategy
    valid_strategies = ['newest', 'largest', 'first']
    if strategy not in valid_strategies:
        console.print(
            f"[red]Error:[/red] Invalid strategy: {strategy}. "
            f"Must be one of: {', '.join(valid_strategies)}"
        )
        raise typer.Exit(1)

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            # Find duplicates
            duplicates = dedup.find_duplicates()

            # Check if there are duplicates
            if not duplicates:
                console.print("[green]No duplicate messages found![/green]\n")
                return

            # Show what will be done
            report = dedup.generate_report(duplicates)

            console.print(f"Strategy: [cyan]{strategy}[/cyan]")
            console.print(
                f"Duplicate Message-IDs: [yellow]{report.duplicate_message_ids:,}[/yellow]"
            )
            console.print(f"Messages to remove: [red]{report.messages_to_remove:,}[/red]")
            console.print(
                f"Space to save: [green]{format_bytes(report.space_recoverable)}[/green]\n"
            )

            if dry_run:
                console.print("[yellow]DRY RUN - No changes will be made[/yellow]\n")

                # Show preview of what would be removed
                result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=True)

                console.print(f"Would remove: [red]{result.messages_removed:,}[/red] messages")
                console.print(f"Would keep: [green]{result.messages_kept:,}[/green] messages")
                console.print(f"Would save: [cyan]{format_bytes(result.space_saved)}[/cyan]\n")

                console.print(
                    "[dim]Run with --no-dry-run to actually remove duplicates[/dim]\n"
                )

            else:
                # Confirm before proceeding
                console.print(
                    "[bold yellow]⚠ WARNING: This will permanently remove "
                    "duplicate messages from the database[/bold yellow]"
                )
                console.print("The mbox files themselves will not be modified.\n")

                if not typer.confirm(
                    f"Remove {report.messages_to_remove:,} duplicate messages "
                    f"using '{strategy}' strategy?"
                ):
                    console.print("[yellow]Cancelled[/yellow]\n")
                    return

                # Perform deduplication
                result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=False)

                console.print("\n[bold green]✓ Deduplication completed![/bold green]\n")
                console.print(f"Removed: [red]{result.messages_removed:,}[/red] messages")
                console.print(f"Kept: [green]{result.messages_kept:,}[/green] messages")
                console.print(f"Space saved: [cyan]{format_bytes(result.space_saved)}[/cyan]\n")

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "\n[yellow]Hint:[/yellow] Run 'gmailarchiver migrate' to upgrade your database"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="verify-offsets")
def verify_offsets_cmd(
    archive_file: str = typer.Argument(..., help="Path to archive file"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Verify mbox offset accuracy for v1.1 databases.

    Validates that stored mbox file offsets accurately point to messages.
    Requires v1.1 schema (run 'gmailarchiver migrate' if needed).

    Example:
        $ gmailarchiver verify-offsets archive_20250114.mbox.gz
        $ gmailarchiver verify-offsets test.mbox --state-db /path/to/archive_state.db
        $ gmailarchiver verify-offsets archive.mbox --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("verify-offsets", f"Verifying offsets for {archive_file}")

    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        output.error(
            f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )

    # Create validator and run verification
    try:
        validator = ArchiveValidator(archive_file, state_db)

        with output.progress_context("Verifying offsets", total=1) as progress:
            task = progress.add_task("Offset verification", total=1) if progress else None
            result = validator.verify_offsets()
            if progress and task:
                progress.update(task, completed=1)

        # Handle skipped (v1.0 schema)
        if result.skipped:
            output.warning("Offset verification skipped (v1.0 schema)")
            output.suggest_next_steps([
                "Upgrade to v1.1: gmailarchiver migrate",
            ])
            output.end_operation(success=True)
            return

        # Build report data
        report_data = {
            "Total Offsets Checked": result.total_checked,
            "Successful Reads": result.successful_reads,
            "Failed Reads": result.failed_reads,
            "Accuracy": f"{result.accuracy_percentage:.1f}%",
        }

        output.show_report("Offset Verification Results", report_data)

        # Success case
        if result.accuracy_percentage == 100.0:
            output.success(f"All {result.total_checked} offsets verified successfully")
            output.end_operation(success=True)
            return

        # Failure case - show details
        if result.failures:
            output.warning(f"Found {len(result.failures)} offset verification failure(s):")
            for failure in result.failures[:10]:  # Limit to first 10
                output.info(f"  • {failure}")

            if len(result.failures) > 10:
                output.info(f"  ... and {len(result.failures) - 10} more failures")

        # Suggest next steps
        output.suggest_next_steps([
            "Repair offsets: gmailarchiver repair --backfill --no-dry-run",
            "Check database integrity: gmailarchiver verify-integrity",
        ])

        output.end_operation(success=False)
        raise typer.Exit(1)

    except Exception as e:
        output.error(f"Offset verification failed: {e}", exit_code=1)


@app.command(name="verify-consistency")
def verify_consistency_cmd(
    archive_file: str = typer.Argument(..., help="Path to archive file"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Deep database consistency check.

    Validates database integrity, checks for orphaned records, missing records,
    duplicates, and FTS synchronization (v1.1 only).

    Example:
        $ gmailarchiver verify-consistency archive_20250114.mbox.gz
        $ gmailarchiver verify-consistency test.mbox --state-db /path/to/archive_state.db
        $ gmailarchiver verify-consistency archive.mbox --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("verify-consistency", f"Checking consistency for {archive_file}")

    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        output.error(
            f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )

    # Create validator and run consistency check
    try:
        validator = ArchiveValidator(archive_file, state_db)

        with output.progress_context("Running consistency checks", total=5) as progress:
            task = progress.add_task("Consistency checks", total=5) if progress else None
            report = validator.verify_consistency()
            if progress and task:
                progress.update(task, completed=5)

        # Build report data
        report_data = {
            "Schema Version": report.schema_version,
            "Orphaned Records": report.orphaned_records,
            "Missing Records": report.missing_records,
            "Duplicate Gmail IDs": report.duplicate_gmail_ids,
        }

        if report.schema_version == "1.1":
            report_data["Duplicate RFC Message-IDs"] = report.duplicate_rfc_message_ids
            report_data["FTS Synchronized"] = "Yes" if report.fts_synced else "No"

        output.show_report("Consistency Check Results", report_data)

        # Show errors if any
        if report.errors:
            output.warning(f"Found {len(report.errors)} issue(s):")
            for error in report.errors:
                output.info(f"  • {error}")

        # Overall status
        if report.passed:
            output.success("All consistency checks passed")
            output.end_operation(success=True)
            return

        # Suggest next steps
        output.suggest_next_steps([
            "Repair database: gmailarchiver repair --no-dry-run",
            "Check integrity: gmailarchiver verify-integrity --verbose",
        ])

        output.end_operation(success=False)
        raise typer.Exit(1)

    except Exception as e:
        output.error(f"Consistency check failed: {e}", exit_code=1)


@app.command()
def search(
    query: str | None = typer.Argument(None, help="Gmail-style search query"),
    from_addr: str | None = typer.Option(None, "--from", help="Filter by sender"),
    to_addr: str | None = typer.Option(None, "--to", help="Filter by recipient"),
    subject: str | None = typer.Option(None, "--subject", help="Filter by subject"),
    after: str | None = typer.Option(None, "--after", help="After date (YYYY-MM-DD)"),
    before: str | None = typer.Option(None, "--before", help="Before date (YYYY-MM-DD)"),
    limit: int = typer.Option(100, help="Maximum results"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON")
) -> None:
    """
    Search archived messages.

    Examples:
        $ gmailarchiver search "from:alice meeting"
        $ gmailarchiver search "invoice payment" --limit 50
        $ gmailarchiver search --from alice@example.com --subject meeting
        $ gmailarchiver search --after 2024-01-01 --before 2024-12-31
    """
    import json
    import time
    from datetime import datetime

    from .migration import MigrationManager
    from .search import SearchEngine

    # Don't print header if JSON output
    if not json_output:
        console.print("\n[bold blue]Search Archived Messages[/bold blue]\n")

    # Check database exists
    db_path = Path(state_db)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    # Check schema version (require v1.1)
    manager = MigrationManager(db_path)
    schema_version = manager.detect_schema_version()
    manager._close()

    if schema_version != "1.1":
        console.print("[red]Error:[/red] Search requires v1.1 database schema")
        console.print("[yellow]Run 'gmailarchiver migrate' to upgrade[/yellow]")
        raise typer.Exit(1)

    # Validate dates if provided
    if after:
        try:
            datetime.strptime(after, '%Y-%m-%d')
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format: {after}")
            console.print("[yellow]Use YYYY-MM-DD format (e.g., 2024-01-15)[/yellow]")
            raise typer.Exit(1)

    if before:
        try:
            datetime.strptime(before, '%Y-%m-%d')
        except ValueError:
            console.print(f"[red]Error:[/red] Invalid date format: {before}")
            console.print("[yellow]Use YYYY-MM-DD format (e.g., 2024-01-15)[/yellow]")
            raise typer.Exit(1)

    # Build query string from filters if no query provided
    if not query:
        query_parts = []
        if from_addr:
            query_parts.append(f"from:{from_addr}")
        if to_addr:
            query_parts.append(f"to:{to_addr}")
        if subject:
            query_parts.append(f"subject:{subject}")
        if after:
            query_parts.append(f"after:{after}")
        if before:
            query_parts.append(f"before:{before}")

        if not query_parts:
            console.print("[red]Error:[/red] No search query or filters provided")
            raise typer.Exit(1)

        query = " ".join(query_parts)

    # Execute search
    try:
        start_time = time.perf_counter()

        with SearchEngine(state_db) as engine:
            results = engine.search(query, limit=limit)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        # Format output
        if json_output:
            # Output JSON array
            data = [
                {
                    'gmail_id': r.gmail_id,
                    'rfc_message_id': r.rfc_message_id,
                    'date': r.date,
                    'from': r.from_addr,
                    'to': r.to_addr,
                    'subject': r.subject,
                    'archive_file': r.archive_file,
                    'mbox_offset': r.mbox_offset,
                    'relevance_score': r.relevance_score
                }
                for r in results.results
            ]
            print(json.dumps(data, indent=2))
        else:
            # Rich table output
            if results.total_results == 0:
                console.print("[yellow]No results found[/yellow]\n")
                return

            table = Table(title=f"Search Results ({results.total_results} found)")
            table.add_column("Date", style="cyan", width=12)
            table.add_column("From", style="green", width=30)
            table.add_column("Subject", style="yellow", width=40)
            table.add_column("Archive", style="magenta", width=30)

            for result in results.results:
                # Truncate long fields
                if len(result.from_addr) > 28:
                    from_display = result.from_addr[:28] + "..."
                else:
                    from_display = result.from_addr

                if len(result.subject) > 38:
                    subject_display = result.subject[:38] + "..."
                else:
                    subject_display = result.subject or "(no subject)"

                archive_display = Path(result.archive_file).name

                table.add_row(
                    result.date[:10] if result.date else "N/A",
                    from_display,
                    subject_display,
                    archive_display
                )

            console.print(table)
            console.print(
                f"\n[dim]Found {results.total_results} results "
                f"in {execution_time_ms:.2f}ms[/dim]\n"
            )

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="import")
def import_cmd(
    archive_pattern: str = typer.Argument(..., help="Mbox file path or glob pattern"),
    account_id: str = typer.Option("default", help="Account identifier"),
    skip_duplicates: bool = typer.Option(True, help="Skip duplicate messages"),
    state_db: str = typer.Option("archive_state.db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Import existing mbox archives into v1.1 database.

    Parses mbox files, extracts metadata with accurate byte offset tracking,
    and populates the v1.1 database for fast message access and searching.

    Examples:
        $ gmailarchiver import archive_2024.mbox
        $ gmailarchiver import archive_*.mbox.gz --skip-duplicates
        $ gmailarchiver import "archives/*.mbox.zst" --account-id gmail_work
        $ gmailarchiver import old_archive.mbox --state-db /path/to/archive_state.db
        $ gmailarchiver import archive.mbox --json
    """
    import glob
    import time

    from gmailarchiver.importer import ArchiveImporter
    from gmailarchiver.migration import MigrationManager
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("import", f"Importing archives: {archive_pattern}")

    db_path = Path(state_db)

    # Handle database schema: auto-create if missing, auto-migrate if v1.0
    if db_path.exists():
        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()

        if version == "1.0":
            # Auto-migrate v1.0 to v1.1
            output.warning("Detected v1.0 database, auto-migrating to v1.1...")
            try:
                manager.migrate_v1_to_v1_1()
                output.success("Migration completed successfully")
            except Exception as e:
                manager._close()
                output.error(f"Migration failed: {e}", exit_code=1)
        elif version == "none":
            # Empty database file exists - delete it and let DBManager create a fresh one
            manager._close()
            output.warning("Found empty database file, recreating with v1.1 schema...")
            try:
                db_path.unlink()
            except Exception as e:
                output.error(f"Failed to delete empty database: {e}", exit_code=1)
        elif version != "1.1":
            manager._close()
            output.error(
                f"Unsupported database schema version: {version}",
                suggestion="Delete the database or use --state-db with a different path",
                exit_code=1,
            )
        else:
            # version == "1.1", all good
            pass

        if version not in ("none",):  # Don't close if we deleted the database
            manager._close()
    # If database doesn't exist, DBManager will auto-create it with v1.1 schema

    # Expand glob pattern
    files = glob.glob(archive_pattern)
    if not files:
        output.error(
            f"No files match pattern: {archive_pattern}",
            suggestion="Check the file path or glob pattern",
            exit_code=1,
        )

    output.info(f"Found {len(files)} file(s) to import")

    # Import each file with progress
    importer = ArchiveImporter(state_db)
    results = []
    start_time = time.perf_counter()

    with output.progress_context(f"Importing {len(files)} file(s)", total=len(files)) as progress:
        task = progress.add_task("Import", total=len(files)) if progress else None

        for file_path in files:
            try:
                result = importer.import_archive(
                    file_path,
                    account_id=account_id,
                    skip_duplicates=skip_duplicates
                )
                results.append(result)
                if progress and task:
                    progress.update(task, advance=1)
            except Exception as e:
                output.error(f"Error importing {file_path}: {e}")
                if progress and task:
                    progress.update(task, advance=1)

    total_time = time.perf_counter() - start_time

    # Calculate totals
    total_imported = sum(r.messages_imported for r in results)
    total_skipped = sum(r.messages_skipped for r in results)
    total_failed = sum(r.messages_failed for r in results)

    # Build report data
    report_data = {
        "Files Imported": len(files),
        "Total Messages Imported": total_imported,
        "Skipped Duplicates": total_skipped,
        "Failed": total_failed,
    }

    # Add performance metrics
    if total_imported > 0 and total_time > 0:
        rate = total_imported / total_time
        report_data["Performance"] = f"{rate:.1f} messages/second"

    output.show_report("Import Summary", report_data)

    # Show detailed error messages if there were failures
    if total_failed > 0:
        output.warning(f"Found {total_failed} import error(s):")
        for result in results:
            if result.errors:
                output.info(f"\n{Path(result.archive_file).name}:")
                for error in result.errors[:10]:  # Limit to first 10 errors per file
                    output.info(f"  • {error}")
                if len(result.errors) > 10:
                    output.info(f"  ... and {len(result.errors) - 10} more errors")

        output.suggest_next_steps([
            "Check database integrity: gmailarchiver verify-integrity",
            "Review error messages above for details",
        ])

    if total_imported > 0:
        output.suggest_next_steps([
            "Search imported messages: gmailarchiver search <query>",
            "Verify database: gmailarchiver verify-integrity",
        ])

    output.end_operation(success=total_failed == 0)


@app.command()
def consolidate(
    archives: list[str] = typer.Argument(..., help="Archive files or glob patterns"),
    output: str = typer.Option(..., "-o", "--output", help="Output archive file"),
    sort: bool = typer.Option(True, help="Sort messages chronologically"),
    dedupe: bool = typer.Option(True, help="Remove duplicate messages"),
    dedupe_strategy: str = typer.Option("newest", help="Dedup strategy: newest/largest/first"),
    compress: str | None = typer.Option(None, help="Compression: gzip/lzma/zstd"),
    state_db: str = typer.Option("archive_state.db", help="State database path")
) -> None:
    """
    Consolidate multiple archives into one.

    Merges multiple mbox archives, optionally sorting by date and removing duplicates.
    Supports compression auto-detection from output file extension.

    Examples:
        $ gmailarchiver consolidate archive_*.mbox -o merged.mbox
        $ gmailarchiver consolidate old1.mbox old2.mbox -o consolidated.mbox.gz
        $ gmailarchiver consolidate "archives/*.mbox" --no-sort --no-dedupe -o unsorted.mbox
        $ gmailarchiver consolidate archive*.mbox -o merged.mbox.zst --dedupe-strategy newest
    """
    import glob

    from rich.progress import Progress, SpinnerColumn, TextColumn

    from .consolidator import ArchiveConsolidator

    console.print("\n[bold blue]Archive Consolidation[/bold blue]\n")

    # 1. Expand glob patterns
    all_files = []
    for pattern in archives:
        matches = glob.glob(pattern)
        if not matches:
            # Try as literal file path
            if Path(pattern).exists():
                all_files.append(pattern)
            else:
                console.print(f"[yellow]Warning: No files match pattern: {pattern}[/yellow]")
        else:
            all_files.extend(matches)

    if not all_files:
        console.print("[red]Error: No archive files found[/red]")
        raise typer.Exit(1)

    console.print(f"Found {len(all_files)} archive(s) to consolidate\n")

    # 2. Validate dedupe strategy
    valid_strategies = ['newest', 'largest', 'first']
    if dedupe_strategy not in valid_strategies:
        console.print(f"[red]Error: Invalid dedupe strategy: {dedupe_strategy}[/red]")
        console.print(f"[yellow]Valid strategies: {', '.join(valid_strategies)}[/yellow]")
        raise typer.Exit(1)

    # 3. Auto-detect compression from output extension
    if compress is None:
        output_path = Path(output)
        if output_path.suffix == '.gz':
            compress = 'gzip'
        elif output_path.suffix == '.xz':
            compress = 'lzma'
        elif output_path.suffix == '.zst':
            compress = 'zstd'

    # 4. Check if output file exists
    output_path = Path(output)
    if output_path.exists():
        overwrite = typer.confirm(f"Output file exists: {output}. Overwrite?")
        if not overwrite:
            console.print("[yellow]Consolidation cancelled[/yellow]")
            raise typer.Exit(0)

    # 5. Consolidate with progress
    consolidator = ArchiveConsolidator(state_db)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Consolidating archives...", total=None)

            # Convert file paths to list[str | Path] for type compatibility
            source_paths: list[str | Path] = [Path(f) for f in all_files]

            result = consolidator.consolidate(
                source_archives=source_paths,
                output_archive=output,
                sort_by_date=sort,
                deduplicate=dedupe,
                dedupe_strategy=dedupe_strategy,
                compress=compress
            )

            progress.update(task, completed=True)

        # 6. Display summary
        table = Table(title="Consolidation Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Source archives", str(len(result.source_files)))
        table.add_row("Total messages", str(result.total_messages))
        table.add_row("Duplicates removed", str(result.duplicates_removed))
        table.add_row("Messages consolidated", str(result.messages_consolidated))
        table.add_row("Sorted by date", "Yes" if result.sort_applied else "No")
        if result.compression_used:
            table.add_row("Compression", result.compression_used)

        console.print(table)

        # 7. Performance metrics
        if result.execution_time_ms > 0:
            rate = (result.messages_consolidated / result.execution_time_ms) * 1000
            console.print("\n[green]✓ Consolidation complete![/green]")
            console.print(f"[dim]Performance: {rate:.1f} messages/second[/dim]")
            console.print(f"[dim]Output: {result.output_file}[/dim]\n")

    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except FileNotFoundError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="verify-integrity")
def verify_integrity_cmd(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show verbose output"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Verify database integrity and report issues.

    Checks for:
    - Orphaned FTS records
    - Missing FTS records
    - Invalid mbox offsets (placeholder values from v1.1.0-beta.1)
    - Duplicate Message-IDs
    - Missing archive files

    Exit code: 0 if clean, 1 if issues found

    Examples:
        $ gmailarchiver verify-integrity
        $ gmailarchiver verify-integrity --state-db /path/to/archive_state.db
        $ gmailarchiver verify-integrity --verbose
        $ gmailarchiver verify-integrity --json
    """
    from gmailarchiver.db_manager import DBManager
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("verify-integrity", "Checking database integrity")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database, or specify path with --state-db",
            exit_code=1,
        )

    try:
        # Initialize DBManager without schema validation to avoid errors
        db = DBManager(str(db_path), validate_schema=False)

        with output.progress_context("Running integrity checks", total=5) as progress:
            task = progress.add_task("Integrity checks", total=5) if progress else None
            issues = db.verify_database_integrity()
            if progress and task:
                progress.update(task, completed=5)

        db.close()

        if not issues:
            output.success("Database integrity verified - no issues found")
            output.end_operation(success=True)
            raise typer.Exit(0)

        # Build report data
        report_data = {
            "Total Issues": len(issues),
            "Status": "FAILED",
        }

        # Add individual issues if verbose
        if verbose:
            for i, issue in enumerate(issues, 1):
                report_data[f"Issue {i}"] = issue

        output.show_report("Database Integrity Results", report_data)

        # Show all issues as warnings
        if not verbose:
            output.warning(f"Found {len(issues)} integrity issue(s):")
            for issue in issues:
                output.info(f"  • {issue}")

        # Suggest next steps
        output.suggest_next_steps([
            "Fix issues: gmailarchiver repair --no-dry-run",
            "Review issues in detail: gmailarchiver verify-integrity --verbose",
        ])

        output.end_operation(success=False)
        raise typer.Exit(1)

    except FileNotFoundError as e:
        output.error(f"File not found: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Integrity check failed: {e}", exit_code=1)


@app.command()
def repair(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Show what would be fixed without making changes (default: True)"
    ),
    backfill: bool = typer.Option(
        False,
        "--backfill",
        help="Fix invalid offsets by scanning mbox files"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Repair database integrity issues.

    Fixes:
    - Orphaned FTS records (removes records not in messages table)
    - Missing FTS records (rebuilds FTS index for missing messages)
    - Invalid mbox offsets with --backfill (scans mbox files to extract real offsets)

    The --backfill option is critical for fixing placeholder records created by
    the v1.1.0-beta.1 migration bug.

    Examples:
        $ gmailarchiver repair
        $ gmailarchiver repair --no-dry-run
        $ gmailarchiver repair --backfill --no-dry-run
        $ gmailarchiver repair --state-db /path/to/archive_state.db
        $ gmailarchiver repair --json
    """
    from gmailarchiver.db_manager import DBManager
    from gmailarchiver.migration import MigrationManager
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    operation_name = "repair (dry-run)" if dry_run else "repair"
    output.start_operation(operation_name, "Repairing database")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database, or specify path with --state-db",
            exit_code=1,
        )

    # Get confirmation for non-dry-run
    if not dry_run:
        output.warning("⚠ WARNING: This will modify the database")
        confirm = typer.confirm("Continue with database repair?", default=False)
        if not confirm:
            output.info("Repair cancelled")
            output.end_operation(success=True)
            raise typer.Exit(0)

    try:
        # Initialize DBManager without schema validation
        db = DBManager(str(db_path), validate_schema=False)

        with output.progress_context("Running repair operations", total=2) as progress:
            # Phase 1: Fix FTS sync issues
            task = progress.add_task("Phase 1: FTS synchronization", total=2) if progress else None
            output.info("Phase 1: Checking FTS synchronization...")
            repairs = db.repair_database(dry_run=dry_run)
            if progress and task:
                progress.update(task, completed=1)

            # Phase 2: Backfill invalid offsets if requested
            if backfill:
                output.info("Phase 2: Checking for invalid offsets...")
                invalid_msgs = db.get_messages_with_invalid_offsets()

                if invalid_msgs:
                    output.info(f"Found {len(invalid_msgs)} messages with invalid offsets")

                    if not dry_run:
                        # Use MigrationManager logic to scan mbox and backfill
                        migrator = MigrationManager(db_path)
                        backfilled = migrator.backfill_offsets_from_mbox(invalid_msgs)
                        repairs['invalid_offsets_fixed'] = backfilled
                        migrator._close()
                    else:
                        repairs['invalid_offsets_would_fix'] = len(invalid_msgs)
                else:
                    output.success("No invalid offsets found")

            if progress and task:
                progress.update(task, completed=2)

        db.close()

        # Display results
        _display_repair_results(output, repairs, dry_run)

        total_repairs = sum(repairs.values())
        output.end_operation(success=True if total_repairs >= 0 else False)

    except FileNotFoundError as e:
        output.error(f"File not found: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Repair failed: {e}", exit_code=1)


def _display_repair_results(
    output: "OutputManager",
    repairs: dict[str, int],
    dry_run: bool
) -> None:
    """Display repair results using OutputManager."""
    # Build report data
    report_data = {}

    # Add FTS repairs
    if 'orphaned_fts_removed' in repairs and repairs['orphaned_fts_removed'] > 0:
        action = "Removed" if not dry_run else "Would remove"
        report_data[f"{action} orphaned FTS records"] = repairs['orphaned_fts_removed']

    if 'missing_fts_added' in repairs and repairs['missing_fts_added'] > 0:
        action = "Added" if not dry_run else "Would add"
        report_data[f"{action} missing FTS records"] = repairs['missing_fts_added']

    # Add offset backfill repairs
    if 'invalid_offsets_fixed' in repairs and repairs['invalid_offsets_fixed'] > 0:
        report_data["Backfilled invalid offsets"] = repairs['invalid_offsets_fixed']

    if 'invalid_offsets_would_fix' in repairs and repairs['invalid_offsets_would_fix'] > 0:
        report_data["Would backfill invalid offsets"] = repairs['invalid_offsets_would_fix']

    # Summary message
    total_repairs = sum(repairs.values())

    title = "Repair Results" if not dry_run else "Repair Preview (Dry Run)"
    report_data["Total"] = total_repairs

    output.show_report(title, report_data)

    if total_repairs == 0:
        output.success("No repairs needed - database is clean")
    elif dry_run:
        output.warning(f"Would perform {total_repairs} repair(s)")
        output.suggest_next_steps([
            "Apply repairs: gmailarchiver repair --no-dry-run",
        ])
    else:
        output.success(f"Successfully performed {total_repairs} repair(s)")


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


if __name__ == "__main__":
    app()
