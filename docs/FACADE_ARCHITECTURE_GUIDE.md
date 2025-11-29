# Facade Architecture Quick Reference

## Overview

The GMailArchiver codebase has been refactored from monolithic modules into a clean facade-based architecture following SOLID principles and design patterns.

## Module Structure Pattern

Each core module follows this standard structure:

```
module_name/
├── __init__.py          # Public API exports (facade only)
├── facade.py            # Public facade class (orchestration)
├── _component1.py       # Private implementation (single responsibility)
├── _component2.py       # Private implementation
└── _component3.py       # Private implementation
```

**Key Conventions:**
- **Public API**: Only the facade class is exported via `__init__.py`
- **Private modules**: Prefix with `_` (not part of public API)
- **Single responsibility**: Each module does one thing well
- **Clear boundaries**: Implementation details hidden from consumers

## All Facade Modules

### 1. Compressor (Strategy Pattern)
```python
from gmailarchiver.core.compressor import Compressor

# Public API
compressor = Compressor()
data = compressor.compress(content, format="zstd")
content = compressor.decompress(data, format="zstd")
```

**Structure:**
- `facade.py` - Compressor class (strategy selector)
- `_gzip.py` - GzipStrategy
- `_lzma.py` - LzmaStrategy
- `_zstd.py` - ZstdStrategy

**Pattern:** Strategy pattern with pluggable compression algorithms

---

### 2. Deduplicator (Pipeline Pattern)
```python
from gmailarchiver.core.deduplicator import MessageDeduplicator

# Public API
deduplicator = MessageDeduplicator(db_manager, hybrid_storage)
report = deduplicator.find_and_remove_duplicates(
    archives=["archive1.mbox", "archive2.mbox"],
    dry_run=True
)
```

**Structure:**
- `facade.py` - MessageDeduplicator class (pipeline orchestrator)
- `_scanner.py` - DuplicateScanner (find duplicates)
- `_resolver.py` - DuplicateResolver (decide which to keep)
- `_remover.py` - DuplicateRemover (delete from storage)

**Pattern:** Pipeline (scan → resolve → remove)

---

### 3. Archiver (Pipeline Pattern)
```python
from gmailarchiver.core.archiver import GmailArchiver

# Public API
archiver = GmailArchiver(gmail_client, db_manager, hybrid_storage)
stats = archiver.archive_messages(
    age="3y",
    archive_file="archive.mbox.zst",
    dry_run=False
)
```

**Structure:**
- `facade.py` - GmailArchiver class (pipeline orchestrator)
- `_lister.py` - MessageLister (list messages from Gmail)
- `_filter.py` - MessageFilter (filter already-archived)
- `_writer.py` - MessageWriter (write to mbox)

**Pattern:** Pipeline (list → filter → write)

---

### 4. Doctor (Diagnostics + Repair)
```python
from gmailarchiver.core.doctor import SystemDoctor

# Public API
doctor = SystemDoctor(db_manager)
report = doctor.run_diagnostics()
doctor.repair_issues(report)
```

**Structure:**
- `facade.py` - SystemDoctor class (coordinator)
- `_diagnostics.py` - Diagnostic checks
- `_repair.py` - Repair operations

**Pattern:** Separation of Concerns (diagnose vs repair)

---

### 5. Search (Parser + Executor)
```python
from gmailarchiver.core.search import MessageSearcher

# Public API
searcher = MessageSearcher(db_manager)
results = searcher.search(
    query="from:example@gmail.com subject:invoice",
    limit=100
)
```

**Structure:**
- `facade.py` - MessageSearcher class (coordinator)
- `_parser.py` - QueryParser (parse Gmail-style syntax)
- `_executor.py` - QueryExecutor (execute FTS5 queries)

**Pattern:** Separation of Concerns (parsing vs execution)

---

### 6. Validator
```python
from gmailarchiver.core.validator import ArchiveValidator

# Public API
validator = ArchiveValidator(db_manager)
is_valid = validator.validate(
    archive_file="archive.mbox.zst",
    spot_check=10
)
```

