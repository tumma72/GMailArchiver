from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.core.workflows.status import StatusConfig, StatusWorkflow
from gmailarchiver.shared.utils import format_bytes


async def status_command(
    ctx: CommandContext,
    state_db: str,
    verbose: bool,
    json_output: bool,
) -> None:
    """Async implementation of the status command."""
    db_path = Path(state_db)

    workflow = StatusWorkflow()
    config = StatusConfig(state_db=db_path, verbose=verbose)

    try:
        result = await workflow.run(config)
    except FileNotFoundError:
        ctx.warning("No archive database found")
        ctx.suggest_next_steps(
            [
                "Archive emails: gmailarchiver archive 3y",
                "Import existing archive: gmailarchiver import archive.mbox",
            ]
        )
        return
    except Exception as e:
        ctx.fail_and_exit(
            title="Status Error",
            message=f"Error reading database: {e}",
            suggestion="Check database file integrity or run 'gmailarchiver doctor'",
        )
        return

    # Build report data
    report_data: dict[str, str] = {
        "Schema Version": result.schema_version,
        "Database Size": format_bytes(result.database_size_bytes),
        "Total Messages": f"{result.total_messages:,}",
        "Archive Files": str(result.archive_files_count),
    }

    # Add archive file details
    if result.archive_files_sample:
        if verbose:
            report_data["Archive Files"] = (
                f"{result.archive_files_count} (recent: {result.archive_files_sample[-1][:25]}...)"
            )
        elif result.archive_files_count == 1:
            # For single archive file, show the name even in non-verbose mode
            report_data["Archive Files"] = (
                f"{result.archive_files_count} ({result.archive_files_sample[0]})"
            )

    ctx.show_report("Archive Status", report_data)

    # Display recent runs table
    run_limit = 10 if verbose else 5
    if result.recent_runs:
        if verbose:
            headers = ["Run ID", "Timestamp", "Query", "Messages", "Archive File"]
            rows: list[list[str]] = []
            for run in result.recent_runs:
                rows.append(
                    [
                        str(run["run_id"]),
                        str(run["run_timestamp"])[:19],
                        str(run["query"])[:30] if run["query"] else "",
                        str(run["messages_archived"]),
                        str(run["archive_file"]),
                    ]
                )
        else:
            headers = ["Run ID", "Timestamp", "Messages", "Archive File"]
            rows = []
            for run in result.recent_runs:
                rows.append(
                    [
                        str(run["run_id"]),
                        str(run["run_timestamp"])[:19],
                        str(run["messages_archived"]),
                        str(run["archive_file"]),
                    ]
                )

        table_title = f"Recent Archive Runs (Last {run_limit})"
        ctx.show_table(table_title, headers, rows)
    else:
        ctx.warning("No archive runs found")
