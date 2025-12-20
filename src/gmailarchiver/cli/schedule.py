"""Schedule commands implementation."""

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.ui import ReportCard, SuggestionList
from gmailarchiver.data.scheduler import Scheduler, ScheduleValidationError


async def schedule_add_command(
    ctx: CommandContext,
    command: str,
    frequency: str,
    time: str,
    day_of_week: int | None,
    day_of_month: int | None,
    json_output: bool,
) -> None:
    """Async implementation of schedule add command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    scheduler = Scheduler(ctx.storage)

    try:
        schedule_id = await scheduler.add_schedule(
            command=command,
            frequency=frequency,
            time=time,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
        )
    except ScheduleValidationError as e:
        ctx.fail_and_exit(
            title="Invalid Schedule",
            message=str(e),
            suggestion="Check frequency, time format (HH:MM), and required parameters",
        )
        return
    except Exception as e:
        ctx.fail_and_exit(
            title="Schedule Creation Failed",
            message=f"Failed to create schedule: {e}",
            suggestion="Check database permissions",
        )
        return

    # Display success
    ctx.success(f"Created schedule #{schedule_id}")

    # Build schedule summary
    schedule_parts = [f"{frequency} at {time}"]
    if frequency == "weekly" and day_of_week is not None:
        days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        schedule_parts.append(f"on {days[day_of_week]}")
    elif frequency == "monthly" and day_of_month is not None:
        schedule_parts.append(f"on day {day_of_month}")

    (
        ReportCard("New Schedule")
        .add_field("Schedule ID", str(schedule_id))
        .add_field("Command", command)
        .add_field("Schedule", " ".join(schedule_parts))
        .render(ctx.output)
    )


async def schedule_list_command(
    ctx: CommandContext,
    enabled_only: bool,
    json_output: bool,
) -> None:
    """Async implementation of schedule list command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    scheduler = Scheduler(ctx.storage)

    try:
        schedules = await scheduler.list_schedules(enabled_only=enabled_only)
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to List Schedules",
            message=f"Error reading schedules: {e}",
            suggestion="Check database permissions",
        )
        return

    if not schedules:
        ctx.warning("No schedules found")
        SuggestionList().add(
            "Add a schedule: gmailarchiver schedule add 'check' --frequency daily --time 02:00"
        ).render(ctx.output)
        return

    # Display schedules as table
    headers = ["ID", "Command", "Frequency", "Time", "Day", "Enabled", "Last Run"]
    rows = []

    for sched in schedules:
        # Format day column based on frequency
        day_display = ""
        if sched.frequency == "weekly" and sched.day_of_week is not None:
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_display = days[sched.day_of_week]
        elif sched.frequency == "monthly" and sched.day_of_month is not None:
            day_display = str(sched.day_of_month)

        rows.append(
            [
                str(sched.id),
                sched.command[:30],
                sched.frequency,
                sched.time,
                day_display,
                "Yes" if sched.enabled else "No",
                sched.last_run[:19] if sched.last_run else "Never",
            ]
        )

    ctx.show_table("Maintenance Schedules", headers, rows)


async def schedule_remove_command(
    ctx: CommandContext,
    schedule_id: int,
    json_output: bool,
) -> None:
    """Async implementation of schedule remove command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    scheduler = Scheduler(ctx.storage)

    try:
        removed = await scheduler.remove_schedule(schedule_id)
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Remove Schedule",
            message=f"Error removing schedule: {e}",
            suggestion="Check database permissions",
        )
        return

    if not removed:
        ctx.fail_and_exit(
            title="Schedule Not Found",
            message=f"Schedule #{schedule_id} not found",
            suggestion="Run 'gmailarchiver schedule list' to see available schedules",
        )
        return

    ctx.success(f"Removed schedule #{schedule_id}")


async def schedule_enable_command(
    ctx: CommandContext,
    schedule_id: int,
    json_output: bool,
) -> None:
    """Async implementation of schedule enable command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    scheduler = Scheduler(ctx.storage)

    try:
        enabled = await scheduler.enable_schedule(schedule_id)
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Enable Schedule",
            message=f"Error enabling schedule: {e}",
            suggestion="Check database permissions",
        )
        return

    if not enabled:
        ctx.fail_and_exit(
            title="Schedule Not Found",
            message=f"Schedule #{schedule_id} not found",
            suggestion="Run 'gmailarchiver schedule list' to see available schedules",
        )
        return

    ctx.success(f"Enabled schedule #{schedule_id}")


async def schedule_disable_command(
    ctx: CommandContext,
    schedule_id: int,
    json_output: bool,
) -> None:
    """Async implementation of schedule disable command."""
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    scheduler = Scheduler(ctx.storage)

    try:
        disabled = await scheduler.disable_schedule(schedule_id)
    except Exception as e:
        ctx.fail_and_exit(
            title="Failed to Disable Schedule",
            message=f"Error disabling schedule: {e}",
            suggestion="Check database permissions",
        )
        return

    if not disabled:
        ctx.fail_and_exit(
            title="Schedule Not Found",
            message=f"Schedule #{schedule_id} not found",
            suggestion="Run 'gmailarchiver schedule list' to see available schedules",
        )
        return

    ctx.success(f"Disabled schedule #{schedule_id}")
