"""Validate command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import (
    CLIProgressAdapter,
    SuggestionList,
    ValidationPanel,
)
from gmailarchiver.core.workflows.validate import (
    ValidateConfig,
    ValidateResult,
    ValidateWorkflow,
)


@with_context(requires_storage=True, has_progress=True, operation_name="validate")
def validate(
    ctx: CommandContext,
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
    asyncio.run(
        _run_validate(
            ctx=ctx,
            archive_file=archive_file,
            state_db=state_db,
            verbose=verbose,
        )
    )


async def _run_validate(
    ctx: CommandContext,
    archive_file: str,
    state_db: str,
    verbose: bool,
) -> None:
    """Async implementation of validate command."""
    # Phase 1: Validate inputs
    archive_path = Path(archive_file)
    if not archive_path.exists():
        ctx.fail_and_exit(
            title="File Not Found",
            message=f"Archive file not found: {archive_file}",
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
        )

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

    # Phase 2: Create workflow and config
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = ValidateWorkflow(ctx.storage, progress=progress)
    config = ValidateConfig(
        archive_file=archive_file,
        state_db=state_db,
        verbose=verbose,
    )

    # Phase 3: Execute workflow
    try:
        with progress.workflow_sequence(show_logs=True, max_logs=5):
            result = await workflow.run(config)
    except FileNotFoundError as e:
        ctx.fail_and_exit(
            title="File Error",
            message=str(e),
            suggestion="Check the file path or use 'gmailarchiver status' to list archives",
        )
    except Exception as e:
        ctx.fail_and_exit(
            title="Validation Failed",
            message=f"Failed to validate archive: {e}",
            suggestion="Check database file permissions and integrity",
        )

    # Phase 4: Handle results
    if ctx.output.json_mode:
        _handle_json_output(ctx, result)
    elif result.passed:
        _show_success(ctx, result, verbose)
    else:
        _show_failure(ctx, result, archive_file, state_db, verbose)


def _handle_json_output(ctx: CommandContext, result: ValidateResult) -> None:
    """Handle JSON output mode."""
    ctx.output.set_json_payload(
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
    ctx.output.end_operation(success=result.passed)


def _show_success(ctx: CommandContext, result: ValidateResult, verbose: bool) -> None:
    """Show successful validation."""
    # Show validation panel with verbose flag
    if verbose:
        _build_validation_panel(result).render(ctx.output)

    # Success message
    ctx.success("Archive validation passed")

    # Suggest next steps
    (
        SuggestionList()
        .add("Safe to delete from Gmail: gmailarchiver archive <age> --trash")
        .add("View archive status: gmailarchiver status")
        .render(ctx.output)
    )


def _show_failure(
    ctx: CommandContext,
    result: ValidateResult,
    archive_file: str,
    state_db: str,
    verbose: bool,
) -> None:
    """Show validation failure."""
    # Always show validation panel on failure
    _build_validation_panel(result).render(ctx.output)

    # Build contextual suggestions
    suggestions = SuggestionList()

    if not result.database_check:
        suggestions.add(
            f"Import archive into database: gmailarchiver import {archive_file} "
            f"--state-db {state_db}"
        )

    if not result.integrity_check:
        suggestions.add("Check archive file for corruption or try re-downloading")

    if not result.count_check or not result.spot_check:
        suggestions.add(
            f"Verify database integrity: gmailarchiver utilities verify-integrity "
            f"--state-db {state_db}"
        )
        suggestions.add(
            f"Repair database if needed: gmailarchiver utilities repair --no-dry-run "
            f"--state-db {state_db}"
        )

    if not suggestions.is_empty():
        suggestions.render(ctx.output)

    # Exit with error
    raise typer.Exit(1)


def _build_validation_panel(result: ValidateResult) -> ValidationPanel:
    """Build ValidationPanel from result."""
    panel = (
        ValidationPanel("Archive Validation")
        .add_check("Count check", passed=result.count_check)
        .add_check("Database check", passed=result.database_check)
        .add_check("Integrity check", passed=result.integrity_check)
        .add_check("Spot check", passed=result.spot_check)
    )

    if result.errors:
        panel.add_errors(result.errors)

    return panel
