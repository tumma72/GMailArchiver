"""Gmail Archiver CLI application."""

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from ._version import __version__
from .cli.command_context import CommandContext, with_context
from .cli.output import OutputManager
from .connectors.auth import GmailAuthenticator
from .connectors.gmail_client import GmailClient
from .core.archiver import ArchiverFacade
from .core.compressor.facade import ArchiveCompressor
from .core.consolidator.facade import ArchiveConsolidator
from .core.deduplicator.facade import DeduplicatorFacade
from .core.doctor.facade import Doctor
from .core.extractor.facade import ExtractStats, MessageExtractor
from .core.importer.facade import ImporterFacade
from .core.search.facade import SearchFacade
from .core.validator.facade import ValidatorFacade
from .data.migration import MigrationManager
from .data.schema_manager import SchemaCapability, SchemaManager, SchemaVersion
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
@with_context(requires_storage=True, has_progress=True, operation_name="archive")
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

    # Phase 1: Authentication - get OAuth credentials (client created in async workflow)
    with ctx.ui.spinner("Authenticating with Gmail") as task:
        try:
            authenticator = GmailAuthenticator(credentials_file=credentials)
            oauth_creds = authenticator.authenticate()
            task.complete("Connected")
        except Exception as e:
            task.fail("Authentication failed")
            ctx.fail_and_exit(
                "Authentication Failed",
                f"Failed to authenticate with Gmail: {e}",
                suggestion="Run 'gmailarchiver auth-reset' and try again",
            )

    # Phase 2: Discovery and Archiving - single async workflow for proper resource management
    message_list: list[dict[str, str]] = []
    messages_to_archive: list[str] = []
    skipped_count: int = 0
    result: dict[str, Any] | None = None
    archive_error: Exception | None = None
    scan_count: int = 0  # Track messages scanned during listing

    # Single async workflow using proper context manager for Gmail client
    async def _archive_workflow() -> tuple[
        list[dict[str, str]], list[str], int, dict[str, Any] | None, Exception | None
    ]:
        nonlocal message_list, messages_to_archive, skipped_count, result, archive_error, scan_count

        # Use async context manager for proper HTTP client lifecycle
        async with GmailClient(oauth_creds) as gmail:
            # Create archiver with the properly initialized client
            archiver = await ArchiverFacade.create(
                gmail_client=gmail,
                state_db_path="archive_state.db",
                output_manager=out,
            )

            try:
                # Task 1: Scan messages from Gmail
                with ctx.ui.task_sequence(show_logs=True) as seq:
                    with seq.task("Scanning messages from Gmail") as task:
                        try:

                            def scan_progress(count: int, page: int) -> None:
                                nonlocal scan_count
                                scan_count = count
                                task.set_status(f"Scanning messages from Gmail... {count:,} found")

                            _query, message_list = await archiver.list_messages_for_archive(
                                age_threshold, progress_callback=scan_progress
                            )

                            if message_list:
                                task.complete(f"Found {len(message_list):,} messages")
                            else:
                                task.complete("No messages found matching criteria")

                        except Exception as e:
                            task.fail(f"Scan failed: {e}")
                            archive_error = e

                    # Task 2: Filter already archived
                    if message_list and not archive_error:
                        with seq.task("Checking for already archived") as task:
                            try:
                                all_ids = [msg["id"] for msg in message_list]
                                (
                                    messages_to_archive,
                                    skipped_count,
                                ) = await archiver.filter_already_archived(all_ids, incremental)

                                if skipped_count > 0:
                                    task.complete(
                                        f"Identified {len(messages_to_archive):,} to archive "
                                        f"({skipped_count:,} already archived)"
                                    )
                                else:
                                    task.complete(
                                        f"Identified {len(messages_to_archive):,} to archive"
                                    )

                            except Exception as e:
                                task.fail(f"Filter failed: {e}")
                                archive_error = e

                    # Task 3: Archive messages
                    if messages_to_archive and not archive_error and not dry_run:
                        with seq.task("Archiving messages", total=len(messages_to_archive)) as task:
                            try:
                                result = await archiver.archive_messages(
                                    message_ids=messages_to_archive,
                                    output_file=output,
                                    compress=compress,
                                    operation=task,
                                )

                                if result.get("interrupted"):
                                    task.complete(
                                        f"Interrupted after {result['archived_count']:,} messages"
                                    )
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
            finally:
                # Clean up archiver resources
                await archiver.close()

        return message_list, messages_to_archive, skipped_count, result, archive_error

    # Run the entire workflow in a single event loop
    asyncio.run(_archive_workflow())

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

    # Phase 5: Validation (with spinner for UI feedback)
    # Get the actual file that was written
    actual_file = result.get("actual_file", output) if result else output

    # Get the actual message IDs that were archived
    # (ctx.storage is guaranteed by requires_storage=True)
    assert ctx.storage is not None

    validation_results: dict[str, Any] = {}
    with ctx.ui.spinner("Validating archive") as task:
        archived_ids = asyncio.run(ctx.storage.get_message_ids_for_archive(actual_file))

        # Validate using ValidatorFacade directly
        validator = ValidatorFacade(actual_file, "archive_state.db", output=out)
        try:
            validation_results = validator.validate_comprehensive(archived_ids)
            if validation_results["passed"]:
                task.complete("Passed all checks")
            else:
                task.fail("Failed")
        finally:
            asyncio.run(validator.close())

    # Show validation report using panel method (outside spinner)
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

            # Perform permanent deletion with proper async resource management
            async def _delete_messages() -> None:
                async with GmailClient(oauth_creds) as gmail:
                    await gmail.delete_messages_permanent(list(archived_ids))

            with out.progress_context("Permanently deleting messages", total=None):
                asyncio.run(_delete_messages())
            ctx.success("Messages permanently deleted")

        elif trash:
            # Move to trash with confirmation
            if not typer.confirm(
                f"\nMove {archived_count} messages to trash? (30-day recovery period)"
            ):
                ctx.info("Cancelled")
                return

            # Trash messages with proper async resource management
            async def _trash_messages() -> None:
                async with GmailClient(oauth_creds) as gmail:
                    await gmail.trash_messages(list(archived_ids))

            with out.progress_context("Moving messages to trash", total=None):
                asyncio.run(_trash_messages())
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

    # Suggest contextual next steps
    next_steps: list[str] = []

    if archived_count > 0 and not trash and not delete:
        # Only suggest deletion options if messages were archived and no deletion was done
        next_steps.append(
            f"Move to trash (recoverable): gmailarchiver archive {age_threshold} --trash"
        )
        next_steps.append(f"Delete permanently: gmailarchiver archive {age_threshold} --delete")
    elif archived_count == 0:
        # No messages archived - suggest status check
        next_steps.append("Check archive status: gmailarchiver status")

    if next_steps:
        ctx.suggest_next_steps(next_steps)


