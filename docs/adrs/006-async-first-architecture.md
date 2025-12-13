# ADR-006: Async-First Architecture

**Status:** Accepted
**Date:** 2025-12-10
**Deciders:** Project Team
**Technical Story:** Gmail Archiver needs a scalable I/O model for concurrent database operations and future web UI support

---

## Context

Gmail Archiver's data layer was initially built with synchronous APIs:

1. **Blocking database calls** - All SQLite operations blocked the main thread
2. **Sync-only HybridStorage** - File I/O and compression were synchronous
3. **No concurrency** - CLI commands ran strictly sequentially
4. **Future constraints** - Blocked web UI development (requires async for HTTP endpoints)

As the application grew, several limitations became apparent:

### Problems with Synchronous Architecture

1. **No Web UI Path** - Modern Python web frameworks (FastAPI, Starlette) require async handlers
2. **Blocking I/O** - Database operations block during slow queries
3. **Poor Responsiveness** - Large archive operations freeze the application
4. **Mixed Patterns** - Scattered `asyncio.run()` calls at various layers

### Options Considered

**Option 1: Maintain Sync (Status Quo)**
- Keep synchronous APIs throughout
- Use WSGI for any future web layer
- Simple but limits future capabilities

**Option 2: Async at Boundaries Only**
- Keep data layer sync, add async wrappers at CLI/web layer
- Multiple `asyncio.run()` bridges per operation
- Compromises performance and adds complexity

**Option 3: Async-First (Bottom-Up Migration)**
- Make data layer 100% async-native
- Single `asyncio.run()` bridge at CLI entry point
- Future-proof for web UI and concurrent operations

---

## Decision

We adopt **Async-First Architecture** (Option 3) with the following principles:

1. **Data layer is 100% async** - DBManager and HybridStorage expose only async methods
2. **Core facades are async** - All 9 facade classes (Archiver, Importer, Validator, etc.) use `async def`
3. **Single bridge at CLI** - Only `asyncio.run()` appears in CLI commands
4. **CPU-bound work offloaded** - File I/O uses `asyncio.to_thread()` for thread pool execution

### Architecture Layers

```
┌──────────────────────────────────────────────────┐
│               CLI Layer (Typer)                  │
│         asyncio.run() bridge per command         │
├──────────────────────────────────────────────────┤
│               Core Layer (Facades)               │
│     async def archive(), search(), etc.          │
├──────────────────────────────────────────────────┤
│               Data Layer                         │
│   DBManager (aiosqlite) + HybridStorage (async)  │
└──────────────────────────────────────────────────┘
```

---

## Consequences

### Positive

1. **Web UI Ready**
   - FastAPI/Starlette can call facades directly
   - No blocking in async HTTP handlers
   - Enables real-time progress via WebSocket

2. **Better Responsiveness**
   - Database queries don't block UI updates
   - Progress callbacks can run during I/O waits
   - Enables future cancellation support

3. **Clean Async Stack**
   - No scattered `asyncio.run()` calls
   - Single entry point for event loop
   - Easier debugging and profiling

4. **Concurrent Operations**
   - Multiple database queries can interleave
   - File I/O runs in thread pool
   - Foundation for parallel archive processing

5. **Modern Python Alignment**
   - Follows aiosqlite best practices
   - Compatible with async ecosystem
   - Future-proof for Python async improvements

### Negative

1. **Migration Complexity**
   - Required touching 30+ files
   - All test files needed async updates
   - Careful mock setup for async methods

2. **Testing Overhead**
   - Tests require `@pytest.mark.asyncio`
   - Fixtures may need async variants
   - Mock setup more verbose (`AsyncMock`)

3. **Learning Curve**
   - Developers must understand async/await
   - Error handling differs from sync
   - Stack traces can be less clear

4. **Sync Compatibility**
   - External callers must use `asyncio.run()`
   - Some testing frameworks need configuration
   - IDE support varies

---

## Implementation Details

### DBManager Pattern

```python
class DBManager:
    """Async-native database manager using aiosqlite."""

    async def initialize(self) -> None:
        """Async initialization (replaces sync __init__ work)."""
        if not self.db_path.exists():
            await self._create_new_database_async()
        self.conn = await aiosqlite.connect(self.db_path)
        await self._apply_pragmas()

    async def close(self) -> None:
        """Clean shutdown of database connection."""
        if self.conn:
            await self.conn.close()

    async def record_archived_message(self, ...) -> None:
        """Example async database operation."""
        await self.conn.execute(
            "INSERT INTO messages (...) VALUES (...)",
            (...)
        )
```

### HybridStorage Pattern

```python
class HybridStorage:
    """Async coordinator for mbox + database operations."""

    async def write_message(self, message: EmailMessage) -> int:
        """Async write with thread pool for file I/O."""
        # CPU-bound compression runs in thread pool
        offset = await asyncio.to_thread(
            self._write_to_mbox_sync,
            message
        )
        # Database write is native async
        await self.db.record_archived_message(...)
        return offset

    def _write_to_mbox_sync(self, message: EmailMessage) -> int:
        """Sync helper for thread pool execution."""
        # Actual file I/O here
        ...
```

### CLI Bridge Pattern

