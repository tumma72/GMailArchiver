"""Verify commands implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import ReportCard, SuggestionList
from gmailarchiver.core.workflows.verify import VerifyConfig, VerifyType, VerifyWorkflow


async def verify_integrity_command(
    ctx: CommandContext,
    state_db: str,
    json_output: bool,
) -> None:
    """Async implementation of verify-integrity command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check database path or archive emails first",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    workflow = VerifyWorkflow(ctx.storage)
    config = VerifyConfig(verify_type=VerifyType.INTEGRITY, state_db=state_db)

    try:
        result = await workflow.run(config)
    except Exception as e:
        ctx.fail_and_exit(
            title="Verification Failed",
            message=f"Failed to verify integrity: {e}",
            suggestion="Check database file permissions",
        )
        return

    # Display results
    (
        ReportCard("Database Integrity")
        .add_field("Verification Type", result.verify_type)
        .add_field("Passed", "Yes" if result.passed else "No")
        .add_field("Issues Found", str(result.issues_found))
        .render(ctx.output)
    )

    if not result.passed:
        SuggestionList().add("Repair database: gmailarchiver utilities repair --no-dry-run").add(
            "Restore from backup: gmailarchiver utilities rollback"
        ).render(ctx.output)
        raise SystemExit(1)


async def verify_consistency_command(
    ctx: CommandContext,
    state_db: str,
    json_output: bool,
) -> None:
    """Async implementation of verify-consistency command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check database path or archive emails first",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    workflow = VerifyWorkflow(ctx.storage)
    config = VerifyConfig(verify_type=VerifyType.CONSISTENCY, state_db=state_db)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Verifying database/mbox consistency") as t:
            try:
                result = await workflow.run(config)
                if result.passed:
                    t.complete("Database and mbox files are consistent")
                else:
                    t.fail("Consistency check failed")
            except Exception as e:
                t.fail("Verification error", reason=str(e))
                ctx.fail_and_exit(
                    title="Verification Failed",
                    message=f"Failed to verify consistency: {e}",
                    suggestion="Check database and mbox file permissions",
                )
                return

    # Display detailed results
    (
        ReportCard("Database/Mbox Consistency")
        .add_field("Verification Type", result.verify_type)
        .add_field("Passed", "Yes" if result.passed else "No")
        .add_field("Issues Found", str(result.issues_found))
        .render(ctx.output)
    )

    if not result.passed:
        SuggestionList().add(
            "Repair database: gmailarchiver utilities repair --backfill --no-dry-run"
        ).add("Re-import archives: gmailarchiver utilities import archive.mbox").render(ctx.output)
        raise SystemExit(1)


async def verify_offsets_command(
    ctx: CommandContext,
    state_db: str,
    json_output: bool,
) -> None:
    """Async implementation of verify-offsets command."""
    db_path = Path(state_db)

    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion="Check database path or archive emails first",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True
    workflow = VerifyWorkflow(ctx.storage)
    config = VerifyConfig(verify_type=VerifyType.OFFSETS, state_db=state_db)

    with ctx.ui.task_sequence() as seq:
        with seq.task("Verifying mbox offsets") as t:
            try:
                result = await workflow.run(config)
                if result.passed:
                    t.complete("All mbox offsets are valid")
                else:
                    t.fail("Offset validation failed")
            except Exception as e:
                t.fail("Verification error", reason=str(e))
                ctx.fail_and_exit(
                    title="Verification Failed",
                    message=f"Failed to verify offsets: {e}",
                    suggestion="Check mbox file accessibility",
                )
                return

    # Display detailed results
    (
        ReportCard("Mbox Offset Verification")
        .add_field("Verification Type", result.verify_type)
        .add_field("Passed", "Yes" if result.passed else "No")
        .add_field("Issues Found", str(result.issues_found))
        .render(ctx.output)
    )

    if not result.passed:
        SuggestionList().add(
            "Repair offsets: gmailarchiver utilities repair --backfill --no-dry-run"
        ).add("Re-import archives: gmailarchiver utilities import archive.mbox").render(ctx.output)
        raise SystemExit(1)