@app.command()
@with_context(requires_storage=True, has_progress=True, operation_name="validate")
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

    # Create validator upfront for use in async workflow
    validator = ValidatorFacade(archive_file, state_db, output=ctx.output)

    async def _validate_workflow() -> tuple[set[str], dict[str, Any]]:
        """Single async workflow for validate command."""
        try:
            assert ctx.storage is not None, "Storage should be initialized by @with_context"
            ids = await ctx.storage.get_message_ids_for_archive(archive_file)
            # validate_comprehensive is sync, run via to_thread to not block
            validation_results = await asyncio.to_thread(
                validator.validate_comprehensive, ids
            )
            return ids, validation_results
        finally:
            await validator.close()

    with ctx.ui.task_sequence() as seq:
        # Task 1: Load database and run validation
        with seq.task("Loading database and validating") as t:
            try:
                expected_ids, results = asyncio.run(_validate_workflow())
                if results["passed"]:
                    t.complete(f"Validated {len(expected_ids):,} messages - all checks passed")
                else:
                    failed_checks = [
                        k.replace("_check", "").replace("_", " ")
                        for k, v in results.items()
                        if k.endswith("_check") and not v
                    ]
                    t.complete(f"Found {len(expected_ids):,} messages - failed: {', '.join(failed_checks)}")
            except Exception as e:
                t.fail("Validation error", reason=str(e))
                ctx.fail_and_exit(
                    title="Validation Error",
                    message=f"Failed to validate: {e}",
                    suggestion="Check database file permissions and integrity",
                )

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
@with_context(requires_storage=True, operation_name="retry-delete")
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
        assert ctx.storage is not None, "Storage should be initialized by @with_context"

        # Authenticate and validate deletion permissions (must happen before async workflow)
        client = ctx.authenticate_gmail(
            credentials=credentials,
            validate_deletion_scope=True,
        )
        assert client is not None  # required=True ensures this

        # Create archiver (for deletion functionality)
        archiver = ArchiverFacade(client, ctx.storage.db, ctx.storage, output_manager=ctx.output)

        # Track deletion result
        deletion_cancelled = False
        deletion_completed = False

        def _confirm_permanent_deletion(num_messages: int) -> bool:
            """Sync confirmation for permanent deletion."""
            ctx.warning("WARNING: PERMANENT DELETION")
            ctx.warning(
                f"This will permanently delete {num_messages} messages. "
                "This action CANNOT be undone!"
            )
            ctx.info("Deleted messages will be gone forever - not in trash and not recoverable.\n")

            confirmation = typer.prompt(f"Type 'DELETE {num_messages} MESSAGES' to confirm")
            return confirmation == f"DELETE {num_messages} MESSAGES"

        def _confirm_trash_deletion(num_messages: int) -> bool:
            """Sync confirmation for trash deletion."""
            ctx.info(f"This will move {num_messages} messages to trash.")
            ctx.info("(Messages can be recovered from trash for 30 days)\n")
            return typer.confirm(f"Move {num_messages} messages to trash?")

        async def _retry_delete_workflow() -> tuple[int, bool, bool]:
            """Single async workflow for retry-delete command.

            Returns:
                Tuple of (message_count, was_cancelled, completed_successfully)
            """
            # Get message IDs
            message_ids = list(await ctx.storage.get_message_ids_for_archive(archive_file))

            if not message_ids:
                return 0, False, False

            # Show message info (sync via to_thread)
            def _show_info() -> None:
                ctx.info(f"Found {len(message_ids)} archived messages")
                ctx.info(f"Archive: {archive_file}\n")

            await asyncio.to_thread(_show_info)

            # Confirm deletion (sync via to_thread)
            if permanent:
                confirmed = await asyncio.to_thread(_confirm_permanent_deletion, len(message_ids))
            else:
                confirmed = await asyncio.to_thread(_confirm_trash_deletion, len(message_ids))

            if not confirmed:
                return len(message_ids), True, False

            # Perform deletion
            await archiver.delete_archived_messages(message_ids, permanent=permanent)
            return len(message_ids), False, True

        message_count, deletion_cancelled, deletion_completed = asyncio.run(_retry_delete_workflow())

        if message_count == 0:
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

        if deletion_cancelled:
            ctx.info("Deletion cancelled" if permanent else "Cancelled")
            return

        if deletion_completed:
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

    def _get_status_data_sync(schema_version: str, run_limit: int) -> tuple[int, list[dict[str, Any]]]:
        """Sync helper to query database statistics."""
        conn = sqlite3.connect(state_db)
        conn.row_factory = sqlite3.Row

        # Get message count - handle both v1.0 (archived_messages) and v1.1+ (messages)
        table_name = "messages" if schema_version in ("1.1", "1.2") else "archived_messages"
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = cursor.fetchone()
        total_archived = int(result[0]) if result else 0

        # Get recent runs
        cursor = conn.execute(
            """
            SELECT run_id, run_timestamp as timestamp, query,
                   messages_archived, archive_file
            FROM archive_runs
            ORDER BY run_id DESC
            LIMIT ?
            """,
            (run_limit,),
        )
        recent_runs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return total_archived, recent_runs

    async def _status_workflow() -> tuple[str, int, list[dict[str, Any]]]:
        """Single async workflow for status command."""
        try:
            version = await manager.detect_schema_version()
            run_limit = 10 if verbose else 5
            total_archived, recent_runs = await asyncio.to_thread(
                _get_status_data_sync, version, run_limit
            )
            return version, total_archived, recent_runs
        finally:
            await manager._close()

    try:
        version, total_archived, recent_runs = asyncio.run(_status_workflow())
        db_size = db_path.stat().st_size

        # Get unique archive files from runs
        archive_files = set(run["archive_file"] for run in recent_runs if run.get("archive_file"))

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
        run_limit = 10 if verbose else 5
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


