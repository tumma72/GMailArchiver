"""Validate command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.output import OutputManager
from gmailarchiver.core.workflows.validate import ValidateConfig, ValidateWorkflow
from gmailarchiver.data.hybrid_storage import HybridStorage


def validate(
    archive_file: str = typer.Argument(..., help="Path to archive file to validate"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed validation output"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Validate an existing archive file.

    Example:
        $ gmailarchiver validate archive_20250113.mbox.gz
        $ gmailarchiver validate archive.mbox --verbose
        $ gmailarchiver validate archive.mbox --json
    """
    output = OutputManager(json_mode=json_output)

    # Check if archive file exists
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

    async def _run() -> None:
        """Run validate workflow."""
        # Create database manager and storage
        from gmailarchiver.data.db_manager import DBManager

        db_manager = DBManager(state_db, validate_schema=False, auto_create=False)
        await db_manager.initialize()
        storage = HybridStorage(db_manager, preload_rfc_ids=False)

        # Create workflow and config
        workflow = ValidateWorkflow(storage)
        config = ValidateConfig(archive_file=archive_file, state_db=state_db, verbose=verbose)

        # Run workflow
        try:
            result = await workflow.run(config)
        except FileNotFoundError as e:
            output.error(
                str(e),
                suggestion="Check the file path or use 'gmailarchiver status' to list archives",
                exit_code=1,
            )
            return
        except Exception as e:
            output.error(
                f"Failed to validate: {e}",
                suggestion="Check database file permissions and integrity",
                exit_code=1,
            )
            return
        finally:
            await db_manager.close()

        # Format and display result
        if json_output:
            output.set_json_payload(
                {
                    "passed": result.passed,
                    "count_check": result.count_check,
                    "database_check": result.database_check,
                    "integrity_check": result.integrity_check,
                    "spot_check": result.spot_check,
                    "errors": result.errors,
                    "details": result.details,
                }
            )
            output.end_operation(success=result.passed)
        else:
            # Build validation results dict for show_validation_report
            validation_dict = {
                "passed": result.passed,
                "count_check": result.count_check,
                "database_check": result.database_check,
                "integrity_check": result.integrity_check,
                "spot_check": result.spot_check,
                "errors": result.errors,
            }

            # Add verbose details if available
            if result.details:
                validation_dict.update(result.details)

            # Show detailed validation panel only on failure or with --verbose
            if not result.passed or verbose:
                output.show_validation_report(validation_dict, title="Archive Validation")

            # Handle failure with suggestions
            if not result.passed:
                suggestions = []

                if not result.database_check:
                    suggestions.append(
                        f"Import archive into database: gmailarchiver import {archive_file} "
                        f"--state-db {state_db}"
                    )

                if not result.integrity_check:
                    suggestions.append("Check archive file for corruption or try re-downloading")

                if not result.count_check or not result.spot_check:
                    suggestions.append(
                        f"Verify database integrity: gmailarchiver verify-integrity "
                        f"--state-db {state_db}"
                    )
                    suggestions.append(
                        f"Repair database if needed: gmailarchiver repair --no-dry-run "
                        f"--state-db {state_db}"
                    )

                if suggestions:
                    output.suggest_next_steps(suggestions)

                raise typer.Exit(1)
            else:
                # Success message
                output.success("Archive validation passed")

    asyncio.run(_run())
