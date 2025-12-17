"""Schedule commands implementation."""

import asyncio

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.schedule import (
    schedule_add_command,
    schedule_disable_command,
    schedule_enable_command,
    schedule_list_command,
    schedule_remove_command,
)


@with_context(requires_storage=True, operation_name="schedule-add")
def add(
    ctx: CommandContext,
    command: str = typer.Argument(..., help="Command to schedule (e.g., 'check', 'archive 3y')"),
    frequency: str = typer.Option(
        ..., "--frequency", "-f", help="Frequency: 'daily', 'weekly', or 'monthly'"
    ),
    time: str = typer.Option(..., "--time", "-t", help="Time in HH:MM format (e.g., '02:00')"),
    day_of_week: int | None = typer.Option(
        None, "--day-of-week", help="Day of week for weekly schedules (0=Sunday, 6=Saturday)"
    ),
    day_of_month: int | None = typer.Option(
        None, "--day-of-month", help="Day of month for monthly schedules (1-31)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Add a new maintenance schedule.

    Examples:
        $ gmailarchiver schedule add "check" --frequency daily --time 02:00
        $ gmailarchiver schedule add "archive 3y" --frequency weekly --time 03:00 --day-of-week 0
        $ gmailarchiver schedule add "check" --frequency monthly --time 01:00 --day-of-month 1
    """
    asyncio.run(
        schedule_add_command(ctx, command, frequency, time, day_of_week, day_of_month, json_output)
    )


@with_context(requires_storage=True, operation_name="schedule-list")
def list_(
    ctx: CommandContext,
    enabled_only: bool = typer.Option(False, "--enabled-only", help="Show only enabled schedules"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    List all maintenance schedules.

    Examples:
        $ gmailarchiver schedule list
        $ gmailarchiver schedule list --enabled-only
        $ gmailarchiver schedule list --json
    """
    asyncio.run(schedule_list_command(ctx, enabled_only, json_output))


@with_context(requires_storage=True, operation_name="schedule-remove")
def remove(
    ctx: CommandContext,
    schedule_id: int = typer.Argument(..., help="Schedule ID to remove"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Remove a maintenance schedule.

    Examples:
        $ gmailarchiver schedule remove 1
        $ gmailarchiver schedule remove 1 --json
    """
    asyncio.run(schedule_remove_command(ctx, schedule_id, json_output))


@with_context(requires_storage=True, operation_name="schedule-enable")
def enable(
    ctx: CommandContext,
    schedule_id: int = typer.Argument(..., help="Schedule ID to enable"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Enable a maintenance schedule.

    Examples:
        $ gmailarchiver schedule enable 1
        $ gmailarchiver schedule enable 1 --json
    """
    asyncio.run(schedule_enable_command(ctx, schedule_id, json_output))


@with_context(requires_storage=True, operation_name="schedule-disable")
def disable(
    ctx: CommandContext,
    schedule_id: int = typer.Argument(..., help="Schedule ID to disable"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Disable a maintenance schedule.

    Examples:
        $ gmailarchiver schedule disable 1
        $ gmailarchiver schedule disable 1 --json
    """
    asyncio.run(schedule_disable_command(ctx, schedule_id, json_output))
