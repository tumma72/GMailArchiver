"""Connectors layer - external system integrations."""

from .auth import SCOPES, Credentials, GmailAuthenticator
from .gmail_client import GmailClient
from .platform_scheduler import (
    LaunchdScheduler,
    PlatformScheduler,
    SystemdScheduler,
    TaskSchedulerWindows,
    UnsupportedPlatformError,
    get_platform_scheduler,
)
from .scheduler import ScheduleEntry, Scheduler, ScheduleValidationError

__all__ = [
    # Authentication
    "GmailAuthenticator",
    "Credentials",
    "SCOPES",
    # Gmail API
    "GmailClient",
    # Scheduling
    "Scheduler",
    "ScheduleEntry",
    "ScheduleValidationError",
    # Platform-specific scheduling
    "PlatformScheduler",
    "SystemdScheduler",
    "LaunchdScheduler",
    "TaskSchedulerWindows",
    "UnsupportedPlatformError",
    "get_platform_scheduler",
]
