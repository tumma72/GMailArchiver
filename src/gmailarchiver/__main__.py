"""Gmail Archiver CLI application."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from ._version import __version__
from .archiver import GmailArchiver
from .auth import GmailAuthenticator
from .deduplicator import MessageDeduplicator
from .gmail_client import GmailClient
from .migration import MigrationManager
from .output import OutputManager
from .state import ArchiveState
from .utils import format_bytes
from .validator import ArchiveValidator


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"Gmail Archiver version {__version__}")
        raise typer.Exit()


app = typer.Typer(help="Archive old Gmail messages to local mbox files", no_args_is_help=True)

# Sub-application for advanced/low-level utilities. This allows us to keep the
# top-level `gmailarchiver --help` focused on high-level workflows, while still
# exposing maintenance commands for power users via:
#   gmailarchiver utilities --help
utilities_app = typer.Typer(help="Advanced utility and maintenance commands")
app.add_typer(
    utilities_app,
    name="utilities",
    help="Low-level utilities (verification, DB maintenance, migration, cleanup)",
)


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
        ...,
        help="Age threshold or exact date. "
        "Relative: '3y' (3 years), '6m' (6 months), '2w' (2 weeks), '30d' (30 days). "
        "Exact: '2024-01-01' (ISO format YYYY-MM-DD)",
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

    \b
    $ gmailarchiver archive 3y
    $ gmailarchiver archive 6m --dry-run
    $ gmailarchiver archive 2024-01-01
    $ gmailarchiver archive 2023-06-15 --compress zstd
    $ gmailarchiver archive 3y --trash
    $ gmailarchiver archive 3y --json
    """
    import sys

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

    # Detect TTY for auto-enabling live mode
    use_live_mode = not json_output and sys.stdout.isatty()

    out = OutputManager(json_mode=json_output, live_mode=use_live_mode)
    operation_mode = "archive (dry-run)" if dry_run else "archive"
    out.start_operation(operation_mode, f"Archiving messages older than {age_threshold}")

    # Phase 1: Authentication (outside live context for cleaner output)
    try:
        out.info("Authenticating with Gmail...")
        authenticator = GmailAuthenticator(credentials_file=credentials)
        creds = authenticator.authenticate()
        out.success("Authentication successful")
    except FileNotFoundError as e:
        out.show_error_panel(
            title="Authentication Failed",
            message=str(e),
            suggestion="Check credentials file path or use bundled credentials",
            exit_code=1,
        )

    # Initialize clients
    gmail_client = GmailClient(creds)
    archiver = GmailArchiver(gmail_client, output=out)

    # Phase 2: Archiving (inside live context for progress tracking)
    result: dict[str, Any] | None = None
    archive_error: Exception | None = None

    with out._handler:
        # Start operation and get handle for live progress
        operation = out._handler.start_operation(
            f"Archiving messages older than {age_threshold}", total=None
        )

        try:
            result = archiver.archive(
                age_threshold=age_threshold,
                output_file=output,
                compress=compress,
                incremental=incremental,
                dry_run=dry_run,
                operation=operation,
            )

            # Handle results based on mode
            if dry_run:
                operation.succeed(f"Would archive {result['messages_to_archive']} messages")
            elif result["messages_archived"] > 0:
                operation.succeed(f"Archived {result['messages_archived']} messages")
            else:
                operation.log("No messages to archive", "WARNING")

        except KeyboardInterrupt:
            # Ctrl+C - the archiver should have handled saving progress
            operation.log("Archive interrupted by user", "WARNING")
            # Result should already be set by archiver with interrupted=True
            # If not, we'll handle it below

        except Exception as e:
            operation.fail(f"Archive operation failed: {e}")
            archive_error = e

    # Phase 3: Handle archive errors (outside live context)
    if archive_error:
        out.show_error_panel(
            title="Archive Failed",
            message=str(archive_error),
            suggestion="Check your network connection and Gmail API access",
            exit_code=1,
        )
        return  # exit_code=1 should exit, but return for type safety

    # Phase 4: Handle results (outside live context)
    if result is None:
        out.show_error_panel(
            title="Archive Failed",
            message="No result returned from archive operation",
            exit_code=1,
        )
        return  # exit_code=1 should exit, but return for type safety

    # Handle dry run result
    if dry_run:
        out.warning("DRY RUN completed - no changes made")
        report_data = {
            "Messages Found": result.get("messages_to_archive", 0),
            "Output File": output,
            "Mode": "Dry Run (no changes made)",
        }
        out.show_report("Archive Preview", report_data)
        out.end_operation(success=True)
        return

    # Handle zero messages case
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

    # Handle interrupted archive (Ctrl+C)
    if result.get("interrupted", False):
        actual_file = result.get("actual_file", output)
        out.warning("Archive was interrupted (Ctrl+C)")
        out.info(f"Partial archive saved: {actual_file}")
        out.info(f"Progress: {result['messages_archived']} messages archived")
        out.suggest_next_steps(
            [
                f"Resume: gmailarchiver archive {age_threshold}",
                "Cleanup: gmailarchiver cleanup --list",
            ]
        )
        out.end_operation(success=True)
        return

    # Phase 5: Validation (outside live context for clean output)
    out.info("Validating archive...")

    # Get the actual file that was written (may differ from output if interrupted)
    actual_file = result.get("actual_file", output)

    # Get the actual message IDs that were archived
    with ArchiveState() as state:
        archived_ids = state.get_archived_message_ids_for_file(actual_file)

    validation_results = archiver.validate_archive(actual_file, archived_ids)

    # Show validation report using new panel method
    out.show_validation_report(validation_results, title="Archive Validation")

    if not validation_results["passed"]:
        out.show_error_panel(
            title="Validation Failed",
            message="Archive validation did not pass all checks",
            details=validation_results.get("errors", []),
            suggestion="Check disk space and file permissions. DO NOT delete Gmail messages yet.",
            exit_code=1,
        )

    out.success("Archive validation passed")

    # Phase 6: Deletion (if requested)
    if trash or delete:
        if delete:
            # Permanent deletion requires explicit confirmation
            out.warning("WARNING: PERMANENT DELETION")
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
            with out.progress_context("Permanently deleting messages", total=None):
                archiver.delete_archived_messages(list(archived_ids), permanent=True)
            out.success("Messages permanently deleted")

        elif trash:
            # Move to trash with confirmation
            if not typer.confirm(
                f"\nMove {result['messages_archived']} messages to trash? (30-day recovery period)"
            ):
                out.info("Cancelled")
                out.end_operation(success=True)
                return

            with out.progress_context("Moving messages to trash", total=None):
                archiver.delete_archived_messages(list(archived_ids), permanent=False)
            out.success("Messages moved to trash")

    # Phase 7: Final report
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
        next_steps.append(f"Permanently delete: gmailarchiver retry-delete {output} --permanent")

    out.suggest_next_steps(next_steps)
    out.end_operation(success=True)


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
        output.show_error_panel(
            title="File Not Found",
            message=f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )
        return

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                f"Import the archive first: 'gmailarchiver import {archive_file}' "
                f"or specify database path with --state-db"
            ),
            exit_code=1,
        )
        return

    # Get expected message IDs from state database for this specific archive
    try:
        with ArchiveState(state_db) as state:
            expected_ids = state.get_archived_message_ids_for_file(archive_file)
    except Exception as e:
        output.show_error_panel(
            title="Database Error",
            message=f"Failed to read database: {e}",
            suggestion="Check database file permissions and integrity",
            exit_code=1,
        )
        return

    # Run validation with progress tracking
    validator = ArchiveValidator(archive_file, state_db, output=output)

    output.info(f"Validating {len(expected_ids):,} expected messages...")

    with output.progress_context("Running validation checks", total=4) as progress:
        task = progress.add_task("Validation", total=4) if progress else None

        # Run comprehensive validation
        results = validator.validate_comprehensive(expected_ids)

        if progress and task:
            progress.update(task, completed=4)

    # Show validation report using new panel method
    output.show_validation_report(results, title="Archive Validation")

    # Handle failure with error panel and suggestions
    if not results["passed"]:
        suggestions = []

        if not results["database_check"]:
            suggestions.append(
                f"Import archive into database: gmailarchiver import {archive_file} "
                f"--state-db {state_db}"
            )

        if not results["integrity_check"]:
            suggestions.append("Check archive file for corruption or try re-downloading")

        if not results["count_check"] or not results["spot_check"]:
            suggestions.append(
                f"Verify database integrity: gmailarchiver verify-integrity --state-db {state_db}"
            )
            suggestions.append(
                f"Repair database if needed: gmailarchiver repair --no-dry-run "
                f"--state-db {state_db}"
            )

        if suggestions:
            output.suggest_next_steps(suggestions)

        output.end_operation(success=False, summary="Validation failed")
        raise typer.Exit(1)

    output.end_operation(success=True, summary="All validation checks passed")


