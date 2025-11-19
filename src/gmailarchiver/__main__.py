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
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Archive Gmail messages older than the specified threshold.

    Examples:
        $ gmailarchiver archive 3y
        $ gmailarchiver archive 3y --compress zstd
        $ gmailarchiver archive 3y --compress gzip
        $ gmailarchiver archive 3y --trash
        $ gmailarchiver archive 6m --dry-run
        $ gmailarchiver archive 3y --json
    """
    from gmailarchiver.output import OutputManager

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

    out = OutputManager(json_mode=json_output)
    operation_mode = "archive (dry-run)" if dry_run else "archive"
    out.start_operation(operation_mode, f"Archiving messages older than {age_threshold}")

    # Authenticate
    try:
        # credentials=None uses bundled OAuth credentials
        # token_file=None uses ~/.config/gmailarchiver/token.json
        out.info("Authenticating with Gmail...")
        authenticator = GmailAuthenticator(credentials_file=credentials)
        creds = authenticator.authenticate()
        out.success("Authentication successful")
    except FileNotFoundError as e:
        out.error(
            str(e),
            suggestion="Check credentials file path or use bundled credentials",
            exit_code=1,
        )

    # Initialize clients
    gmail_client = GmailClient(creds)
    archiver = GmailArchiver(gmail_client)

    # Perform archiving
    try:
        with out.progress_context("Archiving messages", total=None) as progress:
            result = archiver.archive(
                age_threshold=age_threshold,
                output_file=output,
                compress=compress,
                incremental=incremental,
                dry_run=dry_run
            )

        if dry_run:
            out.warning("DRY RUN completed - no changes made")
            report_data = {
                "Messages Found": result['messages_archived'],
                "Output File": output,
                "Mode": "Dry Run (no changes made)",
            }
            out.show_report("Archive Preview", report_data)
            out.end_operation(success=True)
            return

        if result['messages_archived'] == 0:
            out.warning("No messages to archive")
            out.suggest_next_steps([
                "Check your age threshold",
                "Verify messages exist in Gmail matching the criteria",
            ])
            out.end_operation(success=True)
            return

        # Validate archive
        out.info("Validating archive...")

        # Get the actual message IDs that were archived
        with ArchiveState() as state:
            # Get recently archived messages for this file
            archived_ids = state.get_archived_message_ids_for_file(output)

        validation_passed = archiver.validate_archive(output, archived_ids)

        if not validation_passed:
            out.error(
                "Archive validation failed!",
                suggestion="Check disk space and file permissions. DO NOT delete Gmail messages yet.",
                exit_code=1,
            )

        out.success("Archive validation passed")

        # Handle deletion if requested
        if trash or delete:
            if not validation_passed:
                out.error(
                    "Cannot delete: Archive validation failed",
                    suggestion="Resolve validation issues before attempting deletion",
                    exit_code=1,
                )

            if delete:
                # Permanent deletion requires explicit confirmation
                out.warning("⚠ WARNING: PERMANENT DELETION")
                msg_count = result['messages_archived']
                out.warning(f"This will permanently delete {msg_count} messages.")
                out.warning("This action CANNOT be undone!")

                confirmation = typer.prompt(
                    f"\nType 'DELETE {result['messages_archived']} MESSAGES' to confirm"
                )

                if confirmation != f"DELETE {result['messages_archived']} MESSAGES":
                    out.info("Deletion cancelled")
                    out.end_operation(success=True)
                    return

                # Perform permanent deletion
                with out.progress_context("Permanently deleting messages", total=None) as progress:
                    archiver.delete_archived_messages(
                        list(archived_ids),
                        permanent=True
                    )
                out.success("Messages permanently deleted")

            elif trash:
                # Move to trash with confirmation
                if not typer.confirm(
                    f"\nMove {result['messages_archived']} messages to trash? "
                    "(30-day recovery period)"
                ):
                    out.info("Cancelled")
                    out.end_operation(success=True)
                    return

                with out.progress_context("Moving messages to trash", total=None) as progress:
                    archiver.delete_archived_messages(
                        list(archived_ids),
                        permanent=False
                    )
                out.success("Messages moved to trash")

        # Build final report
        report_data = {
            "Messages Archived": result['messages_archived'],
            "Archive File": output,
            "Incremental Mode": "Yes" if incremental else "No",
        }

        if compress:
            report_data["Compression"] = compress

        if trash:
            report_data["Gmail Status"] = "Moved to trash (30-day recovery)"
        elif delete:
            report_data["Gmail Status"] = "Permanently deleted"

        out.show_report("Archive Summary", report_data)
        out.success("Archive completed successfully!")

        # Suggest next steps
        next_steps = [
            f"Validate archive: gmailarchiver validate {output}",
        ]

        if not trash and not delete:
            next_steps.append(f"Move to trash: gmailarchiver retry-delete {output}")
            next_steps.append(f"Permanently delete: gmailarchiver retry-delete {output} --permanent")

        out.suggest_next_steps(next_steps)
        out.end_operation(success=True)

    except Exception as e:
        out.error(f"Archive operation failed: {e}", exit_code=1)


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
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Show archiving status and statistics.

    Examples:
        $ gmailarchiver status
        $ gmailarchiver status --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("status", "Retrieving archive statistics")

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.warning("No archive database found")
        output.suggest_next_steps([
            "Archive emails: gmailarchiver archive 3y",
            "Import existing archive: gmailarchiver import archive.mbox",
        ])
        output.end_operation(success=True)
        raise typer.Exit(0)

    with ArchiveState(state_db) as state:
        # Overall stats
        total_archived = state.get_archived_count()

        # Recent runs
        recent_runs = state.get_archive_runs(limit=10)

        # Build report data
        report_data = {
            "Total Messages Archived": f"{total_archived:,}",
            "Recent Archive Runs": len(recent_runs),
        }

        output.show_report("Archive Status", report_data)

        # Display recent runs table (Rich only, not in JSON)
        if not json_output and recent_runs:
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
            console.print()
        elif not recent_runs:
            output.warning("No archive runs found")

    output.end_operation(success=True)


@app.command()
def migrate(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Migrate database schema to latest version (v1.1.0).

    Automatically detects schema version and migrates from v1.0 to v1.1
    with enhanced features including mbox offset tracking and full-text search.

    Examples:
        $ gmailarchiver migrate
        $ gmailarchiver migrate --state-db /path/to/archive_state.db
        $ gmailarchiver migrate --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("migrate", "Migrating database schema")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Check the database path or use --state-db to specify location",
            exit_code=1,
        )

    # Initialize migration manager
    manager = MigrationManager(db_path)

    # Detect current schema version
    current_version = manager.detect_schema_version()

    # Check if migration is needed
    if current_version == "1.1":
        output.success("Database is already at version 1.1 (up to date)")
        output.end_operation(success=True)
        manager._close()
        return

    if current_version == "none":
        output.error(
            "Database appears to be empty or invalid",
            suggestion="Create a new database with 'gmailarchiver archive' or 'gmailarchiver import'",
            exit_code=1,
        )

    # Show migration info
    output.info(f"Current schema version: {current_version}")
    output.info("\nMigration from v1.0 to v1.1 will:")
    output.info("  • Create backup of current database")
    output.info("  • Add enhanced schema with mbox offset tracking")
    output.info("  • Enable full-text search capabilities")
    output.info("  • Add multi-account support (future-ready)")
    output.info("  • Preserve all existing message data")

    # Confirm migration
    if not typer.confirm("\nProceed with migration?"):
        output.info("Migration cancelled")
        output.end_operation(success=True)
        manager._close()
        return

    try:
        # Create backup with progress
        with output.progress_context("Creating backup", total=3) as progress:
            task = progress.add_task("Migration", total=3) if progress else None

            backup_path = manager.create_backup()
            if progress and task:
                progress.update(task, advance=1)

            output.success(f"Backup created: {backup_path}")

            # Run migration
            manager.migrate_v1_to_v1_1()
            if progress and task:
                progress.update(task, advance=1)

            # Validate migration
            manager.validate_migration()
            if progress and task:
                progress.update(task, advance=1)

        # Build report data
        report_data = {
            "From Version": current_version,
            "To Version": "1.1",
            "Backup Location": str(backup_path),
        }

        output.show_report("Migration Summary", report_data)
        output.success("Migration completed successfully!")

        output.suggest_next_steps([
            "Verify integrity: gmailarchiver verify-integrity",
            "Search messages: gmailarchiver search <query>",
        ])

        output.end_operation(success=True)

    except Exception as e:
        output.error(f"Migration failed: {e}", exit_code=1)
    finally:
        manager._close()


@app.command(name="db-info")
def db_info(
    state_db: str = typer.Option(
        "archive_state.db",
        "--state-db",
        help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Display database information and statistics.

    Shows schema version, message count, database size, and recent archive runs.

    Examples:
        $ gmailarchiver db-info
        $ gmailarchiver db-info --state-db /path/to/archive_state.db
        $ gmailarchiver db-info --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("db-info", "Retrieving database information")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.warning(f"Database not found: {state_db}")
        output.suggest_next_steps([
            "Create database: gmailarchiver archive 3y",
            "Import archive: gmailarchiver import archive.mbox",
        ])
        output.end_operation(success=True)
        return

    # Detect schema version
    manager = MigrationManager(db_path)
    version = manager.detect_schema_version()

    # Show database file size
    db_size = db_path.stat().st_size

    # Get message count and recent runs
    try:
        with ArchiveState(db_path=str(db_path), validate_path=False) as state:
            total_messages = state.get_archived_count()

            # Show recent archive runs
            recent_runs = state.get_archive_runs(limit=5)

            # Build report data
            report_data = {
                "Schema Version": version,
                "Database Size": format_bytes(db_size),
                "Total Messages": f"{total_messages:,}",
                "Recent Archive Runs": len(recent_runs),
            }

            output.show_report("Database Information", report_data)

            # Display recent runs table (Rich only, not in JSON)
            if not json_output and recent_runs:
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
                console.print()
            elif not recent_runs:
                output.warning("No archive runs found")

            output.end_operation(success=True)

    except Exception as e:
        output.error(f"Error reading database: {e}", exit_code=1)
    finally:
        manager._close()


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
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Show deduplication analysis without making changes.

    Analyzes the archive database for duplicate messages (same RFC Message-ID)
    and displays statistics about potential space savings.

    Example:
        $ gmailarchiver dedupe-report
        $ gmailarchiver dedupe-report --state-db /path/to/archive_state.db
        $ gmailarchiver dedupe-report --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("dedupe-report", "Analyzing duplicates")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            with output.progress_context("Analyzing duplicates", total=None) as progress:
                # Find duplicates
                duplicates = dedup.find_duplicates()

                # Generate report
                report = dedup.generate_report(duplicates)

            # Display results
            if report.duplicate_message_ids == 0:
                output.success("No duplicate messages found!")
                output.end_operation(success=True)
                return

            # Build report data
            report_data = {
                "Total Messages": f"{report.total_messages:,}",
                "Duplicate Message-IDs": report.duplicate_message_ids,
                "Total Duplicate Messages": report.total_duplicate_messages,
                "Messages to Remove": report.messages_to_remove,
                "Space Recoverable": format_bytes(report.space_recoverable),
            }

            output.show_report("Deduplication Analysis", report_data)

            # Show breakdown by archive file
            if report.breakdown_by_archive:
                output.info("\nBreakdown by archive file:")
                for archive_file, stats in sorted(report.breakdown_by_archive.items()):
                    output.info(
                        f"  • {archive_file}: {stats['messages_to_remove']} duplicates, "
                        f"{format_bytes(stats['space_recoverable'])} recoverable"
                    )

            output.suggest_next_steps([
                "Remove duplicates (dry run): gmailarchiver dedupe --dry-run",
                "Remove duplicates: gmailarchiver dedupe --strategy newest --no-dry-run",
            ])

            output.end_operation(success=True)

    except ValueError as e:
        output.error(
            str(e),
            suggestion="Run 'gmailarchiver migrate' to upgrade your database",
            exit_code=1,
        )
    except Exception as e:
        output.error(f"Deduplication analysis failed: {e}", exit_code=1)


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
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
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
        $ gmailarchiver dedupe --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    operation_name = "dedupe (dry-run)" if dry_run else "dedupe"
    output.start_operation(operation_name, f"Removing duplicates (strategy: {strategy})")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )

    # Validate strategy
    valid_strategies = ['newest', 'largest', 'first']
    if strategy not in valid_strategies:
        output.error(
            f"Invalid strategy: {strategy}",
            suggestion=f"Must be one of: {', '.join(valid_strategies)}",
            exit_code=1,
        )

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            with output.progress_context("Finding duplicates", total=None) as progress:
                # Find duplicates
                duplicates = dedup.find_duplicates()

            # Check if there are duplicates
            if not duplicates:
                output.success("No duplicate messages found!")
                output.end_operation(success=True)
                return

            # Show what will be done
            report = dedup.generate_report(duplicates)

            report_data = {
                "Strategy": strategy,
                "Duplicate Message-IDs": report.duplicate_message_ids,
                "Messages to Remove": report.messages_to_remove,
                "Space to Save": format_bytes(report.space_recoverable),
            }

            if dry_run:
                output.warning("DRY RUN - No changes will be made")

                with output.progress_context("Analyzing duplicates", total=None) as progress:
                    # Show preview of what would be removed
                    result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=True)

                report_data["Would Remove"] = f"{result.messages_removed:,} messages"
                report_data["Would Keep"] = f"{result.messages_kept:,} messages"
                report_data["Would Save"] = format_bytes(result.space_saved)

                output.show_report("Deduplication Preview (Dry Run)", report_data)

                output.suggest_next_steps([
                    f"Apply changes: gmailarchiver dedupe --strategy {strategy} --no-dry-run",
                ])

            else:
                # Confirm before proceeding
                output.warning(
                    "⚠ WARNING: This will permanently remove duplicate messages from the database"
                )
                output.info("The mbox files themselves will not be modified.")

                if not typer.confirm(
                    f"Remove {report.messages_to_remove:,} duplicate messages "
                    f"using '{strategy}' strategy?"
                ):
                    output.info("Cancelled")
                    output.end_operation(success=True)
                    return

                # Perform deduplication
                with output.progress_context("Removing duplicates", total=None) as progress:
                    result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=False)

                report_data["Removed"] = f"{result.messages_removed:,} messages"
                report_data["Kept"] = f"{result.messages_kept:,} messages"
                report_data["Space Saved"] = format_bytes(result.space_saved)

                output.show_report("Deduplication Results", report_data)
                output.success("Deduplication completed!")

                output.suggest_next_steps([
                    "Verify database: gmailarchiver verify-integrity",
                    "Consolidate archives: gmailarchiver consolidate archive*.mbox -o merged.mbox",
                ])

            output.end_operation(success=True)

    except ValueError as e:
        output.error(
            str(e),
            suggestion="Run 'gmailarchiver migrate' to upgrade your database",
            exit_code=1,
        )
    except Exception as e:
        output.error(f"Deduplication failed: {e}", exit_code=1)


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
        $ gmailarchiver search "meeting notes" --json
    """
    import json
    import time
    from datetime import datetime

    from .migration import MigrationManager
    from .search import SearchEngine
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)

    # Check database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' or 'gmailarchiver import' to create database",
            exit_code=1,
        )

    # Check schema version (require v1.1)
    manager = MigrationManager(db_path)
    schema_version = manager.detect_schema_version()
    manager._close()

    if schema_version != "1.1":
        output.error(
            "Search requires v1.1 database schema",
            suggestion="Run 'gmailarchiver migrate' to upgrade",
            exit_code=1,
        )

    # Validate dates if provided
    if after:
        try:
            datetime.strptime(after, '%Y-%m-%d')
        except ValueError:
            output.error(
                f"Invalid date format: {after}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
                exit_code=1,
            )

    if before:
        try:
            datetime.strptime(before, '%Y-%m-%d')
        except ValueError:
            output.error(
                f"Invalid date format: {before}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
                exit_code=1,
            )

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
            output.error(
                "No search query or filters provided",
                suggestion="Provide a query argument or use filters like --from, --subject, etc.",
                exit_code=1,
            )

        query = " ".join(query_parts)

    output.start_operation("search", f"Searching: {query}")

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
                output.warning("No results found")
                output.suggest_next_steps([
                    "Try a broader search query",
                    "Check query syntax with: gmailarchiver search --help",
                ])
                output.end_operation(success=True)
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
            console.print()

            # Show summary
            report_data = {
                "Query": query,
                "Results Found": results.total_results,
                "Execution Time": f"{execution_time_ms:.2f}ms",
            }
            output.show_report("Search Summary", report_data)

        output.end_operation(success=True)

    except ValueError as e:
        output.error(f"Search query error: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Search failed: {e}", exit_code=1)


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
    output_file: str = typer.Option(..., "-o", "--output", help="Output archive file"),
    sort: bool = typer.Option(True, help="Sort messages chronologically"),
    dedupe: bool = typer.Option(True, help="Remove duplicate messages"),
    dedupe_strategy: str = typer.Option("newest", help="Dedup strategy: newest/largest/first"),
    compress: str | None = typer.Option(None, help="Compression: gzip/lzma/zstd"),
    state_db: str = typer.Option("archive_state.db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
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
        $ gmailarchiver consolidate archive*.mbox -o merged.mbox --json
    """
    import glob

    from gmailarchiver.consolidator import ArchiveConsolidator
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("consolidate", f"Consolidating to {output_file}")

    # 1. Expand glob patterns
    all_files = []
    for pattern in archives:
        matches = glob.glob(pattern)
        if not matches:
            # Try as literal file path
            if Path(pattern).exists():
                all_files.append(pattern)
            else:
                output.warning(f"No files match pattern: {pattern}")
        else:
            all_files.extend(matches)

    if not all_files:
        output.error(
            "No archive files found",
            suggestion="Check file paths or glob patterns",
            exit_code=1,
        )

    output.info(f"Found {len(all_files)} archive(s) to consolidate")

    # 2. Validate dedupe strategy
    valid_strategies = ['newest', 'largest', 'first']
    if dedupe_strategy not in valid_strategies:
        output.error(
            f"Invalid dedupe strategy: {dedupe_strategy}",
            suggestion=f"Valid strategies: {', '.join(valid_strategies)}",
            exit_code=1,
        )

    # 3. Auto-detect compression from output extension
    if compress is None:
        output_path = Path(output_file)
        if output_path.suffix == '.gz':
            compress = 'gzip'
        elif output_path.suffix == '.xz':
            compress = 'lzma'
        elif output_path.suffix == '.zst':
            compress = 'zstd'

    # 4. Check if output file exists
    output_path = Path(output_file)
    if output_path.exists():
        overwrite = typer.confirm(f"Output file exists: {output_file}. Overwrite?")
        if not overwrite:
            output.info("Consolidation cancelled")
            output.end_operation(success=True)
            raise typer.Exit(0)

    # 5. Consolidate with progress
    consolidator = ArchiveConsolidator(state_db)

    try:
        with output.progress_context("Consolidating archives", total=None) as progress:
            # Convert file paths to list[str | Path] for type compatibility
            source_paths: list[str | Path] = [Path(f) for f in all_files]

            result = consolidator.consolidate(
                source_archives=source_paths,
                output_archive=output_file,
                sort_by_date=sort,
                deduplicate=dedupe,
                dedupe_strategy=dedupe_strategy,
                compress=compress
            )

        # 6. Build report data
        report_data = {
            "Source Archives": len(result.source_files),
            "Total Messages": result.total_messages,
            "Duplicates Removed": result.duplicates_removed,
            "Messages Consolidated": result.messages_consolidated,
            "Sorted by Date": "Yes" if result.sort_applied else "No",
        }

        if result.compression_used:
            report_data["Compression"] = result.compression_used

        # 7. Performance metrics
        if result.execution_time_ms > 0:
            rate = (result.messages_consolidated / result.execution_time_ms) * 1000
            report_data["Performance"] = f"{rate:.1f} messages/second"

        output.show_report("Consolidation Summary", report_data)
        output.success(f"Consolidation complete! Output: {result.output_file}")

        output.suggest_next_steps([
            "Verify consolidated archive: gmailarchiver validate " + result.output_file,
            "Search messages: gmailarchiver search <query>",
        ])

        output.end_operation(success=True)

    except ValueError as e:
        output.error(f"Validation error: {e}", exit_code=1)
    except FileNotFoundError as e:
        output.error(f"File not found: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Consolidation failed: {e}", exit_code=1)


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