@app.command()
@with_context(requires_storage=True, operation_name="cleanup")
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
        assert ctx.storage is not None, "Storage should be initialized by @with_context"
        storage_db = ctx.storage.db  # Capture for async closure

        def _confirm_cleanup(num_sessions: int) -> bool:
            """Sync confirmation for cleanup."""
            ctx.warning(
                f"This will delete {num_sessions} partial session(s) "
                "and their associated data"
            )
            return typer.confirm("Continue?")

        async def _cleanup_workflow() -> dict[str, Any]:
            """Single async workflow for cleanup command."""
            try:
                await storage_db.ensure_sessions_table()
                sessions = await storage_db.get_all_partial_sessions()

                # Handle list mode
                if list_sessions:
                    return {"status": "list", "sessions": sessions}

                # Determine which sessions to clean
                sessions_to_clean: list[dict[str, Any]] = []

                if all_sessions:
                    sessions_to_clean = sessions
                    if not sessions_to_clean:
                        return {"status": "no_sessions"}
                elif session_id:
                    matching = [s for s in sessions if s["session_id"].startswith(session_id)]
                    if not matching:
                        return {"status": "not_found", "session_id": session_id}
                    if len(matching) > 1:
                        return {"status": "multiple_matches", "session_id": session_id}
                    sessions_to_clean = matching

                # Get confirmation (sync via to_thread)
                if not force:
                    confirmed = await asyncio.to_thread(_confirm_cleanup, len(sessions_to_clean))
                    if not confirmed:
                        return {"status": "cancelled"}

                # Perform cleanup
                cleaned_count = 0
                for session in sessions_to_clean:
                    target_file = session["target_file"]
                    partial_file = Path(target_file + ".partial")

                    # Delete partial file if it exists (sync file op via to_thread)
                    if partial_file.exists():
                        await asyncio.to_thread(partial_file.unlink)
                        await asyncio.to_thread(
                            ctx.info, f"Deleted partial file: {partial_file.name}"
                        )

                    # Delete messages associated with the partial file
                    deleted_msgs = await storage_db.delete_messages_for_file(str(partial_file))
                    if deleted_msgs > 0:
                        await asyncio.to_thread(ctx.info, f"Removed {deleted_msgs} message records")

                    # Delete session record
                    await storage_db.delete_session(session["session_id"])
                    await asyncio.to_thread(
                        ctx.success, f"Cleaned session: {session['session_id'][:12]}..."
                    )
                    cleaned_count += 1

                return {"status": "success", "cleaned_count": cleaned_count}

            finally:
                await storage_db.close()

        result = asyncio.run(_cleanup_workflow())

        # Handle result based on status
        if result["status"] == "list":
            sessions = result["sessions"]
            if not sessions:
                ctx.info("No partial archive sessions found")
                raise typer.Exit(0)

            headers = ["Session ID", "Target File", "Progress", "Started", "Updated"]
            rows: list[list[str]] = []
            for session in sessions:
                progress = f"{session['processed_count']}/{session['total_count']}"
                started = session["started_at"][:19] if session["started_at"] else "N/A"
                updated = session["updated_at"][:19] if session["updated_at"] else "N/A"
                rows.append(
                    [
                        session["session_id"][:12] + "...",
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

        if result["status"] == "no_sessions":
            ctx.info("No partial archive sessions to clean up")
            raise typer.Exit(0)

        if result["status"] == "not_found":
            ctx.error(f"Session not found: {result['session_id']}")
            ctx.suggest_next_steps(["List sessions: gmailarchiver cleanup --list"])
            raise typer.Exit(1)

        if result["status"] == "multiple_matches":
            ctx.error(f"Multiple sessions match '{result['session_id']}'. Be more specific.")
            raise typer.Exit(1)

        if result["status"] == "cancelled":
            ctx.info("Cleanup cancelled")
            raise typer.Exit(0)

        if result["status"] == "success":
            ctx.success(f"Cleaned up {result['cleaned_count']} partial session(s)")

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

    # Result container for workflow
    migration_result: dict[str, Any] | None = None

    def _show_migration_info_and_confirm(current_ver: str, target_ver: str) -> bool:
        """Show migration info and get user confirmation (sync)."""
        ctx.info(f"Current schema version: {current_ver}")
        ctx.info(f"\nMigration from v{current_ver} to v{target_ver} will:")
        ctx.info("  • Create backup of current database")
        ctx.info("  • Add enhanced schema with mbox offset tracking")
        ctx.info("  • Enable full-text search capabilities")
        ctx.info("  • Add multi-account support (future-ready)")
        ctx.info("  • Preserve all existing message data")
        return typer.confirm("\nProceed with migration?")

    async def _migrate_workflow() -> dict[str, Any]:
        """Single async workflow for migrate command."""
        schema_mgr = SchemaManager(db_path)
        manager: MigrationManager | None = None

        try:
            # Phase 1: Pre-migration checks
            current_version = await schema_mgr.detect_version()

            if not await schema_mgr.needs_migration():
                return {
                    "status": "up_to_date",
                    "version": current_version.value,
                }

            if current_version == SchemaVersion.NONE:
                return {
                    "status": "invalid_database",
                    "version": current_version.value,
                }

            if not await schema_mgr.can_auto_migrate():
                return {
                    "status": "cannot_migrate",
                    "version": current_version.value,
                }

            # Phase 2: Get user confirmation (sync via to_thread)
            confirmed = await asyncio.to_thread(
                _show_migration_info_and_confirm,
                current_version.value,
                SchemaManager.CURRENT_VERSION.value,
            )

            if not confirmed:
                return {"status": "cancelled"}

            # Phase 3: Execute migration
            manager = MigrationManager(db_path)
            backup_path = await manager.create_backup()

            await schema_mgr.auto_migrate_if_needed(progress_callback=lambda msg: ctx.info(msg))

            schema_mgr.invalidate_cache()
            final_version = await schema_mgr.detect_version()

            if final_version != SchemaManager.CURRENT_VERSION:
                raise RuntimeError(
                    f"Migration validation failed: expected {SchemaManager.CURRENT_VERSION.value}, "
                    f"got {final_version.value}"
                )

            return {
                "status": "success",
                "from_version": current_version.value,
                "to_version": final_version.value,
                "backup_path": str(backup_path),
            }

        finally:
            if manager is not None:
                await manager._close()

    # SINGLE asyncio.run() call for entire workflow
    try:
        with ctx.output.progress_context("Migrating database", total=3) as progress:
            task = progress.add_task("Migration", total=3) if progress else None
            migration_result = asyncio.run(_migrate_workflow())
            if progress and task:
                progress.update(task, advance=3, refresh=True)

    except Exception as e:
        ctx.fail_and_exit(
            title="Migration Failed",
            message=str(e),
            suggestion="Check database integrity or restore from backup",
        )

    # Handle post-migration results based on status
    if migration_result is None:
        ctx.fail_and_exit(
            title="Migration Failed",
            message="Unknown error occurred",
            suggestion="Check database integrity or restore from backup",
        )

    status = migration_result["status"]

    if status == "up_to_date":
        ctx.success(f"Database is already at version {migration_result['version']} (up to date)")
        return

    if status == "invalid_database":
        ctx.fail_and_exit(
            title="Invalid Database",
            message="Database appears to be empty or invalid",
            suggestion="Create with 'gmailarchiver archive' or 'gmailarchiver import'",
        )

    if status == "cannot_migrate":
        ctx.fail_and_exit(
            title="Cannot Migrate",
            message=f"Cannot auto-migrate from version {migration_result['version']}",
            suggestion="Manual intervention required",
        )

    if status == "cancelled":
        ctx.info("Migration cancelled")
        return

    if status != "success":
        error_msg = migration_result.get("error", "Unknown error")
        ctx.fail_and_exit(
            title="Migration Failed",
            message=error_msg,
            suggestion="Check database integrity or restore from backup",
        )

    # Build report data for success case
    report_data = {
        "From Version": migration_result["from_version"],
        "To Version": migration_result["to_version"],
        "Backup Location": migration_result["backup_path"],
    }

    ctx.show_report("Migration Summary", report_data)
    ctx.success("Migration completed successfully!")

    ctx.suggest_next_steps(
        [
            "Verify integrity: gmailarchiver verify-integrity",
            "Search messages: gmailarchiver search <query>",
        ]
    )


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
        asyncio.run(manager.rollback_migration(backup_path))

        ctx.success("Rollback completed successfully!")

    except Exception as e:
        ctx.fail_and_exit(
            title="Rollback Failed",
            message=str(e),
            suggestion="Check backup file integrity and try again",
        )


@utilities_app.command()
@app.command(hidden=True)
@with_context(requires_storage=True, requires_schema="1.1", operation_name="dedupe")
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
    # Validate strategy
    valid_strategies = ["newest", "largest", "first"]
    if strategy not in valid_strategies:
        ctx.fail_and_exit(
            "Invalid Strategy",
            f"Invalid strategy: {strategy}",
            suggestion=f"Must be one of: {', '.join(valid_strategies)}",
        )

    try:
        # Use the DBManager from the context (created by @with_context decorator)
        assert ctx.storage is not None, "Storage should be initialized by @with_context"
        db = ctx.storage.db

        def _confirm_dedupe(messages_to_remove: int, strategy_name: str) -> bool:
            """Sync confirmation for deduplication."""
            ctx.warning(
                "⚠ WARNING: This will permanently remove duplicate messages from the database"
            )
            ctx.info("The mbox files themselves will not be modified.")
            return typer.confirm(
                f"Remove {messages_to_remove:,} duplicate messages using '{strategy_name}' strategy?"
            )

        async def _dedupe_workflow() -> dict[str, Any]:
            """Single async workflow for dedupe command."""
            # Task 1: Find duplicates
            async with await DeduplicatorFacade.create(db) as dedup:
                duplicates = await dedup.find_duplicates()

            # Early return if no duplicates
            if not duplicates:
                return {"status": "no_duplicates"}

            # Task 2: Generate report
            async with await DeduplicatorFacade.create(db) as dedup:
                report = await dedup.generate_report(duplicates)

            # For non-dry-run: get confirmation BEFORE actually deduplicating
            if not dry_run:
                confirmed = await asyncio.to_thread(
                    _confirm_dedupe, report.messages_to_remove, strategy
                )
                if not confirmed:
                    return {"status": "cancelled", "report": report}

            # Task 3: Deduplicate (dry run or actual)
            async with await DeduplicatorFacade.create(db) as dedup:
                result = await dedup.deduplicate(duplicates, strategy=strategy, dry_run=dry_run)

            # Task 4: Auto-verify if requested and not dry run
            verification_issues = None
            verification_error = None
            if auto_verify and not dry_run:
                try:
                    verification_issues = await db.verify_database_integrity()
                except Exception as e:
                    verification_error = e

            return {
                "status": "dry_run" if dry_run else "success",
                "duplicates": duplicates,
                "report": report,
                "result": result,
                "verification_issues": verification_issues,
                "verification_error": verification_error,
            }

        # Execute the single async workflow
        workflow_result = asyncio.run(_dedupe_workflow())

        # Post-workflow sync handling (display results)
        status = workflow_result["status"]

        if status == "no_duplicates":
            ctx.success("No duplicate messages found!")
            return

        if status == "cancelled":
            ctx.info("Cancelled")
            return

        report = workflow_result["report"]
        result = workflow_result["result"]

        with ctx.ui.task_sequence() as seq:
            with seq.task("Finding duplicates") as t:
                t.complete(f"Found {len(workflow_result['duplicates']):,} duplicate message IDs")

            with seq.task("Analyzing duplicates") as t:
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

            if status == "dry_run":
                ctx.warning("DRY RUN - No changes will be made")

                with seq.task("Previewing deduplication") as t:
                    t.complete(
                        f"Would remove {result.messages_removed:,} messages, "
                        f"keep {result.messages_kept:,} messages"
                    )

                report_data["Would Remove"] = f"{result.messages_removed:,} messages"
                report_data["Would Keep"] = f"{result.messages_kept:,} messages"
                report_data["Would Save"] = format_bytes(result.space_saved)

                ctx.show_report("Deduplication Preview (Dry Run)", report_data)
                ctx.suggest_next_steps(
                    [(f"Apply changes: gmailarchiver dedupe --strategy {strategy} --no-dry-run")]
                )

            else:  # success
                with seq.task("Removing duplicates") as t:
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
                        "Consolidate archives: gmailarchiver consolidate archive*.mbox -o merged.mbox",
                    ]
                )

                # Auto-verify display if requested
                if auto_verify:
                    ctx.info("\nRunning verification...")
                    verification_issues = workflow_result["verification_issues"]
                    verification_error = workflow_result["verification_error"]

                    with seq.task("Verifying database integrity") as t:
                        if verification_error is not None:
                            t.fail("Verification failed", reason=str(verification_error))
                            ctx.warning(f"Verification failed: {verification_error}")
                        elif verification_issues is not None and not verification_issues:
                            t.complete("No issues found")
                        elif verification_issues is not None:
                            t.complete(f"Found {len(verification_issues)} issue(s)")
                            ctx.warning(f"Verification found {len(verification_issues)} issue(s):")
                            for issue in verification_issues[:5]:
                                ctx.info(f"  • {issue}")
                            if len(verification_issues) > 5:
                                ctx.info(f"  ... and {len(verification_issues) - 5} more issues")

                            ctx.suggest_next_steps(
                                [
                                    "Fix issues automatically: gmailarchiver check --auto-repair",
                                    "View all issues: gmailarchiver verify-integrity --verbose",
                                ]
                            )

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
@with_context(requires_storage=True, operation_name="verify-offsets")
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

        async def _verify_offsets_workflow() -> Any:
            """Single async workflow for verify-offsets command."""
            try:
                return await validator.verify_offsets()
            finally:
                await validator.close()

        result = None

        with ctx.ui.task_sequence() as seq:
            with seq.task("Verifying offsets") as t:
                result = asyncio.run(_verify_offsets_workflow())

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
@with_context(requires_storage=True, operation_name="verify-consistency")
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
        schema_mgr = SchemaManager(state_db)

        async def _verify_consistency_workflow() -> tuple[Any, bool]:
            """Single async workflow for verify-consistency command."""
            try:
                report = await validator.verify_consistency()
                has_fts = await schema_mgr.has_capability(SchemaCapability.FTS_SEARCH)
                return report, has_fts
            finally:
                await validator.close()

        report = None
        has_fts_capability = False

        with ctx.ui.task_sequence() as seq:
            with seq.task("Running consistency checks") as t:
                report, has_fts_capability = asyncio.run(_verify_consistency_workflow())

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

        # Add FTS-specific fields if schema supports it
        if has_fts_capability:
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
@with_context(requires_storage=True, requires_schema="1.1", operation_name="search")
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
    effective_query = query
    if not effective_query:
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

        effective_query = " ".join(query_parts)

    # Helper functions for interactive mode (sync via asyncio.to_thread)
    def _interactive_select_messages(
        results_list: list[Any],
    ) -> tuple[list[str] | None, str | None]:
        """Sync interactive message selection."""
        try:
            import questionary
        except ImportError:
            return None, None

        # Build choices for interactive selection
        choices = []
        for idx, result in enumerate(results_list, 1):
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
        selected_ids = questionary.checkbox(
            "Select messages to extract (space to select, enter to confirm):",
            choices=choices,
        ).ask()

        if not selected_ids:
            return None, None

        # Prompt for output directory
        output_dir_str = questionary.path(
            "Output directory for extracted messages:",
            default="./extracted",
            only_directories=True,
        ).ask()

        return selected_ids, output_dir_str

    async def _search_workflow() -> dict[str, Any]:
        """Single async workflow for search command."""
        from gmailarchiver.core.search._types import SearchResults

        try:
            start_time = time.perf_counter()

            # Execute search
            async with await SearchFacade.create(state_db) as search_facade:
                results: SearchResults = await search_facade.search(
                    effective_query, limit=limit
                )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            workflow_result: dict[str, Any] = {
                "status": "success",
                "results": results,
                "execution_time_ms": execution_time_ms,
                "extraction_stats": None,
                "interactive_cancelled": False,
                "missing_questionary": False,
            }

            # Handle interactive mode
            if interactive and not json_output and results.total_results > 0:
                # Interactive selection via to_thread
                selected_ids, output_dir_str = await asyncio.to_thread(
                    _interactive_select_messages, results.results
                )

                if selected_ids is None:
                    # Check if questionary import failed
                    try:
                        import questionary  # noqa: F401

                        workflow_result["interactive_cancelled"] = True
                    except ImportError:
                        workflow_result["missing_questionary"] = True
                    return workflow_result

                if not output_dir_str:
                    workflow_result["interactive_cancelled"] = True
                    return workflow_result

                # Extract selected messages
                assert ctx.storage is not None
                async with MessageExtractor(ctx.storage.db) as extractor:
                    stats = await extractor.batch_extract(selected_ids, Path(output_dir_str))

                workflow_result["extraction_stats"] = {
                    "selected": len(selected_ids),
                    "extracted": stats["extracted"],
                    "failed": stats["failed"],
                    "errors": stats["errors"],
                    "output_dir": output_dir_str,
                }
                return workflow_result

            # Handle extract mode
            if extract and output_dir:
                gmail_ids = [r.gmail_id for r in results.results]
                assert ctx.storage is not None
                async with MessageExtractor(ctx.storage.db) as extractor:
                    stats = await extractor.batch_extract(gmail_ids, Path(output_dir))

                workflow_result["extraction_stats"] = {
                    "selected": len(gmail_ids),
                    "extracted": stats["extracted"],
                    "failed": stats["failed"],
                    "errors": stats["errors"],
                    "output_dir": output_dir,
                }

            return workflow_result

        except ValueError as e:
            return {"status": "error", "error_type": "ValueError", "error_message": str(e)}
        except Exception as e:
            return {"status": "error", "error_type": "Exception", "error_message": str(e)}

    # Execute single async workflow
    workflow_result = asyncio.run(_search_workflow())

    # Handle errors
    if workflow_result["status"] == "error":
        error_type = workflow_result.get("error_type", "Exception")
        error_message = workflow_result.get("error_message", "Unknown error")

        if error_type == "ValueError":
            ctx.fail_and_exit(
                "Search Query Error",
                error_message,
                suggestion="Check your search query syntax",
            )
        else:
            ctx.fail_and_exit("Search Failed", error_message)

    # Handle missing questionary
    if workflow_result.get("missing_questionary"):
        ctx.fail_and_exit(
            "Missing Dependency",
            "Interactive mode requires the 'questionary' package",
            suggestion="Install with: pip install questionary",
        )

    # Handle interactive cancellation
    if workflow_result.get("interactive_cancelled"):
        ctx.info("No messages selected. Cancelled.")
        return

    # Display search results
    from gmailarchiver.cli._output_search import (
        display_search_results_json,
        display_search_results_rich,
    )
    from gmailarchiver.cli.output import SearchResultEntry

    results = workflow_result["results"]
    execution_time_ms = workflow_result["execution_time_ms"]

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
                "Query": effective_query,
                "Results Found": results.total_results,
                "Execution Time": f"{execution_time_ms:.2f}ms",
            }
            ctx.show_report("Search Summary", report_data)

    # Display extraction results if any
    extraction_stats = workflow_result.get("extraction_stats")
    if extraction_stats:
        if interactive:
            ctx.info(
                f"\nExtracted {extraction_stats['extracted']} of "
                f"{extraction_stats['selected']} selected messages to {extraction_stats['output_dir']}"
            )
        else:
            ctx.info(
                f"\nExtracted {extraction_stats['extracted']} messages to {extraction_stats['output_dir']}"
            )

        extraction_report = {
            "Messages Extracted": extraction_stats["extracted"],
            "Failed": extraction_stats["failed"],
            "Output Directory": extraction_stats["output_dir"],
        }
        if interactive:
            extraction_report["Messages Selected"] = extraction_stats["selected"]
        ctx.show_report("Extraction Summary", extraction_report)

        if extraction_stats["errors"]:
            ctx.warning(f"Encountered {len(extraction_stats['errors'])} error(s):")
            for error in extraction_stats["errors"][:5]:
                ctx.info(f"  • {error}")
            if len(extraction_stats["errors"]) > 5:
                ctx.info(f"  ... and {len(extraction_stats['errors']) - 5} more")


