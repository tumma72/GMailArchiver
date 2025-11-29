"""Gmail Archiver CLI application."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from ._version import __version__
from .cli.command_context import CommandContext, with_context
from .cli.output import OutputManager
from .connectors.auth import GmailAuthenticator
from .core.archiver import ArchiverFacade
from .core.compressor.facade import ArchiveCompressor
from .core.consolidator.facade import ArchiveConsolidator
from .core.deduplicator.facade import DeduplicatorFacade
from .core.doctor.facade import Doctor
from .core.extractor.facade import MessageExtractor
from .core.importer.facade import ImporterFacade
from .core.search.facade import SearchFacade
from .core.validator.facade import ValidatorFacade
from .data.migration import MigrationManager
from .data.schema_manager import SchemaCapability, SchemaManager, SchemaVersion
from .data.state import ArchiveState
from .shared.utils import format_bytes


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
@with_context(has_progress=True, operation_name="archive")
def archive(
    ctx: CommandContext,
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
    out = ctx.output

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

    # Phase 1: Authentication
    gmail_client = ctx.authenticate_gmail(credentials=credentials)
    assert gmail_client is not None  # required=True ensures this
    archiver = ArchiverFacade(
        gmail_client=gmail_client,
        state_db_path="archive_state.db",
        output_manager=out,
    )

    # Phase 2: Discovery and Archiving (multi-task sequence)
    message_list: list[dict[str, str]] = []
    messages_to_archive: list[str] = []
    skipped_count: int = 0
    result: dict[str, Any] | None = None
    archive_error: Exception | None = None
    scan_count: int = 0  # Track messages scanned during listing

    with ctx.ui.task_sequence(show_logs=True) as seq:
        # Task 1: Scan messages from Gmail
        with seq.task("Scanning messages from Gmail") as task:
            try:
                # Progress callback to update counter during scanning
                def scan_progress(count: int, page: int) -> None:
                    nonlocal scan_count
                    scan_count = count
                    task.set_status(f"Scanning messages from Gmail... {count:,} found")

                _query, message_list = archiver.list_messages_for_archive(
                    age_threshold, progress_callback=scan_progress
                )

                if message_list:
                    task.complete(f"Found {len(message_list):,} messages")
                else:
                    task.complete("No messages found matching criteria")

            except Exception as e:
                task.fail(f"Scan failed: {e}")
                archive_error = e

        # Task 2: Filter already archived (only if messages found and no error)
        if message_list and not archive_error:
            with seq.task("Checking for already archived") as task:
                try:
                    all_ids = [msg["id"] for msg in message_list]
                    messages_to_archive, skipped_count = archiver.filter_already_archived(
                        all_ids, incremental=incremental
                    )

                    if skipped_count > 0:
                        task.complete(
                            f"Identified {len(messages_to_archive):,} to archive "
                            f"({skipped_count:,} already archived)"
                        )
                    else:
                        task.complete(f"Identified {len(messages_to_archive):,} to archive")

                except Exception as e:
                    task.fail(f"Filter failed: {e}")
                    archive_error = e

        # Task 3: Archive messages (only if messages to archive and no error)
        if messages_to_archive and not archive_error and not dry_run:
            with seq.task("Archiving messages", total=len(messages_to_archive)) as task:
                try:
                    result = archiver.archive_messages(
                        message_ids=messages_to_archive,
                        output_file=output,
                        compress=compress,
                        operation=task,
                    )

                    if result.get("interrupted"):
                        task.complete(f"Interrupted after {result['archived_count']:,} messages")
                    elif result["archived_count"] > 0:
                        task.complete(f"Archived {result['archived_count']:,} messages")
                    else:
                        task.complete("No messages archived")

                except KeyboardInterrupt:
                    task.log("Archive interrupted by user", "WARNING")
                    task.complete("Interrupted")
                    result = {"interrupted": True, "archived_count": 0}

                except Exception as e:
                    task.fail(f"Archive failed: {e}")
                    archive_error = e

    # Handle errors (outside live context)
    if archive_error:
        ctx.fail_and_exit(
            title="Archive Failed",
            message=str(archive_error),
            suggestion="Check your network connection and Gmail API access",
        )

    # Handle dry run result
    if dry_run:
        ctx.warning("DRY RUN completed - no changes made")
        report_data = {
            "Messages Found": len(message_list),
            "Messages to Archive": len(messages_to_archive),
            "Already Archived": skipped_count,
            "Output File": output,
            "Mode": "Dry Run (no changes made)",
        }
        ctx.show_report("Archive Preview", report_data)
        return

    # Handle no messages case (after dry run check)
    if not message_list:
        ctx.warning("No messages found matching criteria")
        ctx.suggest_next_steps(
            [
                "Check your age threshold",
                "Verify messages exist in Gmail matching the criteria",
            ]
        )
        return

    if not messages_to_archive:
        ctx.warning("All messages already archived")
        ctx.suggest_next_steps(
            [
                "Run 'gmailarchiver status' to see archive statistics",
                "Use --no-incremental to re-archive messages",
            ]
        )
        return

    # Handle interrupted archive (Ctrl+C)
    if result and result.get("interrupted", False):
        actual_file = result.get("actual_file", output)
        ctx.warning("Archive was interrupted (Ctrl+C)")
        ctx.info(f"Partial archive saved: {actual_file}")
        ctx.info(f"Progress: {result['archived_count']} messages archived")
        ctx.suggest_next_steps(
            [
                f"Resume: gmailarchiver archive {age_threshold}",
                "Cleanup: gmailarchiver cleanup --list",
            ]
        )
        return

    # Phase 5: Validation (outside live context for clean output)
    ctx.info("Validating archive...")

    # Get the actual file that was written
    actual_file = result.get("actual_file", output) if result else output

    # Get the actual message IDs that were archived
    with ArchiveState() as state:
        archived_ids = state.get_archived_message_ids_for_file(actual_file)

    # Validate using ValidatorFacade directly
    validator = ValidatorFacade(actual_file, "archive_state.db", output=out)
    validation_results = validator.validate_comprehensive(archived_ids)

    # Show validation report using new panel method
    out.show_validation_report(validation_results, title="Archive Validation")

    if not validation_results["passed"]:
        ctx.fail_and_exit(
            title="Validation Failed",
            message="Archive validation did not pass all checks",
            details=validation_results.get("errors", []),
            suggestion="Check disk space and file permissions. DO NOT delete Gmail messages yet.",
        )

    ctx.success("Archive validation passed")

    # Get archived count from result
    archived_count = result.get("archived_count", 0) if result else 0

    # Phase 6: Deletion (if requested)
    if (trash or delete) and archived_count > 0:
        if delete:
            # Permanent deletion requires explicit confirmation
            ctx.warning("WARNING: PERMANENT DELETION")
            ctx.warning(f"This will permanently delete {archived_count} messages.")
            ctx.warning("This action CANNOT be undone!")

            confirmation = typer.prompt(f"\nType 'DELETE {archived_count} MESSAGES' to confirm")

            if confirmation != f"DELETE {archived_count} MESSAGES":
                ctx.info("Deletion cancelled")
                return

            # Perform permanent deletion
            with out.progress_context("Permanently deleting messages", total=None):
                gmail_client.delete_messages_permanent(list(archived_ids))
            ctx.success("Messages permanently deleted")

        elif trash:
            # Move to trash with confirmation
            if not typer.confirm(
                f"\nMove {archived_count} messages to trash? (30-day recovery period)"
            ):
                ctx.info("Cancelled")
                return

            with out.progress_context("Moving messages to trash", total=None):
                gmail_client.trash_messages(list(archived_ids))
            ctx.success("Messages moved to trash")

    # Phase 7: Final report
    report_data = {
        "Messages Archived": archived_count,
        "Archive File": output,
        "Incremental Mode": "Yes" if incremental else "No",
    }

    if compress:
        report_data["Compression"] = compress

    if trash:
        report_data["Gmail Status"] = "Moved to trash (30-day recovery)"
    elif delete:
        report_data["Gmail Status"] = "Permanently deleted"

    ctx.show_report("Archive Summary", report_data)
    ctx.success("Archive completed successfully!")

    # Suggest next steps
    next_steps = [
        f"Validate archive: gmailarchiver validate {output}",
    ]

    if not trash and not delete:
        next_steps.append(f"Move to trash: gmailarchiver utilities retry-delete {output}")
        next_steps.append(
            f"Permanently delete: gmailarchiver utilities retry-delete {output} --permanent"
        )

    ctx.suggest_next_steps(next_steps)


@app.command()
@with_context(has_progress=True, operation_name="validate")
def validate(
    ctx: CommandContext,
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
    archive_path = Path(archive_file)
    if not archive_path.exists():
        ctx.fail_and_exit(
            title="File Not Found",
            message=f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
        )

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                f"Import the archive first: 'gmailarchiver import {archive_file}' "
                f"or specify database path with --state-db"
            ),
        )

    # Run validation with task sequence pattern
    expected_ids: set[str] = set()
    results: dict[str, Any] = {}

    with ctx.ui.task_sequence() as seq:
        # Task 1: Load database information
        with seq.task("Loading database information") as t:
            try:
                with ArchiveState(state_db) as state:
                    expected_ids = state.get_archived_message_ids_for_file(archive_file)
                t.complete(f"Found {len(expected_ids):,} messages")
            except Exception as e:
                t.fail("Database error", reason=str(e))
                ctx.fail_and_exit(
                    title="Database Error",
                    message=f"Failed to read database: {e}",
                    suggestion="Check database file permissions and integrity",
                )

        # Task 2: Run validation checks
        with seq.task("Running validation checks") as t:
            validator = ValidatorFacade(archive_file, state_db, output=ctx.output)
            results = validator.validate_comprehensive(expected_ids)

            if results["passed"]:
                t.complete("All checks passed")
            else:
                failed_checks = [
                    k.replace("_check", "").replace("_", " ")
                    for k, v in results.items()
                    if k.endswith("_check") and not v
                ]
                t.complete(f"Failed: {', '.join(failed_checks)}")

    # Show validation report using OutputManager method
    ctx.output.show_validation_report(results, title="Archive Validation")

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
            ctx.suggest_next_steps(suggestions)

        raise typer.Exit(1)

    ctx.success("All validation checks passed")


@utilities_app.command("retry-delete")
@with_context(operation_name="retry-delete")
def retry_delete_cmd(
    ctx: CommandContext,
    archive_file: str = typer.Argument(..., help="Archive file to delete messages from"),
    permanent: bool = typer.Option(False, "--permanent", help="Permanent deletion (vs trash)"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    credentials: str | None = typer.Option(
        None,
        "--credentials",
        help="Custom OAuth2 credentials file (optional, uses bundled by default)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Retry deletion for already-archived messages.

    Use this if archiving succeeded but deletion failed due to permission errors.
    This command retrieves message IDs from the database and attempts deletion again.

    IMPORTANT: You must re-authenticate with full Gmail permissions before using this.
    Run 'gmailarchiver auth-reset' first if you see permission errors.

    Examples:
        Trash messages (recoverable for 30 days):
        $ gmailarchiver utilities retry-delete archive_20251114.mbox

        Permanent deletion (IRREVERSIBLE):
        $ gmailarchiver utilities retry-delete archive_20251114.mbox --permanent
    """
    try:
        # 1. Get archived message IDs from database
        with ArchiveState(state_db) as state:
            message_ids = list(state.get_archived_message_ids_for_file(archive_file))

        if not message_ids:
            ctx.fail_and_exit(
                title="No Messages Found",
                message=f"No archived messages found for: {archive_file}",
                details=[
                    "Archive file name doesn't match database records",
                    "Wrong state database path",
                    f"Using state database: {state_db}",
                ],
                suggestion="Check the archive file name and state database path",
            )

        ctx.info(f"Found {len(message_ids)} archived messages")
        ctx.info(f"Archive: {archive_file}\n")

        # Authenticate and validate deletion permissions
        client = ctx.authenticate_gmail(
            credentials=credentials,
            validate_deletion_scope=True,
        )
        assert client is not None  # required=True ensures this

        # Create archiver (for deletion functionality)
        archiver = ArchiverFacade(client, state_db, output_manager=ctx.output)

        # 6. Delete messages with appropriate confirmation
        if permanent:
            ctx.warning("WARNING: PERMANENT DELETION")
            ctx.warning(
                f"This will permanently delete {len(message_ids)} messages. "
                "This action CANNOT be undone!"
            )
            ctx.info("Deleted messages will be gone forever - not in trash and not recoverable.\n")

            confirmation = typer.prompt(f"Type 'DELETE {len(message_ids)} MESSAGES' to confirm")
            if confirmation != f"DELETE {len(message_ids)} MESSAGES":
                ctx.info("Deletion cancelled")
                return

            # Perform permanent deletion
            archiver.delete_archived_messages(message_ids, permanent=True)

        else:
            # Trash deletion (default) - still ask for confirmation
            ctx.info(f"This will move {len(message_ids)} messages to trash.")
            ctx.info("(Messages can be recovered from trash for 30 days)\n")

            if not typer.confirm(f"Move {len(message_ids)} messages to trash?"):
                ctx.info("Cancelled")
                return

            # Move to trash
            archiver.delete_archived_messages(message_ids, permanent=False)

        ctx.success("Deletion completed successfully!")

    except Exception as e:
        ctx.fail_and_exit(
            title="Retry Delete Failed",
            message=str(e),
            suggestion="Check your network connection and authentication status",
        )