@utilities_app.command("retry-delete")
@app.command("retry-delete", hidden=True)
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
    from gmailarchiver.output import OutputManager

    output = OutputManager()
    output.start_operation("retry-delete", f"Retrying deletion for {archive_file}")

    try:
        # 1. Get archived message IDs from database
        with ArchiveState(state_db) as state:
            message_ids = list(state.get_archived_message_ids_for_file(archive_file))

        if not message_ids:
            output.show_error_panel(
                title="No Messages Found",
                message=f"No archived messages found for: {archive_file}",
                details=[
                    "Archive file name doesn't match database records",
                    "Wrong state database path",
                    f"Using state database: {state_db}",
                ],
                suggestion="Check the archive file name and state database path",
                exit_code=1,
            )
            return

        output.info(f"Found {len(message_ids)} archived messages")
        output.info(f"Archive: {archive_file}\n")

        # 2. Authenticate and validate scopes
        authenticator = GmailAuthenticator(credentials_file=credentials)
        output.info("Authenticating with Gmail...")
        creds = authenticator.authenticate()

        # 3. Validate deletion scope
        output.info("Validating permissions...")
        if not authenticator.validate_scopes(["https://mail.google.com/"]):
            # Keep wording so tests still find 'Missing deletion permission' and 'auth-reset'
            output.show_error_panel(
                title="Missing deletion permission",
                message="Your current authorization doesn't include permission to delete messages",
                details=[
                    "This was likely caused by using an older version of the app",
                ],
                suggestion="Run 'gmailarchiver auth-reset' then retry this command",
                exit_code=1,
            )
            return

        output.success("Permissions validated")

        # 4. Create Gmail client
        client = GmailClient(creds)

        # 5. Create archiver (for deletion functionality)
        archiver = GmailArchiver(client, state_db, output=output)

        # 6. Delete messages with appropriate confirmation
        if permanent:
            output.warning("WARNING: PERMANENT DELETION")
            output.warning(
                f"This will permanently delete {len(message_ids)} messages. "
                "This action CANNOT be undone!"
            )
            output.info(
                "Deleted messages will be gone forever - not in trash and not recoverable.\n"
            )

            confirmation = typer.prompt(f"Type 'DELETE {len(message_ids)} MESSAGES' to confirm")
            if confirmation != f"DELETE {len(message_ids)} MESSAGES":
                output.info("Deletion cancelled")
                output.end_operation(success=True)
                return

            # Perform permanent deletion
            archiver.delete_archived_messages(message_ids, permanent=True)

        else:
            # Trash deletion (default) - still ask for confirmation
            output.info(f"This will move {len(message_ids)} messages to trash.")
            output.info("(Messages can be recovered from trash for 30 days)\n")

            if not typer.confirm(f"Move {len(message_ids)} messages to trash?"):
                output.info("Cancelled")
                output.end_operation(success=True)
                return

            # Move to trash
            archiver.delete_archived_messages(message_ids, permanent=False)

        output.success("Deletion completed successfully!")
        output.end_operation(success=True)

    except Exception as e:
        output.show_error_panel(
            title="Retry Delete Failed",
            message=str(e),
            suggestion="Check your network connection and authentication status",
            exit_code=1,
        )


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

        # Display recent runs table
        if recent_runs:
            headers = ["Run ID", "Timestamp", "Query", "Messages", "Archive File"]
            rows: list[list[str]] = []
            for run in recent_runs:
                rows.append(
                    [
                        str(run["run_id"]),
                        run["timestamp"][:19],  # Truncate timestamp
                        run["query"],
                        str(run["messages_archived"]),
                        run["archive_file"],
                    ]
                )

            output.show_table("Recent Archive Runs", headers, rows)
        else:
            output.warning("No archive runs found")

    output.end_operation(success=True)