@app.command()
@with_context(requires_storage=True, operation_name="extract")
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
        assert ctx.storage is not None, "Storage should be initialized by @with_context"
        storage_db = ctx.storage.db  # Capture for async closure

        async def _extract_message() -> bytes:
            async with MessageExtractor(storage_db) as extractor:
                # Try extracting by gmail_id first, then by rfc_message_id
                try:
                    return await extractor.extract_by_gmail_id(message_id, output_file)
                except ExtractorError:
                    # Not found by gmail_id, try rfc_message_id
                    return await extractor.extract_by_rfc_message_id(message_id, output_file)

        try:
            message_bytes = asyncio.run(_extract_message())
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
@with_context(requires_storage=True, has_progress=True, operation_name="import")
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

    # Expand glob pattern first (sync - fast I/O)
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

    async def _import_workflow() -> dict[str, Any]:
        """Single async workflow for import command."""
        assert ctx.storage is not None, "Storage should be initialized by @with_context"

        try:
            # Handle database schema using centralized SchemaManager
            if db_path.exists():
                schema_mgr = SchemaManager(db_path)
                version = await schema_mgr.detect_version()

                if version == SchemaVersion.NONE:
                    # Empty database file exists - delete it and let DBManager create a fresh one
                    try:
                        db_path.unlink()
                    except Exception as e:
                        return {
                            "status": "error",
                            "error_title": "Database Error",
                            "error_message": f"Failed to delete empty database: {e}",
                            "suggestion": "Check file permissions and try again",
                        }
                elif not await schema_mgr.is_supported():
                    return {
                        "status": "error",
                        "error_title": "Unsupported Database",
                        "error_message": f"Unsupported database schema version: {version.value}",
                        "suggestion": "Delete the database or use --state-db with a different path",
                    }
                elif await schema_mgr.needs_migration():
                    # Auto-migrate to current version
                    try:
                        await schema_mgr.auto_migrate_if_needed(
                            progress_callback=lambda msg: ctx.info(msg)
                        )
                    except Exception as e:
                        return {
                            "status": "error",
                            "error_title": "Migration Failed",
                            "error_message": f"Failed to migrate database: {e}",
                            "suggestion": "Run 'gmailarchiver migrate' manually for more details",
                        }

            # Import each file
            importer = ImporterFacade(ctx.storage.db, gmail_client=gmail_client)
            results: list[Any] = []
            start_time = time.perf_counter()

            # Count messages first (sync operation in importer)
            file_message_counts: list[int] = []
            total_messages = 0
            for file_path in files:
                count = importer.count_messages(file_path)
                file_message_counts.append(count)
                total_messages += count

            # Import each file
            import_errors: list[str] = []
            for file_idx, file_path in enumerate(files):
                try:
                    result = await importer.import_archive(
                        file_path,
                        account_id=account_id,
                        skip_duplicates=skip_duplicates,
                        progress_callback=None,  # Progress handled in sync UI
                    )
                    results.append(result)
                except Exception as e:
                    import_errors.append(f"Error importing {file_path}: {e}")

            total_time = time.perf_counter() - start_time

            # Auto-verify if requested
            verify_issues: list[str] | None = None
            if auto_verify and results:
                total_failed = sum(r.messages_failed for r in results)
                if total_failed == 0:
                    try:
                        verify_issues = await ctx.storage.db.verify_database_integrity()
                    except Exception as e:
                        verify_issues = [f"Verification failed: {e}"]

            return {
                "status": "success",
                "results": results,
                "total_time": total_time,
                "total_messages": total_messages,
                "file_message_counts": file_message_counts,
                "import_errors": import_errors,
                "verify_issues": verify_issues,
            }

        except Exception as e:
            return {"status": "error", "error_message": str(e)}

    # Execute single async workflow
    workflow_result = asyncio.run(_import_workflow())

    # Handle errors
    if workflow_result["status"] == "error":
        error_title = workflow_result.get("error_title", "Import Failed")
        error_message = workflow_result.get("error_message", "Unknown error")
        suggestion = workflow_result.get("suggestion")
        ctx.fail_and_exit(error_title, error_message, suggestion=suggestion)

    # Extract results
    results = workflow_result["results"]
    total_time = workflow_result["total_time"]
    total_messages = workflow_result["total_messages"]
    import_errors = workflow_result.get("import_errors", [])
    verify_issues = workflow_result.get("verify_issues")

    # Show progress info
    ctx.success(f"Counted {total_messages:,} messages across {len(files)} file(s)")
    ctx.success(f"Imported messages from {len(results)} file(s)")

    # Show import errors
    for error in import_errors:
        ctx.warning(error)

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

    # Show verification results
    if verify_issues is not None:
        if not verify_issues:
            ctx.success("Verification complete - no issues found")
        else:
            ctx.warning(f"Verification found {len(verify_issues)} issue(s):")
            for issue in verify_issues[:5]:
                ctx.info(f"  • {issue}")
            if len(verify_issues) > 5:
                ctx.info(f"  ... and {len(verify_issues) - 5} more issues")
            ctx.suggest_next_steps(
                [
                    "Fix issues automatically: gmailarchiver check --auto-repair",
                    "View all issues: gmailarchiver verify-integrity --verbose",
                ]
            )


