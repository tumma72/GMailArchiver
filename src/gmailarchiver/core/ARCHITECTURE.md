# Core Layer Architecture

**Last Updated:** 2025-12-16

The core layer contains business logic for email archiving operations: archiving, validation, consolidation, deduplication, search, extraction, compression, and diagnostics.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared`, `data`, `connectors` layers |
| **Dependents** | `cli` layer (via workflows) |
| **Responsibility** | Business logic for all archiving operations |
| **Thread Safety** | Components are not thread-safe (use separate instances per thread) |

### Critical Architecture Rules

**Rule 1: ALL database access MUST go through HybridStorage.**

```mermaid
flowchart TD
    Core -->|ONLY| HybridStorage
    HybridStorage --> DBManager
    Core -.->|NEVER| DBManager
```

**Rule 2: Core layer MUST NOT import from CLI layer.**

```mermaid
flowchart TD
    CLI -->|imports| Core
    Core -.->|NEVER imports| CLI
    Core -->|uses protocol| ProgressReporter
    CLI -->|implements| CLIProgressAdapter
    CLIProgressAdapter -->|satisfies| ProgressReporter
```

For progress reporting, core components should depend on `ProgressReporter` protocol (not `OutputManager`).

**Rationale:**
- HybridStorage provides transactional guarantees
- Ensures atomic operations across mbox + database
- Centralizes validation and integrity checking
- Maintains layer boundaries and testability
- Enables alternative UIs (GUI, API) without changing core

### Known Layer Violations (to fix)

| Component | Violation | Fix |
|-----------|-----------|-----|
| `ArchiverFacade` | Imports `OperationHandle`, `OutputManager` from CLI | Use `ProgressReporter` protocol |
| `workflows/archive.py` | Imports `OutputManager` from CLI | Use `ProgressReporter` protocol |

---

## Components

### ArchiverFacade (archiver/facade.py)

Main archiving orchestrator - coordinates Gmail fetch, mbox write, and database operations.
This is the **public API** for archiving operations.

```mermaid
classDiagram
    class ArchiverFacade {
        +gmail_client: GmailClient
        +storage: HybridStorage
        +list_messages_for_archive(age_threshold, progress_callback) tuple
        +filter_already_archived(message_ids, incremental) FilterResult
        +archive_messages(message_ids, output_file, compress, ...) dict
        +archive(age_threshold, output_file, compress, ...) dict
        +delete_archived_messages(message_ids, permanent) int
    }
    ArchiverFacade --> GmailClient : uses
    ArchiverFacade --> HybridStorage : uses
    ArchiverFacade --> MessageFilter : internal
    ArchiverFacade --> MessageWriter : internal
```

**Internal Modules** (implementation details, not public API):
- `_filter.py`: `MessageFilter` - filters already-archived messages
- `_writer.py`: `MessageWriter` - writes messages to mbox with atomic operations

**Note:** ArchiverFacade currently imports `OperationHandle` from CLI layer - this is a layer violation that should be fixed by using `ProgressReporter` protocol instead.

### ArchiveValidator

Multi-layer archive validation before deletion.

```mermaid
classDiagram
    class ArchiveValidator {
        +archive_path: Path
        +storage: HybridStorage
        +validate() bool
        +verify_offsets() OffsetVerificationResult
        +verify_consistency() ConsistencyReport
    }
    class OffsetVerificationResult {
        +total_checked: int
        +successful_reads: int
        +failed_reads: int
        +accuracy_percentage: float
    }
    class ConsistencyReport {
        +schema_version: str
        +orphaned_records: int
        +missing_records: int
        +passed: bool
    }
```

### ArchiveImporter

Import existing mbox archives into database.

```mermaid
classDiagram
    class ArchiveImporter {
        +storage: HybridStorage
        +import_archive(path) ImportResult
        +import_multiple(patterns) MultiImportResult
    }
    class ImportResult {
        +archive_file: str
        +messages_imported: int
        +duplicates_skipped: int
        +errors: list
    }
```

### ArchiveConsolidator

Merge multiple archives into one.

```mermaid
classDiagram
    class ArchiveConsolidator {
        +storage: HybridStorage
        +consolidate(sources, output, dedupe) ConsolidationResult
    }
    class ConsolidationResult {
        +output_file: str
        +total_messages: int
        +duplicates_removed: int
    }
```

### MessageDeduplicator

Message-ID based deduplication across archives.

```mermaid
classDiagram
    class MessageDeduplicator {
        +storage: HybridStorage
        +find_duplicates() DeduplicationReport
        +deduplicate(archive, output) DeduplicationResult
    }
    class DeduplicationReport {
        +total_messages: int
        +unique_messages: int
        +duplicates: int
    }
```

### SearchEngine

Full-text search via SQLite FTS5.

```mermaid
classDiagram
    class SearchEngine {
        +storage: HybridStorage
        +search(query, limit) SearchResults
    }
    class SearchResults {
        +query: str
        +total: int
        +results: list~MessageSearchResult~
    }
    class MessageSearchResult {
        +gmail_id: str
        +subject: str
        +snippet: str
        +score: float
    }