@app.command()
def cleanup(
    session_id: str | None = typer.Argument(
        None,
        help="Specific session ID to clean up (use --list to see sessions)",
    ),
    list_sessions: bool = typer.Option(
        False, "--list", "-l", help="List all partial archive sessions"
    ),
    all_sessions: bool = typer.Option(False, "--all", "-a", help="Clean up ALL partial sessions"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Manage partial archive sessions from interrupted operations.

    Use this command to list or clean up partial archives left from
    interrupted archiving operations (Ctrl+C, crashes, etc.).

    Examples:
        # List all partial sessions
        $ gmailarchiver cleanup --list

        # Clean up a specific session
        $ gmailarchiver cleanup abc123-session-id

        # Clean up all partial sessions
        $ gmailarchiver cleanup --all

        # Force cleanup without confirmation
        $ gmailarchiver cleanup --all --force
    """
    from gmailarchiver.db_manager import DBManager
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("cleanup", "Managing partial archive sessions")

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.warning("No archive database found")
        output.suggest_next_steps(
            [
                "Archive emails: gmailarchiver archive 3y",
            ]
        )
        output.end_operation(success=True)
        raise typer.Exit(0)

    # Validate arguments
    if not list_sessions and not all_sessions and not session_id:
        output.error("Please specify --list, --all, or provide a session ID", exit_code=0)
        output.suggest_next_steps(
            [
                "List sessions: gmailarchiver cleanup --list",
                "Clean all: gmailarchiver cleanup --all",
            ]
        )
        output.end_operation(success=False)
        raise typer.Exit(1)

    try:
        db = DBManager(state_db, validate_schema=False, auto_create=False)
        db.ensure_sessions_table()

        # Get all partial sessions
        sessions = db.get_all_partial_sessions()

        if list_sessions:
            if not sessions:
                output.info("No partial archive sessions found")
                output.end_operation(success=True)
                raise typer.Exit(0)

            # Display sessions table
            headers = ["Session ID", "Target File", "Progress", "Started", "Updated"]
            rows: list[list[str]] = []
            for session in sessions:
                progress = f"{session['processed_count']}/{session['total_count']}"
                started = session["started_at"][:19] if session["started_at"] else "N/A"
                updated = session["updated_at"][:19] if session["updated_at"] else "N/A"
                rows.append(
                    [
                        session["session_id"][:12] + "...",  # Truncate UUID
                        Path(session["target_file"]).name,
                        progress,
                        started,
                        updated,
                    ]
                )

            output.show_table("Partial Archive Sessions", headers, rows)
            output.info(f"Found {len(sessions)} partial session(s)")
            output.suggest_next_steps(
                [
                    "Clean specific: gmailarchiver cleanup <session-id>",
                    "Clean all: gmailarchiver cleanup --all",
                ]
            )
            output.end_operation(success=True)
            raise typer.Exit(0)

        # Determine which sessions to clean
        sessions_to_clean: list[dict[str, Any]] = []

        if all_sessions:
            sessions_to_clean = sessions
            if not sessions_to_clean:
                output.info("No partial archive sessions to clean up")
                output.end_operation(success=True)
                raise typer.Exit(0)
        elif session_id:
            # Find specific session (support partial UUID match)
            matching = [s for s in sessions if s["session_id"].startswith(session_id)]
            if not matching:
                output.error(f"Session not found: {session_id}", exit_code=0)
                output.suggest_next_steps(["List sessions: gmailarchiver cleanup --list"])
                output.end_operation(success=False)
                raise typer.Exit(1)
            if len(matching) > 1:
                output.error(
                    f"Multiple sessions match '{session_id}'. Be more specific.", exit_code=0
                )
                output.end_operation(success=False)
                raise typer.Exit(1)
            sessions_to_clean = matching

        # Confirmation prompt
        if not force:
            output.warning(
                f"This will delete {len(sessions_to_clean)} partial session(s) "
                "and their associated data"
            )
            confirm = typer.confirm("Continue?")
            if not confirm:
                output.info("Cleanup cancelled")
                output.end_operation(success=True)
                raise typer.Exit(0)

        # Perform cleanup
        cleaned_count = 0
        for session in sessions_to_clean:
            target_file = session["target_file"]
            partial_file = Path(target_file + ".partial")

            # Delete partial file if it exists
            if partial_file.exists():
                partial_file.unlink()
                output.info(f"Deleted partial file: {partial_file.name}")

            # Delete messages associated with the partial file
            deleted_msgs = db.delete_messages_for_file(str(partial_file))
            if deleted_msgs > 0:
                output.info(f"Removed {deleted_msgs} message records")

            # Delete session record
            db.delete_session(session["session_id"])
            output.success(f"Cleaned session: {session['session_id'][:12]}...")
            cleaned_count += 1

        db.close()

        output.success(f"Cleaned up {cleaned_count} partial session(s)")
        output.end_operation(success=True)

    except Exception as e:
        output.error(f"Cleanup failed: {e}", exit_code=0)
        output.end_operation(success=False)
        raise typer.Exit(1)


@utilities_app.command()
@app.command(hidden=True)
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check the database path or use --state-db to specify location",
            exit_code=1,
        )
        return

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
        output.show_error_panel(
            title="Invalid Database",
            message="Database appears to be empty or invalid",
            suggestion="Create a database with 'gmailarchiver archive' or 'gmailarchiver import'",
            exit_code=1,
        )
        return

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
        output.show_error_panel(
            title="Migration Failed",
            message=str(e),
            suggestion="Check database integrity or restore from backup",
            exit_code=1,
        )
    finally:
        manager._close()


@utilities_app.command(name="db-info")
@app.command(name="db-info", hidden=True)
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

            # Display recent runs table
            if recent_runs:
                headers = ["Run ID", "Timestamp", "Messages", "Archive File"]
                rows: list[list[str]] = []
                for run in recent_runs:
                    rows.append(
                        [
                            str(run["run_id"]),
                            run["timestamp"][:19],  # Truncate timestamp
                            str(run["messages_archived"]),
                            run["archive_file"],
                        ]
                    )

                output.show_table("Recent Archive Runs (Last 5)", headers, rows)
            else:
                output.warning("No archive runs found")

            output.end_operation(success=True)

    except Exception as e:
        output.show_error_panel(
            title="Database Error",
            message=f"Error reading database: {e}",
            suggestion="Check database file integrity",
            exit_code=1,
        )
    finally:
        manager._close()


@utilities_app.command()
@app.command(hidden=True)
def rollback(
    backup_file: str | None = typer.Option(
        None, "--backup-file", help="Path to backup file for rollback"
    ),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Rollback database to a previous backup.

    If no backup file is specified, lists available backups.

    Example:
        $ gmailarchiver rollback
        $ gmailarchiver rollback --backup-file archive_state.db.backup.20250114_120000
        $ gmailarchiver rollback --json
    """
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("rollback", "Rolling back database")

    db_path = Path(state_db)

    # If no backup file specified, list available backups
    if not backup_file:
        # Find backup files
        backup_pattern = f"{db_path.name}.backup.*"
        backups = sorted(db_path.parent.glob(backup_pattern), reverse=True)

        if not backups:
            output.show_error_panel(
                title="No Backups Found",
                message="No backup files found",
                suggestion=f"Looking for pattern: {backup_pattern}",
                exit_code=1,
            )
            return

        headers = ["Backup File", "Size", "Created"]
        rows: list[list[str]] = []

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

            rows.append([str(backup), size, timestamp])

        output.show_table("Available backup files", headers, rows)
        output.info("Use --backup-file to specify which backup to restore")
        output.end_operation(success=True)
        return

    # Rollback to specified backup
    backup_path = Path(backup_file)

    if not backup_path.exists():
        output.show_error_panel(
            title="Backup Not Found",
            message=f"Backup file not found: {backup_file}",
            suggestion="Check the backup path and try again",
            exit_code=1,
        )
        return

    output.info(f"Backup file: {backup_file}")
    output.info(f"Target database: {state_db}\n")

    output.warning(
        "⚠ WARNING: This will replace the current database with the backup. "
        "Any changes made after the backup was created will be lost."
    )

    # Confirm rollback
    if not typer.confirm("Proceed with rollback?"):
        output.info("Rollback cancelled")
        output.end_operation(success=True)
        return

    try:
        manager = MigrationManager(db_path)
        manager.rollback_migration(backup_path)

        output.success("Rollback completed successfully!")
        output.end_operation(success=True)

    except Exception as e:
        output.show_error_panel(
            title="Rollback Failed",
            message=str(e),
            suggestion="Check backup file integrity and try again",
            exit_code=1,
        )


@utilities_app.command(name="dedupe-report")
@app.command(name="dedupe-report", hidden=True)
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )
        return

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            with output.progress_context("Analyzing duplicates", total=None):
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
        output.show_error_panel(
            title="Schema Error",
            message=str(e),
            suggestion="Run 'gmailarchiver migrate' to upgrade your database",
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Analysis Failed",
            message=f"Deduplication analysis failed: {e}",
            suggestion="Check database integrity and try again",
            exit_code=1,
        )


@utilities_app.command()
@app.command(hidden=True)
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )
        return

    # Validate strategy
    valid_strategies = ["newest", "largest", "first"]
    if strategy not in valid_strategies:
        output.show_error_panel(
            title="Invalid Strategy",
            message=f"Invalid strategy: {strategy}",
            suggestion=f"Must be one of: {', '.join(valid_strategies)}",
            exit_code=1,
        )
        return

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with MessageDeduplicator(str(db_path)) as dedup:
            with output.progress_context("Finding duplicates", total=None):
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

                with output.progress_context("Analyzing duplicates", total=None):
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
                with output.progress_context("Removing duplicates", total=None):
                    result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=False)

                report_data["Removed"] = f"{result.messages_removed:,} messages"
                report_data["Kept"] = f"{result.messages_kept:,} messages"
                report_data["Space Saved"] = format_bytes(result.space_saved)

                output.show_report("Deduplication Results", report_data)
                output.success("Deduplication completed!")

                output.suggest_next_steps(
                    [
                        "Verify database: gmailarchiver verify-integrity",
                        (
                            "Consolidate archives: "
                            "gmailarchiver consolidate archive*.mbox -o merged.mbox"
                        ),
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
        output.show_error_panel(
            title="Schema Error",
            message=str(e),
            suggestion="Run 'gmailarchiver migrate' to upgrade your database",
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Deduplication Failed",
            message=str(e),
            suggestion="Check database integrity and try again",
            exit_code=1,
        )


@utilities_app.command(name="verify-offsets")
@app.command(name="verify-offsets", hidden=True)
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
        output.show_error_panel(
            title="File Not Found",
            message=f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )
        return

    db_path = Path(state_db)
    if not db_path.exists():
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )
        return

    # Create validator and run verification
    try:
        validator = ArchiveValidator(archive_file, state_db, output=output)

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
        output.show_error_panel(
            title="Verification Failed",
            message=f"Offset verification failed: {e}",
            suggestion="Check database and archive file integrity",
            exit_code=1,
        )


@utilities_app.command(name="verify-consistency")
@app.command(name="verify-consistency", hidden=True)
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
        output.show_error_panel(
            title="File Not Found",
            message=f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
            exit_code=1,
        )
        return

    db_path = Path(state_db)
    if not db_path.exists():
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver import' or specify database path with --state-db",
            exit_code=1,
        )
        return

    # Create validator and run consistency check
    try:
        validator = ArchiveValidator(archive_file, state_db, output=output)

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
        output.show_error_panel(
            title="Consistency Check Failed",
            message=str(e),
            suggestion="Check database and archive file integrity",
            exit_code=1,
        )


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
    import time
    from datetime import datetime

    from gmailarchiver.output import OutputManager

    from .migration import MigrationManager
    from .search import SearchEngine

    output = OutputManager(json_mode=json_output)

    # Validate flags
    if extract and not output_dir:
        output.show_error_panel(
            title="Missing Output Directory",
            message="--extract requires --output-dir",
            suggestion="Specify output directory: --output-dir /path/to/directory",
            exit_code=1,
        )
        return

    # Interactive mode is mutually exclusive with some flags
    if interactive and json_output:
        output.show_error_panel(
            title="Invalid Option Combination",
            message="--interactive cannot be used with --json",
            suggestion="Remove --json flag for interactive mode",
            exit_code=1,
        )
        return

    if interactive and extract:
        output.show_error_panel(
            title="Invalid Option Combination",
            message="--interactive cannot be used with --extract",
            suggestion="Use --interactive alone (extraction is part of interactive mode)",
            exit_code=1,
        )
        return

    # Check database exists
    db_path = Path(state_db)
    if not db_path.exists():
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' or 'gmailarchiver import' to create database",
            exit_code=1,
        )
        return

    # Check schema version (require v1.1)
    manager = MigrationManager(db_path)
    schema_version = manager.detect_schema_version()
    manager._close()

    if schema_version != "1.1":
        output.show_error_panel(
            title="Schema Upgrade Required",
            message="Search requires v1.1 database schema",
            suggestion="Run 'gmailarchiver migrate' to upgrade",
            exit_code=1,
        )
        return

    # Validate dates if provided
    if after:
        try:
            datetime.strptime(after, "%Y-%m-%d")
        except ValueError:
            output.show_error_panel(
                title="Invalid Date Format",
                message=f"Invalid date format: {after}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
                exit_code=1,
            )
            return

    if before:
        try:
            datetime.strptime(before, "%Y-%m-%d")
        except ValueError:
            output.show_error_panel(
                title="Invalid Date Format",
                message=f"Invalid date format: {before}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
                exit_code=1,
            )
            return

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
            output.show_error_panel(
                title="Missing Query",
                message="No search query or filters provided",
                suggestion="Provide a query argument or use filters like --from, --subject",
                exit_code=1,
            )
            return

        query = " ".join(query_parts)

    if not json_output:
        output.start_operation("search", f"Searching: {query}")

    # Execute search
    try:
        from gmailarchiver._output_search import (
            display_search_results_json,
            display_search_results_rich,
        )
        from gmailarchiver.output import SearchResultEntry

        start_time = time.perf_counter()

        with SearchEngine(state_db) as engine:
            results = engine.search(query, limit=limit)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        # Convert search results to SearchResultEntry format
        result_entries = [
            SearchResultEntry(
                gmail_id=r.gmail_id,
                rfc_message_id=r.rfc_message_id,
                subject=r.subject,
                from_addr=r.from_addr,
                to_addr=r.to_addr,
                date=r.date,
                body_preview=r.body_preview,
                archive_file=r.archive_file,
                mbox_offset=r.mbox_offset,
                relevance_score=r.relevance_score,
            )
            for r in results.results
        ]

        # Format output via OutputManager
        if json_output:
            display_search_results_json(output, result_entries, with_preview=with_preview)
        else:
            display_search_results_rich(
                output,
                result_entries,
                results.total_results,
                with_preview=with_preview,
            )
            if results.total_results == 0:
                output.suggest_next_steps(
                    [
                        "Try a broader search query",
                        "Check query syntax with: gmailarchiver search --help",
                    ]
                )
            else:
                # Show summary
                report_data = {
                    "Query": query,
                    "Results Found": results.total_results,
                    "Execution Time": f"{execution_time_ms:.2f}ms",
                }
                output.show_report("Search Summary", report_data)

        # Interactive mode: allow user to select messages for extraction
        if interactive and not json_output:
            # If there are no search results, skip interactive UI entirely
            if results.total_results == 0:
                output.info("No search results found; nothing to select in interactive mode.")
                output.end_operation(success=True)
                return

            try:
                import questionary
            except ImportError:
                output.show_error_panel(
                    title="Missing Dependency",
                    message="Interactive mode requires the 'questionary' package",
                    suggestion="Install with: pip install questionary",
                    exit_code=1,
                )
                return

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
            output.info("")
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

            output.info(
                f"\nExtracting {len(selected_ids)} selected messages to {output_dir_str}..."
            )

            with MessageExtractor(state_db) as extractor:
                with output.progress_context(
                    "Extracting messages", total=len(selected_ids)
                ) as progress:
                    task = (
                        progress.add_task("Extracting", total=len(selected_ids))
                        if progress
                        else None
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

            assert output_dir is not None, "Output directory required for extraction"
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
        output.show_error_panel(
            title="Search Query Error",
            message=str(e),
            suggestion="Check your search query syntax",
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Search Failed",
            message=str(e),
            exit_code=1,
        )


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
    from gmailarchiver.extractor import ExtractorError, MessageExtractor
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
                except ExtractorError:
                    out.error(
                        f"Message not found: {message_id}",
                        suggestion=(
                            "Verify the message ID or search for messages: gmailarchiver search"
                        ),
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
    skip_gmail_lookup: bool = typer.Option(
        False,
        "--skip-gmail-lookup",
        help="Skip Gmail ID lookup (faster, but no instant deduplication)",
    ),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
    ),
    auto_verify: bool = typer.Option(False, "--auto-verify", help="Run verification after import"),
    state_db: str = typer.Option("archive_state.db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Import existing mbox archives into v1.1 database.

    Parses mbox files, extracts metadata with accurate byte offset tracking,
    and populates the v1.1 database for fast message access and searching.

    By default, imports look up real Gmail IDs for each message to enable instant
    deduplication during future archiving. Use --skip-gmail-lookup for offline imports.

    Examples:
        $ gmailarchiver import archive_2024.mbox
        $ gmailarchiver import archive_*.mbox.gz --skip-duplicates
        $ gmailarchiver import archive_*.mbox.gz --auto-verify
        $ gmailarchiver import "archives/*.mbox.zst" --account-id gmail_work
        $ gmailarchiver import old_archive.mbox --state-db /path/to/archive_state.db
        $ gmailarchiver import archive.mbox --json
        $ gmailarchiver import archive.mbox --skip-gmail-lookup  # Offline mode
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
                output.show_error_panel(
                    title="Migration Failed",
                    message=f"Failed to migrate database: {e}",
                    suggestion="Run 'gmailarchiver migrate' manually for more details",
                    exit_code=1,
                )
                return
        elif version == "none":
            # Empty database file exists - delete it and let DBManager create a fresh one
            manager._close()
            output.warning("Found empty database file, recreating with v1.1 schema...")
            try:
                db_path.unlink()
            except Exception as e:
                output.show_error_panel(
                    title="Database Error",
                    message=f"Failed to delete empty database: {e}",
                    suggestion="Check file permissions and try again",
                    exit_code=1,
                )
                return
        elif version != "1.1":
            manager._close()
            output.show_error_panel(
                title="Unsupported Database",
                message=f"Unsupported database schema version: {version}",
                suggestion="Delete the database or use --state-db with a different path",
                exit_code=1,
            )
            return
        else:
            # version == "1.1", all good
            pass

        if version not in ("none",):  # Don't close if we deleted the database
            manager._close()
    # If database doesn't exist, DBManager will auto-create it with v1.1 schema

    # Expand glob pattern
    files = glob.glob(archive_pattern)
    if not files:
        output.show_error_panel(
            title="No Files Found",
            message=f"No files match pattern: {archive_pattern}",
            suggestion="Check the file path or glob pattern",
            exit_code=1,
        )
        return

    output.info(f"Found {len(files)} file(s) to import")

    # Set up Gmail client for Gmail ID lookup (unless skipped)
    gmail_client = None
    if not skip_gmail_lookup:
        output.info("Setting up Gmail ID lookup (use --skip-gmail-lookup for offline mode)")
        try:
            authenticator = GmailAuthenticator(credentials_file=credentials)
            creds = authenticator.authenticate()
            gmail_client = GmailClient(creds)
            output.success("Gmail authentication successful")
        except Exception as e:
            output.warning(f"Gmail authentication failed: {e}")
            output.warning("Continuing without Gmail ID lookup (messages will have NULL gmail_id)")
            gmail_client = None

    # Import each file with progress
    importer = ArchiveImporter(state_db, gmail_client=gmail_client)
    results = []
    start_time = time.perf_counter()

    # Count total messages across all files for progress
    output.info("Counting messages...")
    total_messages = 0
    file_message_counts = []
    for file_path in files:
        count = importer.count_messages(file_path)
        file_message_counts.append(count)
        total_messages += count
    output.info(f"Total: {total_messages:,} messages to import")

    # Track overall progress
    messages_processed = 0

    with output.progress_context(
        "Importing messages", total=total_messages
    ) as progress:
        task = progress.add_task("Import", total=total_messages) if progress else None
        current_task_pos = 0

        for file_idx, file_path in enumerate(files):
            file_name = Path(file_path).name
            output.info(f"\nImporting {file_name} ({file_message_counts[file_idx]:,} messages)...")

            def make_progress_callback(
                base_pos: int,
            ) -> Callable[[int, int, str], None]:
                def callback(current: int, total: int, status: str) -> None:
                    nonlocal messages_processed
                    messages_processed = base_pos + current
                    if progress and task:
                        progress.update(
                            task,
                            completed=messages_processed,
                            description=f"{status} [{current}/{total}]",
                        )

                return callback

            try:
                result = importer.import_archive(
                    file_path,
                    account_id=account_id,
                    skip_duplicates=skip_duplicates,
                    progress_callback=make_progress_callback(current_task_pos),
                )
                results.append(result)
                current_task_pos += file_message_counts[file_idx]
            except Exception as e:
                output.error(f"Error importing {file_path}: {e}")
                current_task_pos += file_message_counts[file_idx]

    total_time = time.perf_counter() - start_time

    # Calculate totals
    total_imported = sum(r.messages_imported for r in results)
    total_skipped = sum(r.messages_skipped for r in results)
    total_failed = sum(r.messages_failed for r in results)

    # Build report data
    report_data: dict[str, str | int] = {
        "Files Imported": len(files),
        "Total Messages Imported": total_imported,
        "Skipped Duplicates": total_skipped,
        "Failed": total_failed,
    }

    # Add performance metrics
    if total_imported > 0 and total_time > 0:
        rate = total_imported / total_time
        report_data["Performance"] = f"{rate:.1f} messages/second"

    # High-level summary across all files
    output.show_report("Import Summary", report_data)

    # Per-file summary table so users can see which archives were processed
    if results:
        per_file_report: dict[str, str] = {}
        for r in results:
            file_name = Path(r.archive_file).name
            per_file_report[file_name] = (
                f"imported={r.messages_imported}, "
                f"skipped={r.messages_skipped}, "
                f"failed={r.messages_failed}"
            )

        output.show_report("Per-File Import Summary", per_file_report)

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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
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
    # ArchiveValidator is imported at module level for proper mocking in tests

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
        output.show_error_panel(
            title="No Archives Found",
            message="No archive files found matching the specified patterns",
            suggestion="Check file paths or glob patterns",
            exit_code=1,
        )
        return

    output.info(f"Found {len(all_files)} archive(s) to consolidate")

    # 2. Validate dedupe strategy
    valid_strategies = ["newest", "largest", "first"]
    if dedupe_strategy not in valid_strategies:
        output.show_error_panel(
            title="Invalid Dedupe Strategy",
            message=f"'{dedupe_strategy}' is not a valid dedupe strategy",
            suggestion=f"Valid strategies: {', '.join(valid_strategies)}",
            exit_code=1,
        )
        return

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
            "Duplicates Deduplicated": result.duplicates_removed,
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
            from gmailarchiver.db_manager import DBManager

            output.info("\nRunning verification...")
            try:
                db = DBManager(str(state_db), validate_schema=False)
                issues = db.verify_database_integrity()
                db.close()

                if not issues:
                    output.success("Verification passed - no issues found")
                else:
                    output.warning(f"Verification found {len(issues)} issue(s):")
                    for issue in issues[:5]:
                        output.info(f"  • {issue}")
                    if len(issues) > 5:
                        output.info(f"  ... and {len(issues) - 5} more issues")

                    output.suggest_next_steps(
                        [
                            "Fix issues automatically: gmailarchiver check --auto-repair",
                            "View all issues: gmailarchiver verify-integrity --verbose",
                        ]
                    )
            except Exception as e:  # pragma: no cover - defensive
                output.warning(f"Verification failed: {e}")

        # 8. Validate consolidated archive before removing sources
        cleanup_data: dict[str, Any] | None = None
        if remove_sources:
            try:
                # First: Basic safety checks - ensure consolidated output exists and is readable
                output.info("\nValidating consolidated archive...")
                output_path = Path(result.output_file)
                if not output_path.exists():
                    output.error(
                        "Consolidated archive does not exist - source files NOT removed",
                        suggestion="Check that consolidation completed successfully",
                        exit_code=0,  # Don't exit harshly, operation partially succeeded
                    )
                    output.end_operation(success=True)
                    return

                try:
                    # Verify we can read the output file (basic safety check)
                    output_size = output_path.stat().st_size
                    if output_size == 0:
                        output.warning(
                            "Consolidated archive appears to be empty "
                            "- skipping source file removal"
                        )
                        output.end_operation(success=True)
                        return
                except OSError as e:
                    output.warning(f"Cannot access consolidated archive: {e}")
                    output.info("Skipping source file removal due to access issues")
                    output.end_operation(success=True)
                    return

                output.info(f"Safety check passed (output: {format_bytes(output_size)})")

                # Second: Verify archive is readable and non-empty via validation
                output.info("Verifying archive readability...")
                try:
                    # Use ArchiveValidator to verify archive can be read
                    validator = ArchiveValidator(str(output_path))
                    # Simple check: verify archive is readable and has content
                    is_valid = validator.validate_all()
                    if not is_valid:
                        # Try to get error details
                        errors = validator.errors
                        if errors:
                            output.warning(f"Archive validation failed: {errors[0]}")
                        else:
                            output.warning(
                                "Consolidated archive validation failed - source files NOT removed"
                            )
                        output.info(
                            "Please review the consolidated archive "
                            "before manually removing sources"
                        )
                        output.end_operation(success=True)
                        return
                    output.success("Archive readability verified")
                except Exception as e:
                    output.warning(f"Archive readability check failed: {e}")
                    output.info("Skipping source file removal due to verification issues")
                    output.end_operation(success=True)
                    return

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
                        output.info(
                            f"\nThe following {len(files_to_remove)} "
                            f"source file(s) will be removed:"
                        )
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

                            # Record cleanup data for JSON top-level summary
                            cleanup_data = {
                                "removed_files": removed_count,
                                "space_freed_bytes": freed_space,
                                "failed_removals": len(failed_removals),
                            }

                            # Add cleanup data to JSON events for scripting
                            if json_output:
                                output._json_events.append(
                                    {
                                        "event": "cleanup",
                                        **cleanup_data,
                                    }
                                )

                        if failed_removals:
                            output.warning(f"Failed to remove {len(failed_removals)} file(s):")
                            for failure in failed_removals[:3]:
                                output.info(f"  • {failure}")
                            if len(failed_removals) > 3:
                                output.info(f"  ... and {len(failed_removals) - 3} more")

            except Exception as e:
                output.warning(f"Source file cleanup failed: {e}")
                output.info("Consolidation succeeded but source files were NOT removed")

        # If in JSON mode and we have cleanup data, attach it to the top-level payload
        if json_output and "output" in locals() and cleanup_data is not None:
            # Merge status with cleanup summary for top-level convenience
            output_payload = {
                "status": "ok",
                "success": True,
                **cleanup_data,
            }
            output.set_json_payload(output_payload)
        output.end_operation(success=True)

    except ValueError as e:
        output.show_error_panel(
            title="Validation Error",
            message=str(e),
            exit_code=1,
        )
    except FileNotFoundError as e:
        output.show_error_panel(
            title="File Not Found",
            message=str(e),
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Consolidation Failed",
            message=str(e),
            suggestion="Check archive files and try again",
            exit_code=1,
        )


@utilities_app.command(name="verify-integrity")
@app.command(name="verify-integrity", hidden=True)
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                "Run 'gmailarchiver archive' to create a database, or specify path with --state-db"
            ),
            exit_code=1,
        )
        return

    issues = None
    try:
        # Initialize DBManager without schema validation to avoid errors
        db = DBManager(str(db_path), validate_schema=False)

        with output.progress_context("Running integrity checks", total=5) as progress:
            task = progress.add_task("Integrity checks", total=5) if progress else None
            issues = db.verify_database_integrity()
            if progress and task:
                progress.update(task, completed=5)

        db.close()

    except FileNotFoundError as e:
        output.show_error_panel(
            title="File Not Found",
            message=str(e),
            exit_code=1,
        )
        return
    except Exception as e:
        output.show_error_panel(
            title="Integrity Check Failed",
            message=str(e),
            suggestion="Check that the database file is not corrupted",
            exit_code=1,
        )
        return

    if issues is None:
        # An earlier error handler should already have exited via OutputManager.error
        return

    if not issues:
        output.success("Database integrity verified - no issues found")
        output.end_operation(success=True)
        raise typer.Exit(0)

    # Build report data for failures
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


