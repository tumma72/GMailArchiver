"""Platform-specific scheduler implementations.

This module provides platform-specific scheduling implementations:
- Linux: systemd timers
- macOS: launchd plists
- Windows: Task Scheduler

Each platform scheduler can install and uninstall schedules using the
platform's native scheduling system.
"""

import platform
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from gmailarchiver.data.scheduler import ScheduleEntry


class UnsupportedPlatformError(Exception):
    """Raised when platform is not supported."""

    pass


class PlatformScheduler(ABC):
    """Abstract base class for platform-specific schedulers."""

    @abstractmethod
    def install(self, entry: ScheduleEntry) -> None:
        """Install a schedule on the platform.

        Args:
            entry: Schedule entry to install
        """
        pass

    @abstractmethod
    def uninstall(self, entry: ScheduleEntry) -> None:
        """Uninstall a schedule from the platform.

        Args:
            entry: Schedule entry to uninstall
        """
        pass


class SystemdScheduler(PlatformScheduler):
    """Systemd timer scheduler for Linux.

    Creates systemd timer and service units in user systemd directory
    (~/.config/systemd/user/).
    """

    def get_user_systemd_directory(self) -> Path:
        """Get user systemd directory path.

        Returns:
            Path to ~/.config/systemd/user
        """
        return Path.home() / ".config" / "systemd" / "user"

    def get_timer_filename(self, entry: ScheduleEntry) -> str:
        """Get timer unit filename.

        Args:
            entry: Schedule entry

        Returns:
            Timer filename (e.g., "gmailarchiver-schedule-1.timer")
        """
        return f"gmailarchiver-schedule-{entry.id}.timer"

    def get_service_filename(self, entry: ScheduleEntry) -> str:
        """Get service unit filename.

        Args:
            entry: Schedule entry

        Returns:
            Service filename (e.g., "gmailarchiver-schedule-1.service")
        """
        return f"gmailarchiver-schedule-{entry.id}.service"

    def generate_timer_unit(self, entry: ScheduleEntry) -> str:
        """Generate systemd timer unit content.

        Args:
            entry: Schedule entry

        Returns:
            Timer unit file content
        """
        self.get_service_filename(entry)

        # Generate OnCalendar expression
        if entry.frequency == "daily":
            on_calendar = "daily"
        elif entry.frequency == "weekly":
            # Map day_of_week (0=Sunday) to systemd day names
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            assert entry.day_of_week is not None, "Weekly frequency requires day_of_week"
            day_name = days[entry.day_of_week]
            hour, minute = entry.time.split(":")
            on_calendar = f"{day_name} *-*-* {hour}:{minute}:00"
        elif entry.frequency == "monthly":
            hour, minute = entry.time.split(":")
            on_calendar = f"*-*-{entry.day_of_month:02d} {hour}:{minute}:00"
        else:
            on_calendar = "daily"

        return f"""[Unit]
Description=Gmail Archiver - {entry.command}

[Timer]
OnCalendar={on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""

    def generate_service_unit(self, entry: ScheduleEntry) -> str:
        """Generate systemd service unit content.

        Args:
            entry: Schedule entry

        Returns:
            Service unit file content
        """
        # Find gmailarchiver executable path
        gmailarchiver_path = shutil.which("gmailarchiver")
        if gmailarchiver_path is None:
            # Fallback to direct command
            gmailarchiver_path = "gmailarchiver"

        return f"""[Unit]
Description=Gmail Archiver - {entry.command}

