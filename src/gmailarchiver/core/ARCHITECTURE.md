# Core Layer Architecture

**Last Updated:** 2025-11-26

The core layer contains business logic for email archiving operations: archiving, validation, consolidation, deduplication, search, extraction, compression, and diagnostics.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared`, `data`, `connectors` layers |
| **Dependents** | `cli` layer only |
| **Responsibility** | Business logic for all archiving operations |
| **Thread Safety** | Components are not thread-safe (use separate instances per thread) |

---

## Components

### GmailArchiver

Main archiving orchestrator - coordinates Gmail fetch, mbox write, and database operations.

```mermaid
classDiagram
    class GmailArchiver {
        +client: GmailClient
        +state_db_path: str
        +archive(age, output, compression, ...) ArchiveResult
        +archive_messages(messages, output, ...) int
    }
    GmailArchiver --> GmailClient
    GmailArchiver --> HybridStorage
    GmailArchiver --> DBManager
```

### ArchiveValidator

Multi-layer archive validation before deletion.

```mermaid
classDiagram
    class ArchiveValidator {
        +archive_path: Path
        +state_db_path: Path
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
        +db_path: Path
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
        +db_path: Path
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
        +db_path: Path
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
        +db_path: Path
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
        +db_path: Path
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
        +db_path: Path
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
        ARCH[GmailArchiver]
        VAL[ArchiveValidator]
        IMP[ArchiveImporter]
        CON[ArchiveConsolidator]
        DED[MessageDeduplicator]
        SEARCH[SearchEngine]
        EXT[MessageExtractor]
        COMP[ArchiveCompressor]
        DOC[Doctor]
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
    ARCH --> DB
    VAL --> DB
    IMP --> DB
    CON --> HS
    DED --> DB
    SEARCH --> DB
    EXT --> DB
    DOC --> DB
    DOC --> AUTH
```

---

## Testing Strategy

| Component | Test Focus |
|-----------|------------|
| `GmailArchiver` | Atomic operations, incremental mode, compression |
| `ArchiveValidator` | Offset verification, consistency checks |
| `ArchiveImporter` | Glob patterns, deduplication, error handling |
| `ArchiveConsolidator` | Merge operations, offset updates |
| `MessageDeduplicator` | Message-ID matching, preservation logic |
| `SearchEngine` | FTS5 queries, ranking, Gmail syntax |
| `MessageExtractor` | Offset-based retrieval, compression support |
| `ArchiveCompressor` | All formats, streaming, integrity |
| `Doctor` | Diagnostics, auto-fix, edge cases |

See `tests/core/` for test implementations.
