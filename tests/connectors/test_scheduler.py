"""Tests for the Scheduler module.

This module tests the core scheduling logic including:
- Schedule CRUD operations (Create, Read, Update, Delete)
- Database schema creation
- Schedule validation
- Edge cases and error handling

Following TDD: These tests are written FIRST, before implementation.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from gmailarchiver.connectors.scheduler import ScheduleEntry, Scheduler, ScheduleValidationError


class TestSchedulerDatabase:
    """Test database initialization and schema."""

    def test_create_scheduler_creates_database(self, tmp_path: Path) -> None:
        """Test that creating a Scheduler instance creates the database file."""
        db_path = tmp_path / "test.db"
        scheduler = Scheduler(str(db_path))

        assert db_path.exists()
        scheduler.close()

    def test_scheduler_creates_schedules_table(self, tmp_path: Path) -> None:
        """Test that the schedules table is created with correct schema."""
        db_path = tmp_path / "test.db"
        scheduler = Scheduler(str(db_path))

        # Verify table exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedules'")
        result = cursor.fetchone()
        assert result is not None
        assert result[0] == "schedules"

        # Verify schema
        cursor.execute("PRAGMA table_info(schedules)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert "id" in columns
        assert "command" in columns
        assert "frequency" in columns
        assert "day_of_week" in columns
        assert "day_of_month" in columns
        assert "time" in columns
        assert "enabled" in columns
        assert "created_at" in columns
        assert "last_run" in columns

        conn.close()
        scheduler.close()

    def test_scheduler_uses_existing_database(self, tmp_path: Path) -> None:
        """Test that Scheduler can use an existing database."""
        db_path = tmp_path / "test.db"

        # Create database with first instance
        scheduler1 = Scheduler(str(db_path))
        schedule_id = scheduler1.add_schedule(command="check", frequency="daily", time="02:00")
        scheduler1.close()

        # Open with second instance
        scheduler2 = Scheduler(str(db_path))
        schedules = scheduler2.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].id == schedule_id
        scheduler2.close()


class TestAddSchedule:
    """Test adding schedules with various configurations."""

    def test_add_daily_check_schedule(self, tmp_path: Path) -> None:
        """Test adding a daily check schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")

        assert schedule_id is not None
        schedules = scheduler.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].id == schedule_id
        assert schedules[0].command == "check"
        assert schedules[0].frequency == "daily"
        assert schedules[0].time == "02:00"
        assert schedules[0].enabled is True
        assert schedules[0].day_of_week is None
        assert schedules[0].day_of_month is None
        scheduler.close()

    def test_add_weekly_archive_schedule(self, tmp_path: Path) -> None:
        """Test adding a weekly archive schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(
            command="archive 3y",
            frequency="weekly",
            day_of_week=0,  # Sunday
            time="02:00",
        )

        schedules = scheduler.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].command == "archive 3y"
        assert schedules[0].frequency == "weekly"
        assert schedules[0].day_of_week == 0
        assert schedules[0].time == "02:00"
        scheduler.close()

    def test_add_monthly_schedule(self, tmp_path: Path) -> None:
        """Test adding a monthly schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(
            command="verify-integrity",
            frequency="monthly",
            day_of_month=1,
            time="03:00",
        )

        schedules = scheduler.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].frequency == "monthly"
        assert schedules[0].day_of_month == 1
        assert schedules[0].time == "03:00"
        scheduler.close()

    def test_add_multiple_schedules(self, tmp_path: Path) -> None:
        """Test adding multiple schedules."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        id1 = scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        id2 = scheduler.add_schedule(
            command="archive 3y", frequency="weekly", day_of_week=0, time="03:00"
        )
        id3 = scheduler.add_schedule(
            command="verify-integrity",
            frequency="monthly",
            day_of_month=1,
            time="04:00",
        )

        schedules = scheduler.list_schedules()
        assert len(schedules) == 3
        assert {s.id for s in schedules} == {id1, id2, id3}
        scheduler.close()

    def test_add_schedule_sets_created_at(self, tmp_path: Path) -> None:
        """Test that created_at timestamp is set when adding schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        before = datetime.now()
        scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        after = datetime.now()

        schedules = scheduler.list_schedules()
        created_at = datetime.fromisoformat(schedules[0].created_at)
        assert before <= created_at <= after
        scheduler.close()


