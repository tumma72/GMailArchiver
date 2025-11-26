# Connectors Layer Architecture

**Last Updated:** 2025-11-26

The connectors layer provides external system integrations: Gmail API access, OAuth authentication, and platform-specific scheduling.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared` layer only |
| **Dependents** | `core`, `cli` layers |
| **Responsibility** | Gmail API, OAuth2, platform scheduling |
| **Thread Safety** | Not thread-safe (credentials/service objects not shared) |

---

## Components

### GmailAuthenticator

OAuth2 authentication flow with bundled credentials support.

```mermaid
classDiagram
    class GmailAuthenticator {
        +credentials_file: Path
        +token_file: Path
        +__init__(credentials_file, token_file)
        +authenticate() Credentials
        +revoke()
        +validate_scopes() bool
        +has_required_scopes() bool
    }
    class Credentials {
        <<google.oauth2>>
        +token: str
        +refresh_token: str
        +expired: bool
        +valid: bool
    }
    GmailAuthenticator --> Credentials
```

#### Interface

- **Authenticate**: `authenticate()` returns valid Google OAuth2 credentials
- **Token storage**: Saves/loads tokens from XDG-compliant paths
- **Bundled credentials**: Uses app credentials by default, no user setup required
- **Scope validation**: `validate_scopes()` checks if token has required permissions

#### Key Functions

| Function | Purpose |
|----------|---------|
| `_get_bundled_credentials_path()` | Get path to bundled OAuth credentials |
| `_get_default_token_path()` | Get XDG-compliant token storage path |

---

### GmailClient

Gmail API wrapper with retry logic and batch operations.

```mermaid
classDiagram
    class GmailClient {
        +service: Resource
        +batch_size: int
        +max_retries: int
        +batch_delay: float
        +__init__(credentials, batch_size, max_retries)
        +list_messages(query) list
        +get_messages_batch(message_ids) list
        +get_message(message_id) dict
        +delete_message(message_id)
        +trash_message(message_id)
    }
```

#### Interface

- **List messages**: Query Gmail with automatic pagination
- **Batch fetch**: Retrieve multiple messages efficiently
- **Retry logic**: Exponential backoff for rate limits and server errors
- **Delete/trash**: Remove messages from Gmail

#### Retry Strategy

```mermaid
sequenceDiagram
    participant C as GmailClient
    participant A as Gmail API

    C->>A: API request
    alt Success
        A-->>C: Response
    else Rate limit (429)
        A-->>C: 429 Error
        C->>C: Wait (2^retry + jitter)
        C->>A: Retry request
    else Server error (500/503)
        A-->>C: 5xx Error
        C->>C: Wait (2^retry + jitter)
        C->>A: Retry request
    end
```

---

### Scheduler

Schedule storage and management (database-backed).

```mermaid
classDiagram
    class Scheduler {
        +db_path: Path
        +__init__(db_path)
        +create_schedule(command, frequency, ...) ScheduleEntry
        +get_schedule(id) ScheduleEntry
        +list_schedules() list
        +update_schedule(id, ...)
        +delete_schedule(id)
        +update_last_run(id, timestamp)
    }
    class ScheduleEntry {
        +id: int
        +command: str
        +frequency: str
        +day_of_week: int
        +day_of_month: int
        +time: str
        +enabled: bool
        +created_at: str
        +last_run: str
        +to_dict() dict
    }
    class ScheduleValidationError {
        <<exception>>
    }
    Scheduler --> ScheduleEntry
```

#### Interface

- **CRUD operations**: Create, read, update, delete schedules
- **Validation**: Ensures schedule parameters are valid
- **Persistence**: SQLite-backed storage

---

### PlatformScheduler

Platform-specific scheduling implementations.

```mermaid
classDiagram
    class PlatformScheduler {
        <<abstract>>
        +install(entry)
        +uninstall(entry)
    }
    class SystemdScheduler {
        +get_user_systemd_directory() Path
        +install(entry)
        +uninstall(entry)
    }
    class LaunchdScheduler {
        +get_user_agents_directory() Path
        +install(entry)
        +uninstall(entry)
    }
    class WindowsTaskScheduler {
        +install(entry)
        +uninstall(entry)
    }
    class UnsupportedPlatformError {
        <<exception>>
    }
    PlatformScheduler <|-- SystemdScheduler
    PlatformScheduler <|-- LaunchdScheduler
    PlatformScheduler <|-- WindowsTaskScheduler
```

#### Platform Support

| Platform | Implementation | Location |
|----------|---------------|----------|
| **Linux** | systemd timers | `~/.config/systemd/user/` |
| **macOS** | launchd plists | `~/Library/LaunchAgents/` |
| **Windows** | Task Scheduler | Windows Task Scheduler |

---

## Data Flow

```mermaid
graph TB
    subgraph "Connectors Layer"
        AUTH[GmailAuthenticator]
        CLIENT[GmailClient]
        SCHED[Scheduler]
        PLAT[PlatformScheduler]
    end

    subgraph "External"
        GOOGLE[(Google OAuth)]
        GMAIL[(Gmail API)]
        SYSTEMD[systemd/launchd/TaskSched]
    end

    AUTH --> GOOGLE
    AUTH --> CLIENT
    CLIENT --> GMAIL
    SCHED --> PLAT
    PLAT --> SYSTEMD
```

---

## Security Considerations

### OAuth Credentials

- Bundled credentials are "installed application" type (client secret not confidential)
- Security relies on user consent at authorization time
- Users can provide custom credentials via `--credentials` flag

### Scopes

- **Current scope**: `https://mail.google.com/` (full Gmail access)
- Required for permanent deletion (`messages.delete` API)
- Breaking change from earlier versions - requires re-auth

### Token Storage

- Tokens stored in XDG-compliant paths
- Permissions: user-only readable (0600)
- Refresh tokens allow offline access

---

## Testing Strategy

| Component | Test Focus |
|-----------|------------|
| `GmailAuthenticator` | OAuth flow mocking, token refresh, scope validation |
| `GmailClient` | API responses, retry logic, batch operations |
| `Scheduler` | CRUD operations, validation, edge cases |
| `PlatformScheduler` | File generation (no actual installation in tests) |

See `tests/connectors/` for test implementations.
