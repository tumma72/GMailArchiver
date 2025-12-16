# Connectors Layer Architecture

**Last Updated:** 2025-12-16

The connectors layer provides external system integrations: Gmail API access, OAuth authentication, and platform-specific scheduling.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared` layer only |
| **Dependents** | `core`, `cli` layers |
| **Responsibility** | Gmail API, OAuth2, platform scheduling |
| **Concurrency Model** | Async-first with asyncio (v1.6.0+) |
| **HTTP Library** | httpx (HTTP/2 support) |

---

## Components

### GmailAuthenticator

OAuth2 authentication flow with bundled credentials support.

```mermaid
classDiagram
    class GmailAuthenticator {
        +credentials_file: Path
        +token_file: Path
        +__init__(credentials_file, token_file, validate_paths, output)
        +authenticate() Credentials
        +authenticate_async() Credentials
        +refresh_token_async() Credentials
        +revoke() None
        +validate_scopes(required_scopes) bool
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

| Method | Purpose | Returns |
|--------|---------|---------|
| `authenticate()` | Sync OAuth2 flow (may open browser) | `Credentials` |
| `authenticate_async()` | Async wrapper via `asyncio.to_thread()` | `Credentials` |
| `refresh_token_async()` | Async token refresh | `Credentials \| None` |
| `revoke()` | Revoke token and delete token file | `None` |
| `validate_scopes(scopes)` | Check if credentials have required scopes | `bool` |

#### Features

- **Token storage**: Saves/loads tokens from XDG-compliant paths
- **Bundled credentials**: Uses app credentials by default, no user setup required
- **Scope validation**: `validate_scopes()` checks if token has required permissions
- **Async support**: All blocking operations have async variants

#### Key Functions

| Function | Purpose |
|----------|---------|
| `_get_bundled_credentials_path()` | Get path to bundled OAuth credentials |
| `_get_default_token_path()` | Get XDG-compliant token storage path |

---

### GmailClient (Async)

Async Gmail API client with adaptive rate limiting and HTTP/2 support.

```mermaid
classDiagram
    class GmailClient {
        -_http_client: httpx.AsyncClient
        -_rate_limiter: AdaptiveRateLimiter
        -_credentials: Credentials
        -_authenticator: GmailAuthenticator
        +batch_size: int
        +max_retries: int
        +__init__(credentials, batch_size, max_retries)
        +create(credentials_file, batch_size, max_retries, output)$ GmailClient
        +connect() GmailClient
        +close() None
        +list_messages(query) AsyncIterator~dict~
        +get_messages_batch(message_ids) AsyncIterator~dict~
        +get_message(message_id) dict
        +trash_messages(message_ids) int
        +delete_messages_permanent(message_ids) int
        +search_by_rfc_message_id(rfc_id) str~None~
        +search_by_rfc_message_ids_batch(rfc_ids) dict
        +decode_message_raw(message) bytes
    }

    class AdaptiveRateLimiter {
        -_tokens: float
        -_max_tokens: float
        -_refill_rate: float
        -_min_refill_rate: float
        -_last_refill: float
        -_consecutive_successes: int
        +acquire() Awaitable~None~
        +on_success() None
        +on_rate_limit(retry_after) float
        +on_server_error() None
    }

    GmailClient --> AdaptiveRateLimiter
    GmailClient ..> GmailAuthenticator : creates via factory
```

#### Factory Method Pattern (Recommended)

The `create()` class method provides a simplified API that encapsulates authentication:

```python
# RECOMMENDED: Factory method handles authentication automatically
async with GmailClient.create() as client:
    async for msg in client.list_messages("before:2022/01/01"):
        print(msg["id"])

# With custom credentials (for testing or advanced use)
async with GmailClient.create(credentials_file="custom_oauth.json") as client:
    ...

# ALTERNATIVE: Direct construction (testing with mocks)
async with GmailClient(mock_credentials) as client:
    ...
```

**When to use each pattern:**

| Pattern | Use Case |
|---------|----------|
| `GmailClient.create()` | Application code, CLI commands (default) |
| `GmailClient(credentials)` | Testing with mock credentials, explicit control |

#### Async Interface

All methods are async and non-blocking:

| Method | Purpose | Returns |
|--------|---------|---------|
| `create(credentials_file, ...)` | **Factory:** Create authenticated client | `GmailClient` |
| `connect()` | Initialize HTTP client (called by `create()`) | `GmailClient` |
| `close()` | Close HTTP client and release resources | `None` |
| `list_messages(query)` | Query Gmail with pagination | `AsyncIterator[dict]` |
| `get_messages_batch(ids)` | Fetch multiple messages | `AsyncIterator[dict]` |
| `get_message(id)` | Fetch single message | `dict` |
| `trash_messages(ids)` | Move to trash | `int` (count) |
| `delete_messages_permanent(ids)` | Permanently delete | `int` (count) |
| `search_by_rfc_message_id(rfc_id)` | Find Gmail ID by Message-ID header | `str \| None` |
| `search_by_rfc_message_ids_batch(ids)` | Batch Message-ID lookup | `dict[str, str \| None]` |
| `decode_message_raw(message)` | Decode base64 raw message | `bytes` |

#### Adaptive Rate Limiting

The `AdaptiveRateLimiter` uses a token bucket algorithm with dynamic rate adjustment:

```mermaid
stateDiagram-v2
    [*] --> Healthy: Initial state

    Healthy --> Healthy: Success (refill tokens)
    Healthy --> Throttled: 429 Rate Limit
    Healthy --> Degraded: 5xx Server Error

    Throttled --> Throttled: More 429s (decrease rate)
    Throttled --> Recovering: Wait + Success

    Recovering --> Healthy: N consecutive successes
    Recovering --> Throttled: 429 Rate Limit

    Degraded --> Recovering: Success after wait
    Degraded --> Degraded: More 5xx (backoff)
```

**Token Bucket Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_tokens` | 20 | Burst capacity |
| `refill_rate` | 10/sec | Sustained rate (baseline) |
| `min_refill_rate` | 1/sec | Floor when heavily throttled |
| `backoff_factor` | 0.5 | Rate reduction on 429 |
| `recovery_threshold` | 10 | Successes before rate increase |

**Behavior:**

1. **Normal operation**: Token bucket allows bursts up to 20 requests, sustains 10 req/sec
2. **On 429**: Reduce refill rate by 50%, wait for `Retry-After` header (or exponential backoff)
3. **On 5xx**: Short backoff, don't reduce rate (transient error)
4. **Recovery**: After 10 consecutive successes, increase rate by 10% (up to baseline)

#### Request Flow (Async)

```mermaid
sequenceDiagram
    participant Core as Core Layer
    participant Client as GmailClient
    participant RL as AdaptiveRateLimiter
    participant HTTP as httpx.AsyncClient
    participant Gmail as Gmail API

    Core->>Client: await get_messages_batch(ids)

    loop For each batch
        Client->>RL: await acquire()
        RL->>RL: Wait for token (if needed)
        RL-->>Client: Token acquired

        Client->>HTTP: POST /batch (HTTP/2)
        HTTP->>Gmail: Multiplexed request

        alt Success (200)
            Gmail-->>HTTP: Batch response
            HTTP-->>Client: Parsed messages
            Client->>RL: on_success()
            Client-->>Core: yield messages
        else Rate Limit (429)
            Gmail-->>HTTP: 429 + Retry-After
            HTTP-->>Client: RateLimitError
            Client->>RL: on_rate_limit(retry_after)
            RL->>RL: Reduce refill_rate
            Client->>Client: await asyncio.sleep(wait)
            Note over Client: Retry same batch
        else Server Error (5xx)
            Gmail-->>HTTP: 500/503
            HTTP-->>Client: ServerError
            Client->>RL: on_server_error()
            Client->>Client: await asyncio.sleep(backoff)
            Note over Client: Retry with exponential backoff
        end
    end
```

#### HTTP/2 Benefits

Using httpx with HTTP/2 provides:

- **Multiplexing**: Multiple requests over single connection (reduces TCP overhead)
- **Header compression**: HPACK reduces bandwidth
- **Server push**: (Not used by Gmail API, but available)
- **Better latency**: No head-of-line blocking

```python
# HTTP/2 enabled by default with httpx
async with httpx.AsyncClient(http2=True) as client:
    response = await client.get("https://gmail.googleapis.com/...")
```

#### Why No Circuit Breaker

We use adaptive rate limiting instead of a full circuit breaker because:

1. **Single-user CLI**: No need to protect downstream services
2. **Predictable API**: Gmail has quota-based limits, not capacity-based
3. **User experience**: Circuit breaker "open" state blocks ALL requests
4. **Gmail behavior**: 429 errors include `Retry-After` guidance

Adaptive rate limiting provides the benefits (backoff, recovery) without the "punishing" aspect of blocking all requests.

---

### Scheduler

Schedule storage and management (database-backed).

```mermaid
classDiagram
    class Scheduler {
        +db_path: Path
        +__init__(db_path)
        +add_schedule(command, frequency, time, ...) int
        +get_schedule(id) ScheduleEntry
        +list_schedules(enabled_only) list~ScheduleEntry~
        +remove_schedule(id) bool
        +enable_schedule(id) bool
        +disable_schedule(id) bool
        +update_last_run(id) None
        +close() None
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

| Method | Purpose | Returns |
|--------|---------|---------|
| `add_schedule(command, frequency, time, ...)` | Create a new schedule | `int` (schedule ID) |
| `get_schedule(id)` | Get schedule by ID | `ScheduleEntry \| None` |
| `list_schedules(enabled_only=False)` | List all schedules | `list[ScheduleEntry]` |
| `remove_schedule(id)` | Delete a schedule | `bool` (success) |
| `enable_schedule(id)` | Enable a schedule | `bool` (success) |
| `disable_schedule(id)` | Disable a schedule | `bool` (success) |
| `update_last_run(id)` | Record execution timestamp | `None` |
| `close()` | Close database connection | `None` |

#### Features

- **CRUD operations**: Create, read, delete schedules (enable/disable for updates)
- **Validation**: Ensures schedule parameters are valid (frequency, time format, day ranges)
- **Persistence**: SQLite-backed storage with context manager support

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
        CLIENT[GmailClient]
        AUTH[GmailAuthenticator]
        RL[AdaptiveRateLimiter]
        SCHED[Scheduler]
        PLAT[PlatformScheduler]
    end

    subgraph "HTTP Layer"
        HTTPX[httpx.AsyncClient<br/>HTTP/2]
    end

    subgraph "External"
        GOOGLE[(Google OAuth)]
        GMAIL[(Gmail API)]
        SYSTEMD[systemd/launchd/TaskSched]
    end

    CLIENT -.->|"create() factory"| AUTH
    AUTH --> GOOGLE
    CLIENT --> RL
    CLIENT --> HTTPX
    HTTPX --> GMAIL
    SCHED --> PLAT
    PLAT --> SYSTEMD
```

### Authentication Flow (Factory Pattern)

```mermaid
sequenceDiagram
    participant App as Application
    participant GC as GmailClient
    participant AUTH as GmailAuthenticator
    participant Google as Google OAuth

    App->>GC: await GmailClient.create()
    GC->>AUTH: GmailAuthenticator()
    GC->>AUTH: await authenticate_async()
    AUTH->>Google: OAuth2 flow
    Google-->>AUTH: Credentials
    AUTH-->>GC: Credentials
    GC->>GC: GmailClient(credentials)
    GC->>GC: await connect()
    GC-->>App: Authenticated client

    Note over App,GC: Client ready for use

    App->>GC: async for msg in list_messages()
    GC-->>App: Messages

    App->>GC: __aexit__()
    GC->>GC: await close()
```

### Async Migration Strategy

The connectors layer is part of the bottom-up async migration:

```mermaid
graph TB
    subgraph "1. Data Layer ✅"
        DB[DBManager<br/>aiosqlite]
        HS[HybridStorage<br/>async context managers]
    end

    subgraph "2. Connectors Layer 🔄"
        GC[GmailClient<br/>httpx + async]
        RL[AdaptiveRateLimiter]
    end

    subgraph "3. Core Layer (Next)"
        ARCH[ArchiverFacade]
        IMP[ImporterFacade]
    end

    subgraph "4. CLI Layer (Bridge)"
        CMD["Commands<br/>asyncio.run()"]
    end

    DB --> HS
    GC --> ARCH
    HS --> ARCH
    ARCH --> CMD
```

**Key Principle:** CLI layer is the ONLY place where `asyncio.run()` bridges sync commands to async processing.

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

| Component | Test Focus | Async |
|-----------|------------|-------|
| `GmailAuthenticator` | OAuth flow mocking, token refresh, scope validation | Mixed |
| `GmailClient` | API responses, retry logic, batch operations, **factory method** | Yes |
| `AdaptiveRateLimiter` | Token bucket behavior, backoff, recovery | Yes |
| `Scheduler` | CRUD operations, validation, edge cases | No |
| `PlatformScheduler` | File generation (no actual installation in tests) | No |

### Factory Method Testing

The factory pattern allows different testing strategies:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from google.oauth2.credentials import Credentials

@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials for testing."""
    creds = MagicMock(spec=Credentials)
    creds.token = "test_token"
    creds.refresh_token = "test_refresh"
    creds.expired = False
    creds.valid = True
    return creds

# Test 1: Factory method with mocked auth
@pytest.mark.asyncio
async def test_create_with_default_credentials(mock_credentials):
    """Test factory method with bundled credentials."""
    with patch("gmailarchiver.connectors.gmail_client.GmailAuthenticator") as mock_auth_cls:
        mock_auth = mock_auth_cls.return_value
        mock_auth.authenticate_async = AsyncMock(return_value=mock_credentials)

        client = await GmailClient.create()
        try:
            assert client is not None
            assert client._credentials == mock_credentials
            mock_auth.authenticate_async.assert_called_once()
        finally:
            await client.close()

# Test 2: Direct construction (testing pattern)
@pytest.mark.asyncio
async def test_direct_construction_for_testing(mock_credentials):
    """Test direct construction pattern for unit tests."""
    # Direct construction allows full control - no auth mocking needed
    async with GmailClient(mock_credentials) as client:
        assert client._credentials == mock_credentials

# Test 3: Factory with custom credentials file
@pytest.mark.asyncio
async def test_create_with_custom_credentials(mock_credentials, tmp_path):
    """Test factory method with custom credentials file."""
    custom_file = tmp_path / "custom_oauth.json"
    custom_file.write_text('{"installed": {}}')

    with patch("gmailarchiver.connectors.gmail_client.GmailAuthenticator") as mock_auth_cls:
        mock_auth = mock_auth_cls.return_value
        mock_auth.authenticate_async = AsyncMock(return_value=mock_credentials)

        client = await GmailClient.create(credentials_file=str(custom_file))
        try:
            mock_auth_cls.assert_called_with(
                credentials_file=str(custom_file),
                output=None,
            )
        finally:
            await client.close()

# Test 4: Auth failure propagation
@pytest.mark.asyncio
async def test_create_handles_auth_failure():
    """Test that factory method propagates auth errors."""
    with patch("gmailarchiver.connectors.gmail_client.GmailAuthenticator") as mock_auth_cls:
        mock_auth = mock_auth_cls.return_value
        mock_auth.authenticate_async = AsyncMock(
            side_effect=FileNotFoundError("Credentials not found")
        )

        with pytest.raises(FileNotFoundError, match="Credentials not found"):
            await GmailClient.create()
```

### Async Testing Patterns

```python
@pytest.mark.asyncio
async def test_rate_limiter_backs_off_on_429():
    """Test that rate limiter reduces rate on 429 errors."""
    limiter = AdaptiveRateLimiter()
    initial_rate = limiter.refill_rate

    # Simulate 429 response
    wait_time = limiter.on_rate_limit(retry_after=5.0)

    assert wait_time == 5.0  # Respects Retry-After
    assert limiter.refill_rate < initial_rate  # Rate reduced

@pytest.mark.asyncio
async def test_client_uses_http2(mock_credentials):
    """Test that client creates HTTP/2 connection."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        async with GmailClient(mock_credentials) as client:
            pass

        # Verify HTTP/2 was enabled
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs.get("http2") is True
```

### Mock Fixtures

```python
@pytest.fixture
def mock_gmail_api():
    """Mock Gmail API responses for testing."""
    return {
        "messages": [{"id": "msg1"}, {"id": "msg2"}],
        "nextPageToken": None,
    }

@pytest.fixture
def mock_rate_limited_response():
    """Mock 429 response with Retry-After header."""
    return httpx.Response(
        429,
        headers={"Retry-After": "5"},
        json={"error": {"code": 429, "message": "Rate limit exceeded"}},
    )
```

See `tests/connectors/` for test implementations.