```

### MessageExtractor

Extract messages from archives by ID or criteria.

```mermaid
classDiagram
    class MessageExtractor {
        +storage: HybridStorage
        +extract_by_id(gmail_id, output) bytes
        +extract_by_query(query, output) ExtractStats
    }
```

### ArchiveCompressor

Compress/decompress archive files.

```mermaid
classDiagram
    class ArchiveCompressor {
        +compress(input, output, format) CompressionResult
        +decompress(input, output) CompressionResult
        +convert(input, output, format) CompressionResult
    }
    class CompressionResult {
        +input_size: int
        +output_size: int
        +ratio: float
    }
```

### Doctor

System diagnostics and auto-repair.

```mermaid
classDiagram
    class Doctor {
        +storage: HybridStorage
        +run_diagnostics() DoctorReport
        +fix_all() list~FixResult~
    }
    class DoctorReport {
        +overall_status: CheckSeverity
        +checks: list~CheckResult~
        +fixable_issues: list
    }
    class CheckSeverity {
        <<enumeration>>
        OK
        WARNING
        ERROR
    }
```

---

## Data Flow

```mermaid
graph TB
    subgraph "Core Layer"
        ARCH[ArchiverFacade]
        VAL[ArchiveValidator]
        IMP[ArchiveImporter]
        CON[ArchiveConsolidator]
        DED[MessageDeduplicator]
        SEARCH[SearchEngine]
        EXT[MessageExtractor]
        COMP[ArchiveCompressor]
        DOC[Doctor]
        WORKFLOWS[Workflows]
    end

    subgraph "Data Layer"
        DB[DBManager]
        HS[HybridStorage]
    end

    subgraph "Connectors Layer"
        GMAIL[GmailClient]
        AUTH[GmailAuthenticator]
    end

    ARCH --> GMAIL
    ARCH --> HS
    VAL --> HS
    IMP --> HS
    CON --> HS
    DED --> HS
    SEARCH --> HS
    EXT --> HS
    DOC --> HS
    DOC --> AUTH
    WORKFLOWS --> ARCH
    WORKFLOWS --> VAL
    WORKFLOWS --> IMP
    WORKFLOWS --> CON
    WORKFLOWS --> SEARCH
    WORKFLOWS --> EXT
    WORKFLOWS --> COMP
    WORKFLOWS --> DOC
    HS --> DB
```

## Workflows Module

The workflows module contains **class-based** async business logic orchestrators:

```mermaid
classDiagram
    class WorkflowProtocol~TConfig, TResult~ {
        <<protocol>>
        +async run(config: TConfig) TResult
    }

    class ProgressReporter {
        <<protocol>>
        +info(message: str)
        +warning(message: str)
        +task_sequence() ContextManager
    }

    class ArchiveWorkflow {
        +storage: HybridStorage
        +client: GmailClient
        +progress: ProgressReporter | None
        +async run(config: ArchiveConfig) ArchiveResult
    }

    class StatusWorkflow {
        +storage: HybridStorage
        +progress: ProgressReporter | None
        +async run(config: StatusConfig) StatusResult
    }

    ArchiveWorkflow ..|> WorkflowProtocol : implements
    StatusWorkflow ..|> WorkflowProtocol : implements
    ArchiveWorkflow ..> ArchiverFacade : uses
    StatusWorkflow ..> HybridStorage : uses
```

### Workflow Pattern

Each workflow:
- Is a **class** implementing `WorkflowProtocol[TConfig, TResult]`
- Has a **`run(config)` method** (not `execute`)
- Receives dependencies via **constructor injection**
- Depends on **ProgressReporter protocol** (not CLI types)
- Returns **typed Result dataclass**
- Uses **facades** for core operations

**Example:**
```python
class ArchiveWorkflow:
    """Workflow for archiving Gmail messages."""

    def __init__(
        self,
        storage: HybridStorage,
        client: GmailClient,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.storage = storage
        self.client = client
        self.progress = progress

    async def run(self, config: ArchiveConfig) -> ArchiveResult:
        """Execute archive workflow."""
        # Report progress via protocol (if available)
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Archiving") as t:
                    result = await self._do_archive(config)
                    t.complete(f"Archived {result.count} messages")

        # Return typed result dataclass
        return ArchiveResult(
            archived_count=result.count,
            output_file=result.file,
            validation_passed=result.validated,
        )
```

**Key Design Decisions:**
- Workflows depend on `ProgressReporter` **protocol**, not CLI types
- CLI layer creates `CLIProgressAdapter` that implements the protocol
- This maintains layer boundaries and enables testability

---

## Testing Strategy

| Component | Test Focus |
|-----------|------------|
| `ArchiverFacade` | Atomic operations, incremental mode, compression |
| `ArchiveValidator` | Offset verification, consistency checks |
| `ArchiveImporter` | Glob patterns, deduplication, error handling |
| `ArchiveConsolidator` | Merge operations, offset updates |
| `MessageDeduplicator` | Message-ID matching, preservation logic |
| `SearchEngine` | FTS5 queries, ranking, Gmail syntax |
| `MessageExtractor` | Offset-based retrieval, compression support |
| `ArchiveCompressor` | All formats, streaming, integrity |
| `Doctor` | Diagnostics, auto-fix, edge cases |
| `Workflows` | Business logic orchestration, error handling, progress reporting |

See `tests/core/` for test implementations.