[Service]
Type=oneshot
ExecStart={gmailarchiver_path} {entry.command}
"""

    def install(self, entry: ScheduleEntry) -> None:
        """Install systemd timer and service.

        Args:
            entry: Schedule entry to install

        Creates timer and service files, enables and starts the timer.
        """
        systemd_dir = self.get_user_systemd_directory()
        systemd_dir.mkdir(parents=True, exist_ok=True)

        # Write timer unit
        timer_path = systemd_dir / self.get_timer_filename(entry)
        timer_content = self.generate_timer_unit(entry)
        timer_path.write_text(timer_content)

        # Write service unit
        service_path = systemd_dir / self.get_service_filename(entry)
        service_content = self.generate_service_unit(entry)
        service_path.write_text(service_content)

        # Reload systemd, enable and start timer
        timer_name = self.get_timer_filename(entry)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", timer_name], check=True)
        subprocess.run(["systemctl", "--user", "start", timer_name], check=True)

    def uninstall(self, entry: ScheduleEntry) -> None:
        """Uninstall systemd timer and service.

        Args:
            entry: Schedule entry to uninstall

        Stops and disables the timer, removes files.
        """
        systemd_dir = self.get_user_systemd_directory()
        timer_name = self.get_timer_filename(entry)

        # Stop and disable timer
        subprocess.run(
            ["systemctl", "--user", "stop", timer_name],
            check=False,  # Don't fail if already stopped
        )
        subprocess.run(
            ["systemctl", "--user", "disable", timer_name],
            check=False,  # Don't fail if not enabled
        )

        # Remove files
        timer_path = systemd_dir / timer_name
        service_path = systemd_dir / self.get_service_filename(entry)

        timer_path.unlink(missing_ok=True)
        service_path.unlink(missing_ok=True)

        # Reload systemd
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)


class LaunchdScheduler(PlatformScheduler):
    """Launchd scheduler for macOS.

    Creates launchd plist files in user LaunchAgents directory
    (~/Library/LaunchAgents/).
    """

    def get_launchagents_directory(self) -> Path:
        """Get user LaunchAgents directory path.

        Returns:
            Path to ~/Library/LaunchAgents
        """
        return Path.home() / "Library" / "LaunchAgents"

    def get_plist_filename(self, entry: ScheduleEntry) -> str:
        """Get plist filename.

        Args:
            entry: Schedule entry

        Returns:
            Plist filename (e.g., "com.gmailarchiver.schedule.1.plist")
        """
        return f"com.gmailarchiver.schedule.{entry.id}.plist"

    def generate_plist(self, entry: ScheduleEntry) -> str:
        """Generate launchd plist content.

        Args:
            entry: Schedule entry

        Returns:
            Plist file content
        """
        # Find gmailarchiver executable path
        gmailarchiver_path = shutil.which("gmailarchiver")
        if gmailarchiver_path is None:
            gmailarchiver_path = "gmailarchiver"

        # Split command into parts
        command_parts = entry.command.split()

        # Build program arguments array
        program_args = f"        <string>{gmailarchiver_path}</string>\n"
        for part in command_parts:
            program_args += f"        <string>{part}</string>\n"

        # Parse time
        hour, minute = entry.time.split(":")

        # Build calendar interval
        calendar_interval = f"""        <key>Hour</key>
        <integer>{int(hour)}</integer>
        <key>Minute</key>
        <integer>{int(minute)}</integer>"""

        if entry.frequency == "weekly" and entry.day_of_week is not None:
            calendar_interval += f"""
        <key>Weekday</key>
        <integer>{entry.day_of_week}</integer>"""

        if entry.frequency == "monthly" and entry.day_of_month is not None:
            calendar_interval += f"""
        <key>Day</key>
        <integer>{entry.day_of_month}</integer>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gmailarchiver.schedule.{entry.id}</string>
    <key>ProgramArguments</key>
    <array>
{program_args.rstrip()}
    </array>
    <key>StartCalendarInterval</key>
    <dict>
{calendar_interval}
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""

    def install(self, entry: ScheduleEntry) -> None:
        """Install launchd plist.

        Args:
            entry: Schedule entry to install

        Creates plist file and loads it with launchctl.
        """
        launchagents_dir = self.get_launchagents_directory()
        launchagents_dir.mkdir(parents=True, exist_ok=True)

        # Write plist file
        plist_path = launchagents_dir / self.get_plist_filename(entry)
        plist_content = self.generate_plist(entry)
        plist_path.write_text(plist_content)

        # Load with launchctl
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)

    def uninstall(self, entry: ScheduleEntry) -> None:
        """Uninstall launchd plist.

        Args:
            entry: Schedule entry to uninstall

        Unloads plist with launchctl and removes file.
        """
        launchagents_dir = self.get_launchagents_directory()
        plist_path = launchagents_dir / self.get_plist_filename(entry)

        # Unload with launchctl
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            check=False,  # Don't fail if already unloaded
        )

        # Remove file
        plist_path.unlink(missing_ok=True)