class TestScheduleValidation:
    """Test schedule validation logic."""

    def test_invalid_frequency_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid frequency raises ScheduleValidationError."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Invalid frequency"):
            scheduler.add_schedule(
                command="check",
                frequency="hourly",
                time="02:00",  # Invalid
            )
        scheduler.close()

    def test_invalid_time_format_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid time format raises ScheduleValidationError."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Invalid time format"):
            scheduler.add_schedule(
                command="check",
                frequency="daily",
                time="25:00",  # Invalid hour
            )
        scheduler.close()

    def test_invalid_time_format_no_colon(self, tmp_path: Path) -> None:
        """Test that time format without colon raises error."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Invalid time format"):
            scheduler.add_schedule(
                command="check",
                frequency="daily",
                time="0200",  # Missing colon
            )
        scheduler.close()

    def test_invalid_day_of_week_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid day_of_week raises ScheduleValidationError."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="day_of_week must be 0-6"):
            scheduler.add_schedule(
                command="check",
                frequency="weekly",
                day_of_week=7,  # Invalid (0-6 only)
                time="02:00",
            )
        scheduler.close()

    def test_invalid_day_of_month_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid day_of_month raises ScheduleValidationError."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="day_of_month must be 1-31"):
            scheduler.add_schedule(
                command="check",
                frequency="monthly",
                day_of_month=32,  # Invalid (1-31 only)
                time="02:00",
            )
        scheduler.close()

    def test_weekly_without_day_of_week_raises_error(self, tmp_path: Path) -> None:
        """Test that weekly frequency requires day_of_week."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Weekly schedules require day_of_week"):
            scheduler.add_schedule(command="check", frequency="weekly", time="02:00")
        scheduler.close()

    def test_monthly_without_day_of_month_raises_error(self, tmp_path: Path) -> None:
        """Test that monthly frequency requires day_of_month."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Monthly schedules require day_of_month"):
            scheduler.add_schedule(command="check", frequency="monthly", time="02:00")
        scheduler.close()

    def test_empty_command_raises_error(self, tmp_path: Path) -> None:
        """Test that empty command raises ScheduleValidationError."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        with pytest.raises(ScheduleValidationError, match="Command cannot be empty"):
            scheduler.add_schedule(command="", frequency="daily", time="02:00")
        scheduler.close()


class TestListSchedules:
    """Test listing schedules."""

    def test_list_empty_schedules(self, tmp_path: Path) -> None:
        """Test listing schedules when none exist."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedules = scheduler.list_schedules()
        assert schedules == []
        scheduler.close()

    def test_list_schedules_returns_all(self, tmp_path: Path) -> None:
        """Test that list_schedules returns all schedules."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        scheduler.add_schedule(
            command="archive 3y", frequency="weekly", day_of_week=0, time="03:00"
        )

        schedules = scheduler.list_schedules()
        assert len(schedules) == 2
        scheduler.close()

    def test_list_schedules_includes_disabled(self, tmp_path: Path) -> None:
        """Test that list_schedules includes disabled schedules."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        scheduler.disable_schedule(schedule_id)

        schedules = scheduler.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].enabled is False
        scheduler.close()

    def test_list_schedules_only_enabled(self, tmp_path: Path) -> None:
        """Test filtering only enabled schedules."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        id1 = scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        id2 = scheduler.add_schedule(
            command="archive 3y", frequency="weekly", day_of_week=0, time="03:00"
        )
        scheduler.disable_schedule(id2)

        schedules = scheduler.list_schedules(enabled_only=True)
        assert len(schedules) == 1
        assert schedules[0].id == id1
        scheduler.close()


class TestGetSchedule:
    """Test getting individual schedules."""

    def test_get_schedule_by_id(self, tmp_path: Path) -> None:
        """Test getting a schedule by ID."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")

        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.id == schedule_id
        assert schedule.command == "check"
        scheduler.close()

    def test_get_nonexistent_schedule_returns_none(self, tmp_path: Path) -> None:
        """Test that getting nonexistent schedule returns None."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule = scheduler.get_schedule(999)
        assert schedule is None
        scheduler.close()