```python
@app.command()
@with_context(requires_storage=True)
def archive(ctx: CommandContext, query: str) -> None:
    """Archive command with single async bridge."""
    facade = ArchiverFacade(
        gmail_client=ctx.gmail_client,
        db_manager=ctx.db,
        storage=ctx.storage,
    )
    # Single asyncio.run() at CLI boundary
    result = asyncio.run(facade.archive_messages(query))
    ctx.output.print_result(result)
```

### Context Manager Integration

```python
@asynccontextmanager
async def get_storage(db_path: Path) -> AsyncIterator[HybridStorage]:
    """Async context manager for storage lifecycle."""
    db = DBManager(db_path)
    await db.initialize()
    storage = HybridStorage(db)
    try:
        yield storage
    finally:
        await db.close()
```

---

## Migration Strategy

### Phase 1: Data Layer Foundation ✅
- Convert DBManager to async with `aiosqlite`
- Add `initialize()` method for lazy async initialization
- Convert HybridStorage file I/O with `asyncio.to_thread()`

### Phase 2: Connectors Layer 🔄
- Replace `google-api-python-client` HTTP calls with `httpx` (HTTP/2 support)
- Implement `AsyncGmailClient` with native async methods
- Add `AdaptiveRateLimiter` with token bucket + dynamic backoff
- See [connectors/ARCHITECTURE.md](../../src/gmailarchiver/connectors/ARCHITECTURE.md) for details

### Phase 3: Core Facades
- Add `async def` to all facade methods
- Update internal method calls with `await`
- Ensure proper async resource cleanup

### Phase 4: CLI Bridge
- Add `asyncio.run()` in each CLI command
- Update `@with_context` decorator for async cleanup
- Test all commands end-to-end

### Phase 5: Test Migration
- Add `@pytest.mark.asyncio` to async tests
- Convert fixtures to async where needed
- Update mocks with `AsyncMock`

---

## Connectors Layer: httpx + Adaptive Rate Limiting

### Why httpx over google-api-python-client

The official `google-api-python-client` has limitations:
- Uses blocking `httplib2` internally
- No native async support ([GitHub #1637](https://github.com/googleapis/google-api-python-client/issues/1637))
- `time.sleep()` for rate limiting blocks event loop

**httpx** provides:
- Native async/await support
- HTTP/2 multiplexing (multiple requests over single connection)
- Familiar requests-like API
- Full type annotations

### Adaptive Rate Limiting vs Circuit Breaker

We chose **adaptive rate limiting** over a full circuit breaker pattern:

| Aspect | Circuit Breaker | Adaptive Rate Limiter |
|--------|-----------------|----------------------|
| On failure | Opens circuit, blocks ALL requests | Reduces rate, allows retries |
| Recovery | Half-open state, slow recovery | Gradual rate increase after successes |
| Use case | Protecting downstream services | Respecting API quotas |
| User impact | Punishing (all requests blocked) | Graceful degradation |

**Rationale:**
1. Gmail API is quota-based, not capacity-based
2. Single-user CLI doesn't need downstream protection
3. 429 responses include `Retry-After` guidance
4. Users waiting for archives shouldn't see total blockage

### Token Bucket Algorithm

```
┌─────────────────────────────────────────┐
│         AdaptiveRateLimiter             │
├─────────────────────────────────────────┤
│  max_tokens = 20      (burst capacity)  │
│  refill_rate = 10/sec (sustained rate)  │
│  min_refill_rate = 1/sec (floor)        │
├─────────────────────────────────────────┤
│  on_success():                          │
│    consecutive_successes++              │
│    if successes >= 10:                  │
│      refill_rate *= 1.1 (up to max)     │
│                                         │
│  on_rate_limit(retry_after):            │
│    refill_rate *= 0.5                   │
│    return retry_after or backoff        │
└─────────────────────────────────────────┘
```

---

## Testing Patterns

### Async Test Example

```python
@pytest.mark.asyncio
async def test_archive_messages():
    """Test async archiving with proper mocking."""
    mock_db = AsyncMock(spec=DBManager)
    mock_db.record_archived_message = AsyncMock()

    storage = HybridStorage(mock_db)
    result = await storage.write_message(test_message)

    mock_db.record_archived_message.assert_called_once()
```

### Fixture Pattern

```python
@pytest.fixture
async def async_db(tmp_path):
    """Async fixture for database tests."""
    db = DBManager(tmp_path / "test.db")
    await db.initialize()
    yield db
    await db.close()
```

---

## Alternatives Considered

### Alternative 1: Sync with WSGI
- Keep everything synchronous
- Use Flask/WSGI for web layer
- Simpler but poor for concurrent operations

**Verdict:** Rejected - Limits future scalability

### Alternative 2: Hybrid Sync/Async
- Mix sync data layer with async facades
- Multiple `asyncio.run()` bridges
- Simpler migration but messy architecture

**Verdict:** Rejected - Technical debt and performance issues

### Alternative 3: Threads Instead of Async
- Use threading for concurrency
- Keep synchronous APIs
- Familiar to more developers

**Verdict:** Rejected - GIL limits, harder to reason about

---

## Related Decisions

- [ADR-001: Hybrid Architecture Model](001-hybrid-architecture-model.md) - Defines mbox + SQLite storage
- [ADR-007: Strict Dependency Injection](007-strict-dependency-injection.md) - DI pattern enables async testing

---

## References

- [aiosqlite documentation](https://aiosqlite.omnilib.dev/)
- [Python asyncio.to_thread](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [FastAPI async support](https://fastapi.tiangolo.com/async/)

---

**Last Updated:** 2025-12-10
