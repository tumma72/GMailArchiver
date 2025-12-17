"""Tests for platform-specific scheduler implementations.

This module tests:
- Platform detection
- Systemd timer generation (Linux)
- Launchd plist generation (macOS)
- Task Scheduler XML generation (Windows)
- Fallback warnings

Following TDD: These tests are written FIRST, before implementation.
"""

from unittest.mock import MagicMock, patch

import pytest

from gmailarchiver.connectors.platform_scheduler import (
    LaunchdScheduler,
    SystemdScheduler,
    TaskSchedulerWindows,
    UnsupportedPlatformError,
    get_platform_scheduler,
)
from gmailarchiver.data.scheduler import ScheduleEntry


class TestPlatformDetection:
    """Test platform detection and scheduler selection."""

    @patch("platform.system", return_value="Linux")
    def test_detect_linux_platform(self, mock_system: MagicMock) -> None:
        """Test that Linux is detected and returns SystemdScheduler."""
        scheduler = get_platform_scheduler()
        assert isinstance(scheduler, SystemdScheduler)

    @patch("platform.system", return_value="Darwin")
    def test_detect_macos_platform(self, mock_system: MagicMock) -> None:
        """Test that macOS is detected and returns LaunchdScheduler."""
        scheduler = get_platform_scheduler()
        assert isinstance(scheduler, LaunchdScheduler)

    @patch("platform.system", return_value="Windows")
    def test_detect_windows_platform(self, mock_system: MagicMock) -> None:
        """Test that Windows is detected and returns TaskSchedulerWindows."""
        scheduler = get_platform_scheduler()
        assert isinstance(scheduler, TaskSchedulerWindows)

    @patch("platform.system", return_value="FreeBSD")
    def test_unsupported_platform_raises_error(self, mock_system: MagicMock) -> None:
        """Test that unsupported platform raises UnsupportedPlatformError."""
        with pytest.raises(UnsupportedPlatformError, match="Unsupported platform"):
            get_platform_scheduler()