**Structure:**
- `facade.py` - ArchiveValidator class (orchestrator)
- `_counter.py` - MessageCounter (count messages)
- `_checksum.py` - ChecksumValidator (verify integrity)
- `_decompressor.py` - ArchiveDecompressor (handle compression)

**Pattern:** Composition (multiple validation strategies)

---

### 7. Importer (Pipeline Pattern)
```python
from gmailarchiver.core.importer import ArchiveImporter

# Public API
importer = ArchiveImporter(db_manager, hybrid_storage, gmail_client)
stats = importer.import_archives(
    pattern="*.mbox",
    deduplicate=True
)
```

**Structure:**
- `facade.py` - ArchiveImporter class (pipeline orchestrator)
- `_scanner.py` - ArchiveScanner (find mbox files)
- `_reader.py` - MboxReader (read messages)
- `_writer.py` - DatabaseWriter (write to database)
- `_gmail_lookup.py` - GmailLookup (cross-check with Gmail)

**Pattern:** Pipeline (scan → read → write → verify)

---

### 8. Consolidator (Merge + Sort)
```python
from gmailarchiver.core.consolidator import ArchiveConsolidator

# Public API
consolidator = ArchiveConsolidator(db_manager, hybrid_storage)
stats = consolidator.consolidate(
    input_archives=["a.mbox", "b.mbox"],
    output_archive="merged.mbox",
    deduplicate=True,
    sort_by_date=True
)
```

**Structure:**
- `facade.py` - ArchiveConsolidator class (orchestrator)
- `_merger.py` - ArchiveMerger (merge multiple archives)
- `_sorter.py` - MessageSorter (sort by date)

**Pattern:** Separation of Concerns (merge vs sort)

---

### 9. Extractor
```python
from gmailarchiver.core.extractor import MessageExtractor

# Public API
extractor = MessageExtractor(db_manager)
messages = extractor.extract_messages(
    archive_file="archive.mbox.zst",
    message_ids=["gmail_id_1", "gmail_id_2"]
)
```

**Structure:**
- `facade.py` - MessageExtractor class (coordinator)
- `_locator.py` - MessageLocator (find offsets in database)
- `_extractor.py` - MboxExtractor (extract from mbox)

**Pattern:** Separation of Concerns (locate vs extract)

---

## Design Principles Applied

### 1. Facade Pattern
**Purpose:** Provide a unified, simple interface to a complex subsystem

**Example (Compressor):**
```python
# Public API (simple)
compressor = Compressor()
data = compressor.compress(content, format="zstd")

# Private implementation (complex)
# - ZstdStrategy handles compression details
# - GzipStrategy handles different algorithm
# - LzmaStrategy handles another algorithm
# Users don't see this complexity
```

### 2. Strategy Pattern
**Purpose:** Define a family of algorithms, make them interchangeable

**Example (Compressor):**
```python
# All strategies implement the same interface
class CompressionStrategy(Protocol):
    def compress(self, data: bytes) -> bytes: ...
    def decompress(self, data: bytes) -> bytes: ...

# Strategies are swappable
GzipStrategy()   # Fast compression
LzmaStrategy()   # High compression
ZstdStrategy()   # Balanced (default)
```

### 3. Pipeline Pattern
**Purpose:** Process data through a series of stages

**Example (Archiver):**
```python
# Stage 1: List messages from Gmail
messages = lister.list_messages(age="3y")

# Stage 2: Filter out already-archived
new_messages = filter.filter_messages(messages)

# Stage 3: Write to mbox
writer.write_messages(new_messages, archive_file)
```

### 4. Separation of Concerns
**Purpose:** Each module has a single, well-defined responsibility

**Example (Search):**
```python
# Parser: ONLY handles query syntax
params = parser.parse("from:user@example.com")

# Executor: ONLY handles database queries
results = executor.execute(params)
```

### 5. Dependency Inversion
**Purpose:** Depend on abstractions, not concrete implementations