class TestRemoveSchedule:
    """Test removing schedules."""

    def test_remove_schedule(self, tmp_path: Path) -> None:
        """Test removing a schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")

        result = scheduler.remove_schedule(schedule_id)
        assert result is True

        schedules = scheduler.list_schedules()
        assert len(schedules) == 0
        scheduler.close()

    def test_remove_nonexistent_schedule(self, tmp_path: Path) -> None:
        """Test removing a nonexistent schedule returns False."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        result = scheduler.remove_schedule(999)
        assert result is False
        scheduler.close()

    def test_remove_one_of_multiple_schedules(self, tmp_path: Path) -> None:
        """Test removing one schedule leaves others intact."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        id1 = scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        id2 = scheduler.add_schedule(
            command="archive 3y", frequency="weekly", day_of_week=0, time="03:00"
        )

        scheduler.remove_schedule(id1)

        schedules = scheduler.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].id == id2
        scheduler.close()


class TestEnableDisableSchedule:
    """Test enabling and disabling schedules."""

    def test_disable_schedule(self, tmp_path: Path) -> None:
        """Test disabling a schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")

        result = scheduler.disable_schedule(schedule_id)
        assert result is True

        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.enabled is False
        scheduler.close()

    def test_enable_schedule(self, tmp_path: Path) -> None:
        """Test enabling a disabled schedule."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")
        scheduler.disable_schedule(schedule_id)

        result = scheduler.enable_schedule(schedule_id)
        assert result is True

        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.enabled is True
        scheduler.close()

    def test_disable_nonexistent_schedule(self, tmp_path: Path) -> None:
        """Test disabling nonexistent schedule returns False."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        result = scheduler.disable_schedule(999)
        assert result is False
        scheduler.close()

    def test_enable_nonexistent_schedule(self, tmp_path: Path) -> None:
        """Test enabling nonexistent schedule returns False."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        result = scheduler.enable_schedule(999)
        assert result is False
        scheduler.close()


class TestUpdateLastRun:
    """Test updating last run timestamp."""

    def test_update_last_run(self, tmp_path: Path) -> None:
        """Test updating the last_run timestamp."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        schedule_id = scheduler.add_schedule(command="check", frequency="daily", time="02:00")

        # Initially last_run should be None
        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.last_run is None

        # Update last_run
        before = datetime.now()
        scheduler.update_last_run(schedule_id)
        after = datetime.now()

        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.last_run is not None
        last_run = datetime.fromisoformat(schedule.last_run)
        assert before <= last_run <= after
        scheduler.close()

    def test_update_last_run_nonexistent_schedule(self, tmp_path: Path) -> None:
        """Test updating last_run for nonexistent schedule does not raise error."""
        scheduler = Scheduler(str(tmp_path / "test.db"))

        # Should not raise error
        scheduler.update_last_run(999)
        scheduler.close()


class TestScheduleEntry:
    """Test ScheduleEntry dataclass."""

    def test_schedule_entry_creation(self) -> None:
        """Test creating a ScheduleEntry."""
        entry = ScheduleEntry(
            id=1,
            command="check",
            frequency="daily",
            day_of_week=None,
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        assert entry.id == 1
        assert entry.command == "check"
        assert entry.frequency == "daily"
        assert entry.enabled is True

    def test_schedule_entry_to_dict(self) -> None:
        """Test converting ScheduleEntry to dictionary."""
        entry = ScheduleEntry(
            id=1,
            command="check",
            frequency="daily",
            day_of_week=None,
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        entry_dict = entry.to_dict()
        assert entry_dict["id"] == 1
        assert entry_dict["command"] == "check"
        assert entry_dict["frequency"] == "daily"
        assert entry_dict["time"] == "02:00"
        assert entry_dict["enabled"] is True


class TestSchedulerContextManager:
    """Test Scheduler as context manager."""

    def test_scheduler_context_manager(self, tmp_path: Path) -> None:
        """Test using Scheduler as context manager."""
        db_path = tmp_path / "test.db"

        with Scheduler(str(db_path)) as scheduler:
            scheduler.add_schedule(command="check", frequency="daily", time="02:00")
            schedules = scheduler.list_schedules()
            assert len(schedules) == 1

        # Connection should be closed after context
        # Verify by opening again
        with Scheduler(str(db_path)) as scheduler:
            schedules = scheduler.list_schedules()
            assert len(schedules) == 1
