"""Tests for schedule CLI commands.

These tests verify the CLI layer behavior for schedule management:
- Command registration and help text
- Argument parsing and validation
- Integration with Scheduler
- Error handling for invalid inputs
- Output formatting (success, error, table display)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.schedule import (
    schedule_add_command,
    schedule_disable_command,
    schedule_enable_command,
    schedule_list_command,
    schedule_remove_command,
)
from gmailarchiver.data.scheduler import ScheduleEntry, ScheduleValidationError

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_output_manager():
    """Create a mock OutputManager for testing."""
    mock = MagicMock()
    mock.console = MagicMock()
    return mock


@pytest.fixture
def mock_storage():
    """Create a mock HybridStorage with mocked DBManager."""
    mock_db = MagicMock()
    mock_storage = MagicMock()
    mock_storage.db = mock_db
    return mock_storage


@pytest.fixture
def command_context(mock_output_manager, mock_storage):
    """Create CommandContext with mocked dependencies."""
    ctx = CommandContext(
        output=mock_output_manager,
        storage=mock_storage,
        json_mode=False,
    )
    return ctx


@pytest.fixture
def sample_schedule_entry():
    """Create a sample ScheduleEntry for testing."""
    return ScheduleEntry(
        id=1,
        command="check",
        frequency="daily",
        day_of_week=None,
        day_of_month=None,
        time="02:00",
        enabled=True,
        created_at="2024-01-01T00:00:00",
        last_run=None,
    )


# ============================================================================
# Schedule Add Command Tests
# ============================================================================


class TestScheduleAddCommand:
    """Tests for schedule add command."""

    @pytest.mark.asyncio
    async def test_add_daily_schedule_success(self, command_context):
        """Test adding a daily schedule successfully."""
        # Mock Scheduler.add_schedule to return schedule ID
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.add_schedule = AsyncMock(return_value=42)

            await schedule_add_command(
                ctx=command_context,
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
                json_output=False,
            )

            # Verify Scheduler was created with storage
            MockScheduler.assert_called_once_with(command_context.storage)

            # Verify add_schedule was called with correct params
            mock_scheduler.add_schedule.assert_called_once_with(
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )

            # Verify success message shown
            command_context.output.success.assert_called_once()
            assert "42" in command_context.output.success.call_args[0][0]

            # Verify report shown with schedule details
            command_context.output.show_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_weekly_schedule_success(self, command_context):
        """Test adding a weekly schedule with day_of_week."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.add_schedule = AsyncMock(return_value=10)

            await schedule_add_command(
                ctx=command_context,
                command="archive 3y",
                frequency="weekly",
                time="03:30",
                day_of_week=1,  # Monday
                day_of_month=None,
                json_output=False,
            )

            # Verify correct day name shown in report
            command_context.output.show_report.assert_called_once()
            report_data = command_context.output.show_report.call_args[0][1]
            assert "Monday" in report_data["Schedule"]

    @pytest.mark.asyncio
    async def test_add_monthly_schedule_success(self, command_context):
        """Test adding a monthly schedule with day_of_month."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.add_schedule = AsyncMock(return_value=20)

            await schedule_add_command(
                ctx=command_context,
                command="consolidate",
                frequency="monthly",
                time="01:00",
                day_of_week=None,
                day_of_month=15,
                json_output=False,
            )

            # Verify day of month shown in report
            command_context.output.show_report.assert_called_once()
            report_data = command_context.output.show_report.call_args[0][1]
            assert "day 15" in report_data["Schedule"]

    @pytest.mark.asyncio
    async def test_add_schedule_validation_error(self, command_context):
        """Test add schedule handles validation errors."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.add_schedule = AsyncMock(
                side_effect=ScheduleValidationError("Invalid time format: 25:00")
            )

            with pytest.raises(typer.Exit):  # fail_and_exit raises typer.Exit
                await schedule_add_command(
                    ctx=command_context,
                    command="check",
                    frequency="daily",
                    time="25:00",
                    day_of_week=None,
                    day_of_month=None,
                    json_output=False,
                )

            # Verify error was shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Invalid Schedule"
            assert "Invalid time format" in error_call[1]["message"]

    @pytest.mark.asyncio
    async def test_add_schedule_generic_error(self, command_context):
        """Test add schedule handles generic exceptions."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.add_schedule = AsyncMock(
                side_effect=Exception("Database connection failed")
            )

            with pytest.raises(typer.Exit):
                await schedule_add_command(
                    ctx=command_context,
                    command="check",
                    frequency="daily",
                    time="02:00",
                    day_of_week=None,
                    day_of_month=None,
                    json_output=False,
                )

            # Verify error was shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Schedule Creation Failed"

    @pytest.mark.asyncio
    async def test_add_schedule_requires_storage(self, mock_output_manager):
        """Test that add schedule requires storage to be set."""
        ctx_no_storage = CommandContext(
            output=mock_output_manager,
            storage=None,  # No storage
            json_mode=False,
        )

        # Should fail assertion that storage is not None
        with pytest.raises(AssertionError):
            await schedule_add_command(
                ctx=ctx_no_storage,
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
                json_output=False,
            )


# ============================================================================
# Schedule List Command Tests
# ============================================================================


class TestScheduleListCommand:
    """Tests for schedule list command."""

    @pytest.mark.asyncio
    async def test_list_schedules_success(self, command_context, sample_schedule_entry):
        """Test listing schedules successfully."""
        weekly_schedule = ScheduleEntry(
            id=2,
            command="archive 3y",
            frequency="weekly",
            day_of_week=3,  # Wednesday
            day_of_month=None,
            time="03:00",
            enabled=False,
            created_at="2024-01-02T00:00:00",
            last_run="2024-01-10T03:00:00",
        )

        monthly_schedule = ScheduleEntry(
            id=3,
            command="consolidate",
            frequency="monthly",
            day_of_week=None,
            day_of_month=15,
            time="01:00",
            enabled=True,
            created_at="2024-01-03T00:00:00",
            last_run=None,
        )

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(
                return_value=[sample_schedule_entry, weekly_schedule, monthly_schedule]
            )

            await schedule_list_command(
                ctx=command_context,
                enabled_only=False,
                json_output=False,
            )

            # Verify list_schedules called with correct params
            mock_scheduler.list_schedules.assert_called_once_with(enabled_only=False)

            # Verify table shown
            command_context.output.show_table.assert_called_once()
            table_call = command_context.output.show_table.call_args

            # Check table structure
            assert table_call[0][0] == "Maintenance Schedules"
            headers = table_call[0][1]
            assert "ID" in headers
            assert "Command" in headers
            assert "Enabled" in headers

            # Check table rows
            rows = table_call[0][2]
            assert len(rows) == 3

            # Check daily schedule row
            assert rows[0][0] == "1"
            assert rows[0][2] == "daily"
            assert rows[0][4] == ""  # No day for daily
            assert rows[0][5] == "Yes"  # Enabled
            assert rows[0][6] == "Never"  # No last run

            # Check weekly schedule row
            assert rows[1][0] == "2"
            assert rows[1][4] == "Wed"  # Day of week
            assert rows[1][5] == "No"  # Disabled
            assert "2024-01-10" in rows[1][6]  # Has last run

            # Check monthly schedule row
            assert rows[2][0] == "3"
            assert rows[2][4] == "15"  # Day of month
            assert rows[2][6] == "Never"  # No last run

    @pytest.mark.asyncio
    async def test_list_schedules_enabled_only(self, command_context, sample_schedule_entry):
        """Test listing only enabled schedules."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(return_value=[sample_schedule_entry])

            await schedule_list_command(
                ctx=command_context,
                enabled_only=True,
                json_output=False,
            )

            # Verify enabled_only flag passed
            mock_scheduler.list_schedules.assert_called_once_with(enabled_only=True)

    @pytest.mark.asyncio
    async def test_list_schedules_empty(self, command_context):
        """Test listing schedules when none exist."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(return_value=[])

            await schedule_list_command(
                ctx=command_context,
                enabled_only=False,
                json_output=False,
            )

            # Verify warning shown
            command_context.output.warning.assert_called_once_with("No schedules found")

            # Verify suggestion shown
            command_context.output.suggest_next_steps.assert_called_once()
            suggestions = command_context.output.suggest_next_steps.call_args[0][0]
            assert any("schedule add" in s for s in suggestions)

    @pytest.mark.asyncio
    async def test_list_schedules_error(self, command_context):
        """Test list schedules handles errors."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(side_effect=Exception("Database error"))

            with pytest.raises(typer.Exit):
                await schedule_list_command(
                    ctx=command_context,
                    enabled_only=False,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Failed to List Schedules"

    @pytest.mark.asyncio
    async def test_list_schedules_truncates_long_commands(self, command_context):
        """Test that long command strings are truncated in the table."""
        long_command_schedule = ScheduleEntry(
            id=1,
            command="archive 3y --query 'from:example@example.com subject:important'",
            frequency="daily",
            day_of_week=None,
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2024-01-01T00:00:00",
            last_run=None,
        )

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(return_value=[long_command_schedule])

            await schedule_list_command(
                ctx=command_context,
                enabled_only=False,
                json_output=False,
            )

            # Verify command is truncated to 30 chars
            rows = command_context.output.show_table.call_args[0][2]
            assert len(rows[0][1]) <= 30


# ============================================================================
# Schedule Remove Command Tests
# ============================================================================


class TestScheduleRemoveCommand:
    """Tests for schedule remove command."""

    @pytest.mark.asyncio
    async def test_remove_schedule_success(self, command_context):
        """Test removing a schedule successfully."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.remove_schedule = AsyncMock(return_value=True)

            await schedule_remove_command(
                ctx=command_context,
                schedule_id=42,
                json_output=False,
            )

            # Verify remove_schedule called with correct ID
            mock_scheduler.remove_schedule.assert_called_once_with(42)

            # Verify success message shown
            command_context.output.success.assert_called_once()
            assert "42" in command_context.output.success.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remove_schedule_not_found(self, command_context):
        """Test removing a non-existent schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.remove_schedule = AsyncMock(return_value=False)

            with pytest.raises(typer.Exit):
                await schedule_remove_command(
                    ctx=command_context,
                    schedule_id=999,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Schedule Not Found"
            assert "999" in error_call[1]["message"]

    @pytest.mark.asyncio
    async def test_remove_schedule_error(self, command_context):
        """Test remove schedule handles errors."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.remove_schedule = AsyncMock(side_effect=Exception("Database error"))

            with pytest.raises(typer.Exit):
                await schedule_remove_command(
                    ctx=command_context,
                    schedule_id=42,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Failed to Remove Schedule"


# ============================================================================
# Schedule Enable Command Tests
# ============================================================================


class TestScheduleEnableCommand:
    """Tests for schedule enable command."""

    @pytest.mark.asyncio
    async def test_enable_schedule_success(self, command_context):
        """Test enabling a schedule successfully."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.enable_schedule = AsyncMock(return_value=True)

            await schedule_enable_command(
                ctx=command_context,
                schedule_id=42,
                json_output=False,
            )

            # Verify enable_schedule called with correct ID
            mock_scheduler.enable_schedule.assert_called_once_with(42)

            # Verify success message shown
            command_context.output.success.assert_called_once()
            assert "42" in command_context.output.success.call_args[0][0]

    @pytest.mark.asyncio
    async def test_enable_schedule_not_found(self, command_context):
        """Test enabling a non-existent schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.enable_schedule = AsyncMock(return_value=False)

            with pytest.raises(typer.Exit):
                await schedule_enable_command(
                    ctx=command_context,
                    schedule_id=999,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Schedule Not Found"
            assert "999" in error_call[1]["message"]

    @pytest.mark.asyncio
    async def test_enable_schedule_error(self, command_context):
        """Test enable schedule handles errors."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.enable_schedule = AsyncMock(side_effect=Exception("Database error"))

            with pytest.raises(typer.Exit):
                await schedule_enable_command(
                    ctx=command_context,
                    schedule_id=42,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Failed to Enable Schedule"


# ============================================================================
# Schedule Disable Command Tests
# ============================================================================


class TestScheduleDisableCommand:
    """Tests for schedule disable command."""

    @pytest.mark.asyncio
    async def test_disable_schedule_success(self, command_context):
        """Test disabling a schedule successfully."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.disable_schedule = AsyncMock(return_value=True)

            await schedule_disable_command(
                ctx=command_context,
                schedule_id=42,
                json_output=False,
            )

            # Verify disable_schedule called with correct ID
            mock_scheduler.disable_schedule.assert_called_once_with(42)

            # Verify success message shown
            command_context.output.success.assert_called_once()
            assert "42" in command_context.output.success.call_args[0][0]

    @pytest.mark.asyncio
    async def test_disable_schedule_not_found(self, command_context):
        """Test disabling a non-existent schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.disable_schedule = AsyncMock(return_value=False)

            with pytest.raises(typer.Exit):
                await schedule_disable_command(
                    ctx=command_context,
                    schedule_id=999,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Schedule Not Found"
            assert "999" in error_call[1]["message"]

    @pytest.mark.asyncio
    async def test_disable_schedule_error(self, command_context):
        """Test disable schedule handles errors."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.disable_schedule = AsyncMock(side_effect=Exception("Database error"))

            with pytest.raises(typer.Exit):
                await schedule_disable_command(
                    ctx=command_context,
                    schedule_id=42,
                    json_output=False,
                )

            # Verify error shown
            command_context.output.show_error_panel.assert_called_once()
            error_call = command_context.output.show_error_panel.call_args
            assert error_call[1]["title"] == "Failed to Disable Schedule"


# ============================================================================
# Edge Cases and Error Handling Tests
# ============================================================================


class TestScheduleCommandsEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_add_schedule_with_all_day_types(self, command_context):
        """Test schedule report formatting for all frequency types."""
        test_cases = [
            # (frequency, day_of_week, day_of_month, expected_in_report)
            ("daily", None, None, "daily at 02:00"),
            ("weekly", 0, None, "Sunday"),
            ("weekly", 1, None, "Monday"),
            ("weekly", 2, None, "Tuesday"),
            ("weekly", 3, None, "Wednesday"),
            ("weekly", 4, None, "Thursday"),
            ("weekly", 5, None, "Friday"),
            ("weekly", 6, None, "Saturday"),
            ("monthly", None, 1, "day 1"),
            ("monthly", None, 15, "day 15"),
            ("monthly", None, 31, "day 31"),
        ]

        for frequency, dow, dom, expected in test_cases:
            with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
                mock_scheduler = MockScheduler.return_value
                mock_scheduler.add_schedule = AsyncMock(return_value=1)

                await schedule_add_command(
                    ctx=command_context,
                    command="check",
                    frequency=frequency,
                    time="02:00",
                    day_of_week=dow,
                    day_of_month=dom,
                    json_output=False,
                )

                # Verify expected text in report
                report_data = command_context.output.show_report.call_args[0][1]
                assert expected in report_data["Schedule"]

                # Reset mock for next iteration
                command_context.output.show_report.reset_mock()

    @pytest.mark.asyncio
    async def test_list_schedules_with_all_day_abbreviations(self, command_context):
        """Test that list displays correct day abbreviations for all days."""
        schedules = []
        day_abbrevs = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

        # Create a schedule for each day of the week
        for i, abbrev in enumerate(day_abbrevs):
            schedules.append(
                ScheduleEntry(
                    id=i + 1,
                    command="check",
                    frequency="weekly",
                    day_of_week=i,
                    day_of_month=None,
                    time="02:00",
                    enabled=True,
                    created_at="2024-01-01T00:00:00",
                    last_run=None,
                )
            )

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(return_value=schedules)

            await schedule_list_command(
                ctx=command_context,
                enabled_only=False,
                json_output=False,
            )

            # Verify all day abbreviations displayed correctly
            rows = command_context.output.show_table.call_args[0][2]
            for i, abbrev in enumerate(day_abbrevs):
                assert rows[i][4] == abbrev

    @pytest.mark.asyncio
    async def test_list_truncates_last_run_timestamp(self, command_context):
        """Test that last_run timestamp is truncated to 19 chars (YYYY-MM-DD HH:MM:SS)."""
        schedule_with_long_timestamp = ScheduleEntry(
            id=1,
            command="check",
            frequency="daily",
            day_of_week=None,
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2024-01-01T00:00:00.123456",
            last_run="2024-01-10T03:00:00.123456+00:00",  # Long timestamp with TZ
        )

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MockScheduler.return_value
            mock_scheduler.list_schedules = AsyncMock(return_value=[schedule_with_long_timestamp])

            await schedule_list_command(
                ctx=command_context,
                enabled_only=False,
                json_output=False,
            )

            # Verify timestamp truncated
            rows = command_context.output.show_table.call_args[0][2]
            assert rows[0][6] == "2024-01-10T03:00:00"

    @pytest.mark.asyncio
    async def test_all_commands_require_storage(self, mock_output_manager):
        """Test that all schedule commands require storage."""
        ctx_no_storage = CommandContext(
            output=mock_output_manager,
            storage=None,
            json_mode=False,
        )

        commands = [
            (
                schedule_add_command,
                {
                    "command": "check",
                    "frequency": "daily",
                    "time": "02:00",
                    "day_of_week": None,
                    "day_of_month": None,
                    "json_output": False,
                },
            ),
            (schedule_list_command, {"enabled_only": False, "json_output": False}),
            (schedule_remove_command, {"schedule_id": 1, "json_output": False}),
            (schedule_enable_command, {"schedule_id": 1, "json_output": False}),
            (schedule_disable_command, {"schedule_id": 1, "json_output": False}),
        ]

        for command_func, kwargs in commands:
            with pytest.raises(AssertionError):
                await command_func(ctx=ctx_no_storage, **kwargs)
