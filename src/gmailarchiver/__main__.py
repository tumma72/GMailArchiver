"""Gmail Archiver CLI application."""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .archiver import GmailArchiver
from .auth import GmailAuthenticator
from .deduplicator import MessageDeduplicator
from .gmail_client import GmailClient
from .migration import MigrationManager
from .state import ArchiveState
from .utils import format_bytes
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
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path")
) -> None:
    """
    Verify mbox offset accuracy for v1.1 databases.

    Validates that stored mbox file offsets accurately point to messages.
    Requires v1.1 schema (run 'gmailarchiver migrate' if needed).

    Example:
        $ gmailarchiver verify-offsets archive_20250114.mbox.gz
        $ gmailarchiver verify-offsets test.mbox --state-db /path/to/archive_state.db
    """
    console.print("\n[bold blue]Offset Verification[/bold blue]\n")

    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        console.print(f"[red]Error:[/red] Archive file not found: {archive_file}")
        raise typer.Exit(1)

    db_path = Path(state_db)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    # Create validator and run verification
    try:
        validator = ArchiveValidator(archive_file, state_db)
        result = validator.verify_offsets()

        # Handle skipped (v1.0 schema)
        if result.skipped:
            console.print("[yellow]Offset verification skipped (v1.0 schema)[/yellow]")
            console.print(
                "[dim]Run 'gmailarchiver migrate' to upgrade to v1.1 for offset tracking[/dim]\n"
            )
            return

        # Display results
        console.print(f"Total offsets checked: [cyan]{result.total_checked}[/cyan]")
        console.print(f"Successful reads: [green]{result.successful_reads}[/green]")
        console.print(f"Failed reads: [red]{result.failed_reads}[/red]")
        console.print(f"Accuracy: [bold]{result.accuracy_percentage:.1f}%[/bold]\n")

        # Success case
        if result.accuracy_percentage == 100.0:
            from rich.panel import Panel
            console.print(Panel(
                f"[green]✓ All {result.total_checked} offsets verified successfully[/green]",
                title="Verification Passed",
                border_style="green"
            ))
            return

        # Failure case - show details
        if result.failures:
            table = Table(title="Offset Verification Failures")
            table.add_column("Failure Details", style="red")

            for failure in result.failures[:20]:  # Limit to first 20
                table.add_row(failure)

            console.print(table)

            if len(result.failures) > 20:
                console.print(
                    f"[dim]... and {len(result.failures) - 20} more failures[/dim]\n"
                )

        console.print(
            f"\n[red]Verification failed: {result.accuracy_percentage:.1f}% accuracy[/red]"
        )
        raise typer.Exit(1)

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="verify-consistency")
def verify_consistency_cmd(
    archive_file: str = typer.Argument(..., help="Path to archive file"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path")
) -> None:
    """
    Deep database consistency check.

    Validates database integrity, checks for orphaned records, missing records,
    duplicates, and FTS synchronization (v1.1 only).

    Example:
        $ gmailarchiver verify-consistency archive_20250114.mbox.gz
        $ gmailarchiver verify-consistency test.mbox --state-db /path/to/archive_state.db
    """
    console.print("\n[bold blue]Database Consistency Check[/bold blue]\n")

    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        console.print(f"[red]Error:[/red] Archive file not found: {archive_file}")
        raise typer.Exit(1)

    db_path = Path(state_db)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        raise typer.Exit(1)

    # Create validator and run consistency check
    try:
        validator = ArchiveValidator(archive_file, state_db)
        report = validator.verify_consistency()

        # Display schema version
        console.print(f"Schema version: [cyan]{report.schema_version}[/cyan]\n")

        # Create results table
        table = Table(title="Consistency Check Results")
        table.add_column("Check", style="cyan")
        table.add_column("Status", style="bold")

        # Add results
        table.add_row(
            "Orphaned records",
            f"[red]{report.orphaned_records}[/red]" if report.orphaned_records > 0
            else "[green]0[/green]"
        )
        table.add_row(
            "Missing records",
            f"[red]{report.missing_records}[/red]" if report.missing_records > 0
            else "[green]0[/green]"
        )
        table.add_row(
            "Duplicate Gmail IDs",
            f"[red]{report.duplicate_gmail_ids}[/red]" if report.duplicate_gmail_ids > 0
            else "[green]0[/green]"
        )

        if report.schema_version == "1.1":
            table.add_row(
                "Duplicate RFC Message-IDs",
                f"[red]{report.duplicate_rfc_message_ids}[/red]"
                if report.duplicate_rfc_message_ids > 0
                else "[green]0[/green]"
            )
            table.add_row(
                "FTS synchronized",
                "[green]Yes[/green]" if report.fts_synced else "[red]No[/red]"
            )

        console.print(table)

        # Show errors if any
        if report.errors:
            console.print("\n[bold red]Issues Found:[/bold red]")
            for error in report.errors:
                console.print(f"  • {error}")

        # Overall status
        if report.passed:
            from rich.panel import Panel
            console.print(Panel(
                "[green]✓ All consistency checks passed[/green]",
                title="Consistency Check Passed",
                border_style="green"
            ))
            return

        console.print("\n[red]Consistency check failed - issues detected[/red]\n")
        raise typer.Exit(1)

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


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
    state_db: str = typer.Option("archive_state.db", help="State database path")
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
    """
    import glob
    import time
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

    from .importer import ArchiveImporter
    from .migration import MigrationManager

    console.print("\n[bold blue]Import Archive[/bold blue]\n")

    db_path = Path(state_db)

    # Check if database exists (require v1.1 schema)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {state_db}")
        console.print("[yellow]Create a v1.1 database first (run 'gmailarchiver migrate')[/yellow]")
        raise typer.Exit(1)

    # Check database schema version (require v1.1)
    manager = MigrationManager(db_path)
    version = manager.detect_schema_version()
    manager._close()

    if version != "1.1":
        console.print("[red]Error:[/red] Import requires v1.1 database schema")
        console.print("[yellow]Run 'gmailarchiver migrate' to upgrade your database[/yellow]")
        raise typer.Exit(1)

    # Expand glob pattern
    files = glob.glob(archive_pattern)
    if not files:
        console.print(f"[red]Error:[/red] No files match pattern: {archive_pattern}")
        raise typer.Exit(1)

    console.print(f"Found {len(files)} file(s) to import\n")

    # Import each file with progress
    importer = ArchiveImporter(state_db)
    results = []
    start_time = time.perf_counter()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"Importing {len(files)} file(s)...", total=len(files))

        for file_path in files:
            try:
                result = importer.import_archive(
                    file_path,
                    account_id=account_id,
                    skip_duplicates=skip_duplicates
                )
                results.append(result)
                progress.advance(task)
            except Exception as e:
                console.print(f"\n[red]Error importing {file_path}:[/red] {e}")
                progress.advance(task)

    total_time = time.perf_counter() - start_time

    # Display summary table
    table = Table(title="Import Summary")
    table.add_column("Archive File", style="cyan")
    table.add_column("Imported", style="green", justify="right")
    table.add_column("Skipped", style="yellow", justify="right")
    table.add_column("Failed", style="red", justify="right")
    table.add_column("Time (ms)", style="magenta", justify="right")

    total_imported = 0
    total_skipped = 0
    total_failed = 0

    for result in results:
        table.add_row(
            Path(result.archive_file).name,
            str(result.messages_imported),
            str(result.messages_skipped),
            str(result.messages_failed),
            f"{result.execution_time_ms:.2f}"
        )
        total_imported += result.messages_imported
        total_skipped += result.messages_skipped
        total_failed += result.messages_failed

    console.print(table)

    # Show aggregate statistics
    console.print(f"\n[green]✓ Total messages imported: {total_imported}[/green]")
    if total_skipped > 0:
        console.print(f"[yellow]  Skipped duplicates: {total_skipped}[/yellow]")
    if total_failed > 0:
        console.print(f"[red]  Failed: {total_failed}[/red]")

    # Show performance metrics
    if total_imported > 0 and total_time > 0:
        rate = total_imported / total_time
        console.print(f"\n[dim]Performance: {rate:.1f} messages/second[/dim]")

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
