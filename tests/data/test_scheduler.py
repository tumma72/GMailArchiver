"""Tests for the async Scheduler module.

This module tests the core scheduling logic including:
- Schedule CRUD operations (Create, Read, Update, Delete)
- Schedule validation
- Integration with HybridStorage

Following TDD: These tests are written FIRST, before implementation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.data.scheduler import ScheduleEntry, Scheduler, ScheduleValidationError


@pytest.fixture
def mock_storage() -> MagicMock:
    """Create a mock HybridStorage with mock db."""
    storage = MagicMock()
    storage.db = MagicMock()
    return storage


class TestScheduleValidation:
    """Test schedule validation logic."""

    def test_invalid_frequency_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that invalid frequency raises ScheduleValidationError."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Invalid frequency"):
            scheduler._validate_schedule(
                command="check",
                frequency="hourly",  # Invalid
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )

    def test_invalid_time_format_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that invalid time format raises ScheduleValidationError."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Invalid time format"):
            scheduler._validate_schedule(
                command="check",
                frequency="daily",
                time="25:00",  # Invalid hour
                day_of_week=None,
                day_of_month=None,
            )

    def test_invalid_time_format_no_colon(self, mock_storage: MagicMock) -> None:
        """Test that time format without colon raises error."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Invalid time format"):
            scheduler._validate_schedule(
                command="check",
                frequency="daily",
                time="0200",  # Missing colon
                day_of_week=None,
                day_of_month=None,
            )

    def test_invalid_day_of_week_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that invalid day_of_week raises ScheduleValidationError."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="day_of_week must be 0-6"):
            scheduler._validate_schedule(
                command="check",
                frequency="weekly",
                time="02:00",
                day_of_week=7,  # Invalid (0-6 only)
                day_of_month=None,
            )

    def test_invalid_day_of_month_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that invalid day_of_month raises ScheduleValidationError."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="day_of_month must be 1-31"):
            scheduler._validate_schedule(
                command="check",
                frequency="monthly",
                time="02:00",
                day_of_week=None,
                day_of_month=32,  # Invalid (1-31 only)
            )

    def test_weekly_without_day_of_week_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that weekly frequency requires day_of_week."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Weekly schedules require day_of_week"):
            scheduler._validate_schedule(
                command="check",
                frequency="weekly",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )

    def test_monthly_without_day_of_month_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that monthly frequency requires day_of_month."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Monthly schedules require day_of_month"):
            scheduler._validate_schedule(
                command="check",
                frequency="monthly",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )

    def test_empty_command_raises_error(self, mock_storage: MagicMock) -> None:
        """Test that empty command raises ScheduleValidationError."""
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError, match="Command cannot be empty"):
            scheduler._validate_schedule(
                command="",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )

    def test_valid_daily_schedule(self, mock_storage: MagicMock) -> None:
        """Test that valid daily schedule passes validation."""
        scheduler = Scheduler(mock_storage)

        # Should not raise
        scheduler._validate_schedule(
            command="check",
            frequency="daily",
            time="02:00",
            day_of_week=None,
            day_of_month=None,
        )

    def test_valid_weekly_schedule(self, mock_storage: MagicMock) -> None:
        """Test that valid weekly schedule passes validation."""
        scheduler = Scheduler(mock_storage)

        # Should not raise
        scheduler._validate_schedule(
            command="archive 3y",
            frequency="weekly",
            time="02:00",
            day_of_week=0,  # Sunday
            day_of_month=None,
        )

    def test_valid_monthly_schedule(self, mock_storage: MagicMock) -> None:
        """Test that valid monthly schedule passes validation."""
        scheduler = Scheduler(mock_storage)

        # Should not raise
        scheduler._validate_schedule(
            command="verify-integrity",
            frequency="monthly",
            time="03:00",
            day_of_week=None,
            day_of_month=1,
        )


