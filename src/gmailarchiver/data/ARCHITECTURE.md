# Data Layer Architecture

**Last Updated:** 2025-11-26

The data layer manages all persistent state: SQLite database and mbox file operations. It provides transactional guarantees for atomic operations across both storage systems.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared` layer only |
| **Dependents** | `core`, `cli` layers |
| **Responsibility** | Database operations, mbox storage, schema management, migrations |
| **Thread Safety** | Not thread-safe (SQLite connections are not shared between threads) |

---

## Components

### DBManager

Single source of truth for all database operations with transaction management and audit trails.

```mermaid
classDiagram
    class DBManager {
        +db_path: Path
        +conn: sqlite3.Connection
        +schema_version: str
        +__init__(db_path, validate_schema, auto_create)
        +record_archived_message(gmail_id, thread_id, ...)
        +get_archived_message_ids() set~str~
        +is_archived(gmail_id) bool
        +get_pending_deletions(archive_file) list
        +mark_as_deleted(gmail_id)
        +get_stats() dict
        +close()
    }
    class DBManagerError {
        <<exception>>
    }
    class SchemaValidationError {
        <<exception>>
    }
    DBManagerError <|-- SchemaValidationError
```

#### Interface

- **Context manager**: Use `with DBManager(path) as db:` for auto-cleanup
- **Transaction support**: All writes are wrapped in transactions with auto-rollback
- **Audit trail**: All operations recorded in `archive_runs` table
- **Schema validation**: Validates database schema on init (configurable)

#### Key Methods

| Method | Purpose |
|--------|---------|
| `record_archived_message()` | Record a newly archived message |
| `get_archived_message_ids()` | Get all archived Gmail IDs (for deduplication) |
| `is_archived(gmail_id)` | Check if message is already archived |
| `get_pending_deletions()` | Get messages archived but not yet deleted |
| `mark_as_deleted(gmail_id)` | Mark message as deleted from Gmail |
| `get_stats()` | Get database statistics |

---

### SchemaManager

Version detection, capability checking, and migration coordination.

```mermaid
classDiagram
    class SchemaManager {
        +db_path: Path
        +detect_version() SchemaVersion
        +has_capability(capability) bool
        +require_version(version)
        +require_capability(capability)
        +auto_migrate_if_needed(callbacks) bool
    }
    class SchemaVersion {
        <<enumeration>>
        V1_0
        V1_1
        V1_2
        NONE
        UNKNOWN
        +from_string(str) SchemaVersion
        +is_valid: bool
    }
    class SchemaCapability {
        <<enumeration>>
        BASIC_ARCHIVING
        MBOX_OFFSETS
        FTS_SEARCH
        RFC_MESSAGE_ID
        NULLABLE_GMAIL_ID
    }
    class SchemaVersionError {
        <<exception>>
        +current_version
        +required_version
        +suggestion
    }
    SchemaManager --> SchemaVersion
    SchemaManager --> SchemaCapability
```

#### Interface

- **Version detection**: `detect_version()` examines table structure
- **Capability checking**: `has_capability()` / `require_capability()` for feature flags
- **Migration coordination**: `auto_migrate_if_needed()` handles upgrades

#### Usage Example

```python
from gmailarchiver.data.schema_manager import SchemaManager, SchemaCapability

mgr = SchemaManager(db_path)

# Check capabilities (preferred over version comparison)
if mgr.has_capability(SchemaCapability.FTS_SEARCH):
    # Use full-text search features
    pass

# Require specific capability
mgr.require_capability(SchemaCapability.MBOX_OFFSETS)  # Raises if not available
```

---

### HybridStorage

Transactional coordinator ensuring atomic mbox + database operations.

```mermaid
classDiagram
    class HybridStorage {
        +db: DBManager
        +staging_dir: Path
        +archive_message(msg, gmail_id, archive_path)
        +consolidate_archives(sources, output, dedupe) ConsolidationResult
        +verify_integrity(archive_path) bool
    }
    class IntegrityError {
        <<exception>>
    }
    class HybridStorageError {
        <<exception>>
    }
    class ConsolidationResult {
        +output_file: str
        +source_files: list
        +total_messages: int
        +duplicates_removed: int
    }
    HybridStorage --> DBManager
    HybridStorage ..> ConsolidationResult
```

#### Guarantees

1. **Atomicity**: Both mbox and database succeed, OR both are rolled back
2. **Validation**: After every write, consistency is verified
3. **Recovery**: Staging area allows rollback on failures

#### Two-Phase Commit Pattern

```mermaid
sequenceDiagram
    participant C as Caller
    participant HS as HybridStorage
    participant S as Staging
    participant M as Mbox
    participant DB as Database

    C->>HS: archive_message()
    HS->>S: Write to staging file
    S-->>HS: Staging OK
    HS->>M: Append to mbox
    M-->>HS: Mbox OK (get offset)
    HS->>DB: Record with offset
    DB-->>HS: DB OK
    HS->>HS: Validate consistency
    HS-->>C: Success

    Note over HS,DB: On any failure, rollback both
```

---

### MigrationManager

Database schema migrations with backup and rollback support.

```mermaid
classDiagram
    class MigrationManager {
        +db_path: Path
        +backup_path: Path
        +migrate_v10_to_v11(archive_patterns) MigrationResult
        +create_backup() Path
        +restore_from_backup(backup_path)
    }
    class MigrationResult {
        +success: bool
        +messages_migrated: int
        +errors: list
    }
```

#### Interface

- **Backup**: Always creates backup before migration
- **Progress**: Optional callback for progress reporting
- **Rollback**: `restore_from_backup()` reverts failed migrations

---

### ArchiveState (Legacy)

Legacy state tracking, preserved for backward compatibility. New code should use `DBManager`.

```mermaid
classDiagram
    class ArchiveState {
        +db_path: Path
        +is_archived(gmail_id) bool
        +record_archived_message(gmail_id, ...)
        +close()
    }
    note for ArchiveState "Legacy - use DBManager for new code"
```

---

## Data Flow

```mermaid
graph TB
    subgraph "Data Layer"
        SM[SchemaManager]
        DB[DBManager]
        HS[HybridStorage]
        MIG[MigrationManager]
        STATE[ArchiveState]
    end

    subgraph "Storage"
        SQLite[(SQLite DB)]
        MBOX[(mbox files)]
    end

    SM --> SQLite
    DB --> SQLite
    HS --> DB
    HS --> MBOX
    MIG --> SQLite
    MIG --> MBOX
    STATE --> SQLite
```

---

## Schema Versions

| Version | Tables | Capabilities |
|---------|--------|--------------|
| **1.0** | `archived_messages`, `archive_runs` | Basic archiving |
| **1.1** | `messages`, `messages_fts`, `archive_runs` | FTS, offsets, Message-ID |
| **1.2** | Same as 1.1 | Nullable gmail_id |

---

## Testing Strategy

| Component | Test Focus |
|-----------|------------|
| `DBManager` | Transactions, rollback, concurrent access, schema validation |
| `SchemaManager` | Version detection, capability checks, migration triggers |
| `HybridStorage` | Atomicity (partial failures), integrity validation |
| `MigrationManager` | Backup/restore, data preservation, error handling |

See `tests/data/` for test implementations.
