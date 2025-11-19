"""Gmail Archiver CLI application."""

from datetime import datetime
from pathlib import Path
from typing import Any

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


app = typer.Typer(help="Archive old Gmail messages to local mbox files", no_args_is_help=True)
console = Console()


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


@app.command()
def archive(
    age_threshold: str = typer.Argument(
        ..., help="Age threshold (e.g., '3y' for 3 years, '6m' for 6 months, '2w' for 2 weeks)"
    ),
    output: str = typer.Option(
        None, "--output", "-o", help="Output file path (default: archive_YYYYMMDD.mbox[.gz])"
    ),
    compress: str | None = typer.Option(
        None,
        "--compress",
        "-c",
        help="Compression format: 'gzip', 'lzma', or 'zstd' (fastest, recommended)",
    ),
    incremental: bool = typer.Option(
        True, "--incremental/--no-incremental", help="Skip already-archived messages"
    ),
    trash: bool = typer.Option(
        False, "--trash", help="Move archived messages to trash (30-day recovery)"
    ),
    delete: bool = typer.Option(
        False, "--delete", help="Permanently delete archived messages (IRREVERSIBLE!)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
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
        timestamp = datetime.now().strftime("%Y%m%d")
        extension = ".mbox"
        if compress == "gzip":
            extension = ".mbox.gz"
        elif compress == "lzma":
            extension = ".mbox.xz"
        elif compress == "zstd":
            extension = ".mbox.zst"
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
                dry_run=dry_run,
            )

        if dry_run:
            out.warning("DRY RUN completed - no changes made")
            report_data = {
                "Messages Found": result["messages_archived"],
                "Output File": output,
                "Mode": "Dry Run (no changes made)",
            }
            out.show_report("Archive Preview", report_data)
            out.end_operation(success=True)
            return

        if result["messages_archived"] == 0:
            out.warning("No messages to archive")
            out.suggest_next_steps(
                [
                    "Check your age threshold",
                    "Verify messages exist in Gmail matching the criteria",
                ]
            )
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
                msg_count = result["messages_archived"]
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
                    archiver.delete_archived_messages(list(archived_ids), permanent=True)
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
                    archiver.delete_archived_messages(list(archived_ids), permanent=False)
                out.success("Messages moved to trash")

        # Build final report
        report_data = {
            "Messages Archived": result["messages_archived"],
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
            next_steps.append(
                f"Permanently delete: gmailarchiver retry-delete {output} --permanent"
            )

        out.suggest_next_steps(next_steps)
        out.end_operation(success=True)

    except Exception as e:
        out.error(f"Archive operation failed: {e}", exit_code=1)


@app.command()
def validate(
    archive_file: str = typer.Argument(..., help="Path to archive file to validate"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
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
            suggestions.append("Check archive file for corruption or try re-downloading")

        if not results["count_check"] or not results["spot_check"]:
            suggestions.append(
                f"Verify database integrity: gmailarchiver verify-integrity --state-db {state_db}"
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
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
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
        if not authenticator.validate_scopes(["https://mail.google.com/"]):
            console.print("\n[red]Error: Missing deletion permission[/red]")
            console.print(
                "\nYour current authorization doesn't include permission to delete messages."
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
            console.print(f"This will [bold]permanently delete[/bold] {len(message_ids)} messages.")
            console.print("[red]This action CANNOT be undone![/red]")
            console.print(
                "\nDeleted messages will be gone forever - not in trash, not recoverable.\n"
            )

            confirmation = typer.prompt(f"Type 'DELETE {len(message_ids)} MESSAGES' to confirm")
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
        "archive_state.db", "--state-db", help="Path to state database file"
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
        output.suggest_next_steps(
            [
                "Archive emails: gmailarchiver archive 3y",
                "Import existing archive: gmailarchiver import archive.mbox",
            ]
        )
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
                    str(run["run_id"]),
                    run["timestamp"][:19],  # Truncate timestamp
                    run["query"],
                    str(run["messages_archived"]),
                    run["archive_file"],
                )

            console.print(table)
            console.print()
        elif not recent_runs:
            output.warning("No archive runs found")

    output.end_operation(success=True)


@app.command()
def migrate(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
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

        output.suggest_next_steps(
            [
                "Verify integrity: gmailarchiver verify-integrity",
                "Search messages: gmailarchiver search <query>",
            ]
        )

        output.end_operation(success=True)

    except Exception as e:
        output.error(f"Migration failed: {e}", exit_code=1)
    finally:
        manager._close()


@app.command(name="db-info")
def db_info(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
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
        output.suggest_next_steps(
            [
                "Create database: gmailarchiver archive 3y",
                "Import archive: gmailarchiver import archive.mbox",
            ]
        )
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
                        str(run["run_id"]),
                        run["timestamp"][:19],  # Truncate timestamp
                        str(run["messages_archived"]),
                        run["archive_file"],
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
        None, "--backup-file", help="Path to backup file for rollback"
    ),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
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
            parts = backup.name.split(".")
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
        "archive_state.db", "--state-db", help="Path to state database file"
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

            output.suggest_next_steps(
                [
                    "Remove duplicates (dry run): gmailarchiver dedupe --dry-run",
                    "Remove duplicates: gmailarchiver dedupe --strategy newest --no-dry-run",
                ]
            )

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
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    strategy: str = typer.Option(
        "newest", "--strategy", help="Which copy to keep: 'newest', 'largest', or 'first'"
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run/--no-dry-run", help="Preview changes without executing"
    ),
    auto_verify: bool = typer.Option(
        False, "--auto-verify", help="Run verification after deduplication"
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
        $ gmailarchiver dedupe --strategy newest --no-dry-run --auto-verify
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
    valid_strategies = ["newest", "largest", "first"]
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

                output.suggest_next_steps(
                    [
                        f"Apply changes: gmailarchiver dedupe --strategy {strategy} --no-dry-run",
                    ]
                )

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

                output.suggest_next_steps(
                    [
                        "Verify database: gmailarchiver verify-integrity",
                        "Consolidate archives: gmailarchiver consolidate archive*.mbox -o merged.mbox",
                    ]
                )

                # Auto-verify if requested (only for non-dry-run)
                if auto_verify:
                    from gmailarchiver.db_manager import DBManager

                    output.info("\nRunning verification...")
                    try:
                        db = DBManager(str(db_path), validate_schema=False)
                        issues = db.verify_database_integrity()
                        db.close()

                        if not issues:
                            output.success("Verification complete - no issues found")
                        else:
                            output.warning(f"Verification found {len(issues)} issue(s):")
                            for issue in issues[:5]:  # Show first 5 issues
                                output.info(f"  • {issue}")
                            if len(issues) > 5:
                                output.info(f"  ... and {len(issues) - 5} more issues")

                            output.suggest_next_steps(
                                [
                                    "Fix issues automatically: gmailarchiver check --auto-repair",
                                    "View all issues: gmailarchiver verify-integrity --verbose",
                                ]
                            )
                    except Exception as e:
                        output.warning(f"Verification failed: {e}")

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
            output.suggest_next_steps(
                [
                    "Upgrade to v1.1: gmailarchiver migrate",
                ]
            )
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
        output.suggest_next_steps(
            [
                "Repair offsets: gmailarchiver repair --backfill --no-dry-run",
                "Check database integrity: gmailarchiver verify-integrity",
            ]
        )

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
        output.suggest_next_steps(
            [
                "Repair database: gmailarchiver repair --no-dry-run",
                "Check integrity: gmailarchiver verify-integrity --verbose",
            ]
        )

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
    extract: bool = typer.Option(False, "--extract", help="Extract all search results"),
    output_dir: str | None = typer.Option(
        None, "--output-dir", help="Directory for extracted messages (required with --extract)"
    ),
    with_preview: bool = typer.Option(False, "--with-preview", help="Show message body preview"),
    interactive: bool = typer.Option(
        False, "--interactive", help="Interactive message selection for extraction"
    ),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Search archived messages.

    Examples:
        $ gmailarchiver search "from:alice meeting"
        $ gmailarchiver search "invoice payment" --limit 50
        $ gmailarchiver search --from alice@example.com --subject meeting
        $ gmailarchiver search --after 2024-01-01 --before 2024-12-31
        $ gmailarchiver search "meeting notes" --json
        $ gmailarchiver search "from:alice" --extract --output-dir /tmp/emails
        $ gmailarchiver search "meeting" --with-preview
        $ gmailarchiver search "important" --interactive
    """
    import json
    import time
    from datetime import datetime

    from .migration import MigrationManager
    from .search import SearchEngine
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)

    # Validate flags
    if extract and not output_dir:
        output.error(
            "--extract requires --output-dir",
            suggestion="Specify output directory: --output-dir /path/to/directory",
            exit_code=1,
        )

    # Interactive mode is mutually exclusive with some flags
    if interactive and json_output:
        output.error(
            "--interactive cannot be used with --json",
            suggestion="Remove --json flag for interactive mode",
            exit_code=1,
        )

    if interactive and extract:
        output.error(
            "--interactive cannot be used with --extract",
            suggestion="Use --interactive alone (extraction is part of interactive mode)",
            exit_code=1,
        )

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
            datetime.strptime(after, "%Y-%m-%d")
        except ValueError:
            output.error(
                f"Invalid date format: {after}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
                exit_code=1,
            )

    if before:
        try:
            datetime.strptime(before, "%Y-%m-%d")
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
            data = []
            for r in results.results:
                entry = {
                    "gmail_id": r.gmail_id,
                    "rfc_message_id": r.rfc_message_id,
                    "date": r.date,
                    "from": r.from_addr,
                    "to": r.to_addr,
                    "subject": r.subject,
                    "archive_file": r.archive_file,
                    "mbox_offset": r.mbox_offset,
                    "relevance_score": r.relevance_score,
                }
                # Add body_preview if --with-preview flag is used
                if with_preview:
                    preview = r.body_preview or ""
                    # Truncate to 200 chars
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    entry["body_preview"] = preview
                data.append(entry)
            print(json.dumps(data, indent=2))
        else:
            # Rich table output
            if results.total_results == 0:
                output.warning("No results found")
                output.suggest_next_steps(
                    [
                        "Try a broader search query",
                        "Check query syntax with: gmailarchiver search --help",
                    ]
                )
                output.end_operation(success=True)
                return

            # Display results based on --with-preview flag
            if with_preview:
                # Display with preview (list format)
                console.print(f"\n[bold cyan]Search Results ({results.total_results} found)[/bold cyan]\n")

                for idx, result in enumerate(results.results, 1):
                    # Truncate preview to 200 chars
                    preview = result.body_preview or ""
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    preview_display = preview if preview else "(no preview)"

                    console.print(f"[bold]{idx}. Subject:[/bold] {result.subject or '(no subject)'}")
                    console.print(f"   [cyan]From:[/cyan] {result.from_addr}")
                    console.print(f"   [cyan]Date:[/cyan] {result.date[:10] if result.date else 'N/A'}")
                    console.print(f"   [yellow]Preview:[/yellow] {preview_display}")
                    console.print(f"   [magenta]Gmail ID:[/magenta] {result.gmail_id}")
                    console.print()
            else:
                # Display table (default)
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
                        archive_display,
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

        # Interactive mode: allow user to select messages for extraction
        if interactive and not json_output:
            try:
                import questionary
            except ImportError:
                output.error(
                    "Interactive mode requires 'questionary' package",
                    suggestion="Install with: pip install questionary",
                    exit_code=1,
                )

            # Build choices for interactive selection
            choices = []
            for idx, result in enumerate(results.results, 1):
                subject_display = result.subject or "(no subject)"
                if len(subject_display) > 50:
                    subject_display = subject_display[:50] + "..."

                choice_label = (
                    f"{idx}. {subject_display} "
                    f"(from: {result.from_addr[:30]}, "
                    f"date: {result.date[:10] if result.date else 'N/A'})"
                )
                choices.append(questionary.Choice(title=choice_label, value=result.gmail_id))

            # Prompt user to select messages
            console.print()
            selected_ids = questionary.checkbox(
                "Select messages to extract (space to select, enter to confirm):",
                choices=choices,
            ).ask()

            # Handle cancellation or no selection
            if not selected_ids:
                output.info("No messages selected. Cancelled.")
                output.end_operation(success=True)
                return

            # Prompt for output directory
            default_output_dir = "./extracted"
            output_dir_str = questionary.path(
                "Output directory for extracted messages:",
                default=default_output_dir,
                only_directories=True,
            ).ask()

            if not output_dir_str:
                output.info("No output directory specified. Cancelled.")
                output.end_operation(success=True)
                return

            # Extract selected messages
            from gmailarchiver.extractor import MessageExtractor

            output.info(f"\nExtracting {len(selected_ids)} selected messages to {output_dir_str}...")

            with MessageExtractor(state_db) as extractor:
                with output.progress_context(
                    "Extracting messages", total=len(selected_ids)
                ) as progress:
                    task = (
                        progress.add_task("Extracting", total=len(selected_ids)) if progress else None
                    )

                    stats = extractor.batch_extract(selected_ids, Path(output_dir_str))

                    if progress and task:
                        progress.update(task, completed=len(selected_ids))

            # Show extraction summary
            extraction_report = {
                "Messages Selected": len(selected_ids),
                "Messages Extracted": stats["extracted"],
                "Failed": stats["failed"],
                "Output Directory": output_dir_str,
            }
            output.show_report("Extraction Summary", extraction_report)

            if stats["errors"]:
                output.warning(f"Encountered {len(stats['errors'])} error(s):")
                for error in stats["errors"][:5]:  # Show first 5 errors
                    output.info(f"  • {error}")
                if len(stats["errors"]) > 5:
                    output.info(f"  ... and {len(stats['errors']) - 5} more")

            output.end_operation(success=True)
            return

        # Extract messages if requested
        if extract:
            from gmailarchiver.extractor import MessageExtractor

            output.info(f"\nExtracting {results.total_results} messages to {output_dir}...")

            gmail_ids = [r.gmail_id for r in results.results]

            with MessageExtractor(state_db) as extractor:
                with output.progress_context(
                    "Extracting messages", total=len(gmail_ids)
                ) as progress:
                    task = (
                        progress.add_task("Extracting", total=len(gmail_ids)) if progress else None
                    )

                    stats = extractor.batch_extract(gmail_ids, Path(output_dir))

                    if progress and task:
                        progress.update(task, completed=len(gmail_ids))

            # Show extraction summary
            extraction_report = {
                "Messages Extracted": stats["extracted"],
                "Failed": stats["failed"],
                "Output Directory": output_dir,
            }
            output.show_report("Extraction Summary", extraction_report)

            if stats["errors"]:
                output.warning(f"Encountered {len(stats['errors'])} error(s):")
                for error in stats["errors"][:5]:  # Show first 5 errors
                    output.info(f"  • {error}")
                if len(stats["errors"]) > 5:
                    output.info(f"  ... and {len(stats['errors']) - 5} more")

        output.end_operation(success=True)

    except ValueError as e:
        output.error(f"Search query error: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Search failed: {e}", exit_code=1)


@app.command()
def extract(
    message_id: str = typer.Argument(..., help="Gmail ID or RFC Message-ID to extract"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output file path (stdout if not specified)"
    ),
    archive: str | None = typer.Option(
        None, "--archive", help="Archive file (auto-detect from database if not specified)"
    ),
    format: str = typer.Option("raw", "--format", help="Output format: raw (default), eml, json"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Extract full message from archive.

    Retrieves a message by Gmail ID or RFC Message-ID and outputs it to stdout
    or a file. Transparently handles compressed archives.

    Examples:
        $ gmailarchiver extract abc123def456
        $ gmailarchiver extract abc123def456 --output message.eml
        $ gmailarchiver extract "<message-id@example.com>" --output msg.eml
        $ gmailarchiver extract abc123 --archive archive.mbox.zst
        $ gmailarchiver extract abc123 --json
    """
    from gmailarchiver.extractor import MessageExtractor, ExtractorError
    from gmailarchiver.output import OutputManager

    out = OutputManager(json_mode=json_output)

    # Check database exists
    db_path = Path(state_db)
    if not db_path.exists():
        out.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' or 'gmailarchiver import' to create database",
            exit_code=1,
        )

    out.start_operation("extract", f"Extracting message: {message_id}")

    try:
        with MessageExtractor(state_db) as extractor:
            # Try extracting by gmail_id first, then by rfc_message_id
            try:
                message_bytes = extractor.extract_by_gmail_id(message_id, output)
            except ExtractorError:
                # Not found by gmail_id, try rfc_message_id
                try:
                    message_bytes = extractor.extract_by_rfc_message_id(message_id, output)
                except ExtractorError as e:
                    out.error(
                        f"Message not found: {message_id}",
                        suggestion="Verify the message ID or search for messages: gmailarchiver search",
                        exit_code=1,
                    )

        # Show success
        if output:
            out.success(f"Message extracted to {output}")
            out.show_report(
                "Extraction Summary",
                {
                    "Message ID": message_id,
                    "Output File": output,
                    "Size": format_bytes(len(message_bytes)),
                },
            )
        else:
            # Message already written to stdout, just show summary in JSON mode
            if json_output:
                out.info(f"Extracted {len(message_bytes)} bytes")

        out.end_operation(success=True)

    except ExtractorError as e:
        out.error(f"Extraction failed: {e}", exit_code=1)
    except Exception as e:
        out.error(f"Unexpected error: {e}", exit_code=1)


@app.command(name="import")
def import_cmd(
    archive_pattern: str = typer.Argument(..., help="Mbox file path or glob pattern"),
    account_id: str = typer.Option("default", help="Account identifier"),
    skip_duplicates: bool = typer.Option(True, help="Skip duplicate messages"),
    auto_verify: bool = typer.Option(False, "--auto-verify", help="Run verification after import"),
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
        $ gmailarchiver import archive_*.mbox.gz --auto-verify
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
                    file_path, account_id=account_id, skip_duplicates=skip_duplicates
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

        output.suggest_next_steps(
            [
                "Check database integrity: gmailarchiver verify-integrity",
                "Review error messages above for details",
            ]
        )

    if total_imported > 0:
        output.suggest_next_steps(
            [
                "Search imported messages: gmailarchiver search <query>",
                "Verify database: gmailarchiver verify-integrity",
            ]
        )

    # Auto-verify if requested
    if auto_verify and total_failed == 0:
        from gmailarchiver.db_manager import DBManager

        output.info("\nRunning verification...")
        try:
            db = DBManager(str(db_path), validate_schema=False)
            issues = db.verify_database_integrity()
            db.close()

            if not issues:
                output.success("Verification complete - no issues found")
            else:
                output.warning(f"Verification found {len(issues)} issue(s):")
                for issue in issues[:5]:  # Show first 5 issues
                    output.info(f"  • {issue}")
                if len(issues) > 5:
                    output.info(f"  ... and {len(issues) - 5} more issues")

                output.suggest_next_steps(
                    [
                        "Fix issues automatically: gmailarchiver check --auto-repair",
                        "View all issues: gmailarchiver verify-integrity --verbose",
                    ]
                )
        except Exception as e:
            output.warning(f"Verification failed: {e}")

    output.end_operation(success=total_failed == 0)


@app.command()
def consolidate(
    archives: list[str] = typer.Argument(..., help="Archive files or glob patterns"),
    output_file: str = typer.Option(..., "-o", "--output", help="Output archive file"),
    sort: bool = typer.Option(True, help="Sort messages chronologically"),
    dedupe: bool = typer.Option(True, help="Remove duplicate messages"),
    dedupe_strategy: str = typer.Option("newest", help="Dedup strategy: newest/largest/first"),
    compress: str | None = typer.Option(None, help="Compression: gzip/lzma/zstd"),
    auto_verify: bool = typer.Option(
        False, "--auto-verify", help="Run verification after consolidation"
    ),
    remove_sources: bool = typer.Option(
        False, "--remove-sources", help="Remove source files after successful consolidation"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompts"
    ),
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
        $ gmailarchiver consolidate archive_*.mbox -o merged.mbox --auto-verify
        $ gmailarchiver consolidate "archives/*.mbox" --no-sort --no-dedupe -o unsorted.mbox
        $ gmailarchiver consolidate archive*.mbox -o merged.mbox.zst --dedupe-strategy newest
        $ gmailarchiver consolidate archive*.mbox -o merged.mbox --json
        $ gmailarchiver consolidate archive*.mbox -o merged.mbox --remove-sources --yes
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
    valid_strategies = ["newest", "largest", "first"]
    if dedupe_strategy not in valid_strategies:
        output.error(
            f"Invalid dedupe strategy: {dedupe_strategy}",
            suggestion=f"Valid strategies: {', '.join(valid_strategies)}",
            exit_code=1,
        )

    # 3. Auto-detect compression from output extension
    if compress is None:
        output_path = Path(output_file)
        if output_path.suffix == ".gz":
            compress = "gzip"
        elif output_path.suffix == ".xz":
            compress = "lzma"
        elif output_path.suffix == ".zst":
            compress = "zstd"

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
                compress=compress,
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

        output.suggest_next_steps(
            [
                "Verify consolidated archive: gmailarchiver validate " + result.output_file,
                "Search messages: gmailarchiver search <query>",
            ]
        )

        # Auto-verify if requested
        if auto_verify:
            output.info("\nRunning verification...")
            try:
                validator = ArchiveValidator(result.output_file, state_db)

                with output.progress_context("Running consistency checks", total=5) as progress:
                    task = progress.add_task("Consistency checks", total=5) if progress else None
                    report = validator.verify_consistency()
                    if progress and task:
                        progress.update(task, completed=5)

                # Build verification report data
                verify_report_data = {
                    "Schema Version": report.schema_version,
                    "Orphaned Records": report.orphaned_records,
                    "Missing Records": report.missing_records,
                    "Duplicate Gmail IDs": report.duplicate_gmail_ids,
                }

                if report.schema_version == "1.1":
                    verify_report_data["Duplicate RFC Message-IDs"] = (
                        report.duplicate_rfc_message_ids
                    )
                    verify_report_data["FTS Synchronized"] = "Yes" if report.fts_synced else "No"

                output.show_report("Verification Results", verify_report_data)

                # Show errors if any
                if report.errors:
                    output.warning(f"Found {len(report.errors)} issue(s):")
                    for error in report.errors[:5]:
                        output.info(f"  • {error}")
                    if len(report.errors) > 5:
                        output.info(f"  ... and {len(report.errors) - 5} more issues")

                # Overall status
                if report.passed:
                    output.success("Verification complete - all consistency checks passed")
                else:
                    output.suggest_next_steps(
                        [
                            "Fix issues automatically: gmailarchiver check --auto-repair",
                            "View all issues: gmailarchiver verify-integrity --verbose",
                        ]
                    )
            except Exception as e:
                output.warning(f"Verification failed: {e}")

        # 8. Remove source files if requested
        if remove_sources:
            try:
                # Validate output before removing sources
                output.info("\nValidating consolidated archive before cleanup...")
                validator = ArchiveValidator(result.output_file, state_db)

                # Basic validation check
                if not validator.validate_all():
                    output.error(
                        "Output validation failed - source files NOT removed",
                        suggestion="Fix validation issues before using --remove-sources",
                        exit_code=1,
                    )

                # Determine which files to remove (exclude output file)
                output_path_resolved = Path(output_file).resolve()
                files_to_remove = []
                total_size = 0

                for source_file in all_files:
                    source_path = Path(source_file).resolve()
                    # Never remove the output file
                    if source_path != output_path_resolved:
                        if source_path.exists():
                            total_size += source_path.stat().st_size
                            files_to_remove.append(source_path)

                if not files_to_remove:
                    output.info("No source files to remove (output file is the only file)")
                else:
                    # Determine if we should proceed with removal
                    # Auto-confirm if --yes or --json is provided
                    should_remove = yes or json_output

                    if not should_remove:
                        # Show confirmation prompt
                        output.info(f"\nThe following {len(files_to_remove)} source file(s) will be removed:")
                        for file_path in files_to_remove:
                            output.info(f"  • {file_path}")
                        output.info(f"\nTotal space to be freed: {format_bytes(total_size)}")

                        should_remove = typer.confirm("\nRemove source files?")
                        if not should_remove:
                            output.info("Source file removal cancelled - files kept")

                    if should_remove:
                        # Proceed with removal
                        removed_count = 0
                        freed_space = 0
                        failed_removals = []

                        for file_path in files_to_remove:
                            try:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                removed_count += 1
                                freed_space += file_size
                            except FileNotFoundError:
                                # File already deleted - that's OK
                                pass
                            except PermissionError as e:
                                failed_removals.append(f"{file_path}: {e}")
                            except Exception as e:
                                failed_removals.append(f"{file_path}: {e}")

                        # Report results
                        if removed_count > 0:
                            output.success(
                                f"Removed {removed_count} source file(s) - "
                                f"Space freed: {format_bytes(freed_space)}"
                            )

                            # Add cleanup data to JSON events for scripting
                            if json_output:
                                output._json_events.append({
                                    "event": "cleanup",
                                    "removed_files": removed_count,
                                    "space_freed_bytes": freed_space,
                                    "failed_removals": len(failed_removals),
                                })

                        if failed_removals:
                            output.warning(f"Failed to remove {len(failed_removals)} file(s):")
                            for failure in failed_removals[:3]:
                                output.info(f"  • {failure}")
                            if len(failed_removals) > 3:
                                output.info(f"  ... and {len(failed_removals) - 3} more")

            except Exception as e:
                output.warning(f"Source file cleanup failed: {e}")
                output.info("Consolidation succeeded but source files were NOT removed")

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
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Show verbose output"),
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
        output.suggest_next_steps(
            [
                "Fix issues: gmailarchiver repair --no-dry-run",
                "Review issues in detail: gmailarchiver verify-integrity --verbose",
            ]
        )

        output.end_operation(success=False)
        raise typer.Exit(1)

    except FileNotFoundError as e:
        output.error(f"File not found: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Integrity check failed: {e}", exit_code=1)


@app.command()
def repair(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Show what would be fixed without making changes (default: True)",
    ),
    backfill: bool = typer.Option(
        False, "--backfill", help="Fix invalid offsets by scanning mbox files"
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
                        repairs["invalid_offsets_fixed"] = backfilled
                        migrator._close()
                    else:
                        repairs["invalid_offsets_would_fix"] = len(invalid_msgs)
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
    output: "OutputManager", repairs: dict[str, int], dry_run: bool
) -> None:
    """Display repair results using OutputManager."""
    # Build report data
    report_data = {}

    # Add FTS repairs
    if "orphaned_fts_removed" in repairs and repairs["orphaned_fts_removed"] > 0:
        action = "Removed" if not dry_run else "Would remove"
        report_data[f"{action} orphaned FTS records"] = repairs["orphaned_fts_removed"]

    if "missing_fts_added" in repairs and repairs["missing_fts_added"] > 0:
        action = "Added" if not dry_run else "Would add"
        report_data[f"{action} missing FTS records"] = repairs["missing_fts_added"]

    # Add offset backfill repairs
    if "invalid_offsets_fixed" in repairs and repairs["invalid_offsets_fixed"] > 0:
        report_data["Backfilled invalid offsets"] = repairs["invalid_offsets_fixed"]

    if "invalid_offsets_would_fix" in repairs and repairs["invalid_offsets_would_fix"] > 0:
        report_data["Would backfill invalid offsets"] = repairs["invalid_offsets_would_fix"]

    # Summary message
    total_repairs = sum(repairs.values())

    title = "Repair Results" if not dry_run else "Repair Preview (Dry Run)"
    report_data["Total"] = total_repairs

    output.show_report(title, report_data)

    if total_repairs == 0:
        output.success("No repairs needed - database is clean")
    elif dry_run:
        output.warning(f"Would perform {total_repairs} repair(s)")
        output.suggest_next_steps(
            [
                "Apply repairs: gmailarchiver repair --no-dry-run",
            ]
        )
    else:
        output.success(f"Successfully performed {total_repairs} repair(s)")


@app.command()
def check(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    auto_repair: bool = typer.Option(
        False, "--auto-repair", help="Automatically repair issues found"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed check results"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Run all health checks in one command.

    Performs comprehensive database health checks:
    - Database integrity (orphaned/missing FTS records, invalid offsets, duplicates)
    - Database consistency (database ↔ mbox sync)
    - Offset accuracy (v1.1 schema only)
    - FTS synchronization

    With --auto-repair, automatically fixes issues and re-checks.

    Examples:
        $ gmailarchiver check
        $ gmailarchiver check --auto-repair
        $ gmailarchiver check --verbose
        $ gmailarchiver check --json
    """
    from gmailarchiver.db_manager import DBManager
    from gmailarchiver.migration import MigrationManager
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("check", "Running all health checks")

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database, or specify path with --state-db",
            exit_code=1,
        )

    # Detect schema version
    manager = MigrationManager(db_path)
    schema_version = manager.detect_schema_version()
    manager._close()

    if schema_version == "none":
        output.error(
            "Database is empty or invalid",
            suggestion="Create a new database with 'gmailarchiver archive' or 'gmailarchiver import'",
            exit_code=1,
        )

    # Initialize results dictionary
    check_results: dict[str, Any] = {
        "database_integrity": {"passed": False, "issues": []},
        "database_consistency": {"passed": False, "checked": False, "report": None},
        "offset_accuracy": {"passed": False, "checked": False, "result": None},
        "fts_synchronization": {"passed": False, "issues": []},
    }

    # ==================== CHECK 1: Database Integrity ====================
    output.info("1. Checking database integrity...")
    try:
        db = DBManager(str(db_path), validate_schema=False)
        issues = db.verify_database_integrity()
        db.close()

        if not issues:
            check_results["database_integrity"]["passed"] = True
            if verbose:
                output.success("  ✓ Database integrity: OK")
        else:
            check_results["database_integrity"]["issues"] = issues
            if verbose:
                output.warning(f"  ✗ Database integrity: {len(issues)} issue(s)")
                for issue in issues[:5]:  # Show first 5 in verbose
                    output.info(f"    • {issue}")
    except Exception as e:
        check_results["database_integrity"]["issues"] = [str(e)]
        if verbose:
            output.warning(f"  ✗ Database integrity check failed: {e}")

    # ==================== CHECK 2: FTS Synchronization ====================
    # FTS sync is part of database integrity check above
    # Extract FTS-specific issues from the integrity issues
    fts_issues = [
        issue
        for issue in check_results["database_integrity"]["issues"]
        if "FTS" in issue or "fts" in issue.lower()
    ]
    if not fts_issues:
        check_results["fts_synchronization"]["passed"] = True
        if verbose:
            output.success("  ✓ FTS synchronization: OK")
    else:
        check_results["fts_synchronization"]["issues"] = fts_issues
        if verbose:
            output.warning(f"  ✗ FTS synchronization: {len(fts_issues)} issue(s)")

    # ==================== CHECK 3: Database Consistency ====================
    # Only run if there are mbox files referenced in database
    output.info("2. Checking database consistency...")
    try:
        db = DBManager(str(db_path), validate_schema=False)
        cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
        has_archives = cursor.fetchone() is not None
        db.close()

        if has_archives:
            # Get first archive file for consistency check
            db = DBManager(str(db_path), validate_schema=False)
            cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
            archive_file = cursor.fetchone()[0]
            db.close()

            # Check if archive file exists
            if Path(archive_file).exists():
                validator = ArchiveValidator(archive_file, state_db)
                report = validator.verify_consistency()
                check_results["database_consistency"]["checked"] = True
                check_results["database_consistency"]["report"] = report
                check_results["database_consistency"]["passed"] = report.passed

                if verbose:
                    if report.passed:
                        output.success("  ✓ Database consistency: OK")
                    else:
                        output.warning(f"  ✗ Database consistency: {len(report.errors)} issue(s)")
            else:
                # Archive file doesn't exist, skip consistency check
                if verbose:
                    output.info("  ⊘ Database consistency: Skipped (archive file not found)")
                check_results["database_consistency"]["checked"] = False
                check_results["database_consistency"]["passed"] = True  # Don't fail if file missing
        else:
            # No archive files in database, skip check
            if verbose:
                output.info("  ⊘ Database consistency: Skipped (no archives in database)")
            check_results["database_consistency"]["checked"] = False
            check_results["database_consistency"]["passed"] = True  # Don't fail if no archives

    except Exception as e:
        check_results["database_consistency"]["issues"] = [str(e)]
        if verbose:
            output.warning(f"  ✗ Database consistency check failed: {e}")

    # ==================== CHECK 4: Offset Accuracy ====================
    # Only for v1.1 databases
    output.info("3. Checking offset accuracy...")
    if schema_version == "1.1":
        try:
            # Get first archive file for offset verification
            db = DBManager(str(db_path), validate_schema=False)
            cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
            row = cursor.fetchone()
            db.close()

            if row and Path(row[0]).exists():
                archive_file = row[0]
                validator = ArchiveValidator(archive_file, state_db)
                result = validator.verify_offsets()

                check_results["offset_accuracy"]["checked"] = True
                check_results["offset_accuracy"]["result"] = result

                if result.accuracy_percentage == 100.0:
                    check_results["offset_accuracy"]["passed"] = True
                    if verbose:
                        output.success(
                            f"  ✓ Offset accuracy: 100% ({result.total_checked:,} checked)"
                        )
                else:
                    check_results["offset_accuracy"]["passed"] = False
                    if verbose:
                        output.warning(
                            f"  ✗ Offset accuracy: {result.accuracy_percentage:.1f}% "
                            f"({result.successful_reads:,}/{result.total_checked:,})"
                        )
            else:
                # No archive files or file doesn't exist
                if verbose:
                    output.info("  ⊘ Offset accuracy: Skipped (no accessible archives)")
                check_results["offset_accuracy"]["checked"] = False
                check_results["offset_accuracy"]["passed"] = True  # Don't fail if no files

        except Exception as e:
            check_results["offset_accuracy"]["issues"] = [str(e)]
            if verbose:
                output.warning(f"  ✗ Offset accuracy check failed: {e}")
    else:
        # v1.0 schema doesn't have offsets
        if verbose:
            output.info("  ⊘ Offset accuracy: Skipped (v1.0 schema)")
        check_results["offset_accuracy"]["checked"] = False
        check_results["offset_accuracy"]["passed"] = True  # Don't fail for v1.0

    # ==================== SUMMARY ====================
    output.info("")  # Blank line

    # Determine overall status
    all_passed = (
        check_results["database_integrity"]["passed"]
        and check_results["database_consistency"]["passed"]
        and check_results["offset_accuracy"]["passed"]
        and check_results["fts_synchronization"]["passed"]
    )

    # Build summary report
    report_data: dict[str, str] = {}

    # Database integrity
    if check_results["database_integrity"]["passed"]:
        report_data["Database integrity"] = "✓ OK"
    else:
        issue_count = len(check_results["database_integrity"]["issues"])
        report_data["Database integrity"] = f"✗ {issue_count} issue(s)"

    # Database consistency
    if not check_results["database_consistency"]["checked"]:
        report_data["Database consistency"] = "⊘ Skipped"
    elif check_results["database_consistency"]["passed"]:
        report_data["Database consistency"] = "✓ OK"
    else:
        consistency_report = check_results["database_consistency"]["report"]
        issue_count = len(consistency_report.errors) if consistency_report else 0
        report_data["Database consistency"] = f"✗ {issue_count} issue(s)"

    # Offset accuracy
    if not check_results["offset_accuracy"]["checked"]:
        report_data["Offset accuracy"] = "⊘ Skipped"
    elif check_results["offset_accuracy"]["passed"]:
        result = check_results["offset_accuracy"]["result"]
        if result:
            report_data["Offset accuracy"] = f"✓ 100% ({result.total_checked:,} checked)"
        else:
            report_data["Offset accuracy"] = "✓ OK"
    else:
        result = check_results["offset_accuracy"]["result"]
        if result:
            report_data["Offset accuracy"] = (
                f"✗ {result.accuracy_percentage:.1f}% "
                f"({result.successful_reads:,}/{result.total_checked:,})"
            )
        else:
            report_data["Offset accuracy"] = "✗ Failed"

    # FTS synchronization
    if check_results["fts_synchronization"]["passed"]:
        report_data["FTS synchronization"] = "✓ OK"
    else:
        fts_issue_count = len(check_results["fts_synchronization"]["issues"])
        report_data["FTS synchronization"] = f"✗ {fts_issue_count} issue(s)"

    # Overall status
    report_data["Overall"] = "✓ HEALTHY" if all_passed else "✗ ISSUES FOUND"

    output.show_report("Health Check Summary", report_data)

    # ==================== AUTO-REPAIR ====================
    if not all_passed and auto_repair:
        output.warning("\n⚠ Auto-repair enabled - attempting to fix issues...")

        try:
            db = DBManager(str(db_path), validate_schema=False)
            repairs = db.repair_database(dry_run=False)
            db.close()

            # Show repair results
            total_repairs = sum(repairs.values())
            if total_repairs > 0:
                output.success(f"Performed {total_repairs} repair(s)")

                # Re-run checks to verify repairs
                output.info("\nRe-checking after repairs...")

                db = DBManager(str(db_path), validate_schema=False)
                post_repair_issues = db.verify_database_integrity()
                db.close()

                if not post_repair_issues:
                    output.success("All issues resolved!")
                    output.end_operation(success=True)
                    raise typer.Exit(0)
                else:
                    output.warning(f"{len(post_repair_issues)} issue(s) remain after repair")
                    output.suggest_next_steps(
                        [
                            "Some issues may require manual intervention",
                            "Check remaining issues: gmailarchiver verify-integrity --verbose",
                        ]
                    )
                    output.end_operation(success=False, summary="Repair incomplete")
                    raise typer.Exit(2)  # Exit code 2 = repair failed
            else:
                output.warning("No automatic repairs available for these issues")
                output.suggest_next_steps(
                    [
                        "Manual intervention may be required",
                        "Check details: gmailarchiver verify-integrity --verbose",
                    ]
                )
                output.end_operation(success=False)
                raise typer.Exit(2)

        except Exception as e:
            output.error(f"Auto-repair failed: {e}", exit_code=2)

    # ==================== EXIT ====================
    if all_passed:
        output.success("All checks passed - database is healthy!")
        output.end_operation(success=True)
        raise typer.Exit(0)
    else:
        # Show suggestions for failed checks
        suggestions = []

        if not check_results["database_integrity"]["passed"]:
            suggestions.append("Fix database issues: gmailarchiver repair --no-dry-run")

        if not check_results["offset_accuracy"]["passed"]:
            suggestions.append("Repair offsets: gmailarchiver repair --backfill --no-dry-run")

        suggestions.append("View detailed issues: gmailarchiver check --verbose")

        if not auto_repair:
            suggestions.append("Auto-fix issues: gmailarchiver check --auto-repair")

        output.suggest_next_steps(suggestions)
        output.end_operation(success=False)
        raise typer.Exit(1)


# ==================== SCHEDULE COMMAND ====================

schedule_app = typer.Typer(help="Manage automated maintenance schedules", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("list")
def schedule_list(
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    enabled_only: bool = typer.Option(False, "--enabled-only", help="Show only enabled schedules"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    List all scheduled tasks.

    Shows all configured maintenance schedules with their frequency, time, and status.

    Examples:
        $ gmailarchiver schedule list
        $ gmailarchiver schedule list --enabled-only
        $ gmailarchiver schedule list --json
    """
    from gmailarchiver.output import OutputManager
    from gmailarchiver.scheduler import Scheduler

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-list", "Listing schedules")

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            schedules = scheduler.list_schedules(enabled_only=enabled_only)

        if not schedules:
            msg = "No enabled schedules found" if enabled_only else "No schedules configured"
            output.warning(msg)
            output.suggest_next_steps(
                [
                    "Add a schedule: gmailarchiver schedule add check --daily --time 02:00",
                ]
            )
            output.end_operation(success=True)
            return

        # Build table
        table = Table(title=f"Scheduled Tasks ({len(schedules)} total)")
        table.add_column("ID", style="cyan", width=6)
        table.add_column("Command", style="green", width=25)
        table.add_column("Frequency", style="yellow", width=12)
        table.add_column("When", style="magenta", width=20)
        table.add_column("Status", style="blue", width=10)
        table.add_column("Last Run", style="dim", width=18)

        for schedule in schedules:
            # Format "When" column
            when_parts = [schedule.time]
            if schedule.frequency == "weekly" and schedule.day_of_week is not None:
                days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                when_parts.insert(0, days[schedule.day_of_week])
            elif schedule.frequency == "monthly" and schedule.day_of_month is not None:
                when_parts.insert(0, f"Day {schedule.day_of_month}")

            when_str = " ".join(when_parts)
            status = "Enabled" if schedule.enabled else "Disabled"
            last_run = schedule.last_run[:19] if schedule.last_run else "Never"

            table.add_row(
                str(schedule.id),
                schedule.command,
                schedule.frequency,
                when_str,
                status,
                last_run,
            )

        console.print()
        console.print(table)
        console.print()

        output.suggest_next_steps(
            [
                "Add schedule: gmailarchiver schedule add <command> --daily --time HH:MM",
                "Remove schedule: gmailarchiver schedule remove <id>",
            ]
        )
        output.end_operation(success=True)

    except Exception as e:
        output.error(f"Failed to list schedules: {e}", exit_code=1)


@schedule_app.command("add")
def schedule_add(
    command: str = typer.Argument(..., help="Command to run (e.g., 'check', 'archive 3y')"),
    daily: bool = typer.Option(False, "--daily", help="Run daily"),
    weekly: bool = typer.Option(False, "--weekly", help="Run weekly"),
    monthly: bool = typer.Option(False, "--monthly", help="Run monthly"),
    day: str | None = typer.Option(
        None, "--day", help="Day of week (Sun-Sat) or day of month (1-31)"
    ),
    time: str = typer.Option("02:00", "--time", help="Time to run (HH:MM)"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    install: bool = typer.Option(
        True, "--install/--no-install", help="Install on system scheduler"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Add a new scheduled task.

    Creates a new maintenance schedule and optionally installs it on the system scheduler
    (systemd on Linux, launchd on macOS, Task Scheduler on Windows).

    Examples:
        $ gmailarchiver schedule add check --daily --time 02:00
        $ gmailarchiver schedule add "archive 3y" --weekly --day Sunday --time 03:00
        $ gmailarchiver schedule add verify-integrity --monthly --day 1 --time 04:00
        $ gmailarchiver schedule add check --daily --time 02:00 --no-install
    """
    from gmailarchiver.output import OutputManager
    from gmailarchiver.platform_scheduler import get_platform_scheduler, UnsupportedPlatformError
    from gmailarchiver.scheduler import Scheduler, ScheduleValidationError

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-add", f"Adding schedule: {command}")

    # Validate frequency
    frequency_count = sum([daily, weekly, monthly])
    if frequency_count == 0:
        output.error(
            "No frequency specified",
            suggestion="Use --daily, --weekly, or --monthly",
            exit_code=1,
        )
    elif frequency_count > 1:
        output.error(
            "Multiple frequencies specified",
            suggestion="Use only one of: --daily, --weekly, --monthly",
            exit_code=1,
        )

    # Determine frequency
    if daily:
        frequency = "daily"
        day_of_week = None
        day_of_month = None
    elif weekly:
        frequency = "weekly"
        if not day:
            output.error(
                "Weekly schedules require --day",
                suggestion="Use --day with day name (e.g., Sunday, Monday, ...)",
                exit_code=1,
            )
        # Parse day name to day_of_week (0=Sunday)
        day_names = {
            "sunday": 0,
            "sun": 0,
            "monday": 1,
            "mon": 1,
            "tuesday": 2,
            "tue": 2,
            "wednesday": 3,
            "wed": 3,
            "thursday": 4,
            "thu": 4,
            "friday": 5,
            "fri": 5,
            "saturday": 6,
            "sat": 6,
        }
        day_lower = day.lower()
        if day_lower not in day_names:
            output.error(
                f"Invalid day name: {day}",
                suggestion="Use day name: Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday",
                exit_code=1,
            )
        day_of_week = day_names[day_lower]
        day_of_month = None
    else:  # monthly
        frequency = "monthly"
        if not day:
            output.error(
                "Monthly schedules require --day",
                suggestion="Use --day with day of month (1-31)",
                exit_code=1,
            )
        try:
            day_of_month = int(day)
            if not (1 <= day_of_month <= 31):
                raise ValueError("Day must be 1-31")
        except ValueError:
            output.error(
                f"Invalid day of month: {day}",
                suggestion="Use a number between 1 and 31",
                exit_code=1,
            )
        day_of_week = None

    db_path = Path(state_db)

    try:
        with Scheduler(str(db_path)) as scheduler:
            schedule_id = scheduler.add_schedule(
                command=command,
                frequency=frequency,
                time=time,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
            )

            schedule = scheduler.get_schedule(schedule_id)

        if not schedule:
            output.error("Failed to retrieve created schedule", exit_code=1)

        output.success(f"Schedule created with ID: {schedule_id}")

        # Install on system scheduler if requested
        if install:
            try:
                platform_scheduler = get_platform_scheduler()
                output.info("Installing on system scheduler...")
                platform_scheduler.install(schedule)
                output.success("Schedule installed on system scheduler")
            except UnsupportedPlatformError as e:
                output.warning(str(e))
                output.suggest_next_steps(
                    [
                        "Manually configure your system scheduler (cron, Task Scheduler, etc.)",
                        f"Run: gmailarchiver {command}",
                    ]
                )
            except Exception as e:
                output.warning(f"Failed to install on system scheduler: {e}")
                output.info("Schedule saved in database but not installed on system")

        # Show schedule details
        report_data = {
            "ID": schedule_id,
            "Command": command,
            "Frequency": frequency,
            "Time": time,
        }
        if day_of_week is not None:
            days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            report_data["Day"] = days[day_of_week]
        if day_of_month is not None:
            report_data["Day"] = str(day_of_month)

        output.show_report("Schedule Details", report_data)

        output.suggest_next_steps(
            [
                "View schedules: gmailarchiver schedule list",
                "Remove schedule: gmailarchiver schedule remove " + str(schedule_id),
            ]
        )

        output.end_operation(success=True)

    except ScheduleValidationError as e:
        output.error(f"Validation error: {e}", exit_code=1)
    except Exception as e:
        output.error(f"Failed to add schedule: {e}", exit_code=1)


@schedule_app.command("remove")
def schedule_remove(
    schedule_id: int = typer.Argument(..., help="Schedule ID to remove"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    uninstall: bool = typer.Option(
        True, "--uninstall/--no-uninstall", help="Uninstall from system scheduler"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Remove a scheduled task.

    Removes a schedule from the database and optionally uninstalls it from the system scheduler.

    Examples:
        $ gmailarchiver schedule remove 1
        $ gmailarchiver schedule remove 2 --no-uninstall
    """
    from gmailarchiver.output import OutputManager
    from gmailarchiver.platform_scheduler import get_platform_scheduler, UnsupportedPlatformError
    from gmailarchiver.scheduler import Scheduler

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-remove", f"Removing schedule ID: {schedule_id}")

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            # Get schedule before removing
            schedule = scheduler.get_schedule(schedule_id)
            if not schedule:
                output.error(
                    f"Schedule not found: ID {schedule_id}",
                    suggestion="List schedules: gmailarchiver schedule list",
                    exit_code=1,
                )

            # Uninstall from system scheduler if requested
            if uninstall:
                try:
                    platform_scheduler = get_platform_scheduler()
                    output.info("Uninstalling from system scheduler...")
                    platform_scheduler.uninstall(schedule)
                    output.success("Schedule uninstalled from system scheduler")
                except UnsupportedPlatformError as e:
                    output.warning(str(e))
                except Exception as e:
                    output.warning(f"Failed to uninstall from system scheduler: {e}")

            # Remove from database
            success = scheduler.remove_schedule(schedule_id)

        if success:
            output.success(f"Schedule {schedule_id} removed successfully")
            output.suggest_next_steps(
                [
                    "View remaining schedules: gmailarchiver schedule list",
                ]
            )
            output.end_operation(success=True)
        else:
            output.error(f"Failed to remove schedule {schedule_id}", exit_code=1)

    except Exception as e:
        output.error(f"Failed to remove schedule: {e}", exit_code=1)


@schedule_app.command("enable")
def schedule_enable(
    schedule_id: int = typer.Argument(..., help="Schedule ID to enable"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Enable a disabled schedule.

    Examples:
        $ gmailarchiver schedule enable 1
    """
    from gmailarchiver.output import OutputManager
    from gmailarchiver.scheduler import Scheduler

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-enable", f"Enabling schedule ID: {schedule_id}")

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            success = scheduler.enable_schedule(schedule_id)

        if success:
            output.success(f"Schedule {schedule_id} enabled")
            output.suggest_next_steps(
                [
                    "View schedules: gmailarchiver schedule list",
                ]
            )
            output.end_operation(success=True)
        else:
            output.error(
                f"Schedule not found: ID {schedule_id}",
                suggestion="List schedules: gmailarchiver schedule list",
                exit_code=1,
            )

    except Exception as e:
        output.error(f"Failed to enable schedule: {e}", exit_code=1)


@schedule_app.command("disable")
def schedule_disable(
    schedule_id: int = typer.Argument(..., help="Schedule ID to disable"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Disable a schedule without removing it.

    Examples:
        $ gmailarchiver schedule disable 1
    """
    from gmailarchiver.output import OutputManager
    from gmailarchiver.scheduler import Scheduler

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-disable", f"Disabling schedule ID: {schedule_id}")

    db_path = Path(state_db)
    if not db_path.exists():
        output.error(
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            success = scheduler.disable_schedule(schedule_id)

        if success:
            output.success(f"Schedule {schedule_id} disabled")
            output.suggest_next_steps(
                [
                    "View schedules: gmailarchiver schedule list",
                    "Re-enable: gmailarchiver schedule enable " + str(schedule_id),
                ]
            )
            output.end_operation(success=True)
        else:
            output.error(
                f"Schedule not found: ID {schedule_id}",
                suggestion="List schedules: gmailarchiver schedule list",
                exit_code=1,
            )

    except Exception as e:
        output.error(f"Failed to disable schedule: {e}", exit_code=1)


@app.command()
def compress(
    files: list[str] = typer.Argument(..., help="Mbox file paths or glob patterns to compress"),
    format: str = typer.Option(
        "zstd", "--format", "-f", help="Compression format: gzip, lzma, or zstd"
    ),
    in_place: bool = typer.Option(
        False, "--in-place", help="Replace original files with compressed versions"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview compression without actually compressing"
    ),
    state_db: str = typer.Option("archive_state.db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Compress mbox archive files to save disk space.

    Supports three compression formats:
    - gzip (.mbox.gz): Good compression, widely compatible
    - lzma (.mbox.xz): Best compression ratio
    - zstd (.mbox.zst): Fastest, good compression (default, Python 3.14 native)

    When using --in-place, the original file is replaced with the compressed
    version, and the database is updated to point to the new file.

    Examples:
        $ gmailarchiver compress archive.mbox
        $ gmailarchiver compress archive.mbox --format gzip
        $ gmailarchiver compress archive_*.mbox --in-place
        $ gmailarchiver compress archive.mbox --dry-run
        $ gmailarchiver compress archive.mbox --json
    """
    import glob

    from gmailarchiver.compressor import ArchiveCompressor
    from gmailarchiver.output import OutputManager
    from gmailarchiver.utils import format_bytes

    output = OutputManager(json_mode=json_output)
    output.start_operation("compress", f"Compressing archives with {format} compression")

    # Expand glob patterns
    expanded_files = []
    for pattern in files:
        matches = glob.glob(pattern)
        if matches:
            expanded_files.extend(matches)
        else:
            # If no matches, treat as literal filename (will fail later if doesn't exist)
            expanded_files.append(pattern)

    if not expanded_files:
        output.error(
            "No files specified",
            suggestion="Provide mbox file paths or glob patterns",
            exit_code=1,
        )

    output.info(f"Found {len(expanded_files)} file(s) to compress")

    if dry_run:
        output.info("[bold yellow]DRY RUN MODE - No actual compression will occur[/bold yellow]")

    try:
        compressor = ArchiveCompressor(state_db)

        # Compress files with progress tracking
        with output.progress_context(
            f"Compressing {len(expanded_files)} file(s)", total=len(expanded_files)
        ) as progress:
            task = progress.add_task("Compress", total=len(expanded_files)) if progress else None

            result = compressor.compress(
                files=expanded_files, format=format, in_place=in_place, dry_run=dry_run
            )

            if progress and task:
                progress.update(task, completed=len(expanded_files))

        # Build report data
        if dry_run:
            report_data = {
                "Total Files": result.total_files,
                "Files to Compress": result.total_files - result.files_skipped,
                "Files to Skip": result.files_skipped,
                "Original Size": format_bytes(result.original_size),
                "Estimated Compressed Size": format_bytes(result.estimated_compressed_size),
                "Estimated Space Saved": format_bytes(result.estimated_space_saved),
                "Estimated Compression Ratio": f"{result.estimated_compression_ratio:.2f}x",
                "Execution Time": f"{result.execution_time_ms:.1f} ms",
            }
            output.show_report("Compression Preview (Dry Run)", report_data)

            if result.files_skipped > 0:
                output.info("\nSkipped files (already compressed):")
                for file_result in result.file_results:
                    if file_result.skipped:
                        file_name = Path(file_result.source_file).name
                        output.info(f"  • {file_name}: {file_result.skip_reason}")

            files_str = " ".join(files)
            output.suggest_next_steps(
                [
                    f"Run without --dry-run to compress: "
                    f"gmailarchiver compress {files_str} --format {format}",
                    f"Use --in-place to replace originals: "
                    f"gmailarchiver compress {files_str} --in-place",
                ]
            )
        else:
            report_data = {
                "Files Compressed": result.files_compressed,
                "Files Skipped": result.files_skipped,
                "Total Files": result.total_files,
                "Original Size": format_bytes(result.original_size),
                "Compressed Size": format_bytes(result.compressed_size),
                "Space Saved": format_bytes(result.space_saved),
                "Compression Ratio": f"{result.compression_ratio:.2f}x",
                "Execution Time": f"{result.execution_time_ms:.1f} ms",
            }
            output.show_report("Compression Summary", report_data)

            if result.files_skipped > 0:
                output.info("\nSkipped files (already compressed):")
                for file_result in result.file_results:
                    if file_result.skipped:
                        file_name = Path(file_result.source_file).name
                        output.info(f"  • {file_name}: {file_result.skip_reason}")

            if result.files_compressed > 0:
                output.success(
                    f"Successfully compressed {result.files_compressed} file(s), "
                    f"saved {format_bytes(result.space_saved)}"
                )

                output.suggest_next_steps(
                    [
                        "Verify integrity: gmailarchiver verify-integrity",
                        "Search archived messages: gmailarchiver search <query>",
                    ]
                )

        output.end_operation(success=True)

    except ValueError as e:
        output.error(f"Compression failed: {e}", exit_code=1)
    except FileNotFoundError as e:
        output.error(
            f"File not found: {e}",
            suggestion="Check the file path or glob pattern",
            exit_code=1,
        )
    except Exception as e:
        output.error(f"Unexpected error: {e}", exit_code=1)


@app.command()
def doctor(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    fix: bool = typer.Option(False, "--fix", help="Automatically fix issues where possible"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Run system diagnostics and health checks.

    Performs comprehensive checks:
    - Database schema and integrity
    - Python version and dependencies
    - OAuth token validity
    - Disk space and permissions
    - Stale lock files

    Use --fix to automatically repair fixable issues.

    Examples:
        $ gmailarchiver doctor
        $ gmailarchiver doctor --fix
        $ gmailarchiver doctor --json
    """
    from gmailarchiver.doctor import CheckSeverity, Doctor
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("doctor", "Running system diagnostics")

    # Initialize doctor
    doctor = Doctor(state_db, validate_schema=False, auto_create=False)

    # Run diagnostics
    with output.progress_context("Running diagnostic checks", total=12) as progress:
        task = progress.add_task("Checking...", total=12) if progress else None

        report = doctor.run_diagnostics()

        if progress and task:
            progress.update(task, completed=12)

    # Show results in Rich format
    if not json_output:
        from rich.table import Table

        # Create results table
        table = Table(title="Diagnostic Results", show_header=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Message")

        for check in report.checks:
            # Color-code status
            if check.severity == CheckSeverity.OK:
                status = "[green]✓ OK[/green]"
            elif check.severity == CheckSeverity.WARNING:
                status = "[yellow]⚠ WARNING[/yellow]"
            else:  # ERROR
                status = "[red]✗ ERROR[/red]"

            # Add fixable indicator
            message = check.message
            if check.fixable and check.severity != CheckSeverity.OK:
                message += " [dim](fixable)[/dim]"

            table.add_row(check.name, status, message)

        console.print()
        console.print(table)
        console.print()

        # Show summary
        if report.overall_status == CheckSeverity.OK:
            output.success(
                f"All checks passed! ({report.checks_passed}/{len(report.checks)} OK)"
            )
        elif report.overall_status == CheckSeverity.WARNING:
            output.warning(
                f"Found {report.warnings} warning(s), {report.errors} error(s), "
                f"{report.checks_passed} passed"
            )
        else:  # ERROR
            output.error(
                f"Found {report.errors} error(s), {report.warnings} warning(s), "
                f"{report.checks_passed} passed",
                exit_code=0,  # Don't exit, continue to show suggestions
            )

        # Show fixable issues
        if report.fixable_issues:
            output.info(
                f"\n{len(report.fixable_issues)} issue(s) can be automatically fixed:"
            )
            for issue in report.fixable_issues:
                output.info(f"  • {issue}")

            if not fix:
                output.suggest_next_steps(["Run with --fix to auto-repair: gmailarchiver doctor --fix"])

    # Run auto-fix if requested
    if fix and report.fixable_issues:
        output.info("\nRunning auto-fix...")

        with output.progress_context("Fixing issues", total=len(report.fixable_issues)) as progress:
            task = progress.add_task("Fixing...", total=len(report.fixable_issues)) if progress else None

            fix_results = doctor.run_auto_fix()

            if progress and task:
                progress.update(task, completed=len(report.fixable_issues))

        # Show fix results
        if not json_output:
            fix_table = Table(title="Auto-Fix Results", show_header=True)
            fix_table.add_column("Check", style="cyan")
            fix_table.add_column("Status", no_wrap=True)
            fix_table.add_column("Message")

            for fix_result in fix_results:
                status = "[green]✓ FIXED[/green]" if fix_result.success else "[red]✗ FAILED[/red]"
                fix_table.add_row(fix_result.check_name, status, fix_result.message)

            console.print()
            console.print(fix_table)
            console.print()

        # Show success/failure summary
        fixed_count = sum(1 for r in fix_results if r.success)
        failed_count = len(fix_results) - fixed_count

        if fixed_count > 0 and failed_count == 0:
            output.success(f"Successfully fixed {fixed_count} issue(s)")
            output.suggest_next_steps(
                [
                    "Verify fixes: gmailarchiver doctor",
                    "Check database: gmailarchiver verify-integrity",
                ]
            )
        elif fixed_count > 0:
            output.warning(f"Fixed {fixed_count} issue(s), {failed_count} failed")
        else:
            output.error(f"Failed to fix {failed_count} issue(s)", exit_code=0)

    # JSON output mode
    if json_output:
        report_dict = report.to_dict()
        output.show_report("Doctor Report", report_dict)

        if fix and report.fixable_issues:
            fix_dict = {
                "fixed": sum(1 for r in fix_results if r.success),
                "failed": sum(1 for r in fix_results if not r.success),
                "results": [
                    {
                        "check": r.check_name,
                        "success": r.success,
                        "message": r.message,
                    }
                    for r in fix_results
                ],
            }
            output.show_report("Fix Results", fix_dict)

    output.end_operation(success=True)


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