@app.command()
@with_context(operation_name="status")
def status(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show more detail"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Show archiving status and statistics.

    Displays database size, schema version, message counts, and recent archive runs.
    Use --verbose for more detail about each statistic.

    Examples:
        $ gmailarchiver status
        $ gmailarchiver status --verbose
        $ gmailarchiver status --json
    """
    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        ctx.warning("No archive database found")
        ctx.suggest_next_steps(
            [
                "Archive emails: gmailarchiver archive 3y",
                "Import existing archive: gmailarchiver import archive.mbox",
            ]
        )
        raise typer.Exit(0)

    # Detect schema version
    manager = MigrationManager(db_path)
    try:
        version = manager.detect_schema_version()
        db_size = db_path.stat().st_size

        with ArchiveState(state_db, validate_path=False) as state:
            # Overall stats
            total_archived = state.get_archived_count()

            # Recent runs - show more in verbose mode
            run_limit = 10 if verbose else 5
            recent_runs = state.get_archive_runs(limit=run_limit)

            # Get unique archive files from runs
            archive_files = set(
                run["archive_file"] for run in recent_runs if run.get("archive_file")
            )

            # Build report data - always show schema version and db size
            report_data: dict[str, str] = {
                "Schema Version": version,
                "Database Size": format_bytes(db_size),
                "Total Messages": f"{total_archived:,}",
                "Archive Files": str(len(archive_files)),
            }

            # Add verbose details (more detail about same info)
            if verbose and archive_files:
                sorted_files = sorted(archive_files)
                if sorted_files:
                    report_data["Archive Files"] = (
                        f"{len(archive_files)} (recent: {sorted_files[-1][:25]}...)"
                    )

            ctx.show_report("Archive Status", report_data)

            # Display recent runs table
            if recent_runs:
                # Include query column in verbose mode
                if verbose:
                    headers = ["Run ID", "Timestamp", "Query", "Messages", "Archive File"]
                    rows: list[list[str]] = []
                    for run in recent_runs:
                        rows.append(
                            [
                                str(run["run_id"]),
                                run["timestamp"][:19],
                                run["query"][:30] if run["query"] else "",
                                str(run["messages_archived"]),
                                run["archive_file"],
                            ]
                        )
                else:
                    headers = ["Run ID", "Timestamp", "Messages", "Archive File"]
                    rows = []
                    for run in recent_runs:
                        rows.append(
                            [
                                str(run["run_id"]),
                                run["timestamp"][:19],
                                str(run["messages_archived"]),
                                run["archive_file"],
                            ]
                        )

                table_title = f"Recent Archive Runs (Last {run_limit})"
                ctx.show_table(table_title, headers, rows)
            else:
                ctx.warning("No archive runs found")

    except Exception as e:
        ctx.fail_and_exit(
            title="Status Error",
            message=f"Error reading database: {e}",
            suggestion="Check database file integrity or run 'gmailarchiver doctor'",
        )
    finally:
        manager._close()


@app.command()
@with_context(operation_name="cleanup")
def cleanup(
    ctx: CommandContext,
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
    from gmailarchiver.data.db_manager import DBManager

    # Check if database exists
    db_path = Path(state_db)
    if not db_path.exists():
        ctx.warning("No archive database found")
        ctx.suggest_next_steps(
            [
                "Archive emails: gmailarchiver archive 3y",
            ]
        )
        raise typer.Exit(0)

    # Validate arguments
    if not list_sessions and not all_sessions and not session_id:
        ctx.error("Please specify --list, --all, or provide a session ID")
        ctx.suggest_next_steps(
            [
                "List sessions: gmailarchiver cleanup --list",
                "Clean all: gmailarchiver cleanup --all",
            ]
        )
        raise typer.Exit(1)

    try:
        db = DBManager(state_db, validate_schema=False, auto_create=False)
        db.ensure_sessions_table()

        # Get all partial sessions
        sessions = db.get_all_partial_sessions()

        if list_sessions:
            if not sessions:
                ctx.info("No partial archive sessions found")
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

            ctx.show_table("Partial Archive Sessions", headers, rows)
            ctx.info(f"Found {len(sessions)} partial session(s)")
            ctx.suggest_next_steps(
                [
                    "Clean specific: gmailarchiver cleanup <session-id>",
                    "Clean all: gmailarchiver cleanup --all",
                ]
            )
            raise typer.Exit(0)

        # Determine which sessions to clean
        sessions_to_clean: list[dict[str, Any]] = []

        if all_sessions:
            sessions_to_clean = sessions
            if not sessions_to_clean:
                ctx.info("No partial archive sessions to clean up")
                raise typer.Exit(0)
        elif session_id:
            # Find specific session (support partial UUID match)
            matching = [s for s in sessions if s["session_id"].startswith(session_id)]
            if not matching:
                ctx.error(f"Session not found: {session_id}")
                ctx.suggest_next_steps(["List sessions: gmailarchiver cleanup --list"])
                raise typer.Exit(1)
            if len(matching) > 1:
                ctx.error(f"Multiple sessions match '{session_id}'. Be more specific.")
                raise typer.Exit(1)
            sessions_to_clean = matching

        # Confirmation prompt
        if not force:
            ctx.warning(
                f"This will delete {len(sessions_to_clean)} partial session(s) "
                "and their associated data"
            )
            confirm = typer.confirm("Continue?")
            if not confirm:
                ctx.info("Cleanup cancelled")
                raise typer.Exit(0)

        # Perform cleanup
        cleaned_count = 0
        for session in sessions_to_clean:
            target_file = session["target_file"]
            partial_file = Path(target_file + ".partial")

            # Delete partial file if it exists
            if partial_file.exists():
                partial_file.unlink()
                ctx.info(f"Deleted partial file: {partial_file.name}")

            # Delete messages associated with the partial file
            deleted_msgs = db.delete_messages_for_file(str(partial_file))
            if deleted_msgs > 0:
                ctx.info(f"Removed {deleted_msgs} message records")

            # Delete session record
            db.delete_session(session["session_id"])
            ctx.success(f"Cleaned session: {session['session_id'][:12]}...")
            cleaned_count += 1

        db.close()

        ctx.success(f"Cleaned up {cleaned_count} partial session(s)")

    except typer.Exit:
        raise
    except Exception as e:
        ctx.error(f"Cleanup failed: {e}")
        raise typer.Exit(1)


@utilities_app.command()
@app.command(hidden=True)
@with_context(has_progress=True, operation_name="migrate")
def migrate(
    ctx: CommandContext,
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
    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check the database path or use --state-db to specify location",
        )

    # Use centralized SchemaManager for version detection
    schema_mgr = SchemaManager(db_path)
    current_version = schema_mgr.detect_version()
    manager: MigrationManager | None = None

    try:
        # Check if migration is needed
        if not schema_mgr.needs_migration():
            ctx.success(f"Database is already at version {current_version.value} (up to date)")
            return

        if current_version == SchemaVersion.NONE:
            ctx.fail_and_exit(
                title="Invalid Database",
                message="Database appears to be empty or invalid",
                suggestion="Create with 'gmailarchiver archive' or 'gmailarchiver import'",
            )

        if not schema_mgr.can_auto_migrate():
            ctx.fail_and_exit(
                title="Cannot Migrate",
                message=f"Cannot auto-migrate from version {current_version.value}",
                suggestion="Manual intervention required",
            )

        # Show migration info
        target_version = SchemaManager.CURRENT_VERSION
        ctx.info(f"Current schema version: {current_version.value}")
        ctx.info(f"\nMigration from v{current_version.value} to v{target_version.value} will:")
        ctx.info("  • Create backup of current database")
        ctx.info("  • Add enhanced schema with mbox offset tracking")
        ctx.info("  • Enable full-text search capabilities")
        ctx.info("  • Add multi-account support (future-ready)")
        ctx.info("  • Preserve all existing message data")

        # Confirm migration
        if not typer.confirm("\nProceed with migration?"):
            ctx.info("Migration cancelled")
            return

        # Create backup with progress
        manager = MigrationManager(db_path)
        with ctx.output.progress_context("Creating backup", total=3) as progress:
            task = progress.add_task("Migration", total=3) if progress else None

            backup_path = manager.create_backup()
            if progress and task:
                progress.update(task, advance=1, refresh=True)

            ctx.success(f"Backup created: {backup_path}")

            # Run migration using SchemaManager
            schema_mgr.auto_migrate_if_needed(progress_callback=lambda msg: ctx.info(msg))
            if progress and task:
                progress.update(task, advance=1, refresh=True)

            # Validate migration using SchemaManager
            schema_mgr.invalidate_cache()
            final_version = schema_mgr.detect_version()
            if final_version != SchemaManager.CURRENT_VERSION:
                raise RuntimeError(
                    f"Migration validation failed: expected {SchemaManager.CURRENT_VERSION.value}, "
                    f"got {final_version.value}"
                )
            if progress and task:
                progress.update(task, advance=1, refresh=True)

        # Build report data
        report_data = {
            "From Version": current_version.value,
            "To Version": target_version.value,
            "Backup Location": str(backup_path),
        }

        ctx.show_report("Migration Summary", report_data)
        ctx.success("Migration completed successfully!")

        ctx.suggest_next_steps(
            [
                "Verify integrity: gmailarchiver verify-integrity",
                "Search messages: gmailarchiver search <query>",
            ]
        )

    except Exception as e:
        ctx.fail_and_exit(
            title="Migration Failed",
            message=str(e),
            suggestion="Check database integrity or restore from backup",
        )
    finally:
        if manager is not None:
            manager._close()


@utilities_app.command()
@app.command(hidden=True)
@with_context(operation_name="rollback")
def rollback(
    ctx: CommandContext,
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
    db_path = Path(state_db)

    # If no backup file specified, list available backups
    if not backup_file:
        # Find backup files
        backup_pattern = f"{db_path.name}.backup.*"
        backups = sorted(db_path.parent.glob(backup_pattern), reverse=True)

        if not backups:
            ctx.fail_and_exit(
                title="No Backups Found",
                message="No backup files found",
                suggestion=f"Looking for pattern: {backup_pattern}",
            )

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

        ctx.show_table("Available backup files", headers, rows)
        ctx.info("Use --backup-file to specify which backup to restore")
        return

    # Rollback to specified backup
    backup_path = Path(backup_file)

    if not backup_path.exists():
        ctx.fail_and_exit(
            title="Backup Not Found",
            message=f"Backup file not found: {backup_file}",
            suggestion="Check the backup path and try again",
        )

    ctx.info(f"Backup file: {backup_file}")
    ctx.info(f"Target database: {state_db}\n")

    ctx.warning(
        "WARNING: This will replace the current database with the backup. "
        "Any changes made after the backup was created will be lost."
    )

    # Confirm rollback
    if not typer.confirm("Proceed with rollback?"):
        ctx.info("Rollback cancelled")
        return

    try:
        manager = MigrationManager(db_path)
        manager.rollback_migration(backup_path)

        ctx.success("Rollback completed successfully!")

    except Exception as e:
        ctx.fail_and_exit(
            title="Rollback Failed",
            message=str(e),
            suggestion="Check backup file integrity and try again",
        )


@utilities_app.command()
@app.command(hidden=True)
@with_context(requires_db=True, operation_name="dedupe")
def dedupe(
    ctx: CommandContext,
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
    db_path = Path(state_db)

    # Validate strategy
    valid_strategies = ["newest", "largest", "first"]
    if strategy not in valid_strategies:
        ctx.fail_and_exit(
            "Invalid Strategy",
            f"Invalid strategy: {strategy}",
            suggestion=f"Must be one of: {', '.join(valid_strategies)}",
        )

    try:
        # Initialize deduplicator (validates v1.1 schema)
        with DeduplicatorFacade(str(db_path)) as dedup:
            with ctx.ui.task_sequence() as seq:
                # Task 1: Find duplicates
                with seq.task("Finding duplicates") as t:
                    duplicates = dedup.find_duplicates()
                    if not duplicates:
                        t.complete("No duplicates found")
                        ctx.success("No duplicate messages found!")
                        return
                    t.complete(f"Found {len(duplicates):,} duplicate message IDs")

                # Task 2: Analyze duplicates
                with seq.task("Analyzing duplicates") as t:
                    report = dedup.generate_report(duplicates)
                    t.complete(
                        f"{report.messages_to_remove:,} messages to remove, "
                        f"{format_bytes(report.space_recoverable)} recoverable"
                    )

                report_data = {
                    "Strategy": strategy,
                    "Duplicate Message-IDs": report.duplicate_message_ids,
                    "Messages to Remove": report.messages_to_remove,
                    "Space to Save": format_bytes(report.space_recoverable),
                }

                if dry_run:
                    ctx.warning("DRY RUN - No changes will be made")

                    # Task 3: Preview deduplication (dry run)
                    with seq.task("Previewing deduplication") as t:
                        result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=True)
                        t.complete(
                            f"Would remove {result.messages_removed:,} messages, "
                            f"keep {result.messages_kept:,} messages"
                        )

                    report_data["Would Remove"] = f"{result.messages_removed:,} messages"
                    report_data["Would Keep"] = f"{result.messages_kept:,} messages"
                    report_data["Would Save"] = format_bytes(result.space_saved)

                    ctx.show_report("Deduplication Preview (Dry Run)", report_data)

                    ctx.suggest_next_steps(
                        [
                            (
                                f"Apply changes: gmailarchiver dedupe "
                                f"--strategy {strategy} --no-dry-run"
                            ),
                        ]
                    )

                else:
                    # Confirm before proceeding
                    ctx.warning(
                        "⚠ WARNING: This will permanently remove duplicate messages "
                        "from the database"
                    )
                    ctx.info("The mbox files themselves will not be modified.")

                    if not typer.confirm(
                        f"Remove {report.messages_to_remove:,} duplicate messages "
                        f"using '{strategy}' strategy?"
                    ):
                        ctx.info("Cancelled")
                        return

                    # Task 3: Perform deduplication
                    with seq.task("Removing duplicates") as t:
                        result = dedup.deduplicate(duplicates, strategy=strategy, dry_run=False)
                        t.complete(
                            f"Removed {result.messages_removed:,} messages, "
                            f"kept {result.messages_kept:,} messages"
                        )

                    report_data["Removed"] = f"{result.messages_removed:,} messages"
                    report_data["Kept"] = f"{result.messages_kept:,} messages"
                    report_data["Space Saved"] = format_bytes(result.space_saved)

                    ctx.show_report("Deduplication Results", report_data)
                    ctx.success("Deduplication completed!")

                    ctx.suggest_next_steps(
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
                        from gmailarchiver.data.db_manager import DBManager

                        ctx.info("\nRunning verification...")

                        with seq.task("Verifying database integrity") as t:
                            try:
                                db = DBManager(str(db_path), validate_schema=False)
                                issues = db.verify_database_integrity()
                                db.close()

                                if not issues:
                                    t.complete("No issues found")
                                else:
                                    t.complete(f"Found {len(issues)} issue(s)")
                                    ctx.warning(f"Verification found {len(issues)} issue(s):")
                                    for issue in issues[:5]:  # Show first 5 issues
                                        ctx.info(f"  • {issue}")
                                    if len(issues) > 5:
                                        ctx.info(f"  ... and {len(issues) - 5} more issues")

                                    ctx.suggest_next_steps(
                                        [
                                            (
                                                "Fix issues automatically: "
                                                "gmailarchiver check --auto-repair"
                                            ),
                                            (
                                                "View all issues: "
                                                "gmailarchiver verify-integrity --verbose"
                                            ),
                                        ]
                                    )
                            except Exception as e:
                                t.fail("Verification failed", reason=str(e))
                                ctx.warning(f"Verification failed: {e}")

    except ValueError as e:
        ctx.fail_and_exit(
            "Schema Error",
            str(e),
            suggestion="Run 'gmailarchiver migrate' to upgrade your database",
        )
    except Exception as e:
        ctx.fail_and_exit(
            "Deduplication Failed",
            str(e),
            suggestion="Check database integrity and try again",
        )


@utilities_app.command(name="verify-offsets")
@app.command(name="verify-offsets", hidden=True)
@with_context(requires_db=True, operation_name="verify-offsets")
def verify_offsets_cmd(
    ctx: CommandContext,
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
    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        ctx.fail_and_exit(
            "File Not Found",
            f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
        )

    # Create validator and run verification
    # Note: Using legacy ValidatorFacade as verify_offsets is not yet in facade
    try:
        from .core.validator import ValidatorFacade

        validator = ValidatorFacade(archive_file, state_db, output=ctx.output)
        result = None

        with ctx.ui.task_sequence() as seq:
            with seq.task("Verifying offsets") as t:
                result = validator.verify_offsets()

                if result.skipped:
                    t.complete("Skipped (v1.0 schema)")
                elif result.accuracy_percentage == 100.0:
                    t.complete(f"All {result.total_checked} offsets verified")
                else:
                    t.complete(f"Found {result.failed_reads} issue(s)")

        # Handle skipped (v1.0 schema)
        if result.skipped:
            ctx.warning("Offset verification skipped (v1.0 schema)")
            ctx.suggest_next_steps(
                [
                    "Upgrade to v1.1: gmailarchiver migrate",
                ]
            )
            return

        # Build report data
        report_data = {
            "Total Offsets Checked": result.total_checked,
            "Successful Reads": result.successful_reads,
            "Failed Reads": result.failed_reads,
            "Accuracy": f"{result.accuracy_percentage:.1f}%",
        }

        ctx.show_report("Offset Verification Results", report_data)

        # Success case
        if result.accuracy_percentage == 100.0:
            ctx.success(f"All {result.total_checked} offsets verified successfully")
            return

        # Failure case - show details
        if result.failures:
            ctx.warning(f"Found {len(result.failures)} offset verification failure(s):")
            for failure in result.failures[:10]:  # Limit to first 10
                ctx.info(f"  • {failure}")

            if len(result.failures) > 10:
                ctx.info(f"  ... and {len(result.failures) - 10} more failures")

        # Suggest next steps
        ctx.suggest_next_steps(
            [
                "Repair offsets: gmailarchiver repair --backfill --no-dry-run",
                "Check database integrity: gmailarchiver verify-integrity",
            ]
        )

        raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            "Verification Failed",
            f"Offset verification failed: {e}",
            suggestion="Check database and archive file integrity",
        )


@utilities_app.command(name="verify-consistency")
@app.command(name="verify-consistency", hidden=True)
@with_context(requires_db=True, operation_name="verify-consistency")
def verify_consistency_cmd(
    ctx: CommandContext,
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
    # Check files exist
    archive_path = Path(archive_file)
    if not archive_path.exists():
        ctx.fail_and_exit(
            "File Not Found",
            f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
        )

    # Create validator and run consistency check
    # Note: Using legacy ValidatorFacade as verify_consistency is not yet in facade
    try:
        from .core.validator import ValidatorFacade

        validator = ValidatorFacade(archive_file, state_db, output=ctx.output)

        with ctx.ui.task_sequence() as seq:
            with seq.task("Running consistency checks") as t:
                report = validator.verify_consistency()

                if report.passed:
                    t.complete("All checks passed")
                else:
                    total_issues = (
                        report.orphaned_records
                        + report.missing_records
                        + report.duplicate_gmail_ids
                    )
                    t.complete(f"Found {total_issues} issue(s)")

        # Build report data
        report_data = {
            "Schema Version": report.schema_version,
            "Orphaned Records": report.orphaned_records,
            "Missing Records": report.missing_records,
            "Duplicate Gmail IDs": report.duplicate_gmail_ids,
        }

        # Use SchemaManager to check capabilities instead of hardcoded version strings
        schema_mgr = SchemaManager(state_db)
        if schema_mgr.has_capability(SchemaCapability.FTS_SEARCH):
            report_data["Duplicate RFC Message-IDs"] = report.duplicate_rfc_message_ids
            report_data["FTS Synchronized"] = "Yes" if report.fts_synced else "No"

        ctx.show_report("Consistency Check Results", report_data)

        # Show errors if any
        if report.errors:
            ctx.warning(f"Found {len(report.errors)} issue(s):")
            for error in report.errors:
                ctx.info(f"  • {error}")

        # Overall status
        if report.passed:
            ctx.success("All consistency checks passed")
            return

        # Suggest next steps
        ctx.suggest_next_steps(
            [
                "Repair database: gmailarchiver repair --no-dry-run",
                "Check integrity: gmailarchiver verify-integrity --verbose",
            ]
        )

        raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            "Consistency Check Failed",
            str(e),
            suggestion="Check database and archive file integrity",
        )


@app.command()
@with_context(requires_db=True, requires_schema="1.1", operation_name="search")
def search(
    ctx: CommandContext,
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

    # Validate flags
    if extract and not output_dir:
        ctx.fail_and_exit(
            "Missing Output Directory",
            "--extract requires --output-dir",
            suggestion="Specify output directory: --output-dir /path/to/directory",
        )

    # Interactive mode is mutually exclusive with some flags
    if interactive and json_output:
        ctx.fail_and_exit(
            "Invalid Option Combination",
            "--interactive cannot be used with --json",
            suggestion="Remove --json flag for interactive mode",
        )

    if interactive and extract:
        ctx.fail_and_exit(
            "Invalid Option Combination",
            "--interactive cannot be used with --extract",
            suggestion="Use --interactive alone (extraction is part of interactive mode)",
        )

    # Validate dates if provided
    if after:
        try:
            datetime.strptime(after, "%Y-%m-%d")
        except ValueError:
            ctx.fail_and_exit(
                "Invalid Date Format",
                f"Invalid date format: {after}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
            )

    if before:
        try:
            datetime.strptime(before, "%Y-%m-%d")
        except ValueError:
            ctx.fail_and_exit(
                "Invalid Date Format",
                f"Invalid date format: {before}",
                suggestion="Use YYYY-MM-DD format (e.g., 2024-01-15)",
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
            ctx.fail_and_exit(
                "Missing Query",
                "No search query or filters provided",
                suggestion="Provide a query argument or use filters like --from, --subject",
            )

        query = " ".join(query_parts)

    # Execute search
    try:
        from gmailarchiver.cli._output_search import (
            display_search_results_json,
            display_search_results_rich,
        )
        from gmailarchiver.cli.output import SearchResultEntry

        start_time = time.perf_counter()

        with SearchFacade(state_db) as search:
            results = search.search(query, limit=limit)

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
            display_search_results_json(ctx.output, result_entries, with_preview=with_preview)
        else:
            display_search_results_rich(
                ctx.output,
                result_entries,
                results.total_results,
                with_preview=with_preview,
            )
            if results.total_results == 0:
                ctx.suggest_next_steps(
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
                ctx.show_report("Search Summary", report_data)

        # Interactive mode: allow user to select messages for extraction
        if interactive and not json_output:
            # If there are no search results, skip interactive UI entirely
            if results.total_results == 0:
                ctx.info("No search results found; nothing to select in interactive mode.")
                return

            try:
                import questionary
            except ImportError:
                ctx.fail_and_exit(
                    "Missing Dependency",
                    "Interactive mode requires the 'questionary' package",
                    suggestion="Install with: pip install questionary",
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
            ctx.info("")
            selected_ids = questionary.checkbox(
                "Select messages to extract (space to select, enter to confirm):",
                choices=choices,
            ).ask()

            # Handle cancellation or no selection
            if not selected_ids:
                ctx.info("No messages selected. Cancelled.")
                return

            # Prompt for output directory
            default_output_dir = "./extracted"
            output_dir_str = questionary.path(
                "Output directory for extracted messages:",
                default=default_output_dir,
                only_directories=True,
            ).ask()

            if not output_dir_str:
                ctx.info("No output directory specified. Cancelled.")
                return

            # Extract selected messages
            ctx.info(f"\nExtracting {len(selected_ids)} selected messages to {output_dir_str}...")

            with MessageExtractor(state_db) as extractor:
                with ctx.output.progress_context(
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
            ctx.show_report("Extraction Summary", extraction_report)

            if stats["errors"]:
                ctx.warning(f"Encountered {len(stats['errors'])} error(s):")
                for error in stats["errors"][:5]:  # Show first 5 errors
                    ctx.info(f"  • {error}")
                if len(stats["errors"]) > 5:
                    ctx.info(f"  ... and {len(stats['errors']) - 5} more")

            return

        # Extract messages if requested
        if extract:
            assert output_dir is not None, "Output directory required for extraction"
            ctx.info(f"\nExtracting {results.total_results} messages to {output_dir}...")

            gmail_ids = [r.gmail_id for r in results.results]

            with MessageExtractor(state_db) as extractor:
                with ctx.output.progress_context(
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
            ctx.show_report("Extraction Summary", extraction_report)

            if stats["errors"]:
                ctx.warning(f"Encountered {len(stats['errors'])} error(s):")
                for error in stats["errors"][:5]:  # Show first 5 errors
                    ctx.info(f"  • {error}")
                if len(stats["errors"]) > 5:
                    ctx.info(f"  ... and {len(stats['errors']) - 5} more")

    except ValueError as e:
        ctx.fail_and_exit(
            "Search Query Error",
            str(e),
            suggestion="Check your search query syntax",
        )
    except Exception as e:
        ctx.fail_and_exit(
            "Search Failed",
            str(e),
        )


@app.command()
@with_context(requires_db=True, operation_name="extract")
def extract(
    ctx: CommandContext,
    message_id: str = typer.Argument(..., help="Gmail ID or RFC Message-ID to extract"),
    output_file: str | None = typer.Option(
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
    from gmailarchiver.core.extractor._extractor import ExtractorError

    try:
        with MessageExtractor(state_db) as extractor:
            # Try extracting by gmail_id first, then by rfc_message_id
            try:
                message_bytes = extractor.extract_by_gmail_id(message_id, output_file)
            except ExtractorError:
                # Not found by gmail_id, try rfc_message_id
                try:
                    message_bytes = extractor.extract_by_rfc_message_id(message_id, output_file)
                except ExtractorError:
                    ctx.fail_and_exit(
                        "Message Not Found",
                        f"Message not found: {message_id}",
                        suggestion="Verify the message ID or search with: gmailarchiver search",
                    )

        # Show success
        if output_file:
            ctx.success(f"Message extracted to {output_file}")
            ctx.show_report(
                "Extraction Summary",
                {
                    "Message ID": message_id,
                    "Output File": output_file,
                    "Size": format_bytes(len(message_bytes)),
                },
            )
        else:
            # Message already written to stdout, just show summary in JSON mode
            if json_output:
                ctx.info(f"Extracted {len(message_bytes)} bytes")

    except typer.Exit:
        raise
    except ExtractorError as e:
        ctx.fail_and_exit("Extraction Failed", str(e))
    except Exception as e:
        ctx.fail_and_exit("Unexpected Error", str(e))


@app.command(name="import")
@with_context(has_progress=True, operation_name="import")
def import_cmd(
    ctx: CommandContext,
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

    db_path = Path(state_db)

    # Handle database schema using centralized SchemaManager
    if db_path.exists():
        schema_mgr = SchemaManager(db_path)
        version = schema_mgr.detect_version()

        if version == SchemaVersion.NONE:
            # Empty database file exists - delete it and let DBManager create a fresh one
            ctx.warning("Found empty database file, recreating...")
            try:
                db_path.unlink()
            except Exception as e:
                ctx.fail_and_exit(
                    "Database Error",
                    f"Failed to delete empty database: {e}",
                    suggestion="Check file permissions and try again",
                )
        elif not schema_mgr.is_supported():
            ctx.fail_and_exit(
                "Unsupported Database",
                f"Unsupported database schema version: {version.value}",
                suggestion="Delete the database or use --state-db with a different path",
            )
        elif schema_mgr.needs_migration():
            # Auto-migrate to current version
            ctx.warning(
                f"Detected v{version.value} database, "
                f"auto-migrating to v{SchemaManager.CURRENT_VERSION.value}..."
            )
            try:
                schema_mgr.auto_migrate_if_needed(progress_callback=lambda msg: ctx.info(msg))
                ctx.success("Migration completed successfully")
            except Exception as e:
                ctx.fail_and_exit(
                    "Migration Failed",
                    f"Failed to migrate database: {e}",
                    suggestion="Run 'gmailarchiver migrate' manually for more details",
                )
    # If database doesn't exist, DBManager will auto-create it with current schema

    # Expand glob pattern
    files = glob.glob(archive_pattern)
    if not files:
        ctx.fail_and_exit(
            "No Files Found",
            f"No files match pattern: {archive_pattern}",
            suggestion="Check the file path or glob pattern",
        )

    ctx.info(f"Found {len(files)} file(s) to import")

    # Set up Gmail client for Gmail ID lookup (unless skipped)
    gmail_client = None
    if not skip_gmail_lookup:
        gmail_client = ctx.authenticate_gmail(credentials=credentials, required=False)
        if gmail_client is None:
            ctx.warning("Continuing without Gmail ID lookup (messages will have NULL gmail_id)")

    # Import each file with progress
    importer = ImporterFacade(state_db, gmail_client=gmail_client)
    results: list[Any] = []
    start_time = time.perf_counter()

    # Use fluent UI builder for task sequence
    total_messages = 0
    file_message_counts: list[int] = []
    messages_processed = 0

    with ctx.ui.task_sequence() as seq:
        # Task 1: Count messages across all files
        with seq.task("Counting messages") as count_task:
            for file_path in files:
                count = importer.count_messages(file_path)
                file_message_counts.append(count)
                total_messages += count
            count_task.complete(f"Found {total_messages:,} messages")

        # Task 2: Import messages with progress tracking
        with seq.task("Importing messages", total=total_messages) as import_task:
            current_task_pos = 0
            last_reported = 0

            for file_idx, file_path in enumerate(files):

                def make_progress_callback(
                    base_pos: int,
                    task: Any,
                ) -> Callable[[int, int, str], None]:
                    def callback(current: int, total: int, status: str) -> None:
                        nonlocal messages_processed, last_reported
                        messages_processed = base_pos + current
                        # Advance progress by the delta since last report
                        delta = messages_processed - last_reported
                        if delta > 0:
                            task.advance(delta)
                            last_reported = messages_processed

                    return callback

                try:
                    result = importer.import_archive(
                        file_path,
                        account_id=account_id,
                        skip_duplicates=skip_duplicates,
                        progress_callback=make_progress_callback(current_task_pos, import_task),
                    )
                    results.append(result)
                    current_task_pos += file_message_counts[file_idx]
                except Exception as e:
                    import_task.log(f"Error importing {file_path}: {e}", "ERROR")
                    current_task_pos += file_message_counts[file_idx]

            import_task.complete(f"Imported {messages_processed:,} messages")

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
    ctx.show_report("Import Summary", report_data)

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

        ctx.show_report("Per-File Import Summary", per_file_report)

    # Show detailed error messages if there were failures
    if total_failed > 0:
        ctx.warning(f"Found {total_failed} import error(s):")
        for result in results:
            if result.errors:
                ctx.info(f"\n{Path(result.archive_file).name}:")
                for error in result.errors[:10]:  # Limit to first 10 errors per file
                    ctx.info(f"  • {error}")
                if len(result.errors) > 10:
                    ctx.info(f"  ... and {len(result.errors) - 10} more errors")

        ctx.suggest_next_steps(
            [
                "Check database integrity: gmailarchiver verify-integrity",
                "Review error messages above for details",
            ]
        )

    if total_imported > 0:
        ctx.suggest_next_steps(
            [
                "Search imported messages: gmailarchiver search <query>",
                "Verify database: gmailarchiver verify-integrity",
            ]
        )

    # Auto-verify if requested
    if auto_verify and total_failed == 0:
        from gmailarchiver.data.db_manager import DBManager

        ctx.info("\nRunning verification...")
        try:
            db = DBManager(str(db_path), validate_schema=False)
            issues = db.verify_database_integrity()
            db.close()

            if not issues:
                ctx.success("Verification complete - no issues found")
            else:
                ctx.warning(f"Verification found {len(issues)} issue(s):")
                for issue in issues[:5]:  # Show first 5 issues
                    ctx.info(f"  • {issue}")
                if len(issues) > 5:
                    ctx.info(f"  ... and {len(issues) - 5} more issues")

                ctx.suggest_next_steps(
                    [
                        "Fix issues automatically: gmailarchiver check --auto-repair",
                        "View all issues: gmailarchiver verify-integrity --verbose",
                    ]
                )
        except Exception as e:
            ctx.warning(f"Verification failed: {e}")


@app.command()
@with_context(has_progress=True, operation_name="consolidate")
def consolidate(
    ctx: CommandContext,
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

    # ArchiveConsolidator and ValidatorFacade are imported at module level

    # 1. Expand glob patterns
    all_files = []
    for pattern in archives:
        matches = glob.glob(pattern)
        if not matches:
            # Try as literal file path
            if Path(pattern).exists():
                all_files.append(pattern)
            else:
                ctx.warning(f"No files match pattern: {pattern}")
        else:
            all_files.extend(matches)

    if not all_files:
        ctx.fail_and_exit(
            "No Archives Found",
            "No archive files found matching the specified patterns",
            suggestion="Check file paths or glob patterns",
        )

    ctx.info(f"Found {len(all_files)} archive(s) to consolidate")

    # 2. Validate dedupe strategy
    valid_strategies = ["newest", "largest", "first"]
    if dedupe_strategy not in valid_strategies:
        ctx.fail_and_exit(
            "Invalid Dedupe Strategy",
            f"'{dedupe_strategy}' is not a valid dedupe strategy",
            suggestion=f"Valid strategies: {', '.join(valid_strategies)}",
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
            ctx.info("Consolidation cancelled")
            raise typer.Exit(0)

    # 5. Consolidate with progress
    consolidator = ArchiveConsolidator(state_db)

    try:
        with ctx.ui.task_sequence() as seq:
            # Task 1: Consolidate archives
            with seq.task("Consolidating archives") as t:
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
                t.complete(
                    f"Consolidated {result.messages_consolidated:,} messages from "
                    f"{len(result.source_files)} archive(s)"
                )

            # Task 2: Auto-verify if requested (within task_sequence)
            if auto_verify:
                from gmailarchiver.data.db_manager import DBManager

                with seq.task("Verifying database integrity") as t:
                    try:
                        db = DBManager(str(state_db), validate_schema=False)
                        issues = db.verify_database_integrity()
                        db.close()

                        if not issues:
                            t.complete("No issues found")
                        else:
                            t.complete(f"Found {len(issues)} issue(s)")
                            ctx.warning(f"Verification found {len(issues)} issue(s):")
                            for issue in issues[:5]:
                                ctx.info(f"  • {issue}")
                            if len(issues) > 5:
                                ctx.info(f"  ... and {len(issues) - 5} more issues")

                            ctx.suggest_next_steps(
                                [
                                    ("Fix issues automatically: gmailarchiver check --auto-repair"),
                                    ("View all issues: gmailarchiver verify-integrity --verbose"),
                                ]
                            )
                    except Exception as e:  # pragma: no cover - defensive
                        t.fail("Verification failed", reason=str(e))
                        ctx.warning(f"Verification failed: {e}")

            # Task 3: Validate consolidated archive before removing sources
            cleanup_data: dict[str, Any] | None = None
            if remove_sources:
                try:
                    with seq.task("Validating consolidated archive") as t:
                        output_path = Path(result.output_file)
                        if not output_path.exists():
                            t.fail("Archive does not exist")
                            ctx.error(
                                "Consolidated archive does not exist - source files NOT removed"
                            )
                            raise typer.Exit(1)

                        try:
                            # Verify we can read the output file (basic safety check)
                            output_size = output_path.stat().st_size
                            if output_size == 0:
                                t.fail("Archive is empty")
                                ctx.warning(
                                    "Consolidated archive appears to be empty "
                                    "- skipping source file removal"
                                )
                                raise typer.Exit(1)
                        except typer.Exit:
                            raise
                        except OSError as e:
                            t.fail("Cannot access archive", reason=str(e))
                            ctx.warning(f"Cannot access consolidated archive: {e}")
                            ctx.info("Skipping source file removal due to access issues")
                            raise typer.Exit(1)

                        try:
                            # Use ValidatorFacade to verify archive can be read
                            validator = ValidatorFacade(str(output_path))
                            # Simple check: verify archive is readable and has content
                            is_valid = validator.validate_all()
                            if not is_valid:
                                # Try to get error details
                                errors = validator.errors
                                error_msg = errors[0] if errors else "Unknown error"
                                t.fail("Validation failed", reason=error_msg)
                                ctx.warning(f"Archive validation failed: {error_msg}")
                                ctx.info(
                                    "Please review the consolidated archive "
                                    "before manually removing sources"
                                )
                                raise typer.Exit(1)
                            t.complete(f"Archive valid ({format_bytes(output_size)})")
                        except typer.Exit:
                            raise
                        except Exception as e:
                            t.fail("Validation error", reason=str(e))
                            ctx.warning(f"Archive readability check failed: {e}")
                            ctx.info("Skipping source file removal due to verification issues")
                            raise typer.Exit(1)

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
                        ctx.info("No source files to remove (output file is the only file)")
                    else:
                        # Determine if we should proceed with removal
                        # Auto-confirm if --yes or --json is provided
                        should_remove = yes or json_output

                        if not should_remove:
                            # Show confirmation prompt
                            ctx.info(
                                f"\nThe following {len(files_to_remove)} "
                                f"source file(s) will be removed:"
                            )
                            for file_path in files_to_remove:
                                ctx.info(f"  • {file_path}")
                            ctx.info(f"\nTotal space to be freed: {format_bytes(total_size)}")

                            should_remove = typer.confirm("\nRemove source files?")
                            if not should_remove:
                                ctx.info("Source file removal cancelled - files kept")

                        if should_remove:
                            # Task 4: Remove source files
                            with seq.task("Removing source files", total=len(files_to_remove)) as t:
                                removed_count = 0
                                freed_space = 0
                                failed_removals = []

                                for file_path in files_to_remove:
                                    try:
                                        file_size = file_path.stat().st_size
                                        file_path.unlink()
                                        removed_count += 1
                                        freed_space += file_size
                                        t.advance()
                                    except FileNotFoundError:
                                        # File already deleted - that's OK
                                        t.advance()
                                    except PermissionError as e:
                                        failed_removals.append(f"{file_path}: {e}")
                                        t.advance()
                                    except Exception as e:
                                        failed_removals.append(f"{file_path}: {e}")
                                        t.advance()

                                # Complete task
                                if removed_count > 0:
                                    t.complete(
                                        f"Removed {removed_count} file(s), "
                                        f"freed {format_bytes(freed_space)}"
                                    )
                                else:
                                    t.fail("No files removed")

                                # Record cleanup data for JSON top-level summary
                                cleanup_data = {
                                    "removed_files": removed_count,
                                    "space_freed_bytes": freed_space,
                                    "failed_removals": len(failed_removals),
                                }

                                # Add cleanup data to JSON events for scripting
                                if json_output:
                                    ctx.output._json_events.append(
                                        {
                                            "event": "cleanup",
                                            **cleanup_data,
                                        }
                                    )

                            if failed_removals:
                                ctx.warning(f"Failed to remove {len(failed_removals)} file(s):")
                                for failure in failed_removals[:3]:
                                    ctx.info(f"  • {failure}")
                                if len(failed_removals) > 3:
                                    ctx.info(f"  ... and {len(failed_removals) - 3} more")

                except typer.Exit:
                    raise
                except Exception as e:
                    ctx.warning(f"Source file cleanup failed: {e}")
                    ctx.info("Consolidation succeeded but source files were NOT removed")

        # 6. Build report data (after task_sequence)
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

        ctx.show_report("Consolidation Summary", report_data)
        ctx.success(f"Consolidation complete! Output: {result.output_file}")

        ctx.suggest_next_steps(
            [
                "Verify consolidated archive: gmailarchiver validate " + result.output_file,
                "Search messages: gmailarchiver search <query>",
            ]
        )

        # If in JSON mode and we have cleanup data, attach it to the top-level payload
        if json_output and cleanup_data is not None:
            # Merge status with cleanup summary for top-level convenience
            output_payload = {
                "status": "ok",
                "success": True,
                **cleanup_data,
            }
            ctx.output.set_json_payload(output_payload)

    except typer.Exit:
        raise
    except ValueError as e:
        ctx.fail_and_exit("Validation Error", str(e))
    except FileNotFoundError as e:
        ctx.fail_and_exit("File Not Found", str(e))
    except Exception as e:
        ctx.fail_and_exit(
            "Consolidation Failed",
            str(e),
            suggestion="Check archive files and try again",
        )


@utilities_app.command(name="verify-integrity")
@app.command(name="verify-integrity", hidden=True)
@with_context(requires_db=True, has_progress=True, operation_name="verify-integrity")
def verify_integrity_cmd(
    ctx: CommandContext,
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
    assert ctx.db is not None, "Database should be initialized by @with_context"

    issues: list[str] = []

    try:
        with ctx.ui.task_sequence() as seq:
            # Task: Run integrity checks
            with seq.task("Running integrity checks") as t:
                issues = ctx.db.verify_database_integrity()

                if not issues:
                    t.complete("No issues found")
                else:
                    t.complete(f"Found {len(issues)} issue(s)")

    except typer.Exit:
        raise
    except FileNotFoundError as e:
        ctx.fail_and_exit("File Not Found", str(e))
    except Exception as e:
        ctx.fail_and_exit(
            "Integrity Check Failed",
            str(e),
            suggestion="Check that the database file is not corrupted",
        )

    if not issues:
        ctx.success("Database integrity verified - no issues found")
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

    ctx.show_report("Database Integrity Results", report_data)

    # Show all issues as warnings
    if not verbose:
        ctx.warning(f"Found {len(issues)} integrity issue(s):")
        for issue in issues:
            ctx.info(f"  • {issue}")

    # Suggest next steps
    ctx.suggest_next_steps(
        [
            "Fix issues: gmailarchiver repair --no-dry-run",
            "Review issues in detail: gmailarchiver verify-integrity --verbose",
        ]
    )

    raise typer.Exit(1)


@utilities_app.command()
@app.command(hidden=True)
@with_context(requires_db=True, has_progress=True, operation_name="repair")
def repair(
    ctx: CommandContext,
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
    assert ctx.db is not None, "Database should be initialized by @with_context"

    from gmailarchiver.data.migration import MigrationManager

    db_path = Path(state_db)

    # Get confirmation for non-dry-run
    if not dry_run:
        ctx.warning("⚠ WARNING: This will modify the database")
        confirm = typer.confirm("Continue with database repair?", default=False)
        if not confirm:
            ctx.info("Repair cancelled")
            raise typer.Exit(0)

    try:
        with ctx.output.progress_context("Running repair operations", total=2) as progress:
            # Phase 1: Fix FTS sync issues
            task = progress.add_task("Phase 1: FTS synchronization", total=2) if progress else None
            ctx.info("Phase 1: Checking FTS synchronization...")
            repairs = ctx.db.repair_database(dry_run=dry_run)
            if progress and task:
                progress.update(task, completed=1)

            # Phase 2: Backfill invalid offsets if requested
            if backfill:
                ctx.info("Phase 2: Checking for invalid offsets...")
                invalid_msgs = ctx.db.get_messages_with_invalid_offsets()

                if invalid_msgs:
                    ctx.info(f"Found {len(invalid_msgs)} messages with invalid offsets")

                    if not dry_run:
                        # Use MigrationManager logic to scan mbox and backfill
                        migrator = MigrationManager(db_path)
                        backfilled = migrator.backfill_offsets_from_mbox(invalid_msgs)
                        repairs["invalid_offsets_fixed"] = backfilled
                        migrator._close()
                    else:
                        repairs["invalid_offsets_would_fix"] = len(invalid_msgs)
                else:
                    ctx.success("No invalid offsets found")

            if progress and task:
                progress.update(task, completed=2)

        # Display results
        _display_repair_results(ctx.output, repairs, dry_run)

    except typer.Exit:
        raise
    except FileNotFoundError as e:
        ctx.fail_and_exit("File Not Found", str(e))
    except Exception as e:
        ctx.fail_and_exit(
            "Repair Failed",
            str(e),
            suggestion="Check the database file and try again",
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
@with_context(has_progress=True, operation_name="check")
def check(
    ctx: CommandContext,
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
    Run internal database health checks.

    Performs comprehensive INTERNAL database validation:
    - Database integrity (orphaned/missing FTS records, invalid offsets, duplicates)
    - Database consistency (database ↔ mbox synchronization)
    - Offset accuracy (v1.1 schema only)
    - FTS index synchronization

    This command focuses on internal data health. For external environment
    checks (Python version, OAuth tokens, disk space), use 'gmailarchiver doctor'.

    With --auto-repair, automatically fixes issues and re-checks.

    Examples:
        $ gmailarchiver check
        $ gmailarchiver check --auto-repair
        $ gmailarchiver check --verbose
        $ gmailarchiver check --json
    """
    from gmailarchiver.data.db_manager import DBManager

    db_path = Path(state_db)

    # Check if database exists
    if not db_path.exists():
        ctx.fail_and_exit(
            "Database Not Found",
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create one, or use --state-db",
        )

    # Use centralized SchemaManager for version detection
    schema_mgr = SchemaManager(db_path)
    schema_version = schema_mgr.detect_version()

    if schema_version == SchemaVersion.NONE:
        ctx.fail_and_exit(
            "Invalid Database",
            "Database is empty or invalid",
            suggestion="Create with 'gmailarchiver archive' or 'gmailarchiver import'",
        )

    # Initialize results dictionary
    check_results: dict[str, Any] = {
        "database_integrity": {"passed": False, "issues": []},
        "database_consistency": {"passed": False, "checked": False, "report": None},
        "offset_accuracy": {"passed": False, "checked": False, "result": None},
        "fts_synchronization": {"passed": False, "issues": []},
    }

    with ctx.ui.task_sequence() as seq:
        # ==================== CHECK 1: Database Integrity ====================
        with seq.task("Checking database integrity") as t:
            try:
                db = DBManager(str(db_path), validate_schema=False)
                issues = db.verify_database_integrity()
                db.close()

                if not issues:
                    check_results["database_integrity"]["passed"] = True
                    t.complete("OK")
                else:
                    check_results["database_integrity"]["issues"] = issues
                    t.complete(f"{len(issues)} issue(s)")
                    if verbose:
                        for issue in issues[:5]:
                            ctx.info(f"    • {issue}")
            except Exception as e:
                check_results["database_integrity"]["issues"] = [str(e)]
                t.fail("Check failed", reason=str(e))

        # Extract FTS-specific issues from integrity issues
        fts_issues = [
            issue
            for issue in check_results["database_integrity"]["issues"]
            if "FTS" in issue or "fts" in issue.lower()
        ]
        check_results["fts_synchronization"]["passed"] = not fts_issues
        check_results["fts_synchronization"]["issues"] = fts_issues

        # ==================== CHECK 2: Database Consistency ====================
        with seq.task("Checking database consistency") as t:
            try:
                db = DBManager(str(db_path), validate_schema=False)
                cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
                has_archives = cursor.fetchone() is not None
                db.close()

                if has_archives:
                    db = DBManager(str(db_path), validate_schema=False)
                    cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
                    archive_file = cursor.fetchone()[0]
                    db.close()

                    if Path(archive_file).exists():
                        from .core.validator import ValidatorFacade

                        validator = ValidatorFacade(archive_file, state_db)
                        report = validator.verify_consistency()
                        check_results["database_consistency"]["checked"] = True
                        check_results["database_consistency"]["report"] = report
                        check_results["database_consistency"]["passed"] = report.passed

                        if report.passed:
                            t.complete("OK")
                        else:
                            t.complete(f"{len(report.errors)} issue(s)")
                    else:
                        check_results["database_consistency"]["checked"] = False
                        check_results["database_consistency"]["passed"] = True
                        t.complete("Skipped (archive file not found)")
                else:
                    check_results["database_consistency"]["checked"] = False
                    check_results["database_consistency"]["passed"] = True
                    t.complete("Skipped (no archives in database)")

            except Exception as e:
                check_results["database_consistency"]["issues"] = [str(e)]
                t.fail("Check failed", reason=str(e))

        # ==================== CHECK 3: Offset Accuracy ====================
        with seq.task("Checking offset accuracy") as t:
            if schema_mgr.has_capability(SchemaCapability.MBOX_OFFSETS):
                try:
                    db = DBManager(str(db_path), validate_schema=False)
                    cursor = db.conn.execute("SELECT DISTINCT archive_file FROM messages LIMIT 1")
                    row = cursor.fetchone()
                    db.close()

                    if row and Path(row[0]).exists():
                        from .core.validator import ValidatorFacade

                        archive_file = row[0]
                        validator = ValidatorFacade(archive_file, state_db)
                        result = validator.verify_offsets()

                        check_results["offset_accuracy"]["checked"] = True
                        check_results["offset_accuracy"]["result"] = result

                        if result.accuracy_percentage == 100.0:
                            check_results["offset_accuracy"]["passed"] = True
                            t.complete(f"100% ({result.total_checked:,} checked)")
                        else:
                            check_results["offset_accuracy"]["passed"] = False
                            t.complete(
                                f"{result.accuracy_percentage:.1f}% "
                                f"({result.successful_reads:,}/{result.total_checked:,})"
                            )
                    else:
                        check_results["offset_accuracy"]["checked"] = False
                        check_results["offset_accuracy"]["passed"] = True
                        t.complete("Skipped (no accessible archives)")

                except Exception as e:
                    check_results["offset_accuracy"]["issues"] = [str(e)]
                    t.fail("Check failed", reason=str(e))
            else:
                check_results["offset_accuracy"]["checked"] = False
                check_results["offset_accuracy"]["passed"] = True
                t.complete("Skipped (v1.0 schema)")

    # ==================== SUMMARY ====================

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

    ctx.show_report("Health Check Summary", report_data)

    # ==================== AUTO-REPAIR ====================
    if not all_passed and auto_repair:
        ctx.warning("\n⚠ Auto-repair enabled - attempting to fix issues...")

        try:
            db = DBManager(str(db_path), validate_schema=False)
            repairs = db.repair_database(dry_run=False)
            db.close()

            # Show repair results
            total_repairs = sum(repairs.values())
            if total_repairs > 0:
                ctx.success(f"Performed {total_repairs} repair(s)")

                # Re-run checks to verify repairs
                ctx.info("\nRe-checking after repairs...")

                db = DBManager(str(db_path), validate_schema=False)
                post_repair_issues = db.verify_database_integrity()
                db.close()

                if not post_repair_issues:
                    ctx.success("All issues resolved!")
                    raise typer.Exit(0)
                else:
                    ctx.warning(f"{len(post_repair_issues)} issue(s) remain after repair")
                    ctx.suggest_next_steps(
                        [
                            "Some issues may require manual intervention",
                            "Check remaining issues: gmailarchiver verify-integrity --verbose",
                        ]
                    )
                    raise typer.Exit(2)  # Exit code 2 = repair failed
            else:
                ctx.warning("No automatic repairs available for these issues")
                ctx.suggest_next_steps(
                    [
                        "Manual intervention may be required",
                        "Check details: gmailarchiver verify-integrity --verbose",
                    ]
                )
                raise typer.Exit(2)

        except typer.Exit:
            raise
        except Exception as e:
            ctx.fail_and_exit(
                title="Auto-Repair Failed",
                message=str(e),
                suggestion="Run 'gmailarchiver repair --no-dry-run' manually to fix issues",
                exit_code=2,
            )

    # ==================== EXIT ====================
    if all_passed:
        ctx.success("All checks passed - database is healthy!")
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

        ctx.suggest_next_steps(suggestions)
        raise typer.Exit(1)


# ==================== SCHEDULE COMMAND ====================

schedule_app = typer.Typer(help="Manage automated maintenance schedules", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("list")
@with_context(operation_name="schedule-list")
def schedule_list(
    ctx: CommandContext,
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
    from gmailarchiver.connectors.scheduler import Scheduler

    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            schedules = scheduler.list_schedules(enabled_only=enabled_only)

        if not schedules:
            msg = "No enabled schedules found" if enabled_only else "No schedules configured"
            ctx.warning(msg)
            ctx.suggest_next_steps(
                [
                    "Add a schedule: gmailarchiver schedule add check --daily --time 02:00",
                ]
            )
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

        ctx.show_table(f"Scheduled Tasks ({len(schedules)} total)", headers, rows)

        ctx.suggest_next_steps(
            [
                "Add schedule: gmailarchiver schedule add <command> --daily --time HH:MM",
                "Remove schedule: gmailarchiver schedule remove <id>",
            ]
        )

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to List Schedules",
            message=str(e),
        )


@schedule_app.command("add")
@with_context(operation_name="schedule-add")
def schedule_add(
    ctx: CommandContext,
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
    from gmailarchiver.connectors.platform_scheduler import (
        UnsupportedPlatformError,
        get_platform_scheduler,
    )
    from gmailarchiver.connectors.scheduler import Scheduler, ScheduleValidationError

    # Validate frequency
    frequency_count = sum([daily, weekly, monthly])
    if frequency_count == 0:
        ctx.fail_and_exit(
            title="No Frequency Specified",
            message="A schedule frequency must be specified",
            suggestion="Use --daily, --weekly, or --monthly",
        )
    elif frequency_count > 1:
        ctx.fail_and_exit(
            title="Multiple Frequencies Specified",
            message="Only one frequency can be specified at a time",
            suggestion="Use only one of: --daily, --weekly, --monthly",
        )

    # Determine frequency
    if daily:
        frequency = "daily"
        day_of_week = None
        day_of_month = None
    elif weekly:
        frequency = "weekly"
        if not day:
            ctx.fail_and_exit(
                title="Day Required",
                message="Weekly schedules require --day to specify which day of the week",
                suggestion="Use --day with day name (e.g., Sunday, Monday, ...)",
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
            ctx.fail_and_exit(
                title="Invalid Day Name",
                message=f"'{day}' is not a valid day name",
                suggestion="Use: Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday",
            )
        day_of_week = day_names[day_lower]
        day_of_month = None
    else:  # monthly
        frequency = "monthly"
        if not day:
            ctx.fail_and_exit(
                title="Day Required",
                message="Monthly schedules require --day to specify which day of the month",
                suggestion="Use --day with day of month (1-31)",
            )
        try:
            day_of_month = int(day)
            if not (1 <= day_of_month <= 31):
                raise ValueError("Day must be 1-31")
        except ValueError:
            ctx.fail_and_exit(
                title="Invalid Day of Month",
                message=f"'{day}' is not a valid day of month",
                suggestion="Use a number between 1 and 31",
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
            ctx.fail_and_exit(
                title="Schedule Creation Failed",
                message="Failed to retrieve created schedule",
            )

        ctx.success(f"Schedule created with ID: {schedule_id}")

        # Install on system scheduler if requested
        if install:
            assert schedule is not None, "Schedule should not be None"
            try:
                platform_scheduler = get_platform_scheduler()
                ctx.info("Installing on system scheduler...")
                platform_scheduler.install(schedule)
                ctx.success("Schedule installed on system scheduler")
            except UnsupportedPlatformError as e:
                ctx.warning(str(e))
                ctx.suggest_next_steps(
                    [
                        "Manually configure your system scheduler (cron, Task Scheduler, etc.)",
                        f"Run: gmailarchiver {command}",
                    ]
                )
            except Exception as e:
                ctx.warning(f"Failed to install on system scheduler: {e}")
                ctx.info("Schedule saved in database but not installed on system")

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

        ctx.show_report("Schedule Details", report_data)

        ctx.suggest_next_steps(
            [
                "View schedules: gmailarchiver schedule list",
                "Remove schedule: gmailarchiver schedule remove " + str(schedule_id),
            ]
        )

    except typer.Exit:
        raise
    except ScheduleValidationError as e:
        ctx.fail_and_exit(
            title="Validation Error",
            message=str(e),
        )
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Add Schedule",
            message=str(e),
        )


@schedule_app.command("remove")
@with_context(operation_name="schedule-remove")
def schedule_remove(
    ctx: CommandContext,
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
    from gmailarchiver.connectors.platform_scheduler import (
        UnsupportedPlatformError,
        get_platform_scheduler,
    )
    from gmailarchiver.connectors.scheduler import Scheduler

    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            # Get schedule before removing
            schedule = scheduler.get_schedule(schedule_id)
            if not schedule:
                ctx.fail_and_exit(
                    title="Schedule Not Found",
                    message=f"Schedule with ID {schedule_id} does not exist",
                    suggestion="List schedules: gmailarchiver schedule list",
                )

            # Uninstall from system scheduler if requested
            if uninstall:
                assert schedule is not None, "Schedule should not be None"
                try:
                    platform_scheduler = get_platform_scheduler()
                    ctx.info("Uninstalling from system scheduler...")
                    platform_scheduler.uninstall(schedule)
                    ctx.success("Schedule uninstalled from system scheduler")
                except UnsupportedPlatformError as e:
                    ctx.warning(str(e))
                except Exception as e:
                    ctx.warning(f"Failed to uninstall from system scheduler: {e}")

            # Remove from database
            success = scheduler.remove_schedule(schedule_id)

        if success:
            ctx.success(f"Schedule {schedule_id} removed successfully")
            ctx.suggest_next_steps(
                [
                    "View remaining schedules: gmailarchiver schedule list",
                ]
            )
        else:
            ctx.fail_and_exit(
                title="Failed to Remove Schedule",
                message=f"Failed to remove schedule {schedule_id}",
            )

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Remove Schedule",
            message=str(e),
        )


@schedule_app.command("enable")
@with_context(operation_name="schedule-enable")
def schedule_enable(
    ctx: CommandContext,
    schedule_id: int = typer.Argument(..., help="Schedule ID to enable"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Enable a disabled schedule.

    Examples:
        $ gmailarchiver schedule enable 1
    """
    from gmailarchiver.connectors.scheduler import Scheduler

    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            success = scheduler.enable_schedule(schedule_id)

        if success:
            ctx.success(f"Schedule {schedule_id} enabled")
            ctx.suggest_next_steps(
                [
                    "View schedules: gmailarchiver schedule list",
                ]
            )
        else:
            ctx.fail_and_exit(
                title="Schedule Not Found",
                message=f"Schedule with ID {schedule_id} does not exist",
                suggestion="List schedules: gmailarchiver schedule list",
            )

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Enable Schedule",
            message=str(e),
        )


@schedule_app.command("disable")
@with_context(operation_name="schedule-disable")
def schedule_disable(
    ctx: CommandContext,
    schedule_id: int = typer.Argument(..., help="Schedule ID to disable"),
    state_db: str = typer.Option("archive_state.db", "--state-db", help="State database path"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Disable a schedule without removing it.

    Examples:
        $ gmailarchiver schedule disable 1
    """
    from gmailarchiver.connectors.scheduler import Scheduler

    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create a database",
        )

    try:
        with Scheduler(str(db_path)) as scheduler:
            success = scheduler.disable_schedule(schedule_id)

        if success:
            ctx.success(f"Schedule {schedule_id} disabled")
            ctx.suggest_next_steps(
                [
                    "View schedules: gmailarchiver schedule list",
                    "Re-enable: gmailarchiver schedule enable " + str(schedule_id),
                ]
            )
        else:
            ctx.fail_and_exit(
                title="Schedule Not Found",
                message=f"Schedule with ID {schedule_id} does not exist",
                suggestion="List schedules: gmailarchiver schedule list",
            )

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Disable Schedule",
            message=str(e),
        )


@app.command()
@with_context(has_progress=True, operation_name="compress")
def compress(
    ctx: CommandContext,
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

    from gmailarchiver.shared.utils import format_bytes

    # ArchiveCompressor is imported at module level

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
        ctx.fail_and_exit(
            title="No Files Specified",
            message="No mbox files found to compress",
            suggestion="Provide mbox file paths or glob patterns",
        )

    ctx.info(f"Found {len(expanded_files)} file(s) to compress")

    if dry_run:
        ctx.info("[bold yellow]DRY RUN MODE - No actual compression will occur[/bold yellow]")

    try:
        compressor = ArchiveCompressor(state_db)

        # Compress files with progress tracking
        with ctx.output.progress_context(
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
            ctx.show_report("Compression Preview (Dry Run)", report_data)

            if result.files_skipped > 0:
                ctx.info("\nSkipped files (already compressed):")
                for file_result in result.file_results:
                    if file_result.skipped:
                        file_name = Path(file_result.source_file).name
                        ctx.info(f"  • {file_name}: {file_result.skip_reason}")

            files_str = " ".join(files)
            ctx.suggest_next_steps(
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
            ctx.show_report("Compression Summary", report_data)

            if result.files_skipped > 0:
                ctx.info("\nSkipped files (already compressed):")
                for file_result in result.file_results:
                    if file_result.skipped:
                        file_name = Path(file_result.source_file).name
                        ctx.info(f"  • {file_name}: {file_result.skip_reason}")

            if result.files_compressed > 0:
                ctx.success(
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

                ctx.suggest_next_steps(next_steps)

    except typer.Exit:
        raise
    except ValueError as e:
        ctx.fail_and_exit(
            title="Compression Failed",
            message=str(e),
        )
    except FileNotFoundError as e:
        ctx.fail_and_exit(
            title="File Not Found",
            message=str(e),
            suggestion="Check the file path or glob pattern",
        )
    except Exception as e:
        ctx.fail_and_exit(
            title="Unexpected Error",
            message=str(e),
        )


@app.command()
@with_context(has_progress=True, operation_name="doctor")
def doctor(
    ctx: CommandContext,
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    fix: bool = typer.Option(False, "--fix", help="Automatically fix issues where possible"),
    include_check: bool = typer.Option(
        False, "--check", help="Also run internal database checks (same as 'gmailarchiver check')"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """Run EXTERNAL system and environment diagnostics.

    Performs comprehensive EXTERNAL environment checks:
    - Python version and dependencies
    - OAuth token validity and scopes
    - Disk space and write permissions
    - Stale lock files
    - Database file accessibility

    This command focuses on external/environment issues. For internal database
    health (integrity, consistency, offsets), use 'gmailarchiver check' or
    add --check to include those checks.

    Use --fix to automatically repair fixable issues.

    Examples:
        $ gmailarchiver doctor              # External checks only
        $ gmailarchiver doctor --check      # External + internal checks
        $ gmailarchiver doctor --fix        # Auto-fix issues
        $ gmailarchiver doctor --json
    """
    from gmailarchiver.core.doctor._diagnostics import CheckSeverity

    # Initialize doctor
    doctor_instance = Doctor(state_db, validate_schema=False, auto_create=False)

    # Run diagnostics
    with ctx.ui.task_sequence() as seq:
        with seq.task("Running diagnostic checks") as t:
            report = doctor_instance.run_diagnostics()

            if report.overall_status == CheckSeverity.OK:
                t.complete(f"{report.checks_passed}/{len(report.checks)} passed")
            else:
                t.complete(f"{report.errors} error(s), {report.warnings} warning(s)")

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

        ctx.show_table("Diagnostic Results", headers, rows)

        # Show summary
        if report.overall_status == CheckSeverity.OK:
            ctx.success(f"All checks passed! ({report.checks_passed}/{len(report.checks)} OK)")
        elif report.overall_status == CheckSeverity.WARNING:
            ctx.warning(
                f"Found {report.warnings} warning(s), {report.errors} error(s), "
                f"{report.checks_passed} passed"
            )
        else:  # ERROR
            ctx.error(
                f"Found {report.errors} error(s), {report.warnings} warning(s), "
                f"{report.checks_passed} passed"
            )

        # Show fixable issues
        if report.fixable_issues:
            ctx.info(f"\n{len(report.fixable_issues)} issue(s) can be automatically fixed:")
            for issue in report.fixable_issues:
                ctx.info(f"  • {issue}")

            if not fix:
                ctx.suggest_next_steps(
                    ["Run with --fix to auto-repair: gmailarchiver doctor --fix"]
                )

    # Run auto-fix if requested
    if fix and report.fixable_issues:
        with ctx.ui.task_sequence() as seq:
            with seq.task("Running auto-fix", total=len(report.fixable_issues)) as t:
                fix_results = doctor_instance.run_auto_fix()
                fixed_count = sum(1 for r in fix_results if r.success)
                failed_count = len(fix_results) - fixed_count

                if failed_count == 0:
                    t.complete(f"Fixed {fixed_count} issue(s)")
                else:
                    t.complete(f"Fixed {fixed_count}, failed {failed_count}")

        # Show fix results
        if not json_output:
            headers = ["Check", "Status", "Message"]
            fix_rows: list[list[str]] = []

            for fix_result in fix_results:
                status = "[green]✓ FIXED[/green]" if fix_result.success else "[red]✗ FAILED[/red]"
                fix_rows.append([fix_result.check_name, status, fix_result.message])

            ctx.show_table("Auto-Fix Results", headers, fix_rows)

        # Show success/failure summary (fixed_count and failed_count computed above)
        if fixed_count > 0 and failed_count == 0:
            ctx.success(f"Successfully fixed {fixed_count} issue(s)")
            ctx.suggest_next_steps(
                [
                    "Verify fixes: gmailarchiver doctor",
                    "Check database: gmailarchiver verify-integrity",
                ]
            )
        elif fixed_count > 0:
            ctx.warning(f"Fixed {fixed_count} issue(s), {failed_count} failed")
        else:
            ctx.error(f"Failed to fix {failed_count} issue(s)")

    # Run internal database checks if --check flag is used
    if include_check:
        ctx.info("\n── Internal Database Checks ──")
        db_path = Path(state_db)
        if db_path.exists():
            from gmailarchiver.data.db_manager import DBManager

            with ctx.ui.task_sequence() as seq:
                with seq.task("Running internal checks") as t:
                    try:
                        db = DBManager(str(db_path), validate_schema=False)
                        issues = db.verify_database_integrity()
                        db.close()

                        if not issues:
                            t.complete("All internal checks passed")
                        else:
                            t.complete(f"{len(issues)} issue(s) found")
                            for issue in issues[:5]:
                                ctx.info(f"  • {issue}")
                            if len(issues) > 5:
                                ctx.info(f"  ... and {len(issues) - 5} more")
                    except Exception as e:
                        t.fail("Check failed", reason=str(e))

            ctx.suggest_next_steps(["Run full internal checks: gmailarchiver check --verbose"])
        else:
            ctx.warning("Database not found, skipping internal checks")
    elif not json_output:
        # Suggest running check for full internal validation
        ctx.suggest_next_steps(
            [
                "Run internal database checks: gmailarchiver check",
                "Full health check: gmailarchiver doctor --check",
            ]
        )

    # JSON output mode
    if json_output:
        report_dict = report.to_dict()
        ctx.show_report("Doctor Report", report_dict)

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
            ctx.show_report("Fix Results", fix_dict)


@utilities_app.command()
@app.command(hidden=True)
@with_context(operation_name="auth-reset")
def auth_reset(
    ctx: CommandContext,
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """Clear OAuth token and re-authenticate."""
    authenticator = GmailAuthenticator()
    authenticator.revoke()

    ctx.success("Authentication token deleted")
    ctx.info("Run any command to re-authenticate")


@utilities_app.command(name="backfill-gmail-ids")
@with_context(requires_gmail=True, has_progress=True, operation_name="backfill-gmail-ids")
def backfill_gmail_ids_cmd(
    ctx: CommandContext,
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

    from gmailarchiver.data.db_manager import DBManager

    # Pattern to detect synthetic gmail_ids (start with 000...)
    synthetic_id_pattern = re.compile(r"^0{3,}[0-9a-f]+$", re.IGNORECASE)

    try:
        # Gmail client is already authenticated via @with_context
        assert ctx.gmail is not None, "Gmail client should be initialized"
        client = ctx.gmail

        # 2. Find messages needing Gmail ID lookup
        ctx.info("Scanning database for messages needing backfill...")
        with DBManager(state_db, validate_schema=False, auto_create=False) as db:
            cursor = db.conn.execute("SELECT gmail_id, rfc_message_id FROM messages")
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

        ctx.info(f"Total messages in database: {len(all_messages):,}")
        ctx.info(f"Messages with real Gmail IDs: {real_messages_count:,}")
        ctx.info(f"Messages with NULL gmail_id: {null_gmail_id_count:,}")
        ctx.info(f"Messages with synthetic IDs: {synthetic_gmail_id_count:,}")
        ctx.info(f"Total needing backfill: {len(messages_needing_backfill):,}")

        if not messages_needing_backfill:
            ctx.success("No messages need backfill!")
            return

        # Apply offset and limit
        messages_to_process = messages_needing_backfill[offset:]
        if limit > 0:
            messages_to_process = messages_to_process[:limit]

        if offset > 0:
            ctx.info(f"Skipping first {offset} messages (--offset)")
        if limit > 0:
            ctx.info(f"Processing up to {limit} messages (--limit)")

        total_to_process = len(messages_to_process)
        ctx.info(f"\nProcessing {total_to_process:,} messages in batches of {batch_size}...")

        # Estimate time (batch processing is faster: ~1 batch per 1.5 seconds)
        num_batches = (total_to_process + batch_size - 1) // batch_size
        est_seconds = num_batches * 1.5  # ~1.5s per batch (API call + delay)
        ctx.info(f"Estimated time: {est_seconds / 60:.1f} minutes")

        if dry_run:
            ctx.warning("[DRY RUN] No changes will be made")

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
                ctx.info(f"  Progress: {processed:,}/{total:,} ({pct}%)")
                last_progress_update[0] = processed

        # Use the batch method for efficient lookups
        ctx.info("\nLooking up Gmail IDs...")
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
        ctx.info("\nResults:")
        ctx.info(f"  Found in Gmail: {found:,}")
        ctx.info(f"  Not in Gmail (deleted): {not_found:,}")

        if dry_run:
            ctx.warning(f"\n[DRY RUN] Would update {len(updates):,} messages")
            if updates[:5]:
                ctx.info("Sample updates:")
                for new_id, rfc_id in updates[:5]:
                    status = new_id[:16] + "..." if new_id else "NULL"
                    rfc_display = rfc_id[:40] + "..." if len(rfc_id) > 40 else rfc_id
                    ctx.info(f"  {rfc_display} -> {status}")
        else:
            ctx.info(f"\nUpdating database with {len(updates):,} changes...")
            with DBManager(state_db, validate_schema=False, auto_create=False) as db:
                for new_gmail_id, rfc_message_id in updates:
                    db.conn.execute(
                        "UPDATE messages SET gmail_id = ? WHERE rfc_message_id = ?",
                        (new_gmail_id, rfc_message_id),
                    )
                db.conn.commit()
            ctx.success("Database updated!")

        # Summary
        remaining = len(messages_needing_backfill) - len(messages_to_process) - offset
        if remaining > 0:
            ctx.info(f"\nRemaining messages to process: {remaining:,}")
            next_offset = offset + len(messages_to_process)
            ctx.info(f"Resume with: --offset {next_offset}")

    except typer.Exit:
        raise
    except Exception as e:
        ctx.fail_and_exit(
            title="Backfill Failed",
            message=str(e),
            suggestion="Check your internet connection and Gmail authentication",
        )


if __name__ == "__main__":
    app()
