"""Status command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.output import OutputManager
from gmailarchiver.core.workflows.status import StatusConfig, StatusWorkflow
from gmailarchiver.shared.utils import format_bytes


def status(
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
    output = OutputManager(json_mode=json_output)
    db_path = Path(state_db)

    async def _run() -> None:
        """Run status workflow."""
        # Create workflow and config
        workflow = StatusWorkflow()
        config = StatusConfig(state_db=db_path, verbose=verbose)

        # Run workflow
        try:
            result = await workflow.run(config)
        except FileNotFoundError:
            output.warning("No archive database found")
            output.suggest_next_steps(
                [
                    "Archive emails: gmailarchiver archive 3y",
                    "Import existing archive: gmailarchiver import archive.mbox",
                ]
            )
            return
        except Exception as e:
            output.error(
                f"Error reading database: {e}",
                suggestion="Check database file integrity or run 'gmailarchiver doctor'",
                exit_code=1,
            )
            return

        # Format and display result
        if json_output:
            output.set_json_payload(
                {
                    "schema_version": result.schema_version,
                    "database_size_bytes": result.database_size_bytes,
                    "total_messages": result.total_messages,
                    "archive_files_count": result.archive_files_count,
                    "archive_files_sample": result.archive_files_sample,
                    "recent_runs": result.recent_runs,
                }
            )
            output.end_operation(success=True)
        else:
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
                        f"{result.archive_files_count} "
                        f"(recent: {result.archive_files_sample[-1][:25]}...)"
                    )
                elif result.archive_files_count == 1:
                    # For single archive file, show the name even in non-verbose mode
                    report_data["Archive Files"] = (
                        f"{result.archive_files_count} ({result.archive_files_sample[0]})"
                    )

            output.show_report("Archive Status", report_data)

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
                output.show_table(table_title, headers, rows)
            else:
                output.warning("No archive runs found")

    asyncio.run(_run())
