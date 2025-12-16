# Connectors Layer

**Status:** Complete (v1.6.0+)

The connectors layer provides external system integrations: Gmail API access, OAuth2 authentication, and platform-specific scheduling.

## Quick Start

### Gmail API (Recommended: Factory Pattern)

```python
import asyncio
from gmailarchiver.connectors import GmailClient

async def main():
    # Factory method handles authentication automatically
    async with GmailClient.create() as client:
        async for msg in client.list_messages("before:2022/01/01"):
            print(msg["id"])

asyncio.run(main())
```

### Gmail API (Alternative: Explicit Auth)

```python
import asyncio
from gmailarchiver.connectors import GmailAuthenticator, GmailClient

async def main():
    # Step 1: Authenticate
    auth = GmailAuthenticator()
    creds = await auth.authenticate_async()

    # Step 2: Create client with credentials
    async with GmailClient(creds) as client:
        async for msg in client.list_messages("before:2022/01/01"):
            print(msg["id"])

asyncio.run(main())
```

### Scheduling

```python
from gmailarchiver.connectors import Scheduler, get_platform_scheduler

# Create schedule in database
with Scheduler("schedules.db") as scheduler:
    schedule_id = scheduler.add_schedule(
        command="archive 3y",
        frequency="weekly",
        day_of_week=0,  # Sunday
        time="02:00",
    )
    entry = scheduler.get_schedule(schedule_id)

# Install on platform (systemd/launchd/Task Scheduler)
platform = get_platform_scheduler()
platform.install(entry)
```

## Components

| Component | Purpose | Test Coverage |
|-----------|---------|---------------|
| `GmailAuthenticator` | OAuth2 authentication | `tests/connectors/test_auth.py` |
| `GmailClient` | Async Gmail API wrapper (HTTP/2) | `tests/connectors/test_gmail_client.py` |
| `AdaptiveRateLimiter` | Token bucket rate limiting | `tests/connectors/test_gmail_client.py` |
| `Scheduler` | Schedule CRUD operations | `tests/connectors/test_scheduler.py` |
| `PlatformScheduler` | Platform-specific scheduling | `tests/connectors/test_platform_scheduler.py` |

## Directory Structure

```
connectors/
├── __init__.py              # Public exports
├── ARCHITECTURE.md          # Design specification
├── README.md                # This file
├── auth.py                  # GmailAuthenticator
├── gmail_client.py          # GmailClient (async, HTTP/2)
├── rate_limiter.py          # AdaptiveRateLimiter
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

# Gmail API (async)
GmailClient

# Rate Limiting
AdaptiveRateLimiter

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
# Sync (blocks during browser auth)
auth = GmailAuthenticator()
creds = auth.authenticate()

# Async (non-blocking via thread pool)
creds = await auth.authenticate_async()
```

### Factory Pattern (Recommended)

The `GmailClient.create()` factory method encapsulates authentication:

```python
# Handles auth + connection automatically
async with GmailClient.create() as client:
    ...
```

### Adaptive Rate Limiting

GmailClient uses `AdaptiveRateLimiter` (token bucket algorithm):

- **Normal**: Bursts up to 20 requests, sustains 10/sec
- **On 429**: Reduce rate by 50%, wait for `Retry-After`
- **On 5xx**: Short backoff (transient error)
- **Recovery**: After 10 successes, increase rate by 10%

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
