# Connectors Layer

**Status:** Complete (v1.5.0+)

The connectors layer provides external system integrations: Gmail API access, OAuth2 authentication, and platform-specific scheduling.

## Quick Start

```python
from gmailarchiver.connectors import (
    GmailAuthenticator,
    GmailClient,
    Scheduler,
    get_platform_scheduler,
)

# Authentication
auth = GmailAuthenticator()
creds = auth.authenticate()

# Gmail API access
client = GmailClient(creds)
messages = client.list_messages("before:2022/01/01")

# Scheduling
scheduler = Scheduler("schedules.db")
entry = scheduler.create_schedule(
    command="archive 3y",
    frequency="weekly",
    day_of_week=0,  # Sunday
    time="02:00",
)

# Platform-specific scheduling
platform = get_platform_scheduler()
platform.install(entry)
```

## Components

| Component | Purpose | Test Coverage |
|-----------|---------|---------------|
| `GmailAuthenticator` | OAuth2 authentication | `tests/connectors/test_auth.py` |
| `GmailClient` | Gmail API wrapper | `tests/connectors/test_gmail_client.py` |
| `Scheduler` | Schedule CRUD operations | `tests/connectors/test_scheduler.py` |
| `PlatformScheduler` | Platform-specific scheduling | `tests/connectors/test_platform_scheduler.py` |

## Directory Structure

```
connectors/
├── __init__.py              # Public exports
├── ARCHITECTURE.md          # Design specification
├── README.md                # This file
├── auth.py                  # GmailAuthenticator
├── gmail_client.py          # GmailClient
├── scheduler.py             # Scheduler, ScheduleEntry
├── platform_scheduler.py    # Platform-specific implementations
└── config/
    └── oauth_credentials.json  # Bundled OAuth credentials
```

## Exports

The layer exports these symbols via `gmailarchiver.connectors`:

```python
# Authentication
GmailAuthenticator
Credentials
SCOPES

# Gmail API
GmailClient

# Scheduling
Scheduler
ScheduleEntry
ScheduleValidationError

# Platform-specific scheduling
PlatformScheduler
SystemdScheduler
LaunchdScheduler
TaskSchedulerWindows
UnsupportedPlatformError
get_platform_scheduler
```

## Dependencies

- **Internal:** `gmailarchiver.shared` (utils, validators)
- **External:**
  - `google-api-python-client` (Gmail API)
  - `google-auth`, `google-auth-oauthlib` (OAuth2)

## Design Notes

### OAuth Flow

1. Check for existing token at XDG-compliant path
2. If valid, return credentials
3. If expired, attempt refresh
4. If missing/invalid, launch OAuth flow
5. Save token for future use

```python
auth = GmailAuthenticator()
creds = auth.authenticate()  # Handles all cases automatically
```

### Retry Logic

Gmail API calls use exponential backoff:

```python
# On rate limit (429) or server error (500/503):
# wait = 2^retry + random_jitter
# max_retries = 5 (configurable)
```

### Platform Detection

`get_platform_scheduler()` automatically selects the correct implementation:

| Platform | Scheduler | Unit Files |
|----------|-----------|------------|
| Linux | `SystemdScheduler` | `~/.config/systemd/user/` |
| macOS | `LaunchdScheduler` | `~/Library/LaunchAgents/` |
| Windows | `TaskSchedulerWindows` | Windows Task Scheduler |

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Design specification with Mermaid diagrams
- [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) - System-wide architecture