class TestAddSchedule:
    """Test adding schedules."""

    @pytest.mark.asyncio
    async def test_add_daily_schedule(self, mock_storage: MagicMock) -> None:
        """Test adding a daily schedule."""
        mock_storage.db.add_schedule = AsyncMock(return_value=1)
        scheduler = Scheduler(mock_storage)

        schedule_id = await scheduler.add_schedule(
            command="check",
            frequency="daily",
            time="02:00",
        )

        assert schedule_id == 1
        mock_storage.db.add_schedule.assert_called_once_with(
            command="check",
            frequency="daily",
            time="02:00",
            day_of_week=None,
            day_of_month=None,
        )

    @pytest.mark.asyncio
    async def test_add_weekly_schedule(self, mock_storage: MagicMock) -> None:
        """Test adding a weekly schedule."""
        mock_storage.db.add_schedule = AsyncMock(return_value=2)
        scheduler = Scheduler(mock_storage)

        schedule_id = await scheduler.add_schedule(
            command="archive 3y",
            frequency="weekly",
            time="03:00",
            day_of_week=0,
        )

        assert schedule_id == 2
        mock_storage.db.add_schedule.assert_called_once_with(
            command="archive 3y",
            frequency="weekly",
            time="03:00",
            day_of_week=0,
            day_of_month=None,
        )

    @pytest.mark.asyncio
    async def test_add_monthly_schedule(self, mock_storage: MagicMock) -> None:
        """Test adding a monthly schedule."""
        mock_storage.db.add_schedule = AsyncMock(return_value=3)
        scheduler = Scheduler(mock_storage)

        schedule_id = await scheduler.add_schedule(
            command="verify-integrity",
            frequency="monthly",
            time="04:00",
            day_of_month=15,
        )

        assert schedule_id == 3
        mock_storage.db.add_schedule.assert_called_once_with(
            command="verify-integrity",
            frequency="monthly",
            time="04:00",
            day_of_week=None,
            day_of_month=15,
        )

    @pytest.mark.asyncio
    async def test_add_schedule_with_validation_error(self, mock_storage: MagicMock) -> None:
        """Test that validation error prevents database call."""
        mock_storage.db.add_schedule = AsyncMock()
        scheduler = Scheduler(mock_storage)

        with pytest.raises(ScheduleValidationError):
            await scheduler.add_schedule(
                command="check",
                frequency="invalid",
                time="02:00",
            )

        # DB should not be called if validation fails
        mock_storage.db.add_schedule.assert_not_called()


class TestListSchedules:
    """Test listing schedules."""

    @pytest.mark.asyncio
    async def test_list_empty_schedules(self, mock_storage: MagicMock) -> None:
        """Test listing schedules when none exist."""
        mock_storage.db.list_schedules = AsyncMock(return_value=[])
        scheduler = Scheduler(mock_storage)

        schedules = await scheduler.list_schedules()

        assert schedules == []
        mock_storage.db.list_schedules.assert_called_once_with(enabled_only=False)

    @pytest.mark.asyncio
    async def test_list_schedules_returns_entries(self, mock_storage: MagicMock) -> None:
        """Test that list_schedules returns ScheduleEntry objects."""
        mock_storage.db.list_schedules = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "command": "check",
                    "frequency": "daily",
                    "day_of_week": None,
                    "day_of_month": None,
                    "time": "02:00",
                    "enabled": 1,
                    "created_at": "2025-01-01T00:00:00",
                    "last_run": None,
                },
                {
                    "id": 2,
                    "command": "archive 3y",
                    "frequency": "weekly",
                    "day_of_week": 0,
                    "day_of_month": None,
                    "time": "03:00",
                    "enabled": 0,
                    "created_at": "2025-01-02T00:00:00",
                    "last_run": "2025-01-08T03:00:00",
                },
            ]
        )
        scheduler = Scheduler(mock_storage)

        schedules = await scheduler.list_schedules()

        assert len(schedules) == 2
        assert all(isinstance(s, ScheduleEntry) for s in schedules)
        assert schedules[0].id == 1
        assert schedules[0].command == "check"
        assert schedules[0].enabled is True
        assert schedules[1].id == 2
        assert schedules[1].enabled is False

    @pytest.mark.asyncio
    async def test_list_schedules_enabled_only(self, mock_storage: MagicMock) -> None:
        """Test filtering only enabled schedules."""
        mock_storage.db.list_schedules = AsyncMock(return_value=[])
        scheduler = Scheduler(mock_storage)

        await scheduler.list_schedules(enabled_only=True)

        mock_storage.db.list_schedules.assert_called_once_with(enabled_only=True)