@utilities_app.command()
@app.command(hidden=True)
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                "Run 'gmailarchiver archive' to create a database, or specify path with --state-db"
            ),
            exit_code=1,
        )
        return

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
        output.show_error_panel(
            title="File Not Found",
            message=str(e),
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Repair Failed",
            message=str(e),
            suggestion="Check the database file and try again",
            exit_code=1,
        )


def _display_repair_results(output: OutputManager, repairs: dict[str, int], dry_run: bool) -> None:
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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                "Run 'gmailarchiver archive' to create a database, or specify path with --state-db"
            ),
            exit_code=1,
        )
        return

    # Detect schema version
    manager = MigrationManager(db_path)
    schema_version = manager.detect_schema_version()
    manager._close()

    if schema_version == "none":
        output.show_error_panel(
            title="Invalid Database",
            message="Database is empty or invalid",
            suggestion=(
                "Create a new database with 'gmailarchiver archive' or 'gmailarchiver import'"
            ),
            exit_code=1,
        )
        return

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
        if consistency_report:
            # Count actual issues from report fields (not just errors list)
            issue_count = (
                consistency_report.orphaned_records
                + consistency_report.missing_records
                + consistency_report.duplicate_gmail_ids
                + consistency_report.duplicate_rfc_message_ids
                + (0 if consistency_report.fts_synced else 1)
                + len(consistency_report.errors)
            )
        else:
            issue_count = 0
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
            output.show_error_panel(
                title="Auto-Repair Failed",
                message=str(e),
                suggestion="Run 'gmailarchiver repair --no-dry-run' manually to fix issues",
                exit_code=2,
            )
            return

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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )
        return

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

        # Build table rows
        headers = ["ID", "Command", "Frequency", "When", "Status", "Last Run"]
        rows: list[list[str]] = []

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

            rows.append(
                [
                    str(schedule.id),
                    schedule.command,
                    schedule.frequency,
                    when_str,
                    status,
                    last_run,
                ]
            )

        output.show_table(f"Scheduled Tasks ({len(schedules)} total)", headers, rows)

        output.suggest_next_steps(
            [
                "Add schedule: gmailarchiver schedule add <command> --daily --time HH:MM",
                "Remove schedule: gmailarchiver schedule remove <id>",
            ]
        )
        output.end_operation(success=True)

    except Exception as e:
        output.show_error_panel(
            title="Failed to List Schedules",
            message=str(e),
            exit_code=1,
        )


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
    from gmailarchiver.platform_scheduler import UnsupportedPlatformError, get_platform_scheduler
    from gmailarchiver.scheduler import Scheduler, ScheduleValidationError

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-add", f"Adding schedule: {command}")

    # Validate frequency
    frequency_count = sum([daily, weekly, monthly])
    if frequency_count == 0:
        output.show_error_panel(
            title="No Frequency Specified",
            message="A schedule frequency must be specified",
            suggestion="Use --daily, --weekly, or --monthly",
            exit_code=1,
        )
        return
    elif frequency_count > 1:
        output.show_error_panel(
            title="Multiple Frequencies Specified",
            message="Only one frequency can be specified at a time",
            suggestion="Use only one of: --daily, --weekly, --monthly",
            exit_code=1,
        )
        return

    # Determine frequency
    if daily:
        frequency = "daily"
        day_of_week = None
        day_of_month = None
    elif weekly:
        frequency = "weekly"
        if not day:
            output.show_error_panel(
                title="Day Required",
                message="Weekly schedules require --day to specify which day of the week",
                suggestion="Use --day with day name (e.g., Sunday, Monday, ...)",
                exit_code=1,
            )
            return
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
            output.show_error_panel(
                title="Invalid Day Name",
                message=f"'{day}' is not a valid day name",
                suggestion="Use: Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday",
                exit_code=1,
            )
            return
        day_of_week = day_names[day_lower]
        day_of_month = None
    else:  # monthly
        frequency = "monthly"
        if not day:
            output.show_error_panel(
                title="Day Required",
                message="Monthly schedules require --day to specify which day of the month",
                suggestion="Use --day with day of month (1-31)",
                exit_code=1,
            )
            return
        try:
            day_of_month = int(day)
            if not (1 <= day_of_month <= 31):
                raise ValueError("Day must be 1-31")
        except ValueError:
            output.show_error_panel(
                title="Invalid Day of Month",
                message=f"'{day}' is not a valid day of month",
                suggestion="Use a number between 1 and 31",
                exit_code=1,
            )
            return
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
            output.show_error_panel(
                title="Schedule Creation Failed",
                message="Failed to retrieve created schedule",
                exit_code=1,
            )
            return

        output.success(f"Schedule created with ID: {schedule_id}")

        # Install on system scheduler if requested
        if install:
            assert schedule is not None, "Schedule should not be None"
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
        output.show_error_panel(
            title="Validation Error",
            message=str(e),
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Failed to Add Schedule",
            message=str(e),
            exit_code=1,
        )


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
    from gmailarchiver.platform_scheduler import UnsupportedPlatformError, get_platform_scheduler
    from gmailarchiver.scheduler import Scheduler

    output = OutputManager(json_mode=json_output)
    output.start_operation("schedule-remove", f"Removing schedule ID: {schedule_id}")

    db_path = Path(state_db)
    if not db_path.exists():
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )
        return

    try:
        with Scheduler(str(db_path)) as scheduler:
            # Get schedule before removing
            schedule = scheduler.get_schedule(schedule_id)
            if not schedule:
                output.show_error_panel(
                    title="Schedule Not Found",
                    message=f"Schedule with ID {schedule_id} does not exist",
                    suggestion="List schedules: gmailarchiver schedule list",
                    exit_code=1,
                )
                return

            # Uninstall from system scheduler if requested
            if uninstall:
                assert schedule is not None, "Schedule should not be None"
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
            output.show_error_panel(
                title="Failed to Remove Schedule",
                message=f"Failed to remove schedule {schedule_id}",
                exit_code=1,
            )

    except Exception as e:
        output.show_error_panel(
            title="Failed to Remove Schedule",
            message=str(e),
            exit_code=1,
        )


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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )
        return

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
            output.show_error_panel(
                title="Schedule Not Found",
                message=f"Schedule with ID {schedule_id} does not exist",
                suggestion="List schedules: gmailarchiver schedule list",
                exit_code=1,
            )

    except Exception as e:
        output.show_error_panel(
            title="Failed to Enable Schedule",
            message=str(e),
            exit_code=1,
        )


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
        output.show_error_panel(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
            exit_code=1,
        )
        return

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
            output.show_error_panel(
                title="Schedule Not Found",
                message=f"Schedule with ID {schedule_id} does not exist",
                suggestion="List schedules: gmailarchiver schedule list",
                exit_code=1,
            )

    except Exception as e:
        output.show_error_panel(
            title="Failed to Disable Schedule",
            message=str(e),
            exit_code=1,
        )