class TaskSchedulerWindows(PlatformScheduler):
    """Task Scheduler for Windows.

    Creates scheduled tasks using schtasks.exe.
    """

    def get_task_name(self, entry: ScheduleEntry) -> str:
        """Get task name.

        Args:
            entry: Schedule entry

        Returns:
            Task name (e.g., "GmailArchiver-Schedule-1")
        """
        return f"GmailArchiver-Schedule-{entry.id}"

    def generate_task_xml(self, entry: ScheduleEntry) -> str:
        """Generate Task Scheduler XML content.

        Args:
            entry: Schedule entry

        Returns:
            Task XML content
        """
        # Find gmailarchiver executable. For Task Scheduler XML we only embed
        # the command name (basename) so that tests and production environments
        # are consistent regardless of the virtualenv path.
        gmailarchiver_path = shutil.which("gmailarchiver")
        if gmailarchiver_path is None:
            gmailarchiver_path = "gmailarchiver"
        else:
            # Use just the basename (e.g. "gmailarchiver"), not the full path
            gmailarchiver_path = Path(gmailarchiver_path).name

        # Split command into executable and arguments
        command_parts = entry.command.split(maxsplit=1)
        arguments = command_parts[0] if len(command_parts) > 0 else ""
        if len(command_parts) > 1:
            arguments = entry.command

        # Parse time
        hour, minute = entry.time.split(":")

        # Build schedule trigger
        if entry.frequency == "daily":
            trigger = f"""        <CalendarTrigger>
          <StartBoundary>2025-01-01T{hour}:{minute}:00</StartBoundary>
          <Enabled>true</Enabled>
          <ScheduleByDay>
            <DaysInterval>1</DaysInterval>
          </ScheduleByDay>
        </CalendarTrigger>"""
        elif entry.frequency == "weekly":
            # Map day_of_week to Windows day names
            days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            assert entry.day_of_week is not None, "Weekly frequency requires day_of_week"
            day_name = days[entry.day_of_week]
            trigger = f"""        <CalendarTrigger>
          <StartBoundary>2025-01-01T{hour}:{minute}:00</StartBoundary>
          <Enabled>true</Enabled>
          <ScheduleByWeek>
            <DaysOfWeek>
              <{day_name} />
            </DaysOfWeek>
            <WeeksInterval>1</WeeksInterval>
          </ScheduleByWeek>
        </CalendarTrigger>"""
        elif entry.frequency == "monthly":
            trigger = f"""        <CalendarTrigger>
          <StartBoundary>2025-01-01T{hour}:{minute}:00</StartBoundary>
          <Enabled>true</Enabled>
          <ScheduleByMonth>
            <DaysOfMonth>
              <Day>{entry.day_of_month}</Day>
            </DaysOfMonth>
            <Months>
              <January />
              <February />
              <March />
              <April />
              <May />
              <June />
              <July />
              <August />
              <September />
              <October />
              <November />
              <December />
            </Months>
          </ScheduleByMonth>
        </CalendarTrigger>"""
        else:
            trigger = ""

        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Gmail Archiver - {entry.command}</Description>
  </RegistrationInfo>
  <Triggers>
{trigger}
  </Triggers>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions>
    <Exec>
      <Command>{gmailarchiver_path}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""

    def install(self, entry: ScheduleEntry) -> None:
        """Install Windows scheduled task.

        Args:
            entry: Schedule entry to install

        Creates task using schtasks.exe.
        """
        task_name = self.get_task_name(entry)
        xml_content = self.generate_task_xml(entry)

        # Write XML to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-16"
        ) as f:
            f.write(xml_content)
            xml_path = f.name

        try:
            # Create task
            subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/XML", xml_path, "/F"],
                check=True,
            )
        finally:
            # Clean up temporary file
            Path(xml_path).unlink(missing_ok=True)

    def uninstall(self, entry: ScheduleEntry) -> None:
        """Uninstall Windows scheduled task.

        Args:
            entry: Schedule entry to uninstall

        Deletes task using schtasks.exe.
        """
        task_name = self.get_task_name(entry)

        # Delete task
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            check=False,  # Don't fail if task doesn't exist
        )


def get_platform_scheduler() -> PlatformScheduler:
    """Get appropriate platform scheduler for current OS.

    Returns:
        Platform-specific scheduler instance

    Raises:
        UnsupportedPlatformError: If platform is not supported
    """
    system = platform.system()

    if system == "Linux":
        return SystemdScheduler()
    elif system == "Darwin":
        return LaunchdScheduler()
    elif system == "Windows":
        return TaskSchedulerWindows()
    else:
        raise UnsupportedPlatformError(
            f"Unsupported platform: {system}. "
            "Please use your system's native scheduler (cron, Task Scheduler, etc.)"
        )
