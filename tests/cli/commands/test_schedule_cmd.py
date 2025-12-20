"""Tests for CLI schedule commands.

Tests the async command implementations for schedule operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.output import OutputManager
from gmailarchiver.cli.schedule import (
    schedule_add_command,
    schedule_disable_command,
    schedule_enable_command,
    schedule_list_command,
    schedule_remove_command,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock CommandContext for testing."""
    ctx = MagicMock(spec=CommandContext)
    ctx.output = MagicMock(spec=OutputManager)
    ctx.storage = MagicMock()
    ctx.json_mode = False
    ctx.success = MagicMock()
    ctx.warning = MagicMock()
    ctx.fail_and_exit = MagicMock()
    ctx.show_table = MagicMock()
    return ctx


class TestScheduleAddCommand:
    """Tests for schedule add command."""

    @pytest.mark.asyncio
    async def test_add_daily_schedule(self, mock_ctx: MagicMock) -> None:
        """Test adding a daily schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.add_schedule = AsyncMock(return_value=1)
            MockScheduler.return_value = mock_scheduler

            await schedule_add_command(
                ctx=mock_ctx,
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
                json_output=False,
            )

            mock_scheduler.add_schedule.assert_called_once_with(
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
            )
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_weekly_schedule(self, mock_ctx: MagicMock) -> None:
        """Test adding a weekly schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.add_schedule = AsyncMock(return_value=2)
            MockScheduler.return_value = mock_scheduler

            await schedule_add_command(
                ctx=mock_ctx,
                command="archive 3y",
                frequency="weekly",
                time="03:00",
                day_of_week=0,
                day_of_month=None,
                json_output=False,
            )

            mock_scheduler.add_schedule.assert_called_once_with(
                command="archive 3y",
                frequency="weekly",
                time="03:00",
                day_of_week=0,
                day_of_month=None,
            )

    @pytest.mark.asyncio
    async def test_add_monthly_schedule(self, mock_ctx: MagicMock) -> None:
        """Test adding a monthly schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.add_schedule = AsyncMock(return_value=3)
            MockScheduler.return_value = mock_scheduler

            await schedule_add_command(
                ctx=mock_ctx,
                command="check",
                frequency="monthly",
                time="01:00",
                day_of_week=None,
                day_of_month=1,
                json_output=False,
            )

            mock_scheduler.add_schedule.assert_called_once_with(
                command="check",
                frequency="monthly",
                time="01:00",
                day_of_week=None,
                day_of_month=1,
            )

    @pytest.mark.asyncio
    async def test_add_with_json_output(self, mock_ctx: MagicMock) -> None:
        """Test adding a schedule with JSON output flag."""
        mock_ctx.json_mode = True

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.add_schedule = AsyncMock(return_value=4)
            MockScheduler.return_value = mock_scheduler

            await schedule_add_command(
                ctx=mock_ctx,
                command="check",
                frequency="daily",
                time="02:00",
                day_of_week=None,
                day_of_month=None,
                json_output=True,
            )

            mock_scheduler.add_schedule.assert_called_once()


class TestScheduleListCommand:
    """Tests for schedule list command."""

    @pytest.mark.asyncio
    async def test_list_schedules_empty(self, mock_ctx: MagicMock) -> None:
        """Test listing schedules when none exist."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.list_schedules = AsyncMock(return_value=[])
            MockScheduler.return_value = mock_scheduler

            await schedule_list_command(
                ctx=mock_ctx,
                enabled_only=False,
                json_output=False,
            )

            mock_scheduler.list_schedules.assert_called_once_with(enabled_only=False)
            mock_ctx.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, mock_ctx: MagicMock) -> None:
        """Test listing only enabled schedules."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.list_schedules = AsyncMock(return_value=[])
            MockScheduler.return_value = mock_scheduler

            await schedule_list_command(
                ctx=mock_ctx,
                enabled_only=True,
                json_output=False,
            )

            mock_scheduler.list_schedules.assert_called_once_with(enabled_only=True)

    @pytest.mark.asyncio
    async def test_list_with_json_output(self, mock_ctx: MagicMock) -> None:
        """Test listing schedules with JSON output."""
        mock_ctx.json_mode = True

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.list_schedules = AsyncMock(return_value=[])
            MockScheduler.return_value = mock_scheduler

            await schedule_list_command(
                ctx=mock_ctx,
                enabled_only=False,
                json_output=True,
            )

            mock_scheduler.list_schedules.assert_called_once()


class TestScheduleRemoveCommand:
    """Tests for schedule remove command."""

    @pytest.mark.asyncio
    async def test_remove_schedule(self, mock_ctx: MagicMock) -> None:
        """Test removing a schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.remove_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_remove_command(
                ctx=mock_ctx,
                schedule_id=1,
                json_output=False,
            )

            mock_scheduler.remove_schedule.assert_called_once_with(1)
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_with_json_output(self, mock_ctx: MagicMock) -> None:
        """Test removing a schedule with JSON output."""
        mock_ctx.json_mode = True

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.remove_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_remove_command(
                ctx=mock_ctx,
                schedule_id=2,
                json_output=True,
            )

            mock_scheduler.remove_schedule.assert_called_once_with(2)


class TestScheduleEnableCommand:
    """Tests for schedule enable command."""

    @pytest.mark.asyncio
    async def test_enable_schedule(self, mock_ctx: MagicMock) -> None:
        """Test enabling a schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.enable_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_enable_command(
                ctx=mock_ctx,
                schedule_id=1,
                json_output=False,
            )

            mock_scheduler.enable_schedule.assert_called_once_with(1)
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_with_json_output(self, mock_ctx: MagicMock) -> None:
        """Test enabling a schedule with JSON output."""
        mock_ctx.json_mode = True

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.enable_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_enable_command(
                ctx=mock_ctx,
                schedule_id=3,
                json_output=True,
            )

            mock_scheduler.enable_schedule.assert_called_once_with(3)


class TestScheduleDisableCommand:
    """Tests for schedule disable command."""

    @pytest.mark.asyncio
    async def test_disable_schedule(self, mock_ctx: MagicMock) -> None:
        """Test disabling a schedule."""
        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.disable_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_disable_command(
                ctx=mock_ctx,
                schedule_id=1,
                json_output=False,
            )

            mock_scheduler.disable_schedule.assert_called_once_with(1)
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_with_json_output(self, mock_ctx: MagicMock) -> None:
        """Test disabling a schedule with JSON output."""
        mock_ctx.json_mode = True

        with patch("gmailarchiver.cli.schedule.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.disable_schedule = AsyncMock(return_value=True)
            MockScheduler.return_value = mock_scheduler

            await schedule_disable_command(
                ctx=mock_ctx,
                schedule_id=2,
                json_output=True,
            )

            mock_scheduler.disable_schedule.assert_called_once_with(2)