@app.command()
@with_context(requires_storage=True, has_progress=True, operation_name="consolidate")
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

    # 1. Expand glob patterns (sync - fast I/O)
    all_files: list[str] = []
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
    effective_compress = compress
    if effective_compress is None:
        output_path = Path(output_file)
        if output_path.suffix == ".gz":
            effective_compress = "gzip"
        elif output_path.suffix == ".xz":
            effective_compress = "lzma"
        elif output_path.suffix == ".zst":
            effective_compress = "zstd"

    # Helper functions for sync operations via asyncio.to_thread
    def _confirm_overwrite() -> bool:
        """Sync confirmation for overwrite."""
        return typer.confirm(f"Output file exists: {output_file}. Overwrite?")

    def _confirm_remove_sources(files: list[Path], total_size: int) -> bool:
        """Sync confirmation for removing source files."""
        ctx.info(f"\nThe following {len(files)} source file(s) will be removed:")
        for file_path in files:
            ctx.info(f"  • {file_path}")
        ctx.info(f"\nTotal space to be freed: {format_bytes(total_size)}")
        return typer.confirm("\nRemove source files?")

    def _validate_archive_sync(archive_path: str) -> tuple[bool, str]:
        """Sync validation of archive (CPU-bound)."""
        validator = ValidatorFacade(archive_path)
        try:
            is_valid = validator.validate_all()
            if not is_valid:
                errors = validator.errors
                error_msg = errors[0] if errors else "Unknown error"
                return False, error_msg
            return True, ""
        finally:
            # ValidatorFacade.close() is async, but we're in sync context
            # The async close will be handled in the workflow
            pass

    async def _consolidate_workflow() -> dict[str, Any]:
        """Single async workflow for consolidate command."""
        assert ctx.storage is not None, "Storage should be initialized by @with_context"
        consolidator = ArchiveConsolidator(ctx.storage.db)

        try:
            # 4. Check if output file exists (with async confirmation)
            output_path = Path(output_file)
            if output_path.exists():
                overwrite = await asyncio.to_thread(_confirm_overwrite)
                if not overwrite:
                    return {"status": "cancelled", "reason": "overwrite_declined"}

            # 5. Consolidate archives
            source_paths: list[str | Path] = [Path(f) for f in all_files]

            result = await consolidator.consolidate(
                source_archives=source_paths,
                output_archive=output_file,
                sort_by_date=sort,
                deduplicate=dedupe,
                dedupe_strategy=dedupe_strategy,
                compress=effective_compress,
            )

            # 6. Auto-verify if requested
            verify_issues: list[str] | None = None
            if auto_verify:
                try:
                    verify_issues = await ctx.storage.db.verify_database_integrity()
                except Exception as e:
                    verify_issues = [f"Verification failed: {e}"]

            # 7. Validate and remove sources if requested
            cleanup_data: dict[str, Any] | None = None
            cleanup_warnings: list[str] = []
            validation_failed = False

            if remove_sources:
                # Validate consolidated archive first
                output_path = Path(result.output_file)
                if not output_path.exists():
                    return {
                        "status": "error",
                        "error_type": "validation",
                        "error_title": "Archive Not Found",
                        "error_message": "Consolidated archive does not exist - source files NOT removed",
                    }

                try:
                    output_size = output_path.stat().st_size
                    if output_size == 0:
                        return {
                            "status": "error",
                            "error_type": "validation",
                            "error_title": "Empty Archive",
                            "error_message": "Consolidated archive appears to be empty - skipping source file removal",
                        }
                except OSError as e:
                    return {
                        "status": "error",
                        "error_type": "validation",
                        "error_title": "Access Error",
                        "error_message": f"Cannot access consolidated archive: {e}",
                    }

                # Validate archive content (CPU-bound via to_thread)
                is_valid, error_msg = await asyncio.to_thread(
                    _validate_archive_sync, str(output_path)
                )
                if not is_valid:
                    return {
                        "status": "error",
                        "error_type": "validation",
                        "error_title": "Validation Failed",
                        "error_message": f"Archive validation failed: {error_msg}",
                        "suggestion": "Please review the consolidated archive before manually removing sources",
                    }

                # Determine which files to remove (exclude output file)
                output_path_resolved = Path(output_file).resolve()
                files_to_remove: list[Path] = []
                total_size = 0

                for source_file in all_files:
                    source_path = Path(source_file).resolve()
                    if source_path != output_path_resolved and source_path.exists():
                        total_size += source_path.stat().st_size
                        files_to_remove.append(source_path)

                if files_to_remove:
                    # Determine if we should proceed with removal
                    should_remove = yes or json_output

                    if not should_remove:
                        should_remove = await asyncio.to_thread(
                            _confirm_remove_sources, files_to_remove, total_size
                        )

                    if should_remove:
                        # Remove source files
                        removed_count = 0
                        freed_space = 0
                        failed_removals: list[str] = []

                        for file_path in files_to_remove:
                            try:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                removed_count += 1
                                freed_space += file_size
                            except FileNotFoundError:
                                pass  # Already deleted
                            except (PermissionError, Exception) as e:
                                failed_removals.append(f"{file_path}: {e}")

                        cleanup_data = {
                            "removed_files": removed_count,
                            "space_freed_bytes": freed_space,
                            "failed_removals": len(failed_removals),
                            "failed_details": failed_removals,
                        }
                    else:
                        cleanup_warnings.append("Source file removal cancelled - files kept")

            return {
                "status": "success",
                "result": result,
                "verify_issues": verify_issues,
                "cleanup_data": cleanup_data,
                "cleanup_warnings": cleanup_warnings,
            }

        except ValueError as e:
            return {"status": "error", "error_type": "ValueError", "error_message": str(e)}
        except FileNotFoundError as e:
            return {"status": "error", "error_type": "FileNotFoundError", "error_message": str(e)}
        except Exception as e:
            return {"status": "error", "error_type": "Exception", "error_message": str(e)}
        finally:
            if ctx.storage:
                await ctx.storage.db.close()

    # Execute single async workflow
    workflow_result = asyncio.run(_consolidate_workflow())

    # Handle result based on status
    if workflow_result["status"] == "cancelled":
        ctx.info("Consolidation cancelled")
        raise typer.Exit(0)

    if workflow_result["status"] == "error":
        error_type = workflow_result.get("error_type", "Exception")
        error_message = workflow_result.get("error_message", "Unknown error")
        error_title = workflow_result.get("error_title")
        suggestion = workflow_result.get("suggestion")

        if error_title:
            ctx.fail_and_exit(error_title, error_message, suggestion=suggestion)
        elif error_type == "ValueError":
            ctx.fail_and_exit("Validation Error", error_message)
        elif error_type == "FileNotFoundError":
            ctx.fail_and_exit("File Not Found", error_message)
        else:
            ctx.fail_and_exit(
                "Consolidation Failed",
                error_message,
                suggestion="Check archive files and try again",
            )

    # Success - display results
    result = workflow_result["result"]
    verify_issues = workflow_result.get("verify_issues")
    cleanup_data = workflow_result.get("cleanup_data")
    cleanup_warnings = workflow_result.get("cleanup_warnings", [])

    # Show consolidation progress summary
    ctx.success(
        f"Consolidated {result.messages_consolidated:,} messages from "
        f"{len(result.source_files)} archive(s)"
    )

    # Show verification results if auto-verify was used
    if verify_issues is not None:
        if not verify_issues:
            ctx.success("Database integrity verified - no issues found")
        else:
            ctx.warning(f"Verification found {len(verify_issues)} issue(s):")
            for issue in verify_issues[:5]:
                ctx.info(f"  • {issue}")
            if len(verify_issues) > 5:
                ctx.info(f"  ... and {len(verify_issues) - 5} more issues")
            ctx.suggest_next_steps(
                [
                    ("Fix issues automatically: gmailarchiver check --auto-repair"),
                    ("View all issues: gmailarchiver verify-integrity --verbose"),
                ]
            )

    # Show cleanup results
    for warning in cleanup_warnings:
        ctx.info(warning)

    if cleanup_data:
        removed = cleanup_data["removed_files"]
        freed = cleanup_data["space_freed_bytes"]
        failed = cleanup_data["failed_removals"]

        if removed > 0:
            ctx.success(f"Removed {removed} source file(s), freed {format_bytes(freed)}")

        if failed > 0:
            ctx.warning(f"Failed to remove {failed} file(s):")
            for failure in cleanup_data.get("failed_details", [])[:3]:
                ctx.info(f"  • {failure}")

        # Add cleanup data to JSON events for scripting
        if json_output:
            ctx.output._json_events.append({"event": "cleanup", **cleanup_data})

    # Build and show report
    report_data = {
        "Source Archives": len(result.source_files),
        "Total Messages": result.total_messages,
        "Duplicates Deduplicated": result.duplicates_removed,
        "Messages Consolidated": result.messages_consolidated,
        "Sorted by Date": "Yes" if result.sort_applied else "No",
    }

    if result.compression_used:
        report_data["Compression"] = result.compression_used

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

    # JSON mode output
    if json_output and cleanup_data is not None:
        output_payload = {
            "status": "ok",
            "success": True,
            **cleanup_data,
        }
        ctx.output.set_json_payload(output_payload)


