# ADR-007: Strict Dependency Injection for Storage

**Status:** Accepted
**Date:** 2025-12-09
**Deciders:** Architecture team

## Context

Consistent storage access requires:
- Single HybridStorage instance per command execution
- Facades receive storage via constructor (never create it)
- Core layer accesses data only through HybridStorage gateway
- CLI layer owns storage lifecycle

## Decision

**Enforce strict dependency injection for all storage access.**

### Rules

**Rule 1: HybridStorage is the ONLY data gateway for core layer**
- Core facades MUST access data through HybridStorage
- Core facades MUST NOT create DBManager instances
- Core facades MUST NOT access DBManager directly

**Rule 2: Storage is created by CLI, injected into facades**
- `@with_context` decorator creates HybridStorage (if `requires_storage=True`)
- CommandContext exposes `ctx.storage: HybridStorage`
- Facades receive storage via constructor: `facade = ImporterFacade(ctx.storage)`

**Rule 3: One storage instance per command execution**
- Single HybridStorage instance per CLI command
- Single underlying DBManager connection
- Consistent transaction scope across all facades

### Implementation Pattern

**CLI Layer:**
```python
@app.command()
@with_context(requires_storage=True, has_progress=True)
def import_archive(ctx: CommandContext, path: str) -> None:
    """CLI command creates NO storage instances."""
    facade = ImporterFacade(ctx.storage)  # Inject ctx.storage
    result = asyncio.run(facade.import_archive(Path(path)))
    ctx.show_report("Import Complete", result)
```

**@with_context Decorator:**
```python
def with_context(requires_storage: bool = False, ...):
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Create storage ONCE per command
            storage = None
            if requires_storage:
                db = DBManager(state_db)
                storage = HybridStorage(db)
                ctx.storage = storage  # Inject via CommandContext

            try:
                return func(ctx, *args, **kwargs)
            finally:
                if storage:
                    asyncio.run(storage.close())  # Cleanup
```

**Facade Layer:**
```python
class ImporterFacade:
    """Facade receives storage via DI, never creates it."""

    def __init__(self, storage: HybridStorage):
        self._storage = storage  # Injected dependency

    async def import_archive(self, path: Path) -> ImportResult:
        # Use storage gateway
        messages = await self._storage.read_messages_from_archives([path])
        # CORRECT: No DBManager access, no instance creation
```

## Consequences

### Positive
- **Single source of truth:** One HybridStorage instance per command
- **Consistent transactions:** All facades share same DB connection
- **Testability:** Easy to inject mock HybridStorage in tests
- **Resource safety:** CLI handles cleanup (no facade responsibility)
- **Layer contract enforcement:** Core layer physically cannot access DBManager
- **Clear ownership:** CommandContext owns storage lifecycle

### Negative
- More verbose CLI (must explicitly inject `ctx.storage` into facades)

### Neutral
- Facades become more functional (dependencies explicit)
- CommandContext becomes the "composition root" (DI pattern)

## Alternatives Considered

### Alternative 1: Facades Create Their Own Storage
- **Pros:** Less boilerplate in CLI
- **Cons:** Multiple connections, transaction issues, hard to test, resource leaks

### Alternative 2: Global Storage Singleton
- **Pros:** No injection needed
- **Cons:** Testing nightmare, state leakage, not thread-safe, violates DI principles

### Alternative 3: Service Locator Pattern
- **Pros:** Facades fetch storage from registry
- **Cons:** Hidden dependencies, testing harder than DI, anti-pattern in modern Python

## Enforcement

### Linting Rule
Custom ruff rule prevents DBManager imports in core layer:
```python
# core/** modules MUST NOT import DBManager
# Violation example:
from gmailarchiver.data.db_manager import DBManager  # FORBIDDEN
```

### Code Review Checklist
- Facades receive HybridStorage via `__init__`
- No `DBManager(...)` calls in core layer
- No `from ...data.db_manager import DBManager` in core layer
- CLI injects `ctx.storage` into facades

## References
- [Dependency Injection Principles (Martin Fowler)](https://martinfowler.com/articles/injection.html)
- [ADR-001: Hybrid Architecture Model](./001-hybrid-architecture-model.md)
- [ADR-006: Async-First Architecture](./006-async-first-architecture.md)