class TestSystemdScheduler:
    """Test systemd timer generation for Linux."""

    def test_generate_timer_unit_daily(self) -> None:
        """Test generating systemd timer unit for daily schedule."""
        scheduler = SystemdScheduler()
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

        timer_content = scheduler.generate_timer_unit(entry)

        assert "[Unit]" in timer_content
        assert "Description=Gmail Archiver - check" in timer_content
        assert "[Timer]" in timer_content
        assert "OnCalendar=daily" in timer_content
        assert "Persistent=true" in timer_content
        assert "[Install]" in timer_content
        assert "WantedBy=timers.target" in timer_content

    def test_generate_timer_unit_weekly(self) -> None:
        """Test generating systemd timer unit for weekly schedule."""
        scheduler = SystemdScheduler()
        entry = ScheduleEntry(
            id=1,
            command="archive 3y",
            frequency="weekly",
            day_of_week=0,  # Sunday
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        timer_content = scheduler.generate_timer_unit(entry)

        assert "OnCalendar=Sun *-*-* 02:00:00" in timer_content

    def test_generate_timer_unit_monthly(self) -> None:
        """Test generating systemd timer unit for monthly schedule."""
        scheduler = SystemdScheduler()
        entry = ScheduleEntry(
            id=1,
            command="verify-integrity",
            frequency="monthly",
            day_of_week=None,
            day_of_month=1,
            time="03:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        timer_content = scheduler.generate_timer_unit(entry)

        assert "OnCalendar=*-*-01 03:00:00" in timer_content

    def test_generate_service_unit(self) -> None:
        """Test generating systemd service unit."""
        scheduler = SystemdScheduler()
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

        service_content = scheduler.generate_service_unit(entry)

        assert "[Unit]" in service_content
        assert "Description=Gmail Archiver - check" in service_content
        assert "[Service]" in service_content
        assert "Type=oneshot" in service_content
        assert "ExecStart=" in service_content
        assert "gmailarchiver check" in service_content

    def test_get_timer_filename(self) -> None:
        """Test getting systemd timer filename."""
        scheduler = SystemdScheduler()
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

        filename = scheduler.get_timer_filename(entry)
        assert filename == "gmailarchiver-schedule-1.timer"

    def test_get_service_filename(self) -> None:
        """Test getting systemd service filename."""
        scheduler = SystemdScheduler()
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

        filename = scheduler.get_service_filename(entry)
        assert filename == "gmailarchiver-schedule-1.service"

    def test_get_user_systemd_directory(self) -> None:
        """Test getting user systemd directory path."""
        scheduler = SystemdScheduler()
        systemd_dir = scheduler.get_user_systemd_directory()

        assert ".config/systemd/user" in str(systemd_dir)

    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    def test_install_creates_directory(
        self, mock_write: MagicMock, mock_mkdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install creates systemd directory if it doesn't exist."""
        scheduler = SystemdScheduler()
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

        with patch("subprocess.run"):
            scheduler.install(entry)

        mock_mkdir.assert_called_once()

    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.write_text")
    @patch("subprocess.run")
    def test_install_creates_timer_and_service_files(
        self, mock_run: MagicMock, mock_write: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install creates both timer and service files."""
        scheduler = SystemdScheduler()
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

        scheduler.install(entry)

        # Should write 2 files (timer and service)
        assert mock_write.call_count == 2

    @patch("pathlib.Path.exists", return_value=True)
    @patch("builtins.open")
    @patch("subprocess.run")
    def test_install_enables_and_starts_timer(
        self, mock_run: MagicMock, mock_open: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install enables and starts the timer."""
        scheduler = SystemdScheduler()
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

        scheduler.install(entry)

        # Should run systemctl commands
        assert mock_run.call_count >= 2
        # Check for daemon-reload, enable, and start
        calls = [str(call) for call in mock_run.call_args_list]
        assert any("daemon-reload" in call for call in calls)
        assert any("enable" in call for call in calls)
        assert any("start" in call for call in calls)

    @patch("subprocess.run")
    @patch("pathlib.Path.unlink")
    def test_uninstall_stops_and_disables_timer(
        self, mock_unlink: MagicMock, mock_run: MagicMock
    ) -> None:
        """Test that uninstall stops and disables the timer."""
        scheduler = SystemdScheduler()
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

        scheduler.uninstall(entry)

        # Should run systemctl commands
        calls = [str(call) for call in mock_run.call_args_list]
        assert any("stop" in call for call in calls)
        assert any("disable" in call for call in calls)

    @patch("subprocess.run")
    @patch("pathlib.Path.unlink")
    def test_uninstall_removes_files(self, mock_unlink: MagicMock, mock_run: MagicMock) -> None:
        """Test that uninstall removes timer and service files."""
        scheduler = SystemdScheduler()
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

        scheduler.uninstall(entry)

        # Should remove 2 files (timer and service)
        assert mock_unlink.call_count == 2


class TestLaunchdScheduler:
    """Test launchd plist generation for macOS."""

    def test_generate_plist_daily(self) -> None:
        """Test generating launchd plist for daily schedule."""
        scheduler = LaunchdScheduler()
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

        plist_content = scheduler.generate_plist(entry)

        assert '<?xml version="1.0" encoding="UTF-8"?>' in plist_content
        assert "<plist" in plist_content
        assert "<key>Label</key>" in plist_content
        assert "<string>com.gmailarchiver.schedule.1</string>" in plist_content
        assert "<key>ProgramArguments</key>" in plist_content
        assert "<key>StartCalendarInterval</key>" in plist_content
        assert "<key>Hour</key>" in plist_content
        assert "<integer>2</integer>" in plist_content
        assert "<key>Minute</key>" in plist_content
        assert "<integer>0</integer>" in plist_content

    def test_generate_plist_weekly(self) -> None:
        """Test generating launchd plist for weekly schedule."""
        scheduler = LaunchdScheduler()
        entry = ScheduleEntry(
            id=1,
            command="archive 3y",
            frequency="weekly",
            day_of_week=0,  # Sunday
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        plist_content = scheduler.generate_plist(entry)

        assert "<key>Weekday</key>" in plist_content
        assert "<integer>0</integer>" in plist_content

    def test_generate_plist_monthly(self) -> None:
        """Test generating launchd plist for monthly schedule."""
        scheduler = LaunchdScheduler()
        entry = ScheduleEntry(
            id=1,
            command="verify-integrity",
            frequency="monthly",
            day_of_week=None,
            day_of_month=1,
            time="03:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        plist_content = scheduler.generate_plist(entry)

        assert "<key>Day</key>" in plist_content
        assert "<integer>1</integer>" in plist_content

    def test_get_plist_filename(self) -> None:
        """Test getting launchd plist filename."""
        scheduler = LaunchdScheduler()
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

        filename = scheduler.get_plist_filename(entry)
        assert filename == "com.gmailarchiver.schedule.1.plist"

    def test_get_launchagents_directory(self) -> None:
        """Test getting LaunchAgents directory path."""
        scheduler = LaunchdScheduler()
        launchagents_dir = scheduler.get_launchagents_directory()

        assert "Library/LaunchAgents" in str(launchagents_dir)

    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    def test_install_creates_directory(
        self, mock_write: MagicMock, mock_mkdir: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install creates LaunchAgents directory if it doesn't exist."""
        scheduler = LaunchdScheduler()
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

        with patch("subprocess.run"):
            scheduler.install(entry)

        mock_mkdir.assert_called_once()

    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.write_text")
    @patch("subprocess.run")
    def test_install_creates_plist_file(
        self, mock_run: MagicMock, mock_write: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install creates plist file."""
        scheduler = LaunchdScheduler()
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

        scheduler.install(entry)

        mock_write.assert_called_once()

    @patch("pathlib.Path.exists", return_value=True)
    @patch("builtins.open")
    @patch("subprocess.run")
    def test_install_loads_plist(
        self, mock_run: MagicMock, mock_open: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test that install loads the plist with launchctl."""
        scheduler = LaunchdScheduler()
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

        scheduler.install(entry)

        # Should run launchctl load
        mock_run.assert_called_once()
        call_str = str(mock_run.call_args)
        assert "launchctl" in call_str
        assert "load" in call_str

    @patch("subprocess.run")
    @patch("pathlib.Path.unlink")
    def test_uninstall_unloads_plist(self, mock_unlink: MagicMock, mock_run: MagicMock) -> None:
        """Test that uninstall unloads the plist."""
        scheduler = LaunchdScheduler()
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

        scheduler.uninstall(entry)

        # Should run launchctl unload
        call_str = str(mock_run.call_args)
        assert "launchctl" in call_str
        assert "unload" in call_str

    @patch("subprocess.run")
    @patch("pathlib.Path.unlink")
    def test_uninstall_removes_plist_file(
        self, mock_unlink: MagicMock, mock_run: MagicMock
    ) -> None:
        """Test that uninstall removes plist file."""
        scheduler = LaunchdScheduler()
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

        scheduler.uninstall(entry)

        mock_unlink.assert_called_once()


class TestTaskSchedulerWindows:
    """Test Task Scheduler XML generation for Windows."""

    def test_generate_task_xml_daily(self) -> None:
        """Test generating Task Scheduler XML for daily schedule."""
        scheduler = TaskSchedulerWindows()
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

        xml_content = scheduler.generate_task_xml(entry)

        assert '<?xml version="1.0" encoding="UTF-16"?>' in xml_content
        assert "<Task" in xml_content
        assert "<RegistrationInfo>" in xml_content
        assert "<Description>Gmail Archiver - check</Description>" in xml_content
        assert "<Triggers>" in xml_content
        assert "<CalendarTrigger>" in xml_content
        assert "<ScheduleByDay>" in xml_content
        assert "<DaysInterval>1</DaysInterval>" in xml_content
        assert "<StartBoundary>" in xml_content
        assert "T02:00:00" in xml_content
        assert "<Actions>" in xml_content
        assert "<Exec>" in xml_content
        assert "<Command>gmailarchiver</Command>" in xml_content
        assert "<Arguments>check</Arguments>" in xml_content

    def test_generate_task_xml_weekly(self) -> None:
        """Test generating Task Scheduler XML for weekly schedule."""
        scheduler = TaskSchedulerWindows()
        entry = ScheduleEntry(
            id=1,
            command="archive 3y",
            frequency="weekly",
            day_of_week=0,  # Sunday
            day_of_month=None,
            time="02:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        xml_content = scheduler.generate_task_xml(entry)

        assert "<ScheduleByWeek>" in xml_content
        assert "<DaysOfWeek>" in xml_content
        assert "<Sunday />" in xml_content

    def test_generate_task_xml_monthly(self) -> None:
        """Test generating Task Scheduler XML for monthly schedule."""
        scheduler = TaskSchedulerWindows()
        entry = ScheduleEntry(
            id=1,
            command="verify-integrity",
            frequency="monthly",
            day_of_week=None,
            day_of_month=1,
            time="03:00",
            enabled=True,
            created_at="2025-01-01T00:00:00",
            last_run=None,
        )

        xml_content = scheduler.generate_task_xml(entry)

        assert "<ScheduleByMonth>" in xml_content
        assert "<DaysOfMonth>" in xml_content
        assert "<Day>1</Day>" in xml_content

    def test_get_task_name(self) -> None:
        """Test getting Task Scheduler task name."""
        scheduler = TaskSchedulerWindows()
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

        task_name = scheduler.get_task_name(entry)
        assert task_name == "GmailArchiver-Schedule-1"

    @patch("tempfile.NamedTemporaryFile")
    @patch("subprocess.run")
    def test_install_creates_task(self, mock_run: MagicMock, mock_tempfile: MagicMock) -> None:
        """Test that install creates Windows scheduled task."""
        # Mock temporary file
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.name = "temp.xml"
        mock_tempfile.return_value = mock_file

        scheduler = TaskSchedulerWindows()
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

        scheduler.install(entry)

        # Should run schtasks /Create
        mock_run.assert_called_once()
        call_str = str(mock_run.call_args)
        assert "schtasks" in call_str
        assert "/Create" in call_str

    @patch("subprocess.run")
    def test_uninstall_deletes_task(self, mock_run: MagicMock) -> None:
        """Test that uninstall deletes Windows scheduled task."""
        scheduler = TaskSchedulerWindows()
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

        scheduler.uninstall(entry)

        # Should run schtasks /Delete
        mock_run.assert_called_once()
        call_str = str(mock_run.call_args)
        assert "schtasks" in call_str
        assert "/Delete" in call_str


class TestPlatformSchedulerInterface:
    """Test that all platform schedulers implement required interface."""

    def test_systemd_implements_install(self) -> None:
        """Test that SystemdScheduler implements install method."""
        scheduler = SystemdScheduler()
        assert hasattr(scheduler, "install")
        assert callable(scheduler.install)

    def test_systemd_implements_uninstall(self) -> None:
        """Test that SystemdScheduler implements uninstall method."""
        scheduler = SystemdScheduler()
        assert hasattr(scheduler, "uninstall")
        assert callable(scheduler.uninstall)

    def test_launchd_implements_install(self) -> None:
        """Test that LaunchdScheduler implements install method."""
        scheduler = LaunchdScheduler()
        assert hasattr(scheduler, "install")
        assert callable(scheduler.install)

    def test_launchd_implements_uninstall(self) -> None:
        """Test that LaunchdScheduler implements uninstall method."""
        scheduler = LaunchdScheduler()
        assert hasattr(scheduler, "uninstall")
        assert callable(scheduler.uninstall)

    def test_taskscheduler_implements_install(self) -> None:
        """Test that TaskSchedulerWindows implements install method."""
        scheduler = TaskSchedulerWindows()
        assert hasattr(scheduler, "install")
        assert callable(scheduler.install)

    def test_taskscheduler_implements_uninstall(self) -> None:
        """Test that TaskSchedulerWindows implements uninstall method."""
        scheduler = TaskSchedulerWindows()
        assert hasattr(scheduler, "uninstall")
        assert callable(scheduler.uninstall)