@utilities_app.command(name="verify-integrity")
@app.command(name="verify-integrity", hidden=True)
@with_context(requires_storage=True, has_progress=True, operation_name="verify-integrity")
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
    assert ctx.storage is not None, "Storage should be initialized by @with_context"

    issues: list[str] = []

    try:
        with ctx.ui.task_sequence() as seq:
            # Task: Run integrity checks
            with seq.task("Running integrity checks") as t:
                # Access DBManager directly for low-level database operations
                assert ctx.storage is not None
                issues = asyncio.run(ctx.storage.db.verify_database_integrity())

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
@with_context(requires_storage=True, has_progress=True, operation_name="repair")
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
    assert ctx.storage is not None, "Storage should be initialized by @with_context"

    from gmailarchiver.data.migration import MigrationManager

    db_path = Path(state_db)

    # Helper for sync confirmation via asyncio.to_thread
    def _confirm_repair() -> bool:
        """Sync confirmation for repair."""
        ctx.warning("⚠ WARNING: This will modify the database")
        return typer.confirm("Continue with database repair?", default=False)

    async def _repair_workflow() -> dict[str, Any]:
        """Single async workflow for repair command."""
        assert ctx.storage is not None

        try:
            # Get confirmation for non-dry-run
            if not dry_run:
                confirmed = await asyncio.to_thread(_confirm_repair)
                if not confirmed:
                    return {"status": "cancelled"}

            # Phase 1: Fix FTS sync issues
            repairs = await ctx.storage.db.repair_database(dry_run=dry_run)

            # Phase 2: Backfill invalid offsets if requested
            invalid_count = 0
            if backfill:
                invalid_msgs = await ctx.storage.db.get_messages_with_invalid_offsets()
                invalid_count = len(invalid_msgs) if invalid_msgs else 0

                if invalid_msgs:
                    if not dry_run:
                        # Use MigrationManager logic to scan mbox and backfill
                        migrator = MigrationManager(db_path)
                        try:
                            backfilled = await migrator.backfill_offsets_from_mbox(invalid_msgs)
                            repairs["invalid_offsets_fixed"] = backfilled
                        finally:
                            await migrator._close()
                    else:
                        repairs["invalid_offsets_would_fix"] = len(invalid_msgs)

            return {
                "status": "success",
                "repairs": repairs,
                "invalid_count": invalid_count,
            }

        except FileNotFoundError as e:
            return {"status": "error", "error_type": "FileNotFoundError", "error_message": str(e)}
        except Exception as e:
            return {"status": "error", "error_type": "Exception", "error_message": str(e)}

    # Execute single async workflow
    workflow_result = asyncio.run(_repair_workflow())

    # Handle result based on status
    if workflow_result["status"] == "cancelled":
        ctx.info("Repair cancelled")
        raise typer.Exit(0)

    if workflow_result["status"] == "error":
        error_type = workflow_result.get("error_type", "Exception")
        error_message = workflow_result.get("error_message", "Unknown error")

        if error_type == "FileNotFoundError":
            ctx.fail_and_exit("File Not Found", error_message)
        else:
            ctx.fail_and_exit(
                "Repair Failed",
                error_message,
                suggestion="Check the database file and try again",
            )

    # Display progress info
    ctx.info("Phase 1: FTS synchronization complete")
    if backfill:
        invalid_count = workflow_result.get("invalid_count", 0)
        if invalid_count > 0:
            ctx.info(f"Phase 2: Found {invalid_count} messages with invalid offsets")
        else:
            ctx.success("Phase 2: No invalid offsets found")

    # Display results
    repairs = workflow_result["repairs"]
    _display_repair_results(ctx.output, repairs, dry_run)


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
@with_context(requires_storage=True, has_progress=True, operation_name="check")
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
    db_path = Path(state_db)

    # Check if database exists (sync - no async needed)
    if not db_path.exists():
        ctx.fail_and_exit(
            "Database Not Found",
            f"Database not found: {state_db}",
            suggestion="Run 'gmailarchiver archive' to create one, or use --state-db",
        )

    async def _check_workflow() -> dict[str, Any]:
        """Single async workflow for all check operations."""
        from .core.validator import ValidatorFacade

        # Use centralized SchemaManager for version detection
        schema_mgr = SchemaManager(db_path)
        schema_version = await schema_mgr.detect_version()

        if schema_version == SchemaVersion.NONE:
            return {"status": "invalid_database"}

        # Initialize results dictionary
        check_results: dict[str, Any] = {
            "database_integrity": {"passed": False, "issues": [], "error": None},
            "database_consistency": {
                "passed": False,
                "checked": False,
                "report": None,
                "skip_reason": None,
                "error": None,
            },
            "offset_accuracy": {
                "passed": False,
                "checked": False,
                "result": None,
                "skip_reason": None,
                "error": None,
            },
            "fts_synchronization": {"passed": False, "issues": []},
        }

        assert ctx.storage is not None, "Storage should be initialized by @with_context"
        storage_db = ctx.storage.db

        # Helper function for async database query
        async def get_first_archive_file() -> str | None:
            if storage_db.conn is None:
                return None
            cursor = await storage_db.conn.execute(
                "SELECT DISTINCT archive_file FROM messages LIMIT 1"
            )
            row = await cursor.fetchone()
            return row[0] if row else None

        # ==================== CHECK 1: Database Integrity ====================
        try:
            issues = await storage_db.verify_database_integrity()
            if not issues:
                check_results["database_integrity"]["passed"] = True
            else:
                check_results["database_integrity"]["issues"] = issues
        except Exception as e:
            check_results["database_integrity"]["issues"] = [str(e)]
            check_results["database_integrity"]["error"] = str(e)

        # Extract FTS-specific issues from integrity issues
        fts_issues = [
            issue
            for issue in check_results["database_integrity"]["issues"]
            if "FTS" in issue or "fts" in issue.lower()
        ]
        check_results["fts_synchronization"]["passed"] = not fts_issues
        check_results["fts_synchronization"]["issues"] = fts_issues

        # ==================== CHECK 2: Database Consistency ====================
        try:
            archive_file = await get_first_archive_file()
            has_archives = archive_file is not None

            if has_archives and archive_file is not None:
                if Path(archive_file).exists():
                    validator = ValidatorFacade(archive_file, state_db)
                    try:
                        report = await validator.verify_consistency()
                        check_results["database_consistency"]["checked"] = True
                        check_results["database_consistency"]["report"] = report
                        check_results["database_consistency"]["passed"] = report.passed
                    finally:
                        await validator.close()
                else:
                    check_results["database_consistency"]["checked"] = False
                    check_results["database_consistency"]["passed"] = True
                    check_results["database_consistency"]["skip_reason"] = "archive file not found"
            else:
                check_results["database_consistency"]["checked"] = False
                check_results["database_consistency"]["passed"] = True
                check_results["database_consistency"]["skip_reason"] = "no archives in database"
        except Exception as e:
            check_results["database_consistency"]["error"] = str(e)

        # ==================== CHECK 3: Offset Accuracy ====================
        has_offsets = await schema_mgr.has_capability(SchemaCapability.MBOX_OFFSETS)
        if has_offsets:
            try:
                archive_file_for_offset = await get_first_archive_file()

                if archive_file_for_offset and Path(archive_file_for_offset).exists():
                    validator = ValidatorFacade(archive_file_for_offset, state_db)
                    try:
                        result = await validator.verify_offsets()
                        check_results["offset_accuracy"]["checked"] = True
                        check_results["offset_accuracy"]["result"] = result
                        check_results["offset_accuracy"]["passed"] = (
                            result.accuracy_percentage == 100.0
                        )
                    finally:
                        await validator.close()
                else:
                    check_results["offset_accuracy"]["checked"] = False
                    check_results["offset_accuracy"]["passed"] = True
                    check_results["offset_accuracy"]["skip_reason"] = "no accessible archives"
            except Exception as e:
                check_results["offset_accuracy"]["error"] = str(e)
        else:
            check_results["offset_accuracy"]["checked"] = False
            check_results["offset_accuracy"]["passed"] = True
            check_results["offset_accuracy"]["skip_reason"] = "v1.0 schema"

        # Determine overall status
        all_passed = (
            check_results["database_integrity"]["passed"]
            and check_results["database_consistency"]["passed"]
            and check_results["offset_accuracy"]["passed"]
            and check_results["fts_synchronization"]["passed"]
        )

        # ==================== AUTO-REPAIR (if requested and issues found) ====================
        repair_result: dict[str, Any] | None = None
        if not all_passed and auto_repair:
            try:
                repairs = await storage_db.repair_database(dry_run=False)
                total_repairs = sum(repairs.values())

                if total_repairs > 0:
                    # Re-run checks to verify repairs
                    post_repair_issues = await storage_db.verify_database_integrity()
                    repair_result = {
                        "performed": True,
                        "total_repairs": total_repairs,
                        "repairs": repairs,
                        "post_repair_issues": post_repair_issues,
                        "all_resolved": not post_repair_issues,
                    }
                else:
                    repair_result = {
                        "performed": False,
                        "reason": "no automatic repairs available",
                    }
            except Exception as e:
                repair_result = {
                    "performed": False,
                    "error": str(e),
                }

        return {
            "status": "success",
            "check_results": check_results,
            "all_passed": all_passed,
            "repair_result": repair_result,
        }

    # Execute single async workflow
    workflow_result = asyncio.run(_check_workflow())

    # Handle invalid database (sync)
    if workflow_result["status"] == "invalid_database":
        ctx.fail_and_exit(
            "Invalid Database",
            "Database is empty or invalid",
            suggestion="Create with 'gmailarchiver archive' or 'gmailarchiver import'",
        )

    check_results = workflow_result["check_results"]
    all_passed = workflow_result["all_passed"]
    repair_result = workflow_result["repair_result"]

    # ==================== Display Results with Task Sequence ====================
    with ctx.ui.task_sequence() as seq:
        # Database integrity
        with seq.task("Checking database integrity") as t:
            if check_results["database_integrity"]["error"]:
                t.fail("Check failed", reason=check_results["database_integrity"]["error"])
            elif check_results["database_integrity"]["passed"]:
                t.complete("OK")
            else:
                issues = check_results["database_integrity"]["issues"]
                t.complete(f"{len(issues)} issue(s)")
                if verbose:
                    for issue in issues[:5]:
                        ctx.info(f"    • {issue}")

        # Database consistency
        with seq.task("Checking database consistency") as t:
            if check_results["database_consistency"]["error"]:
                t.fail("Check failed", reason=check_results["database_consistency"]["error"])
            elif not check_results["database_consistency"]["checked"]:
                skip_reason = check_results["database_consistency"]["skip_reason"]
                t.complete(f"Skipped ({skip_reason})")
            elif check_results["database_consistency"]["passed"]:
                t.complete("OK")
            else:
                report = check_results["database_consistency"]["report"]
                t.complete(f"{len(report.errors) if report else 0} issue(s)")

        # Offset accuracy
        with seq.task("Checking offset accuracy") as t:
            if check_results["offset_accuracy"]["error"]:
                t.fail("Check failed", reason=check_results["offset_accuracy"]["error"])
            elif not check_results["offset_accuracy"]["checked"]:
                skip_reason = check_results["offset_accuracy"]["skip_reason"]
                t.complete(f"Skipped ({skip_reason})")
            elif check_results["offset_accuracy"]["passed"]:
                result = check_results["offset_accuracy"]["result"]
                if result:
                    t.complete(f"100% ({result.total_checked:,} checked)")
                else:
                    t.complete("OK")
            else:
                result = check_results["offset_accuracy"]["result"]
                if result:
                    t.complete(
                        f"{result.accuracy_percentage:.1f}% "
                        f"({result.successful_reads:,}/{result.total_checked:,})"
                    )

    # ==================== SUMMARY ====================
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

    # ==================== HANDLE AUTO-REPAIR RESULTS ====================
    if repair_result is not None:
        ctx.warning("\n⚠ Auto-repair enabled - attempting to fix issues...")

        if repair_result.get("error"):
            ctx.fail_and_exit(
                title="Auto-Repair Failed",
                message=repair_result["error"],
                suggestion="Run 'gmailarchiver repair --no-dry-run' manually to fix issues",
                exit_code=2,
            )

        if repair_result.get("performed"):
            ctx.success(f"Performed {repair_result['total_repairs']} repair(s)")
            ctx.info("\nRe-checking after repairs...")

            if repair_result["all_resolved"]:
                ctx.success("All issues resolved!")
                raise typer.Exit(0)
            else:
                post_issues = repair_result["post_repair_issues"]
                ctx.warning(f"{len(post_issues)} issue(s) remain after repair")
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
@with_context(requires_storage=True, has_progress=True, operation_name="compress")
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

    assert ctx.storage is not None, "Storage should be initialized by @with_context"
    compressor = ArchiveCompressor(ctx.storage.db)

    async def _compress_workflow() -> Any:
        """Single async workflow for compress command."""
        try:
            return await compressor.compress(
                files=expanded_files,
                format=format,
                in_place=in_place,
                dry_run=dry_run,
                keep_original=keep_original,
            )
        finally:
            await ctx.storage.db.close()

    try:
        # Compress files with progress tracking
        with ctx.output.progress_context(
            f"Compressing {len(expanded_files)} file(s)", total=len(expanded_files)
        ) as progress:
            task = progress.add_task("Compress", total=len(expanded_files)) if progress else None

            result = asyncio.run(_compress_workflow())

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
@with_context(requires_storage=True, has_progress=True, operation_name="doctor")
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

    async def _doctor_workflow() -> dict[str, Any]:
        """Single async workflow for doctor command."""
        try:
            # Initialize doctor
            doctor_instance = await Doctor.create(state_db, validate_schema=False, auto_create=False)

            try:
                # Run diagnostics
                report = await doctor_instance.run_diagnostics()

                # Run auto-fix if requested
                fix_results: list[Any] = []
                if fix and report.fixable_issues:
                    fix_results = await doctor_instance.run_auto_fix()

                # Run internal database checks if --check flag is used
                internal_issues: list[str] | None = None
                if include_check:
                    db_path = Path(state_db)
                    if db_path.exists():
                        assert ctx.storage is not None
                        try:
                            internal_issues = await ctx.storage.db.verify_database_integrity()
                        except Exception as e:
                            internal_issues = [f"Check failed: {e}"]

                return {
                    "status": "success",
                    "report": report,
                    "fix_results": fix_results,
                    "internal_issues": internal_issues,
                }

            finally:
                await doctor_instance.close()

        except Exception as e:
            return {"status": "error", "error_message": str(e)}

    # Execute single async workflow
    workflow_result = asyncio.run(_doctor_workflow())

    # Handle errors
    if workflow_result["status"] == "error":
        ctx.fail_and_exit(
            "Doctor Failed",
            workflow_result.get("error_message", "Unknown error"),
        )

    # Extract results
    from gmailarchiver.core.doctor._diagnostics import CheckSeverity

    report = workflow_result["report"]
    fix_results = workflow_result.get("fix_results", [])
    internal_issues = workflow_result.get("internal_issues")

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

    # Show fix results if auto-fix was run
    if fix_results:
        fixed_count = sum(1 for r in fix_results if r.success)
        failed_count = len(fix_results) - fixed_count

        if not json_output:
            headers = ["Check", "Status", "Message"]
            fix_rows: list[list[str]] = []

            for fix_result in fix_results:
                if fix_result.success:
                    status = "[green]✓ FIXED[/green]"
                else:
                    status = "[red]✗ FAILED[/red]"
                fix_rows.append([fix_result.check_name, status, fix_result.message])

            ctx.show_table("Auto-Fix Results", headers, fix_rows)

        # Show success/failure summary
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

    # Show internal check results
    if include_check:
        ctx.info("\n── Internal Database Checks ──")
        db_path = Path(state_db)
        if db_path.exists():
            if internal_issues is None:
                ctx.warning("Database not found, skipping internal checks")
            elif not internal_issues:
                ctx.success("All internal checks passed")
            else:
                ctx.warning(f"{len(internal_issues)} issue(s) found")
                for issue in internal_issues[:5]:
                    ctx.info(f"  • {issue}")
                if len(internal_issues) > 5:
                    ctx.info(f"  ... and {len(internal_issues) - 5} more")
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

        if fix_results:
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
@with_context(
    requires_storage=True,
    requires_gmail=True,
    has_progress=True,
    operation_name="backfill-gmail-ids",
)
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

    # Pattern to detect synthetic gmail_ids (start with 000...)
    synthetic_id_pattern = re.compile(r"^0{3,}[0-9a-f]+$", re.IGNORECASE)

    async def _backfill_workflow() -> dict[str, Any]:
        """Single async workflow for backfill command."""
        try:
            # Gmail client and storage are already initialized via @with_context
            assert ctx.gmail is not None, "Gmail client should be initialized"
            assert ctx.storage is not None, "Storage should be initialized"
            client = ctx.gmail
            storage_db = ctx.storage.db

            # Get all messages from database
            if storage_db.conn is None:
                return {"status": "error", "error_message": "Database connection not initialized"}

            cursor = await storage_db.conn.execute(
                "SELECT gmail_id, rfc_message_id FROM messages"
            )
            rows = await cursor.fetchall()
            all_messages = [(row[0], row[1]) for row in rows]

            # Categorize messages
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

            # Early return if no backfill needed
            if not messages_needing_backfill:
                return {
                    "status": "success",
                    "no_backfill_needed": True,
                    "total_messages": len(all_messages),
                    "real_count": real_messages_count,
                    "null_count": null_gmail_id_count,
                    "synthetic_count": synthetic_gmail_id_count,
                }

            # Apply offset and limit
            messages_to_process = messages_needing_backfill[offset:]
            if limit > 0:
                messages_to_process = messages_to_process[:limit]

            # Extract rfc_message_ids for batch lookup
            rfc_ids_to_lookup = [rfc for _, rfc in messages_to_process]

            # Use batch lookup
            results = await client.search_by_rfc_message_ids_batch(
                rfc_ids_to_lookup,
                progress_callback=None,  # Progress handled in sync UI
                batch_size=batch_size,
            )

            # Process results
            found = 0
            not_found = 0
            updates: list[tuple[str | None, str]] = []

            for rfc_id, gmail_id in results.items():
                if gmail_id:
                    found += 1
                    updates.append((gmail_id, rfc_id))
                else:
                    not_found += 1

            # Update database if not dry run
            if not dry_run and updates:
                for new_gmail_id, rfc_message_id in updates:
                    await storage_db.conn.execute(
                        "UPDATE messages SET gmail_id = ? WHERE rfc_message_id = ?",
                        (new_gmail_id, rfc_message_id),
                    )
                await storage_db.conn.commit()

            return {
                "status": "success",
                "no_backfill_needed": False,
                "total_messages": len(all_messages),
                "real_count": real_messages_count,
                "null_count": null_gmail_id_count,
                "synthetic_count": synthetic_gmail_id_count,
                "total_needing_backfill": len(messages_needing_backfill),
                "processed": len(messages_to_process),
                "found": found,
                "not_found": not_found,
                "updates": updates,
                "remaining": len(messages_needing_backfill) - len(messages_to_process) - offset,
            }

        except Exception as e:
            return {"status": "error", "error_message": str(e)}

    # Execute single async workflow
    workflow_result = asyncio.run(_backfill_workflow())

    # Handle errors
    if workflow_result["status"] == "error":
        ctx.fail_and_exit(
            title="Backfill Failed",
            message=workflow_result.get("error_message", "Unknown error"),
            suggestion="Check your internet connection and Gmail authentication",
        )

    # Display scan results
    ctx.info(f"Total messages in database: {workflow_result['total_messages']:,}")
    ctx.info(f"Messages with real Gmail IDs: {workflow_result['real_count']:,}")
    ctx.info(f"Messages with NULL gmail_id: {workflow_result['null_count']:,}")
    ctx.info(f"Messages with synthetic IDs: {workflow_result['synthetic_count']:,}")

    # Handle no backfill needed
    if workflow_result.get("no_backfill_needed"):
        ctx.success("No messages need backfill!")
        return

    ctx.info(f"Total needing backfill: {workflow_result['total_needing_backfill']:,}")

    if offset > 0:
        ctx.info(f"Skipping first {offset} messages (--offset)")
    if limit > 0:
        ctx.info(f"Processing up to {limit} messages (--limit)")

    ctx.info(f"\nProcessed {workflow_result['processed']:,} messages in batches of {batch_size}")

    if dry_run:
        ctx.warning("[DRY RUN] No changes were made")

    # Display results
    ctx.info("\nResults:")
    ctx.info(f"  Found in Gmail: {workflow_result['found']:,}")
    ctx.info(f"  Not in Gmail (deleted): {workflow_result['not_found']:,}")

    updates = workflow_result.get("updates", [])
    if dry_run:
        ctx.warning(f"\n[DRY RUN] Would update {len(updates):,} messages")
        if updates[:5]:
            ctx.info("Sample updates:")
            for new_id, rfc_id in updates[:5]:
                status = new_id[:16] + "..." if new_id else "NULL"
                rfc_display = rfc_id[:40] + "..." if len(rfc_id) > 40 else rfc_id
                ctx.info(f"  {rfc_display} -> {status}")
    elif updates:
        ctx.success(f"Database updated with {len(updates):,} changes!")

    # Summary for resumption
    remaining = workflow_result.get("remaining", 0)
    if remaining > 0:
        ctx.info(f"\nRemaining messages to process: {remaining:,}")
        next_offset = offset + workflow_result["processed"]
        ctx.info(f"Resume with: --offset {next_offset}")


if __name__ == "__main__":
    app()