class TestGetSchedule:
    """Test getting individual schedules."""

    @pytest.mark.asyncio
    async def test_get_schedule_by_id(self, mock_storage: MagicMock) -> None:
        """Test getting a schedule by ID."""
        mock_storage.db.get_schedule = AsyncMock(
            return_value={
                "id": 1,
                "command": "check",
                "frequency": "daily",
                "day_of_week": None,
                "day_of_month": None,
                "time": "02:00",
                "enabled": 1,
                "created_at": "2025-01-01T00:00:00",
                "last_run": None,
            }
        )
        scheduler = Scheduler(mock_storage)

        schedule = await scheduler.get_schedule(1)

        assert schedule is not None
        assert isinstance(schedule, ScheduleEntry)
        assert schedule.id == 1
        assert schedule.command == "check"
        mock_storage.db.get_schedule.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_nonexistent_schedule_returns_none(self, mock_storage: MagicMock) -> None:
        """Test that getting nonexistent schedule returns None."""
        mock_storage.db.get_schedule = AsyncMock(return_value=None)
        scheduler = Scheduler(mock_storage)

        schedule = await scheduler.get_schedule(999)

        assert schedule is None


class TestRemoveSchedule:
    """Test removing schedules."""

    @pytest.mark.asyncio
    async def test_remove_schedule(self, mock_storage: MagicMock) -> None:
        """Test removing a schedule."""
        mock_storage.db.remove_schedule = AsyncMock(return_value=True)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.remove_schedule(1)

        assert result is True
        mock_storage.db.remove_schedule.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_schedule(self, mock_storage: MagicMock) -> None:
        """Test removing a nonexistent schedule returns False."""
        mock_storage.db.remove_schedule = AsyncMock(return_value=False)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.remove_schedule(999)

        assert result is False


class TestEnableDisableSchedule:
    """Test enabling and disabling schedules."""

    @pytest.mark.asyncio
    async def test_disable_schedule(self, mock_storage: MagicMock) -> None:
        """Test disabling a schedule."""
        mock_storage.db.disable_schedule = AsyncMock(return_value=True)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.disable_schedule(1)

        assert result is True
        mock_storage.db.disable_schedule.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_enable_schedule(self, mock_storage: MagicMock) -> None:
        """Test enabling a schedule."""
        mock_storage.db.enable_schedule = AsyncMock(return_value=True)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.enable_schedule(1)

        assert result is True
        mock_storage.db.enable_schedule.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_disable_nonexistent_schedule(self, mock_storage: MagicMock) -> None:
        """Test disabling nonexistent schedule returns False."""
        mock_storage.db.disable_schedule = AsyncMock(return_value=False)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.disable_schedule(999)

        assert result is False

    @pytest.mark.asyncio
    async def test_enable_nonexistent_schedule(self, mock_storage: MagicMock) -> None:
        """Test enabling nonexistent schedule returns False."""
        mock_storage.db.enable_schedule = AsyncMock(return_value=False)
        scheduler = Scheduler(mock_storage)

        result = await scheduler.enable_schedule(999)

        assert result is False


class TestUpdateLastRun:
    """Test updating last run timestamp."""

    @pytest.mark.asyncio
    async def test_update_last_run(self, mock_storage: MagicMock) -> None:
        """Test updating the last_run timestamp."""
        mock_storage.db.update_schedule_last_run = AsyncMock()
        scheduler = Scheduler(mock_storage)

        await scheduler.update_last_run(1)

        mock_storage.db.update_schedule_last_run.assert_called_once_with(1)


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
