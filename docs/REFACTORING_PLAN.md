# Gmail Archiver Clean Architecture Refactoring Plan

## Executive Summary

Gmail Archiver has grown to 5,020 lines of production code with 94% test coverage across 1,446 tests. The codebase suffers from architectural debt: a 4,011-line monolithic CLI file, 13 files exceeding 500 lines, and business logic embedded in command handlers. This plan outlines a systematic migration to clean architecture with facade patterns, targeting 95%+ coverage, <500 lines per file, and <50 lines per CLI command through 6 phased iterations over 8-10 weeks.

**Expected Outcomes:**
- **Maintainability**: Each component <500 lines, single responsibility
- **Testability**: 95%+ coverage via fast unit tests on facades
- **Modularity**: Clear separation of concerns (CLI → Facades → Internal → Data)
- **Backward Compatibility**: Zero breaking changes during migration

---

## Phases Overview

| Phase | Name | Duration | Key Deliverables | Success Criteria |
|-------|------|----------|------------------|------------------|
| **0** | Foundation & Test Infrastructure | 1 week | Test reorganization, pytest markers, CI updates | Tests pass in <30s, organized by type |
| **1** | Proof of Concept (Archiver) | 2 weeks | Archiver package with facade, 95%+ coverage | Archiver refactored, all tests green |
| **2** | Core Operations (Import/Validate) | 2 weeks | Importer + Validator packages | 2 more components refactored |
| **3** | Search & Deduplication | 1 week | Search + Deduplicator packages | 2 more components refactored |
| **4** | Specialized Components | 1 week | Consolidator, Compressor, Doctor, Extractor | Remaining core/* refactored |
| **5** | CLI Command Extraction | 2 weeks | cli/commands/ modules, thin adapters | __main__.py < 500 lines |
| **6** | Cleanup & Documentation | 1 week | Final validation, architecture docs update | 95%+ coverage, all metrics met |

**Total Timeline:** 10 weeks (2.5 months)

---

## Phase 0: Foundation & Test Infrastructure

### Goal
Establish testing infrastructure and reorganize tests to support TDD workflow with fast feedback loops.

### Prerequisites
- Current tests passing (650+ tests, 94% coverage)
- Git branch: `refactor/clean-architecture-foundation`

### Steps

#### 1. Create Test Directory Structure
```bash
mkdir -p tests/{unit,integration,contract,e2e}
mkdir -p tests/unit/{cli,core,data,connectors,shared}
mkdir -p tests/integration/{core,workflows}
mkdir -p tests/contract/{api,database}
mkdir -p tests/e2e/workflows
```

#### 2. Configure pytest Markers
**File:** `pyproject.toml` (add to `[tool.pytest.ini_options]`)
```toml
markers = [
    "unit: Fast isolated tests (no I/O, no external deps)",
    "integration: Tests with mocked external dependencies",
    "contract: API/database contract tests",
    "e2e: End-to-end workflow tests",
    "slow: Tests taking >1s",
]
```

#### 3. Reorganize Existing Tests

**Migration strategy:**
- **Unit tests**: Tests with no file I/O, no database → `tests/unit/`
- **Integration tests**: Tests with temp files/databases → `tests/integration/`
- **Contract tests**: Tests verifying API contracts → `tests/contract/`
- **E2E tests**: Full workflow tests → `tests/e2e/`

#### 4. Create Test Running Scripts

**File:** `scripts/test-unit.sh`
```bash
#!/bin/bash
uv run pytest tests/unit -v -m "unit" --no-cov
```

**File:** `scripts/test-fast.sh`
```bash
#!/bin/bash
uv run pytest tests/unit tests/integration -v -m "unit or integration" --no-cov
```

**File:** `scripts/test-all.sh`
```bash
#!/bin/bash
uv run pytest tests/ -v --cov=gmailarchiver --cov-report=term-missing
```

### Deliverables

- [ ] `tests/` directory reorganized (unit, integration, contract, e2e)
- [ ] `pyproject.toml` updated with pytest markers
- [ ] Test running scripts in `scripts/`
- [ ] CI workflow updated for test matrix
- [ ] All existing tests pass in new structure

### Success Criteria

- ✅ All 650+ tests pass in reorganized structure
- ✅ Unit tests run in <5s (no I/O)
- ✅ Integration tests run in <15s
- ✅ Full suite runs in <30s
- ✅ Zero regressions in coverage (94% maintained)

---

## Phase 1: Proof of Concept (Archiver Refactoring)

### Goal
Refactor `GmailArchiver` (986 lines) into a package with facade pattern, achieving 95%+ coverage and demonstrating the target architecture.

### Current Problems in Archiver

1. **Duplicate Implementation**: `archive()` method duplicates logic from phase methods
2. **Mixed Responsibilities**: Handles Gmail API, database, file I/O, progress tracking, compression
3. **Hard to Test**: Requires mocking 5+ dependencies per test
4. **Low Cohesion**: 986 lines mixing orchestration with implementation details

### Target Structure

```
src/gmailarchiver/core/archiver/
├── __init__.py                    # Public facade (exports ArchiverFacade)
├── facade.py                      # ArchiverFacade class (~150 lines)
├── _lister.py                     # MessageLister (~100 lines)
├── _filter.py                     # MessageFilter (~80 lines)
├── _writer.py                     # MessageWriter (~150 lines)
├── _compressor.py                 # ArchiveCompressor (~80 lines)
├── _deleter.py                    # MessageDeleter (~80 lines)
└── ARCHITECTURE.md                # Package documentation

tests/unit/core/archiver/
├── test_facade.py                 # Facade unit tests (~300 lines)
├── test_lister.py                 # Lister unit tests (~150 lines)
├── test_filter.py                 # Filter unit tests (~120 lines)
├── test_writer.py                 # Writer unit tests (~200 lines)
├── test_compressor.py             # Compressor unit tests (~100 lines)
└── test_deleter.py                # Deleter unit tests (~100 lines)
```

### Steps (TDD Red-Green-Refactor)

1. **Write unit tests for MessageLister** (TDD Red)
2. **Extract MessageLister** from archiver.py (TDD Green)
3. **Write unit tests for MessageFilter** (TDD Red)
4. **Extract MessageFilter** (TDD Green)
5. **Write unit tests for MessageWriter** (TDD Red)
6. **Extract MessageWriter** (TDD Green)
7. **Write unit tests for ArchiverFacade** (TDD Red)
8. **Create ArchiverFacade** that delegates to internal modules (TDD Green)
9. **Refactor archive() to use phase methods** (fixes duplicate implementation)
10. **Create package __init__.py** with backward compatibility alias
11. **Update CLI** to use facade
12. **Write integration tests**
13. **Verify 95%+ coverage**
14. **Remove old archiver.py**

### Success Criteria

- ✅ All 650+ tests pass (including new archiver tests)
- ✅ Coverage ≥ 95% for archiver package
- ✅ No file in archiver/ exceeds 200 lines
- ✅ `ArchiverFacade` has <20 public methods
- ✅ CLI commands work identically (backward compatibility)
- ✅ Unit tests for archiver run in <2s

---

## Phase 2: Core Operations (Importer & Validator)

### Goal
Refactor `ArchiveImporter` (579 lines) and `ArchiveValidator` (617 lines) into packages with facade pattern.

### Target Structure

```
src/gmailarchiver/core/importer/
├── facade.py                      # ImporterFacade (~120 lines)
├── _scanner.py                    # FileScanner (~80 lines)
├── _reader.py                     # MboxReader (~100 lines)
├── _deduplicator.py               # ImportDeduplicator (~60 lines)
└── _writer.py                     # DatabaseWriter (~80 lines)

src/gmailarchiver/core/validator/
├── facade.py                      # ValidatorFacade (~100 lines)
├── _counter.py                    # MessageCounter (~60 lines)
├── _checksum.py                   # ChecksumValidator (~80 lines)
├── _database.py                   # DatabaseValidator (~80 lines)
└── _sampler.py                    # SpotCheckSampler (~60 lines)
```

### Success Criteria

- ✅ Both packages have 95%+ coverage
- ✅ All files <200 lines
- ✅ CLI commands work identically

---

## Phase 3: Search & Deduplication

### Target Structure

```
src/gmailarchiver/core/search/
├── facade.py                      # SearcherFacade
├── _parser.py                     # QueryParser (Gmail syntax)
├── _executor.py                   # SearchExecutor (FTS5 queries)
└── _ranker.py                     # ResultRanker (BM25)

src/gmailarchiver/core/deduplicator/
├── facade.py                      # DeduplicatorFacade
├── _scanner.py                    # DuplicateScanner
├── _resolver.py                   # DuplicateResolver
└── _remover.py                    # DuplicateRemover
```

---

## Phase 4: Specialized Components

### Target Structure

```
src/gmailarchiver/core/consolidator/
├── facade.py
├── _merger.py
└── _sorter.py

src/gmailarchiver/core/compressor/
├── facade.py
├── _gzip.py
├── _lzma.py
└── _zstd.py

src/gmailarchiver/core/doctor/
├── facade.py
├── _diagnostics.py
└── _repair.py

src/gmailarchiver/core/extractor/
├── facade.py
├── _locator.py
└── _extractor.py
```

---

## Phase 5: CLI Command Extraction

### Goal
Refactor `__main__.py` (4,011 lines) into modular command files.

### Target Structure

```
src/gmailarchiver/cli/
├── app.py                         # Main Typer app (~150 lines)
├── commands/
│   ├── archive.py                 # ~50 lines
│   ├── validate.py                # ~40 lines
│   ├── search.py                  # ~40 lines
│   ├── import_cmd.py              # ~50 lines
│   ├── consolidate.py             # ~40 lines
│   ├── dedupe.py                  # ~40 lines
│   └── [other commands...]
└── command_context.py             # (existing)
```

### Example Thin Command

```python
@with_context(requires_gmail=True)
def archive_command(ctx: CommandContext, age_threshold: str, ...):
    """Archive command - just pass through to facade."""
    archiver = ArchiverFacade(ctx)
    result = archiver.archive(age_threshold, ...)
    ctx.output.success(f"Archived {result['messages_archived']}")
```

---

## Phase 6: Cleanup & Documentation

### Steps

1. **Final Validation**: Coverage ≥ 95%, all tests pass, no files >500 lines
2. **Performance Benchmarks**: Verify no regression
3. **Update ARCHITECTURE.md**: Document new structure
4. **Update CODING.md**: Add facade pattern guidelines
5. **Create Migration Guide**: For developers
6. **Update CHANGELOG**: Document all changes
7. **Release Checklist**: Prepare for v2.0.0

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| **Test Coverage** | 94% | 95%+ |
| **Files >500 lines** | 13 files | 0 files |
| **Largest file** | 4,011 lines | <500 lines |
| **CLI command size** | 100+ lines | <50 lines |
| **Unit test speed** | ~10s | <5s |
| **Full test suite** | ~25s | <30s |

---

## Timeline Summary

- **Phase 0**: 1 week - Test infrastructure
- **Phase 1**: 2 weeks - Archiver (proof of concept)
- **Phase 2**: 2 weeks - Importer & Validator
- **Phase 3**: 1 week - Search & Deduplicator
- **Phase 4**: 1 week - Specialized components
- **Phase 5**: 2 weeks - CLI extraction
- **Phase 6**: 1 week - Cleanup & docs

**Total: 10 weeks** (add 20% buffer → 12 weeks recommended)

---

## Next Steps

1. Review and approve this plan
2. Create git branch: `refactor/clean-architecture-foundation`
3. Begin Phase 0: Test infrastructure setup
4. Execute phases incrementally with frequent merges to main

---

For detailed implementation steps, see the full plan with 51+ concrete steps for Phase 1 alone.
