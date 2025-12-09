# Data Layer

**Status:** Complete (v1.5.0+)

The data layer manages all persistent state operations: SQLite database interactions and mbox file storage. It ensures transactional integrity across both storage systems.

## Quick Start

```python
from gmailarchiver.data import (
    DBManager,
    HybridStorage,
    SchemaManager,
    SchemaCapability,
    SchemaVersion,
)

# Database operations
with DBManager("archive_state.db") as db:
    db.record_archived_message(
        gmail_id="abc123",
        rfc_message_id="<msg@example.com>",
        archive_file="archive.mbox",
        mbox_offset=0,
        mbox_length=1024,
        subject="Test",
        from_addr="sender@example.com",
    )

    if db.is_archived("abc123"):
        print("Already archived")

# Schema version checking
mgr = SchemaManager("archive_state.db")
if mgr.has_capability(SchemaCapability.FTS_SEARCH):
    # Safe to use full-text search
    pass

# Atomic storage operations
with DBManager("archive_state.db") as db:
    storage = HybridStorage(db)
    storage.archive_message(
        message_bytes=raw_email,
        gmail_id="xyz789",
        archive_path="archive.mbox",
    )
```

## Components

| Component | Purpose | Test Coverage |
|-----------|---------|---------------|
| `DBManager` | Database CRUD operations | `tests/data/test_db_manager.py` |
| `SchemaManager` | Version detection and capability checking | `tests/data/test_schema_manager.py` |
| `HybridStorage` | Atomic mbox + database operations | `tests/data/test_hybrid_storage.py` |
| `MigrationManager` | Schema upgrades (v1.0 -> v1.1) | `tests/data/test_migration.py` |

## Directory Structure

```
data/
├── __init__.py          # Public exports
├── ARCHITECTURE.md      # Design specification
├── README.md            # This file
├── db_manager.py        # DBManager implementation
├── schema_manager.py    # SchemaManager implementation
├── hybrid_storage.py    # HybridStorage implementation
└── migration.py         # MigrationManager implementation
```

## Exports

The layer exports these symbols via `gmailarchiver.data`:

```python
# Core classes
DBManager
SchemaManager
HybridStorage
MigrationManager

# Enums
SchemaVersion
SchemaCapability

# Exceptions
DBManagerError
SchemaValidationError
SchemaVersionError
HybridStorageError
IntegrityError

# Results
ConsolidationResult
```

## Dependencies

- **Internal:** `gmailarchiver.shared` (utils, validators)
- **External:** `sqlite3` (stdlib)

## Design Notes

### Transaction Safety

All `DBManager` write operations are wrapped in transactions. On any failure, changes roll back automatically:

```python
with DBManager(db_path) as db:
    db.record_archived_message(...)  # Commits on success
# Connection closed, changes committed

# Or with explicit transaction control:
db = DBManager(db_path)
try:
    db.record_archived_message(...)
    db.commit()
except Exception:
    db.rollback()
finally:
    db.close()
```

### Two-Phase Commit

`HybridStorage` ensures atomicity across mbox and database:

1. Write to staging area
2. Append to mbox (capture offset)
3. Record in database
4. Validate consistency
5. On failure at any step: rollback both

### Schema Capability Checking

Prefer capability checks over version comparisons:

```python
# Good - intent is clear
if mgr.has_capability(SchemaCapability.FTS_SEARCH):
    results = db.search_messages(query)

# Avoid - version numbers are implementation details
if mgr.detect_version() >= SchemaVersion.V1_1:
    results = db.search_messages(query)
```

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Design specification with Mermaid diagrams
- [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) - System-wide architecture
