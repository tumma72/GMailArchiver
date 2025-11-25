"""Scheduler module for managing automated maintenance tasks.

This module provides the core scheduling logic for Gmail Archiver, including:
- Schedule storage in SQLite database
- Schedule validation
- CRUD operations for schedules
- Last run timestamp tracking

Platform-specific scheduling (systemd, launchd, Task Scheduler) is handled by
the platform_scheduler module.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


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

    Stores schedules in SQLite database and provides CRUD operations.
    Does not handle platform-specific scheduling - use PlatformScheduler for that.

    Usage:
        scheduler = Scheduler("state.db")
        schedule_id = scheduler.add_schedule(
            command="check",
            frequency="daily",
            time="02:00"
        )
        schedules = scheduler.list_schedules()
        scheduler.close()

    Or as context manager:
        with Scheduler("state.db") as scheduler:
            scheduler.add_schedule(...)
    """

    def __init__(self, db_path: str) -> None:
        """Initialize scheduler with database path.

        Args:
            db_path: Path to SQLite database file

        Creates database and schedules table if they don't exist.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_table()

    def _create_table(self) -> None:
        """Create schedules table if it doesn't exist."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                frequency TEXT NOT NULL,
                day_of_week INTEGER,
                day_of_month INTEGER,
                time TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_run TEXT
            )
            """
        )
        self.conn.commit()

    def add_schedule(
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

        cursor = self.conn.cursor()
        created_at = datetime.now().isoformat()

        cursor.execute(
            """
            INSERT INTO schedules
            (command, frequency, day_of_week, day_of_month, time, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (command, frequency, day_of_week, day_of_month, time, created_at),
        )
        self.conn.commit()

        schedule_id = cursor.lastrowid
        assert schedule_id is not None, "Failed to get lastrowid from database"
        return schedule_id

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

    def list_schedules(self, enabled_only: bool = False) -> list[ScheduleEntry]:
        """List all schedules.

        Args:
            enabled_only: If True, only return enabled schedules

        Returns:
            List of ScheduleEntry objects
        """
        cursor = self.conn.cursor()

        if enabled_only:
            cursor.execute(
                """
                SELECT id, command, frequency, day_of_week, day_of_month,
                       time, enabled, created_at, last_run
                FROM schedules
                WHERE enabled = 1
                ORDER BY id
                """
            )
        else:
            cursor.execute(
                """
                SELECT id, command, frequency, day_of_week, day_of_month,
                       time, enabled, created_at, last_run
                FROM schedules
                ORDER BY id
                """
            )

        schedules = []
        for row in cursor.fetchall():
            schedules.append(
                ScheduleEntry(
                    id=row[0],
                    command=row[1],
                    frequency=row[2],
                    day_of_week=row[3],
                    day_of_month=row[4],
                    time=row[5],
                    enabled=bool(row[6]),
                    created_at=row[7],
                    last_run=row[8],
                )
            )

        return schedules

    def get_schedule(self, schedule_id: int) -> ScheduleEntry | None:
        """Get a specific schedule by ID.

        Args:
            schedule_id: Schedule ID to retrieve

        Returns:
            ScheduleEntry if found, None otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, command, frequency, day_of_week, day_of_month,
                   time, enabled, created_at, last_run
            FROM schedules
            WHERE id = ?
            """,
            (schedule_id,),
        )

        row = cursor.fetchone()
        if row is None:
            return None

        return ScheduleEntry(
            id=row[0],
            command=row[1],
            frequency=row[2],
            day_of_week=row[3],
            day_of_month=row[4],
            time=row[5],
            enabled=bool(row[6]),
            created_at=row[7],
            last_run=row[8],
        )

    def remove_schedule(self, schedule_id: int) -> bool:
        """Remove a schedule.

        Args:
            schedule_id: Schedule ID to remove

        Returns:
            True if schedule was removed, False if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        self.conn.commit()

        return cursor.rowcount > 0

    def enable_schedule(self, schedule_id: int) -> bool:
        """Enable a schedule.

        Args:
            schedule_id: Schedule ID to enable

        Returns:
            True if schedule was enabled, False if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE schedules SET enabled = 1 WHERE id = ?", (schedule_id,))
        self.conn.commit()

        return cursor.rowcount > 0

    def disable_schedule(self, schedule_id: int) -> bool:
        """Disable a schedule.

        Args:
            schedule_id: Schedule ID to disable

        Returns:
            True if schedule was disabled, False if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule_id,))
        self.conn.commit()

        return cursor.rowcount > 0

    def update_last_run(self, schedule_id: int) -> None:
        """Update the last_run timestamp for a schedule.

        Args:
            schedule_id: Schedule ID to update
        """
        cursor = self.conn.cursor()
        last_run = datetime.now().isoformat()
        cursor.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (last_run, schedule_id))
        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self) -> Scheduler:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