@app.command()
def compress(
    files: list[str] = typer.Argument(..., help="Mbox file paths or glob patterns to compress"),
    format: str = typer.Option(
        "zstd", "--format", "-f", help="Compression format: gzip, lzma, or zstd"
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help=("Replace original files with compressed versions and update the database"),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview compression without actually compressing"
    ),
    keep_original: bool = typer.Option(
        False,
        "--keep-original",
        help=(
            "Keep original uncompressed files on disk (useful with --in-place when you "
            "want database paths updated but also retain the source files)"
        ),
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

    When using --in-place, the database is updated to point to the compressed
    version. By default the original file is removed after successful validation;
    combine --in-place with --keep-original to update the database while also
    retaining the uncompressed source files on disk.

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
        output.show_error_panel(
            title="No Files Specified",
            message="No mbox files found to compress",
            suggestion="Provide mbox file paths or glob patterns",
            exit_code=1,
        )
        return

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
                files=expanded_files,
                format=format,
                in_place=in_place,
                dry_run=dry_run,
                keep_original=keep_original,
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

                next_steps = [
                    "Verify integrity: gmailarchiver verify-integrity",
                    "Search archived messages: gmailarchiver search <query>",
                ]
                if in_place and not keep_original:
                    next_steps.insert(
                        0,
                        (
                            "Restore from backup or re-import if needed "
                            "before deleting any other copies"
                        ),
                    )

                output.suggest_next_steps(next_steps)

        output.end_operation(success=True)

    except ValueError as e:
        output.show_error_panel(
            title="Compression Failed",
            message=str(e),
            exit_code=1,
        )
    except FileNotFoundError as e:
        output.show_error_panel(
            title="File Not Found",
            message=str(e),
            suggestion="Check the file path or glob pattern",
            exit_code=1,
        )
    except Exception as e:
        output.show_error_panel(
            title="Unexpected Error",
            message=str(e),
            exit_code=1,
        )


@app.command()
def doctor(
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    fix: bool = typer.Option(False, "--fix", help="Automatically fix issues where possible"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """Run system diagnostics and health checks.

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
        # Build diagnostic results table via OutputManager
        headers = ["Check", "Status", "Message"]
        rows: list[list[str]] = []

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
                message += " (fixable)"

            rows.append([check.name, status, message])

        output.show_table("Diagnostic Results", headers, rows)

        # Show summary
        if report.overall_status == CheckSeverity.OK:
            output.success(f"All checks passed! ({report.checks_passed}/{len(report.checks)} OK)")
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
            output.info(f"\n{len(report.fixable_issues)} issue(s) can be automatically fixed:")
            for issue in report.fixable_issues:
                output.info(f"  • {issue}")

            if not fix:
                output.suggest_next_steps(
                    ["Run with --fix to auto-repair: gmailarchiver doctor --fix"]
                )

    # Run auto-fix if requested
    if fix and report.fixable_issues:
        output.info("\nRunning auto-fix...")

        with output.progress_context("Fixing issues", total=len(report.fixable_issues)) as progress:
            task = (
                progress.add_task("Fixing...", total=len(report.fixable_issues))
                if progress
                else None
            )

            fix_results = doctor.run_auto_fix()

            if progress and task:
                progress.update(task, completed=len(report.fixable_issues))

        # Show fix results
        if not json_output:
            headers = ["Check", "Status", "Message"]
            fix_rows: list[list[str]] = []

            for fix_result in fix_results:
                status = "[green]✓ FIXED[/green]" if fix_result.success else "[red]✗ FAILED[/red]"
                fix_rows.append([fix_result.check_name, status, fix_result.message])

            output.show_table("Auto-Fix Results", headers, fix_rows)

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


@utilities_app.command()
@app.command(hidden=True)
def auth_reset(
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    from gmailarchiver.output import OutputManager

    output = OutputManager(json_mode=json_output)
    output.start_operation("auth-reset", "Resetting authentication")

    authenticator = GmailAuthenticator()
    authenticator.revoke()

    output.success("Authentication token deleted")
    output.info("Run any command to re-authenticate")
    output.end_operation(success=True)


@utilities_app.command(name="backfill-gmail-ids")
def backfill_gmail_ids_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without updating"),
    limit: int = typer.Option(0, "--limit", help="Maximum messages to process (0 = all)"),
    offset: int = typer.Option(0, "--offset", help="Skip first N messages (for resuming)"),
    batch_size: int = typer.Option(50, "--batch-size", help="Messages per batch (default 50)"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Backfill real Gmail IDs for imported messages.

    This command fixes databases with synthetic gmail_ids from older imports
    by looking up each message's RFC Message-ID in Gmail to find its real Gmail ID.

    Messages deleted from Gmail will have their gmail_id set to NULL, which is
    correct - they cannot be duplicates of current Gmail messages.

    This is a ONE-TIME operation. After running, future imports will automatically
    capture real Gmail IDs, enabling instant deduplication.

    Examples:
        Preview what would be updated:
        $ gmailarchiver utilities backfill-gmail-ids --dry-run

        Process all messages with synthetic IDs:
        $ gmailarchiver utilities backfill-gmail-ids

        Resume from offset (if interrupted):
        $ gmailarchiver utilities backfill-gmail-ids --offset 5000
    """
    import re
    import sys

    from gmailarchiver.db_manager import DBManager
    from gmailarchiver.output import OutputManager

    # Use live mode for TTY (consistent with archive command)
    use_live_mode = not json_output and sys.stdout.isatty()
    output = OutputManager(json_mode=json_output, live_mode=use_live_mode)
    operation_mode = "backfill-gmail-ids (dry-run)" if dry_run else "backfill-gmail-ids"
    output.start_operation(operation_mode, "Backfilling real Gmail IDs")

    # Pattern to detect synthetic gmail_ids (start with 000...)
    synthetic_id_pattern = re.compile(r"^0{3,}[0-9a-f]+$", re.IGNORECASE)

    try:
        # 1. Authenticate with Gmail
        output.info("Authenticating with Gmail...")
        authenticator = GmailAuthenticator(credentials_file=credentials)
        creds = authenticator.authenticate()
        client = GmailClient(creds)
        output.success("Authenticated")

        # 2. Find messages needing Gmail ID lookup
        output.info("Scanning database for messages needing backfill...")
        with DBManager(state_db, validate_schema=False, auto_create=False) as db:
            cursor = db.conn.execute(
                "SELECT gmail_id, rfc_message_id FROM messages"
            )
            all_messages = cursor.fetchall()

        # Messages needing backfill: NULL gmail_id OR synthetic pattern
        messages_needing_backfill: list[tuple[str | None, str]] = []
        real_messages_count = 0
        null_gmail_id_count = 0
        synthetic_gmail_id_count = 0

        for gid, rfc in all_messages:
            if gid is None:
                messages_needing_backfill.append((gid, rfc))
                null_gmail_id_count += 1
            elif synthetic_id_pattern.match(gid):
                messages_needing_backfill.append((gid, rfc))
                synthetic_gmail_id_count += 1
            else:
                real_messages_count += 1

        output.info(f"Total messages in database: {len(all_messages):,}")
        output.info(f"Messages with real Gmail IDs: {real_messages_count:,}")
        output.info(f"Messages with NULL gmail_id: {null_gmail_id_count:,}")
        output.info(f"Messages with synthetic IDs: {synthetic_gmail_id_count:,}")
        output.info(f"Total needing backfill: {len(messages_needing_backfill):,}")

        if not messages_needing_backfill:
            output.success("No messages need backfill!")
            output.end_operation(success=True)
            return

        # Apply offset and limit
        messages_to_process = messages_needing_backfill[offset:]
        if limit > 0:
            messages_to_process = messages_to_process[:limit]

        if offset > 0:
            output.info(f"Skipping first {offset} messages (--offset)")
        if limit > 0:
            output.info(f"Processing up to {limit} messages (--limit)")

        total_to_process = len(messages_to_process)
        output.info(f"\nProcessing {total_to_process:,} messages in batches of {batch_size}...")

        # Estimate time (batch processing is faster: ~1 batch per 1.5 seconds)
        num_batches = (total_to_process + batch_size - 1) // batch_size
        est_seconds = num_batches * 1.5  # ~1.5s per batch (API call + delay)
        output.info(f"Estimated time: {est_seconds/60:.1f} minutes")

        if dry_run:
            output.warning("[DRY RUN] No changes will be made")

        # 3. Process messages in batches using batch API
        found = 0
        not_found = 0
        updates: list[tuple[str | None, str]] = []  # (new_gmail_id, rfc_message_id)

        # Extract just the rfc_message_ids for batch lookup
        rfc_ids_to_lookup = [rfc for _, rfc in messages_to_process]

        # Track progress state for periodic updates
        last_progress_update = [0]  # Use list to allow mutation in nested function

        # Use batch lookup with progress callback
        def progress_callback(processed: int, total: int) -> None:
            # Only update every 10 messages or at completion for clean output
            if processed - last_progress_update[0] >= 10 or processed == total:
                pct = 100 * processed // total if total > 0 else 0
                output.info(f"  Progress: {processed:,}/{total:,} ({pct}%)")
                last_progress_update[0] = processed

        # Use the batch method for efficient lookups
        output.info("\nLooking up Gmail IDs...")
        results = client.search_by_rfc_message_ids_batch(
            rfc_ids_to_lookup,
            progress_callback=progress_callback,
            batch_size=batch_size,
            batch_delay=1.2,  # Delay between batches to avoid rate limits
        )

        # Process results
        for rfc_id, gmail_id in results.items():
            if gmail_id:
                found += 1
                updates.append((gmail_id, rfc_id))
            else:
                not_found += 1

        # 4. Update database
        output.info("\nResults:")
        output.info(f"  Found in Gmail: {found:,}")
        output.info(f"  Not in Gmail (deleted): {not_found:,}")

        if dry_run:
            output.warning(f"\n[DRY RUN] Would update {len(updates):,} messages")
            if updates[:5]:
                output.info("Sample updates:")
                for new_id, rfc_id in updates[:5]:
                    status = new_id[:16] + "..." if new_id else "NULL"
                    rfc_display = rfc_id[:40] + "..." if len(rfc_id) > 40 else rfc_id
                    output.info(f"  {rfc_display} -> {status}")
        else:
            output.info(f"\nUpdating database with {len(updates):,} changes...")
            with DBManager(state_db, validate_schema=False, auto_create=False) as db:
                for new_gmail_id, rfc_message_id in updates:
                    db.conn.execute(
                        "UPDATE messages SET gmail_id = ? WHERE rfc_message_id = ?",
                        (new_gmail_id, rfc_message_id),
                    )
                db.conn.commit()
            output.success("Database updated!")

        # Summary
        remaining = len(messages_needing_backfill) - len(messages_to_process) - offset
        if remaining > 0:
            output.info(f"\nRemaining messages to process: {remaining:,}")
            next_offset = offset + len(messages_to_process)
            output.info(f"Resume with: --offset {next_offset}")

        output.end_operation(success=True)

    except Exception as e:
        output.show_error_panel(
            title="Backfill Failed",
            message=str(e),
            suggestion="Check your internet connection and Gmail authentication",
            exit_code=1,
        )


if __name__ == "__main__":
    app()
