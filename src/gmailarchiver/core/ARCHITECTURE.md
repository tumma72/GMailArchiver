# Core Layer Architecture

**Last Updated:** 2025-11-26

The core layer contains business logic for email archiving operations: archiving, validation, consolidation, deduplication, search, extraction, compression, and diagnostics.

---

## Layer Contract

| Property | Value |
|----------|-------|
| **Dependencies** | `shared`, `data`, `connectors` layers |
| **Dependents** | `cli` layer, `workflows` module |
| **Responsibility** | Business logic for all archiving operations |
| **Thread Safety** | Components are not thread-safe (use separate instances per thread) |

### Critical Architecture Rule

**ALL database access MUST go through HybridStorage.**

```mermaid
flowchart TD
    Core -->|ONLY| HybridStorage
    HybridStorage --> DBManager
    Core -.->|NEVER| DBManager
```

**Rationale:**
- HybridStorage provides transactional guarantees
- Ensures atomic operations across mbox + database
- Centralizes validation and integrity checking
- Maintains the single entry point principle

---

## Components

### GmailArchiver

Main archiving orchestrator - coordinates Gmail fetch, mbox write, and database operations.

```mermaid
classDiagram
    class GmailArchiver {
        +client: GmailClient
        +storage: HybridStorage
        +archive(age, output, compression, ...) ArchiveResult
        +archive_messages(messages, output, ...) int
    }
    GmailArchiver --> GmailClient
    GmailArchiver --> HybridStorage
```

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
        ARCH[GmailArchiver]
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

The workflows module contains async business logic for CLI commands:

```mermaid
classDiagram
    class Workflows {
        +archive_workflow(ctx, params) dict
        +status_workflow(ctx, params) dict
        +validate_workflow(ctx, params) dict
        +search_workflow(ctx, params) dict
        +import_workflow(ctx, params) dict
        +consolidate_workflow(ctx, params) dict
        +dedupe_workflow(ctx, params) dict
        +repair_workflow(ctx, params) dict
        +doctor_workflow(ctx, params) dict
    }

    class CommandContext {
        +output: OutputManager
        +storage: HybridStorage
        +gmail: GmailClient
        +ui: UIBuilder
    }

    Workflows ..> CommandContext : uses
    Workflows ..> GmailArchiver : orchestrates
    Workflows ..> SearchEngine : queries
    Workflows ..> ArchiveValidator : validates
```

### Workflow Pattern

Each workflow:
- Is **async** (business logic)
- Takes **CommandContext** for dependencies
- Returns **structured data** for CLI formatting
- Uses **facades** for core operations
- Reports **progress** via CommandContext

**Example:**
```python
async def archive_workflow(
    ctx: CommandContext,
    age_threshold: str,
    output: str | None,
    compress: str | None,
    # ... other params
) -> dict[str, Any]:
    """Async implementation of archive command."""
    
    # Use facades for business logic
    archiver = ArchiverFacade(ctx.gmail, ctx.storage)
    
    # Report progress
    with ctx.ui.task_sequence() as seq:
        with seq.task("Authenticating") as t:
            await ctx.authenticate_gmail()
            t.complete("Connected")
            
        with seq.task("Archiving") as t:
            result = await archiver.archive(age_threshold, output, compress)
            t.complete(f"Archived {result.count} messages")
    
    # Return structured data for CLI
    return {
        "status": "success",
        "archived": result.count,
        "output_file": result.file,
    }
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
| `Workflows` | Business logic orchestration, error handling, progress reporting |

See `tests/core/` for test implementations.
