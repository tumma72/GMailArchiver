"""Connectors layer - external system integrations.

Note: Scheduler, ScheduleEntry, and ScheduleValidationError have moved to
the data layer (gmailarchiver.data.scheduler) as of v1.3.
"""

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
from .rate_limiter import AdaptiveRateLimiter

__all__ = [
    # Authentication
    "GmailAuthenticator",
    "Credentials",
    "SCOPES",
    # Gmail API (async-only)
    "GmailClient",
    # Rate Limiting
    "AdaptiveRateLimiter",
    # Platform-specific scheduling
    "PlatformScheduler",
    "SystemdScheduler",
    "LaunchdScheduler",
    "TaskSchedulerWindows",
    "UnsupportedPlatformError",
    "get_platform_scheduler",
]