**Example:**
```python
# High-level facade
class MessageDeduplicator:
    def __init__(self, db_manager, hybrid_storage):
        # Depends on interfaces, not concrete classes
        self.db = db_manager          # Abstract DBManager
        self.storage = hybrid_storage  # Abstract HybridStorage

# Implementation details hidden in private modules
```

## SOLID Principles Verification

### Single Responsibility Principle (SRP)
✅ **Applied:** Each module has one reason to change
- `_scanner.py` - ONLY finds duplicates
- `_resolver.py` - ONLY decides which to keep
- `_remover.py` - ONLY deletes messages

### Open/Closed Principle (OCP)
✅ **Applied:** Open for extension, closed for modification
- Add new compression format: Create new strategy, don't modify facade
- Add new diagnostic check: Extend diagnostics, don't modify doctor

### Liskov Substitution Principle (LSP)
✅ **Applied:** Subtypes can replace parent types
- Any `CompressionStrategy` can replace another
- All strategies implement the same interface

### Interface Segregation Principle (ISP)
✅ **Applied:** Clients shouldn't depend on unused interfaces
- `__init__.py` exports ONLY the facade (minimal public API)
- Private modules not exposed to consumers

### Dependency Inversion Principle (DIP)
✅ **Applied:** Depend on abstractions, not concretions
- Facades accept interfaces (DBManager, HybridStorage)
- No direct coupling to implementation details

## Testing Strategy

### Unit Tests (Private Modules)
Test each component in isolation:
```python
# tests/unit/core/deduplicator/test_dup_scanner.py
def test_scanner_finds_duplicates():
    scanner = DuplicateScanner(db_manager)
    duplicates = scanner.scan(["archive.mbox"])
    assert len(duplicates) == expected_count
```

### Integration Tests (Facades)
Test the facade orchestration:
```python
# tests/core/test_deduplicator.py
def test_deduplicator_end_to_end():
    deduplicator = MessageDeduplicator(db_manager, storage)
    report = deduplicator.find_and_remove_duplicates(["a.mbox"])
    # Verify full pipeline (scan → resolve → remove)
```

## Migration from Legacy

### Before (Monolithic)
```python
from gmailarchiver.core.compressor_legacy import Compressor

# All logic in one 489-line file
# Mixed concerns: compression, decompression, error handling
# Hard to test individual components
```

### After (Facade)
```python
from gmailarchiver.core.compressor import Compressor

# Same public API (backward compatible)
# Implementation split across 5 focused modules
# Each component easily testable
# 93% test coverage (vs 0% legacy)
```

**Key insight:** Facades maintain the same public API, so existing code works unchanged.

## Best Practices for Contributors

### Adding New Features

1. **Identify the right facade**: Which module owns this functionality?
2. **Extend private modules**: Add new `_component.py` if needed
3. **Update facade**: Add method to orchestrate new functionality
4. **Update __init__.py**: Export new public API (if applicable)
5. **Write tests**: Unit tests for components, integration for facade

### Example: Adding a new compression format

```python
# 1. Create strategy (private module)
# src/gmailarchiver/core/compressor/_brotli.py
class BrotliStrategy(CompressionStrategy):
    def compress(self, data: bytes) -> bytes:
        return brotli.compress(data)

    def decompress(self, data: bytes) -> bytes:
        return brotli.decompress(data)

# 2. Register in facade
# src/gmailarchiver/core/compressor/facade.py
class Compressor:
    def __init__(self):
        self._strategies = {
            "gzip": GzipStrategy(),
            "lzma": LzmaStrategy(),
            "zstd": ZstdStrategy(),
            "brotli": BrotliStrategy(),  # ← Add here
        }

# 3. Write tests
# tests/unit/core/compressor/test_brotli.py
def test_brotli_compression():
    strategy = BrotliStrategy()
    compressed = strategy.compress(b"test data")
    assert strategy.decompress(compressed) == b"test data"

# 4. No changes to __init__.py needed (facade already exported)
```

## Common Patterns

