"""Doctor command handler implementation."""

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import (
    CLIProgressAdapter,
    ReportCard,
    SuggestionList,
    ValidationPanel,
)
from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.workflows.doctor import DoctorConfig, DoctorResult, DoctorWorkflow


async def _run_doctor(
    ctx: CommandContext,
    verbose: bool,
    json_output: bool,
) -> None:
    """Async implementation of doctor command."""
    assert ctx.storage is not None  # Guaranteed by @with_context(requires_storage=True)

    # Create workflow with storage
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = DoctorWorkflow(ctx.storage, progress=progress)
    config = DoctorConfig(verbose=verbose)

    # Run diagnostics workflow
    with progress.workflow_sequence(show_logs=verbose):
        result = await workflow.run(config)

    # Handle JSON output
    if json_output:
        ctx.output.set_json_payload(
            {
                "overall_status": result.overall_status.value,
                "checks_passed": result.checks_passed,
                "total_checks": len(result.checks),
                "warnings": result.warnings,
                "errors": result.errors,
                "fixable_issues": result.fixable_issues,
                "checks": [
                    {
                        "name": c.name,
                        "severity": c.severity.value,
                        "message": c.message,
                        "fixable": c.fixable,
                        "details": c.details,
                    }
                    for c in result.checks
                ],
            }
        )
        return

    # Display results by category using ValidationPanel
    _display_database_checks(ctx, result.database_checks, verbose)
    _display_environment_checks(ctx, result.environment_checks, verbose)
    _display_system_checks(ctx, result.system_checks, verbose)

    # Display summary
    _display_summary(ctx, result)


def _display_database_checks(
    ctx: CommandContext,
    checks: list[CheckResult],
    verbose: bool,
) -> None:
    """Display archive and database diagnostics."""
    if not checks:
        return

    panel = ValidationPanel("Archive Health")
    for check in checks:
        panel.add_check(
            check.name,
            passed=(check.severity == CheckSeverity.OK),
            detail=check.message if verbose else None,
        )
    panel.render_if_failures_or_verbose(ctx.output, verbose)


def _display_environment_checks(
    ctx: CommandContext,
    checks: list[CheckResult],
    verbose: bool,
) -> None:
    """Display environment diagnostics."""
    if not checks:
        return

    panel = ValidationPanel("Environment Health")
    for check in checks:
        panel.add_check(
            check.name,
            passed=(check.severity == CheckSeverity.OK),
            detail=check.message if verbose else None,
        )
    panel.render_if_failures_or_verbose(ctx.output, verbose)


def _display_system_checks(
    ctx: CommandContext,
    checks: list[CheckResult],
    verbose: bool,
) -> None:
    """Display system health diagnostics."""
    if not checks:
        return

    panel = ValidationPanel("System Health")
    for check in checks:
        panel.add_check(
            check.name,
            passed=(check.severity == CheckSeverity.OK),
            detail=check.message if verbose else None,
        )
    panel.render_if_failures_or_verbose(ctx.output, verbose)


def _display_summary(ctx: CommandContext, result: DoctorResult) -> None:
    """Display overall summary and suggestions."""
    (
        ReportCard("Diagnostic Summary")
        .add_field("Overall Status", result.overall_status.value)
        .add_field("Checks Passed", f"{result.checks_passed}/{len(result.checks)}")
        .add_field("Warnings", str(result.warnings))
        .add_field("Errors", str(result.errors))
        .render(ctx.output)
    )

    # Show fixable issues and next steps
    if result.fixable_issues:
        suggestions = SuggestionList().add(
            f"Run 'gmailarchiver utilities repair' to fix {len(result.fixable_issues)} issue(s)"
        )
        if len(result.fixable_issues) <= 3:
            for issue in result.fixable_issues:
                suggestions.add(f"Fixable: {issue}")
        else:
            for issue in result.fixable_issues[:3]:
                suggestions.add(f"Fixable: {issue}")
            suggestions.add(f"... and {len(result.fixable_issues) - 3} more")
        suggestions.render(ctx.output)
    elif result.overall_status != CheckSeverity.OK:
        (
            SuggestionList()
            .add("Review diagnostics above for manual fixes")
            .add("Check documentation: https://github.com/you/gmailarchiver")
            .render(ctx.output)
        )
