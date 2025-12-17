"""Scheduler module for managing automated maintenance tasks.

This module provides the core scheduling logic for Gmail Archiver, including:
- Schedule storage in SQLite database (via HybridStorage)
- Schedule validation
- CRUD operations for schedules
- Last run timestamp tracking

Platform-specific scheduling (systemd, launchd, Task Scheduler) is handled by
the connectors.platform_scheduler module.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gmailarchiver.data.hybrid_storage import HybridStorage


class ScheduleValidationError(Exception):
    """Raised when schedule validation fails."""

    pass


@dataclass
class ScheduleEntry:
    """Represents a scheduled task.

    Attributes:
        id: Unique schedule identifier (auto-increment)
        command: Command to execute (e.g., "check", "archive 3y")
        frequency: How often to run ("daily", "weekly", "monthly")
        day_of_week: Day of week for weekly schedules (0=Sunday, 6=Saturday)
        day_of_month: Day of month for monthly schedules (1-31)
        time: Time to run in HH:MM format
        enabled: Whether schedule is currently enabled
        created_at: ISO 8601 timestamp when schedule was created
        last_run: ISO 8601 timestamp of last execution (None if never run)
    """

    id: int
    command: str
    frequency: str
    day_of_week: int | None
    day_of_month: int | None
    time: str
    enabled: bool
    created_at: str
    last_run: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert ScheduleEntry to dictionary."""
        return asdict(self)


class Scheduler:
    """Manages scheduled tasks for Gmail Archiver.

    Stores schedules in SQLite database via HybridStorage and provides
    async CRUD operations.

    Usage:
        scheduler = Scheduler(storage)
        schedule_id = await scheduler.add_schedule(
            command="check",
            frequency="daily",
            time="02:00"
        )
        schedules = await scheduler.list_schedules()

    Note:
        For platform-specific scheduling (systemd, launchd, Task Scheduler),
        use PlatformScheduler from the connectors layer.
    """

    def __init__(self, storage: HybridStorage) -> None:
        """Initialize scheduler with HybridStorage.

        Args:
            storage: HybridStorage instance for data access
        """
        self.storage = storage

    async def add_schedule(
        self,
        command: str,
        frequency: str,
        time: str,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
    ) -> int:
        """Add a new schedule.

        Args:
            command: Command to execute (e.g., "check", "archive 3y")
            frequency: "daily", "weekly", or "monthly"
            time: Time in HH:MM format
            day_of_week: For weekly schedules (0=Sunday, 6=Saturday)
            day_of_month: For monthly schedules (1-31)

        Returns:
            Schedule ID of newly created schedule

        Raises:
            ScheduleValidationError: If validation fails
        """
        self._validate_schedule(command, frequency, time, day_of_week, day_of_month)

        return await self.storage.db.add_schedule(
            command=command,
            frequency=frequency,
            time=time,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
        )

    def _validate_schedule(
        self,
        command: str,
        frequency: str,
        time: str,
        day_of_week: int | None,
        day_of_month: int | None,
    ) -> None:
        """Validate schedule parameters.

        Args:
            command: Command to execute
            frequency: "daily", "weekly", or "monthly"
            time: Time in HH:MM format
            day_of_week: For weekly schedules (0-6)
            day_of_month: For monthly schedules (1-31)

        Raises:
            ScheduleValidationError: If any validation fails
        """
        # Validate command
        if not command or command.strip() == "":
            raise ScheduleValidationError("Command cannot be empty")

        # Validate frequency
        valid_frequencies = {"daily", "weekly", "monthly"}
        if frequency not in valid_frequencies:
            raise ScheduleValidationError(
                f"Invalid frequency: {frequency}. Must be one of: {', '.join(valid_frequencies)}"
            )

        # Validate time format
        if not self._is_valid_time(time):
            raise ScheduleValidationError(
                f"Invalid time format: {time}. Must be HH:MM (e.g., 02:00)"
            )

        # Validate frequency-specific requirements
        if frequency == "weekly":
            if day_of_week is None:
                raise ScheduleValidationError("Weekly schedules require day_of_week (0-6)")
            if not isinstance(day_of_week, int) or not (0 <= day_of_week <= 6):
                raise ScheduleValidationError(f"day_of_week must be 0-6, got: {day_of_week}")

        if frequency == "monthly":
            if day_of_month is None:
                raise ScheduleValidationError("Monthly schedules require day_of_month (1-31)")
            if not isinstance(day_of_month, int) or not (1 <= day_of_month <= 31):
                raise ScheduleValidationError(f"day_of_month must be 1-31, got: {day_of_month}")

    def _is_valid_time(self, time_str: str) -> bool:
        """Validate time format.

        Args:
            time_str: Time string to validate

        Returns:
            True if valid HH:MM format, False otherwise
        """
        if ":" not in time_str:
            return False

        parts = time_str.split(":")
        if len(parts) != 2:
            return False

        try:
            hour = int(parts[0])
            minute = int(parts[1])
            return 0 <= hour <= 23 and 0 <= minute <= 59
        except ValueError:
            return False

    async def list_schedules(self, enabled_only: bool = False) -> list[ScheduleEntry]:
        """List all schedules.

        Args:
            enabled_only: If True, only return enabled schedules

        Returns:
            List of ScheduleEntry objects
        """
        rows = await self.storage.db.list_schedules(enabled_only=enabled_only)
        return [
            ScheduleEntry(
                id=row["id"],
                command=row["command"],
                frequency=row["frequency"],
                day_of_week=row["day_of_week"],
                day_of_month=row["day_of_month"],
                time=row["time"],
                enabled=bool(row["enabled"]),
                created_at=row["created_at"],
                last_run=row["last_run"],
            )
            for row in rows
        ]

    async def get_schedule(self, schedule_id: int) -> ScheduleEntry | None:
        """Get a specific schedule by ID.

        Args:
            schedule_id: Schedule ID to retrieve

        Returns:
            ScheduleEntry if found, None otherwise
        """
        row = await self.storage.db.get_schedule(schedule_id)
        if row is None:
            return None

        return ScheduleEntry(
            id=row["id"],
            command=row["command"],
            frequency=row["frequency"],
            day_of_week=row["day_of_week"],
            day_of_month=row["day_of_month"],
            time=row["time"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_run=row["last_run"],
        )

    async def remove_schedule(self, schedule_id: int) -> bool:
        """Remove a schedule.

        Args:
            schedule_id: Schedule ID to remove

        Returns:
            True if schedule was removed, False if not found
        """
        return await self.storage.db.remove_schedule(schedule_id)

    async def enable_schedule(self, schedule_id: int) -> bool:
        """Enable a schedule.

        Args:
            schedule_id: Schedule ID to enable

        Returns:
            True if schedule was enabled, False if not found
        """
        return await self.storage.db.enable_schedule(schedule_id)

    async def disable_schedule(self, schedule_id: int) -> bool:
        """Disable a schedule.

        Args:
            schedule_id: Schedule ID to disable

        Returns:
            True if schedule was disabled, False if not found
        """
        return await self.storage.db.disable_schedule(schedule_id)

    async def update_last_run(self, schedule_id: int) -> None:
        """Update the last_run timestamp for a schedule.

        Args:
            schedule_id: Schedule ID to update
        """
        await self.storage.db.update_schedule_last_run(schedule_id)