### Error Handling
```python
# Facades handle errors at the orchestration level
class MessageDeduplicator:
    def find_and_remove_duplicates(self, archives: list[str]) -> DedupReport:
        try:
            duplicates = self._scanner.scan(archives)
            to_remove = self._resolver.resolve(duplicates)
            self._remover.remove(to_remove)
        except DuplicateError as e:
            logger.error(f"Deduplication failed: {e}")
            raise
```

### Dependency Injection
```python
# Facades receive dependencies via constructor
class GmailArchiver:
    def __init__(
        self,
        gmail_client: GmailClient,
        db_manager: DBManager,
        hybrid_storage: HybridStorage,
    ):
        self._client = gmail_client
        self._db = db_manager
        self._storage = hybrid_storage

        # Create private components
        self._lister = MessageLister(gmail_client)
        self._filter = MessageFilter(db_manager)
        self._writer = MessageWriter(hybrid_storage)
```

### Progress Reporting
```python
# Facades coordinate progress across components
def archive_messages(self, age: str, archive_file: str) -> ArchiveStats:
    with Progress() as progress:
        # Stage 1: List (30% of work)
        task = progress.add_task("Listing messages", total=100)
        messages = self._lister.list_messages(age)
        progress.update(task, advance=30)

        # Stage 2: Filter (10% of work)
        new_messages = self._filter.filter_messages(messages)
        progress.update(task, advance=10)

        # Stage 3: Write (60% of work)
        stats = self._writer.write_messages(new_messages, archive_file)
        progress.update(task, advance=60)

    return stats
```

## Performance Characteristics

### Module Load Time
- **Lazy loading**: Private modules loaded only when facade methods called
- **Fast imports**: `from gmailarchiver.core.compressor import Compressor` is instant

### Test Performance
- **Unit tests**: Fast (isolated components, mocked dependencies)
- **Integration tests**: Moderate (full facade orchestration)
- **Total suite**: 10.81s for 1608 tests (excellent)

### Code Size Impact
- **Legacy**: 4,708 lines across 9 monolithic files
- **Facade**: 5,195 lines across 42 focused modules (+10% code)
- **Benefit**: 4.2x smaller modules, 85-100% test coverage

## Troubleshooting

### "Module not found" errors
```python
# ❌ Wrong: Don't import private modules
from gmailarchiver.core.compressor._gzip import GzipStrategy

# ✅ Correct: Import facade only
from gmailarchiver.core.compressor import Compressor
```

### "Circular import" errors
```python
# ❌ Wrong: Private modules shouldn't import facade
# _scanner.py
from .facade import MessageDeduplicator  # Circular!

# ✅ Correct: Facades import private modules, not vice versa
# facade.py
from ._scanner import DuplicateScanner
```

### Coverage gaps
```python
# If facade coverage is low, check:
# 1. Are all public methods tested?
# 2. Are integration tests covering full pipelines?
# 3. Are error paths tested?

# Example: Test both success and failure paths
def test_deduplicator_success():
    report = deduplicator.find_and_remove_duplicates(["archive.mbox"])
    assert report.removed > 0

def test_deduplicator_handles_errors():
    with pytest.raises(DuplicateError):
        deduplicator.find_and_remove_duplicates(["nonexistent.mbox"])
```

## References

- **Full refactoring report**: `docs/REFACTORING_PHASE6_REPORT.md`
- **Architecture documentation**: `docs/ARCHITECTURE.md`
- **Testing guidelines**: `CONTRIBUTING.md`
- **Code examples**: Browse `src/gmailarchiver/core/*/facade.py`

## Summary

The facade architecture provides:
- ✅ **Clear boundaries**: Public facades vs private implementation
- ✅ **Single responsibility**: Each module does one thing well
- ✅ **High testability**: 85-100% coverage on all modules
- ✅ **Easy maintenance**: 4.2x smaller modules (~124 lines avg)
- ✅ **Extensibility**: Add features without modifying facades
- ✅ **SOLID compliance**: All five principles applied

**For developers**: Use facades as your interface, never import private modules.
**For contributors**: Extend private modules, update facade orchestration.
**For maintainers**: Each facade is independently testable and swappable.
