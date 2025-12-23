# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **AsyncGmailClient**: Native async Gmail API client using httpx with HTTP/2 support
  - Uses `httpx` with HTTP/2 for multiplexed connections
  - Async context manager for proper resource cleanup
  - Methods: `list_messages()`, `get_message()`, `get_messages_batch()`, `trash_messages()`, `delete_messages_permanent()`
  - Foundation for connectors layer async migration (Phase 2 of ADR-006)
- **AdaptiveRateLimiter**: Token bucket rate limiter with dynamic backoff
  - Token bucket algorithm for smooth rate limiting with burst capability
  - Adaptive rate adjustment based on API responses (429, 5xx errors)
  - Gradual rate recovery after consecutive successes
  - Better than circuit breaker for quota-based APIs (graceful degradation vs. blocking)
- **ArchiverFacade async integration** (Phase 3 of ADR-006):
  - `is_async_client` property to detect async vs sync Gmail clients
  - `list_messages_for_archive_async()` method for async message listing
  - `delete_archived_messages_async()` method for async deletion
  - `archive()` method auto-detects client type and uses appropriate listing method
- **CLI async bridge** (Phase 4 of ADR-006):
  - `CommandContext.async_gmail` attribute for async Gmail client access
  - `CommandContext.is_async` property to check async client availability
  - `@with_context(requires_async_gmail=True)` decorator parameter
  - Automatic AsyncGmailClient initialization and cleanup in decorator

### Changed
- **Connectors module exports**: Added `AsyncGmailClient` and `AdaptiveRateLimiter` to public API
- **ArchiverFacade**: Now supports both sync `GmailClient` and async `AsyncGmailClient`
- **CommandContext**: Extended with async Gmail client support and `is_async` property
- **`with_context` decorator**: Now accepts `requires_async_gmail` parameter
- **Architecture documentation**: Updated ADR-006 with httpx rationale and adaptive rate limiting design

### Dependencies
- Added `httpx[http2]` for async HTTP client with HTTP/2 support

## [1.5.2] - 2025-12-23

### Changed
- **Coverage Threshold**: Raised minimum from 90% to 95% (enforced in pyproject.toml)
- **Protocol Exclusions**: Added `# pragma: no cover` to Protocol classes in `cli/ui/protocols.py`

### Added
- **CLI Command Tests**: 59 new tests for complete CLI coverage
  - 18 tests for `schedule.py` commands (100% coverage)
  - 30 tests for `verify.py` commands (100% coverage)
  - 11 tests for `repair.py` error paths (98% coverage)
- **Deprecation Warning Filter**: Python 3.14 mailbox module warnings filtered in conftest.py

### Fixed
- **Python 3.14 Compatibility**: Resolved deprecation warnings from mailbox module text mode
- **Linting Issues**: Fixed all ruff linting and formatting errors

### Quality
- **Test Coverage**: 95% (3,195 tests passing, zero warnings)
- **Enforced Minimum**: CI will fail if coverage drops below 95%

## [1.5.0] - 2025-12-21

### Changed
- **Workflows Module Refactoring** (Major Architectural Modernization):
  - All 5 primary commands (archive, verify, migrate, repair, consolidate) migrated to **WorkflowComposer + Steps pattern**
  - Created 27 reusable step classes across 13 files in `core/workflows/steps/`
  - Replaced monolithic workflows with composable, independently testable steps
  - Implemented conditional step execution for dry-run, validation, and optional operations
  - Steps follow single responsibility principle, each calling one facade method
  - Added 315+ new tests (TDD methodology) maintaining 96% coverage (2,897 total tests)
  - All CLI commands remain thin (<50 LOC) with pure async logic in workflows
  - Enhanced documentation: workflows README updated with v1.9.0 pattern documentation

### Quality
- **Test Coverage**: 96% (2,897 tests passing, zero warnings)
- **Code Quality**: Ruff linting all checks passing, mypy no issues (133 source files)
- **Architecture**: Complete layer boundary enforcement (no CLI imports in core/workflows)

### No Breaking Changes
- All CLI interfaces remain identical
- All commands work exactly as before
- Performance maintained (all async operations preserved)
- Backward compatibility guaranteed

### Benefits
- **Foundation for GUI/API**: Workflows can be reused by non-CLI interfaces
- **Improved Maintainability**: Single-responsibility steps enable easier debugging
- **Better Extensibility**: Composable steps simplify adding new features
- **Enhanced Observability**: Better error handling and progress reporting

## [1.4.5] - 2025-12-05

### Fixed
- **PyPI Publishing**: Configured PyPI Trusted Publishing for secure token-less releases
- **CI Test Fixes**: Repaired two test failures unrelated to performance fix
  - `test_run_diagnostics_all_checks_pass`: Fixed mock target (was patching facade, now patches runner)
  - `test_cleanup_keeps_most_recent`: Fixed file ordering (sort by filename for reliable timestamp ordering)

## [1.4.3] - 2025-12-05

### Fixed
- **Bug #6 (GitHub) - Complete Fix**: Resolved O(n²) performance bottleneck in archive operations
  - **Issue**: Severe performance degradation - 10,000 messages took ~4 days instead of 30 minutes
  - **Root Cause**: Per-message mbox open/parse/close/fsync operations created O(n²) complexity
    - Python's mbox library parses entire file on every open (O(n) per message → O(n²) total)
    - Per-message fsync caused additional I/O overhead
  - **Solution**: Batch archiving pattern with single mbox open, batched DB commits, single fsync
  - **Impact**: O(n) complexity achieved - 500-1000x faster for large archives
  - **New API**: `archive_messages_batch()` replaces deprecated `archive_message()`
  - **Progress**: Real-time callbacks for progress tracking during batch operations
  - **Interrupts**: Graceful Ctrl+C handling saves progress for resumable operations

### Removed
- **`HybridStorage.archive_message()`**: Deprecated per-message API removed to prevent future misuse
  - All code now uses `archive_messages_batch()` for O(n) performance
  - Tests updated to use batch API or helper wrapper

### Technical Details
- Batch method: single mbox open/close, configurable commit interval (default: 100)
- Offset calculation: proper seek-to-end for appending to existing mbox files
- Dict return type: `{archived, skipped, failed, interrupted, actual_file}`
- Thread-safe interrupt handling via `threading.Event`

### Quality
- **Test coverage**: 94% (1569 tests passing)
- All hybrid storage tests updated for new batch API
- Offset calculation tests added

## [1.4.2] - 2025-12-01

### Added
- **`--verbose` flag to `status` command**: Shows more detail including full query column and 10 archive runs (default 5)
- **`--check` flag to `doctor` command**: Also runs internal database checks (same as `gmailarchiver check`)
- **UI/UX Guidelines**: New Section 2 in docs/UI_UX_CLI.md documenting `--verbose` semantics
  - Core principle: `--verbose` shows MORE DETAIL about SAME info, NOT different info
  - Pattern: Without verbose shows summary counts; with verbose shows detailed breakdowns
- **docs/USAGE.md**: Complete command reference documentation (externalized from README)

### Changed
- **`status` command**: Now includes database schema version, database size, and archive files count (previously in separate `db-info` command)
- **`doctor` vs `check` separation clarified**: `doctor` = external/environment checks, `check` = internal/database health
- **`retry-delete` command**: Moved to utilities subcommand only (`gmailarchiver utilities retry-delete`)
- **README.md**: Streamlined with quick command reference table, full docs in USAGE.md

### Fixed
- **Bug #2 (GitHub)**: Progress bars not updating during import and verify-integrity commands
  - **Issue**: Progress bar counter showed total but never incremented (time indicator worked correctly)
  - **Root Cause**: `progress_context()` wrapped Rich's `Progress` object in an external `Live()` context, which disabled Progress's internal refresh mechanism
  - **Solution**: Use `Progress` as its own context manager instead of wrapping in external `Live()`
  - **Impact**: Progress bars now update correctly during all operations
- **Bug #6 (GitHub)**: Performance improvements for archiving operations
  - **Issue**: 100x performance regression from 50 msg/sec to 0.5 msg/sec
  - **Root Cause**: Overly conservative `batch_delay=1.0s` in GmailClient
  - **Solution**: Optimized to `batch_delay=0.5s` (2x faster) while respecting Gmail API concurrent request limits
  - **Impact**: 2x performance improvement (~20 msg/sec theoretical, 10-15 msg/sec practical)

### Removed
- **`dedupe-report` command**: Consolidated into `dedupe --dry-run` (same functionality)
- **`db-info` command**: Merged into `status` command with database info
- **`retry-delete` from main commands**: Now utilities-only (still accessible via `gmailarchiver utilities retry-delete`)
- **All 9 legacy module files**: Completed facade pattern migration, removed `_legacy.py` files
  - `archiver_legacy.py`, `importer_legacy.py`, `validator_legacy.py`
  - `search_legacy.py`, `deduplicator_legacy.py`, `consolidator_legacy.py`
  - `compressor_legacy.py`, `doctor_legacy.py`, `extractor_legacy.py`
- Dead code in `OutputManager.task_complete()` that referenced unused `_live` and `_progress` attributes
- Unused `make_status_panel()` function that was never called

### Refactoring
- **Completed facade pattern migration**: All CLI commands now use facade pattern for cleaner architecture
- **Test suite updated**: All tests migrated from legacy modules to facade APIs

### Quality
- **Test coverage**: 94% (1570 tests passing, +182 from v1.4.1)
- Added 7 new tests for doctor CLI command with --check flag
- All legacy module references removed from tests

## [1.3.2] - 2025-11-24

### Added
- **Live Layout Integration**: Archive command now uses live layout with 10-row scrolling log buffer
  - **OperationHandle Protocol**: Abstraction for operation status reporting with 5 methods
    - `log(message, level)` - Add message to live log buffer
    - `update_progress(advance)` - Increment progress counter
    - `set_status(status)` - Update operation status text
    - `succeed(message)` - Mark operation as successful
    - `fail(message)` - Mark operation as failed
  - **OutputHandler Protocol**: Strategy interface for different output modes
    - `print(content)` - Display content
    - `start_operation(description, total)` - Begin tracked operation
    - Context manager support (`__enter__` / `__exit__`)
  - **StaticOutputHandler**: Default handler for backward compatibility (preserves v1.2.0 behavior)
  - **LiveOutputHandler**: New handler that integrates LiveLayoutContext for terminal sessions
  - **TTY Detection**: Auto-enables live mode when running in terminal (`sys.stdout.isatty()`)
  - Added ISO date examples to `archive` command help text

### Fixed
- **Critical Bug #1**: Fixed UNIQUE constraint failures during archiving
  - **Issue**: Messages with duplicate RFC Message-IDs (same email in multiple folders, forwarded emails) caused database constraint violations
  - **Root Cause**: Incremental filtering only checked `gmail_id`, but database UNIQUE constraint is on `rfc_message_id`
  - **Solution**: Added duplicate check in `hybrid_storage.py` BEFORE writing to mbox (Phase 1a)
  - **Behavior**: Duplicates are now skipped gracefully with INFO log message, not treated as errors
  - **Impact**: Eliminates "UNIQUE constraint failed" errors and orphaned messages in mbox files

- **Critical Bug #2**: Fixed ISO date validation blocking advertised feature
  - **Issue**: CLI help text promised ISO date support (e.g., `2024-01-01`) but validation rejected it
  - **Root Cause**: Validation layer mismatch - parser supported ISO dates but validator didn't
  - **Solution**: Updated `input_validator.py` to accept both relative ages (`3y`) and ISO dates (`2024-01-01`)
  - **Impact**: ISO date format now works as documented in help text and README

- **Critical Bug #3**: Fixed help text formatting in CLI
  - **Issue**: Typer was collapsing example commands into a single line
  - **Solution**: Added `\b` escape sequence to preserve formatting
  - **Impact**: Help text now displays properly formatted example list

- **Critical Bug #4**: Eliminated 38 bare print() statements bypassing OutputManager
  - **Issue**: Direct print() calls bypassed centralized output system, breaking JSON mode and consistency
  - **Files affected**: `auth.py` (22), `validator.py` (10), `archiver.py` (6)
  - **Solution**: Replaced all print() with OutputManager methods (info/warning/success/error)
  - **Impact**: All output now flows through OutputManager with proper JSON support and consistent formatting

### Changed
- **OutputManager Architecture**: Refactored to use Strategy Pattern for output handling
  - `OutputManager.__init__()` now accepts `live_mode: bool = False` parameter
  - Internal `_handler` attribute uses OutputHandler protocol (StaticOutputHandler or LiveOutputHandler)
  - `start_operation()` delegates to handler, returns OperationHandle
  - Maintains complete backward compatibility with existing API
- **Archive Command Integration**:
  - `archive()` now detects TTY and enables live mode automatically
  - Wraps operation in handler context manager (`with out._handler:`)
  - Creates operation handle and passes to archiver
  - Shows live 10-row scrolling log during archiving (terminal sessions only)
- **Archiver Integration**:
  - `GmailArchiver.archive()` accepts optional `operation: OperationHandle | None = None`
  - `_archive_messages_hybrid_storage()` uses operation.log() instead of creating standalone Progress bars
  - Operation logging is conditional (backward compatible with `operation=None`)
  - Reports per-message status: "Processing message X/Y", "✓ Archived: <subject>", "✗ Failed: <error>"
- **Data Model Changes**:
  - `HybridStorage.archive_message()` now returns `None` when skipping duplicate messages (v1.3.2+)
  - Updated method signature: `-> tuple[int, int] | None` (was `-> tuple[int, int]`)
- **Validation Changes**:
  - `validate_age_expression()` now accepts ISO dates in addition to relative ages (v1.3.2+)
  - `GmailAuthenticator`, `GmailArchiver`, and `ArchiveValidator` now accept optional `OutputManager` parameter
  - Added `_log()` helper method to all three classes for consistent output handling with fallback to print()

### Quality
- **Test coverage: 95%** (up from 93%, target achieved)
- **Total tests: 1152** (up from 1071, +81 new tests across bug fixes and live layout integration)
- **TDD methodology**: Strict RED → GREEN → REFACTOR followed for all changes
- **No overmocking**: Verified tests exercise real code, not mocks; only external dependencies mocked
- **SOLID Principles**: Architecture review confirmed compliance (Strategy Pattern, Protocol-based design)

#### New Test Coverage:
- **Bug Fixes** (41 tests):
  - Duplicate message handling: 1 test
  - ISO date validation: 8 tests
  - Print statement elimination: 6 tests
  - Error path coverage in hybrid_storage.py: 11 tests
  - Error path coverage in migration.py: 12 tests (100% coverage achieved)
  - Error path coverage in validator.py: 10 tests (96% coverage achieved)
  - Error path coverage in importer.py: 5 tests

- **Live Layout Integration** (46 tests):
  - Protocol compliance: 4 tests
  - StaticOperationHandle behavior: 5 tests
  - StaticOutputHandler behavior: 4 tests
  - OutputManager with static handler: 2 tests
  - LiveOperationHandle behavior: 5 tests
  - LiveOutputHandler behavior: 3 tests
  - OutputManager with live mode: 1 test
  - Archive command integration: 2 tests
  - Additional output.py tests: 20 tests

#### Coverage by Module:
- `migration.py`: 90% → 100% (+10%)
- `validator.py`: 91% → 96% (+5%)
- `auth.py`: 18% → 97% (+79%)
- `archiver.py`: 18% → 93% (+75%)
- `hybrid_storage.py`: 90% → 92% (+2%)
- `output.py`: 93% → 95% (+2%)
- Overall: 93% → 95% (+2%)

## [1.3.1] - 2025-11-24

### Added
- **Live Layout System**: Flicker-free progress tracking with integrated logging
  - **LogBuffer**: Ring buffer with message deduplication and severity-based styling (89 LOC, 100% coverage)
  - **SessionLogger**: XDG-compliant persistent logging with automatic cleanup (67 LOC, 97% coverage)
  - **LiveLayoutContext**: Unified context manager for live UI + file logging (58 LOC, 100% coverage)
  - `live_layout_context()` method on OutputManager for easy integration

### Changed
- **archiver.py**: Replaced raw `print()` calls with structured logging via OutputManager
  - Added optional `output` parameter to `GmailArchiver.__init__()`
  - Implemented `_log()` helper method with severity routing (INFO, WARNING, ERROR, SUCCESS)
  - Maintains backward compatibility with print() fallback
- **CLI commands**: Updated `archive` and `retry-delete` commands to pass OutputManager to GmailArchiver
- **hybrid_storage.py**: Verified logging uses Python's logging module (appropriate for low-level diagnostics)

### Quality
- Test coverage: 93% overall (1071 tests passing)
- New code coverage: 97-100% (platform-specific code excluded)
- TDD methodology: All new code written test-first (RED → GREEN → REFACTOR)
- New test classes: TestLogBuffer (16 tests), TestSessionLogger (34 tests), TestLiveLayoutContext (7 tests), TestGmailArchiverWithOutput (4 tests)
- Lines changed: ~250 (implementation + tests)

## [1.3.0] - 2025-11-24

### Added
- **Exact date support**: Archive command now accepts ISO date format (YYYY-MM-DD) in addition to relative ages
  - New format: `gmailarchiver archive 2024-01-01`
  - Existing format still works: `gmailarchiver archive 3y`
  - Lenient parsing: Accepts dates with or without zero-padding (e.g., both `2024-01-01` and `2024-1-1`)
  - Backward compatible: All existing relative age formats unchanged

### Changed
- Enhanced `parse_age()` function to support both relative ages and ISO dates
- Updated archive command help text to document both formats
- Improved error messages to show both format options (relative age + ISO date)

### Quality
- Test coverage: 95%+ maintained
- All existing tests pass (backward compatibility verified)
- Added 16 new test cases for ISO date parsing (valid dates, invalid formats, edge cases)
- Lines changed: ~40 (implementation + tests)

## [1.2.0] - 2025-11-23

### 🎉 Major Release: Ergonomics & Automation

This release focuses on completing core workflows, adding automation capabilities, and significantly improving user experience. All existing features now have consistent, professional output with JSON support for scripting.

### Added

#### Unified Output System
- **OutputManager**: Professional Rich-formatted output across all commands (366 LOC, 95% coverage)
  - Progress bars with ETA and processing rates
  - JSON mode (`--json` flag) for all commands
  - Actionable next-steps suggestions on errors
  - Task status indicators (✓/✗ emoji)
  - Consistent uv/poetry-style interface

#### New Commands
- **`extract`**: Message retrieval with search integration
  - Extract messages by gmail_id or rfc_message_id
  - Transparent decompression for all compression formats (gzip, lzma, zstd)
  - Output to stdout or file (.eml format)
  - Batch extraction support
  - Integration with search via `--extract` flag
  - 95%+ test coverage

- **`check`**: Unified health check with auto-repair
  - Runs all verification checks in one command (integrity, consistency, offsets, FTS sync)
  - Single consolidated report
  - `--auto-repair` flag for automatic issue resolution
  - Correct exit codes: 0=healthy, 1=issues, 2=repair failed
  - 95%+ test coverage

- **`schedule`**: Automated maintenance scheduling
  - Platform-native scheduling (cron on Linux/macOS, Task Scheduler on Windows)
  - Schedule periodic health checks
  - Logging to `~/.gmailarchiver/logs/`
  - View logs with `schedule logs --tail N`
  - List and disable scheduled jobs
  - Graceful handling when scheduling unavailable
  - 90%+ test coverage

- **`compress`**: Post-hoc compression with database updates
  - Compress existing mbox files (gzip, lzma, zstd)
  - Atomically updates database `archive_file` paths
  - Validates before deleting original
  - `--keep-original` flag for safety
  - Batch processing support
  - Shows compression ratio and savings
  - 95%+ test coverage

- **`doctor`**: Comprehensive diagnostics and health check
  - Database checks (integrity, size, vacuum status, schema version)
  - Archive checks (existence, accessibility, compression)
  - Authentication checks (token validity, scopes, expiration)
  - Performance metrics (search latency)
  - Disk space monitoring
  - Actionable recommendations for issues found
  - 90%+ test coverage

#### Command Enhancements
- **Search improvements**:
  - `--with-preview`: Shows first 200 chars of message body in results
  - `--interactive`: Questionary-based menu for search/select/extract workflow
  - Rich formatting for preview display
  - Integration with extract command

- **Auto-verification flags**:
  - `--auto-verify` on `import`, `consolidate`, and `dedupe` commands
  - Runs appropriate verification checks after operation
  - Shows results and offers auto-repair if issues found

- **Consolidate cleanup**:
  - `--remove-sources` flag safely deletes source archives after successful consolidation
  - Only deletes if consolidation succeeds and passes validation
  - Detailed logging of files removed
  - Works with all compression formats

- **Progress estimation**:
  - ETA calculation based on rolling average
  - Rate display (messages/sec or messages/min)
  - Adaptive smoothing for variable speeds (API rate limits, I/O)
  - Applied to all long-running operations (archive, import, consolidate, search)

### Changed

- **All commands migrated to OutputManager**:
  - Consistent Rich output with progress bars
  - All commands support `--json` flag for scripting
  - Error messages include next-steps suggestions
  - No more plain text output

- **Test suite expanded**:
  - 989 tests (from 650)
  - 93% coverage maintained
  - Comprehensive testing of new features
  - All tests passing

### Metrics

- **New features**: 9 (OutputManager, extract, check, schedule, compress, doctor, search enhancements, cleanup, progress)
- **New commands**: 5 (extract, check, schedule, compress, doctor)
- **Enhanced commands**: 13 (all commands migrated to OutputManager)
- **New dependency**: questionary (interactive UI)
- **Lines of code added**: ~2,500
- **Tests added**: ~340
- **Development time**: 4-5 weeks (as planned)
- **TDD methodology**: All tests written first

### Documentation

- **docs/OUTPUT_SYSTEM.md**: Unified output system documentation
- **docs/PLAN.md**: Updated with v1.2.0 completion status
- All command help text updated with new flags and features

## [1.1.4] - 2025-11-19

### Fixed
- **Release Process**: Fixed GitHub releases having development versions instead of clean release versions
  - Consolidated release and publish workflows into single `release-and-publish.yml`
  - Added version verification to ensure built version matches git tag
  - Removed duplicate builds that caused version mismatches
  - GitHub releases now have correct version numbers (e.g., `1.1.4` not `1.1.5.dev0+...`)

- **Test Suite**: Fixed all test failures after Phase 0 refactoring
  - Updated archiver tests to use new DBManager and HybridStorage mocks
  - Fixed tests expecting FileNotFoundError to use `auto_create=False` parameter
  - Updated import test to verify auto-migration behavior
  - All 619 tests now passing

- **Code Quality**: Fixed ruff linting and mypy type checking errors
  - Fixed import sorting and removed unused imports
  - Fixed line length violations
  - Removed duplicate import statements

### Added
- **Release Documentation**: Added RELEASE.md with comprehensive release workflow
  - Documents proper tag creation process
  - Explains version verification
  - Includes troubleshooting for common issues
  - Provides emergency procedures for bad releases

## [1.1.3] - 2025-11-18

### Fixed
- **Build Issue**: Removed duplicate config directory inclusion in wheel
  - Fixed PyPI rejection due to duplicate filenames in wheel archive
  - Config directory now included only once via packages declaration

## [1.1.2] - 2025-11-18

### Changed
- **BREAKING**: Package renamed from `gmailarchiver` to `gmail-archiver-cli` for PyPI
  - Old package name `gmailarchiver` was too similar to existing `pygmailarchive` package
  - New name clearly distinguishes this as a modern CLI tool
  - **Action Required**: Uninstall old package and install `gmail-archiver-cli`

### Added
- **First PyPI Release**: Package now available via `pip install gmail-archiver-cli`
- **Detailed Import Error Reporting**: Failed imports now show specific error messages
  - Displays up to 10 error messages per file with context
  - Shows which archive file had errors and specific failure reasons
  - Helps users diagnose and fix import issues

### Fixed
- **Auto-Migration**: Import command now automatically migrates v1.0 databases to v1.1
  - Detects v1.0 schema and runs migration before import
  - Creates proper v1.1 schema for new installations
  - Handles empty database files by recreating them

- **Archive Run Recording**: Fixed duplicate archive run entries
  - Import operations now record single run entry per import
  - Added `record_run` parameter to `DBManager.record_archived_message()`
  - Added public `DBManager.record_archive_run()` method for bulk operations

- **Error Messages**: Improved error messages for missing databases
  - Status and validate commands now provide helpful next-step guidance
  - Suggests running `archive` or `import` commands when database missing

## [1.1.0] - 2025-11-15

### 🎉 Stable Release

This is the first stable release of Gmail Archiver v1.1, consolidating all features and fixes from beta.1 and beta.2 into a production-ready release.

### Major Features

#### Database Architecture (v1.1 Schema)
- **Automatic v1.0 → v1.1 migration** with backup and rollback support
- **Enhanced schema** with 17-field messages table (vs 7 in v1.0)
- **O(1) message access** via `mbox_offset` and `mbox_length` fields
- **FTS5 full-text search** with auto-sync triggers and BM25 ranking
- **DBManager** - Centralized database operations (754 LOC, 92% test coverage)
- **HybridStorage** - Atomic mbox + database coordinator (1,167 LOC, 87% test coverage)

#### Search & Discovery
- **Gmail-style query syntax**: `from:`, `to:`, `subject:`, `after:`, `before:`, free-text
- **Performance**: 0.85ms for 1000 messages (118x faster than 100ms target)
- **BM25 ranking algorithm** for relevance-based results

#### Archive Management
- **Import existing archives**: Support for gzip/lzma/zstd compressed mbox files
- **Message deduplication**: 100% precision via RFC Message-ID matching
- **Archive consolidation**: Merge multiple archives with chronological sorting
- **Three deduplication strategies**: 'newest', 'largest', 'first'
- **Performance**: 10,145 messages/second (import), 3.57s for 10k messages (consolidate)

#### Validation & Recovery
- **Database integrity verification** with comprehensive checks
- **Automated repair** with dry-run mode and backfill support
- **Offset validation** for mbox file accuracy
- **Consistency checks** across database and FTS index

#### New CLI Commands (17 total)
- `migrate` - Migrate v1.0 → v1.1 database schema
- `db-info` - Display database schema version and statistics
- `rollback` - Restore database from backup
- `search` - Search archived messages with Gmail-style syntax
- `import` - Import existing mbox archives
- `dedupe-report` - Analyze duplicate messages
- `dedupe` - Remove duplicates with configurable strategy
- `verify-offsets` - Validate mbox offsets (v1.1 only)
- `verify-consistency` - Deep database consistency check
- `verify-integrity` - Comprehensive integrity verification
- `consolidate` - Merge multiple archives
- `repair` - Automated database repair with backfill option
- `retry-delete` - Retry deletion for authorization failures

### Fixed

#### Critical Fixes
- **zstd import inconsistency**: Standardized to Python 3.14 native `compression.zstd` API
- **Migration placeholder bug**: Migration now scans actual mbox files for real offsets (beta.1 issue)
- **Missing audit trail**: All operations recorded in `archive_runs` with `operation_type`
- **Schema divergence**: Unified `archive_runs` table structure across all code paths
- **OAuth scope**: Changed to full Gmail access (`https://mail.google.com/`) for deletion support

#### Quality Improvements
- **Consolidator regression**: Restored sorting and all deduplication strategies
- **FTS repair logic**: Handles both content-based and external content FTS modes
- **Performance test failures**: Updated fixtures to use complete v1.1 schema
- **Code quality**: All ruff linting issues resolved

### Changed

- **Breaking**: OAuth scope changed from `gmail.modify` to full Gmail access
  - **Action Required**: Run `gmailarchiver auth-reset` and re-authenticate
  - **Reason**: Previous scope lacked `messages.delete` permission

### Performance

All operations meet or exceed targets:
- **Search**: 0.85ms for 1000 messages (118x faster than 100ms target)
- **Import**: 10,145 messages/second (60x faster than target)
- **Consolidate**: 3.57s for 10k messages (16x faster than 60s target)

### Test Coverage

- **Total tests**: 619 (up from 283 in v1.0.3)
- **Pass rate**: 100% (619 passing, 4 skipped)
- **Coverage**: 92%
- **New tests since v1.0**: 336 additional tests

### Migration from v1.0.x

**Automatic migration on first run:**

```bash
# Backup created automatically at ~/.local/share/gmailarchiver/archives.db.backup_v1.0
gmailarchiver db-info  # Triggers migration if needed
```

**Re-authentication required** (OAuth scope change):

```bash
gmailarchiver auth-reset
gmailarchiver archive 3y  # Re-authenticate during first archive
```

### Migration from v1.1.0-beta.1

**If you upgraded to beta.1 and migrated your v1.0 database:**

1. Upgrade to v1.1.0:
   ```bash
   pip install --upgrade gmailarchiver
   ```

2. Verify database integrity:
   ```bash
   gmailarchiver verify-integrity
   ```

3. If issues found (likely invalid offsets from beta.1 bug):
   ```bash
   # Preview repairs
   gmailarchiver repair --backfill

   # Apply repairs
   gmailarchiver repair --backfill --no-dry-run
   ```

4. Verify repair succeeded:
   ```bash
   gmailarchiver verify-integrity
   # Should show: "✓ Database integrity verified - no issues found"
   ```

[1.1.0]: https://github.com/tumma72/GMailArchiver/compare/v1.0.3...v1.1.0

## [1.1.0-beta.2] - 2025-11-14

### 🔴 Critical Fixes (Data Integrity)

This release fixes critical data integrity issues discovered in v1.1.0-beta.1. **All beta.1 users should upgrade immediately.**

- **CRITICAL**: Fixed migration placeholder bug creating invalid database records
  - **Problem**: Migration created placeholder records with `offset=-1` instead of scanning actual mbox files
  - **Impact**: Users who migrated from v1.0 to beta.1 have invalid offset data for pre-migration messages
  - **Fix**: Migration now scans actual mbox files to extract real offsets, lengths, and Message-IDs
  - **Action Required**: Run `gmailarchiver repair --backfill --no-dry-run` to fix existing invalid records

- **CRITICAL**: Fixed missing audit trail in archive_runs table
  - **Problem**: Import and consolidate operations were not recorded in archive_runs
  - **Impact**: Incomplete operation history and missing metadata
  - **Fix**: All operations now properly recorded with `operation_type` field

- **CRITICAL**: Fixed schema divergence in archive_runs table
  - **Problem**: Inconsistent table structure across different code paths
  - **Impact**: Database operations failed with "no such column: operation_type" error
  - **Fix**: Standardized schema with `account_id` and `operation_type` columns in v1.1

### Added

#### New CLI Commands (2 total)

- **`verify-integrity`** - Comprehensive database integrity verification
  - Detects orphaned FTS records
  - Detects missing FTS records
  - Detects invalid mbox offsets (offset < 0 or length <= 0)
  - Detects duplicate Message-IDs
  - Detects missing archive files
  - Rich table output with clear issue descriptions
  - Exit code 0 if clean, 1 if issues found

- **`repair [--dry-run] [--backfill]`** - Automated database repair
  - **Dry-run mode by default** (safe preview before making changes)
  - Fixes orphaned FTS records (removes records without corresponding messages)
  - Fixes missing FTS records (rebuilds FTS index for messages)
  - **`--backfill` flag**: Fixes invalid offsets by scanning mbox files (critical for beta.1 users)
  - Requires explicit confirmation for non-dry-run operations
  - All repairs recorded in audit trail (archive_runs table)
  - Rich progress output with repair summaries

#### Architecture Improvements

- **DBManager** - Centralized database operations manager
  - All database operations go through single class (no scattered SQL)
  - Parameterized queries (SQL injection prevention)
  - Automatic transaction management (commit/rollback)
  - Complete audit trail for all operations
  - Built-in integrity verification and repair methods
  - 92% test coverage

- **HybridStorage** - Transactional coordinator for mbox + database
  - Atomic operations (both mbox and database succeed or both fail)
  - Two-phase commit pattern implementation
  - Automatic validation after every write
  - Staging area for safe operations
  - Rollback support on failures
  - New primitives: `read_messages_from_archives`, `bulk_write_messages`, `bulk_update_archive_locations_with_dedup`
  - 87% test coverage

### Changed

#### Refactored Core Modules

- **migration.py** - Fixed to scan actual mbox files instead of creating placeholders
  - Extracts real RFC Message-IDs from mbox messages
  - Calculates accurate mbox offsets and lengths
  - Properly handles compressed archives
  - Enhanced error handling for corrupt mbox files
  - 90% test coverage (up from 47%)

- **archiver.py** - Integrated HybridStorage for atomic archiving
  - Backward compatible with v1.0 databases
  - Automatic validation after archiving
  - Proper lock file cleanup
  - Enhanced error handling
  - 93% test coverage (up from 89%)

- **importer.py** - Uses DBManager for all database operations
  - Automatic audit trail generation
  - Removed direct SQL queries
  - Better error handling
  - 91% test coverage (up from 74%)

- **consolidator.py** - Restored full functionality using HybridStorage primitives
  - Chronological sorting by date (restored)
  - All deduplication strategies: 'newest', 'largest', 'first' (restored)
  - Atomic operations (mbox + database)
  - Enhanced error handling
  - 99% test coverage (up from 100%, minor edge case)

### Fixed

- **Migration placeholder bug**: Migration now scans actual mbox files to extract real data
- **Missing audit trail**: All operations now recorded in archive_runs with operation_type
- **Schema divergence**: Unified archive_runs schema across all code paths
- **Consolidator regression**: Restored sorting and all deduplication strategies
- **FTS repair logic**: Now handles both content-based and external content FTS modes
- **Performance test failures**: Updated test fixtures to use complete v1.1 schema
- **Code quality**: Fixed all ruff linting issues

### Test Coverage

- **Total tests**: 619 (up from 435 in beta.1)
- **New tests**: 184
- **Pass rate**: 100% (619 passing, 4 skipped)
- **Coverage**: 92% (maintained)

### Performance

No performance regressions. All operations maintain or exceed beta.1 performance:
- Search: 0.85ms for 1000 messages
- Import: 10,145 messages/second
- Consolidate: 3.57s for 10k messages

### Migration from v1.1.0-beta.1

**If you upgraded to beta.1 and migrated your v1.0 database:**

1. Upgrade to beta.2:
   ```bash
   pip install --upgrade gmailarchiver
   ```

2. Verify your database integrity:
   ```bash
   gmailarchiver verify-integrity
   ```

3. If issues found (likely invalid offsets from beta.1 migration bug):
   ```bash
   # Preview repairs
   gmailarchiver repair --backfill

   # Apply repairs
   gmailarchiver repair --backfill --no-dry-run
   ```

4. Verify repair succeeded:
   ```bash
   gmailarchiver verify-integrity
   # Should show: "✓ Database integrity verified - no issues found"
   ```

[1.1.0-beta.2]: https://github.com/tumma72/GMailArchiver/compare/v1.1.0-beta.1...v1.1.0-beta.2

## [1.1.0-beta.1] - 2025-11-14

### ⚠️ Breaking Changes

- **OAuth Scopes**: Changed from `gmail.modify` to full Gmail access (`https://mail.google.com/`) to support permanent deletion
  - **Action Required**: Run `gmailarchiver auth-reset` and re-authenticate
  - **Why**: Previous scope did not include `messages.delete` permission, causing HTTP 403 errors after archiving
  - **Fix**: Added `retry-delete` command to retry deletion for already-archived messages

### Added

#### Core Features

- **Database Migration System** (v1.0 → v1.1)
  - Automatic schema migration with backup and rollback support
  - Enhanced schema with `mbox_offset` and `mbox_length` for O(1) message access
  - FTS5 full-text search with auto-sync triggers
  - 17-field messages table (vs 7 in v1.0)

- **FTS5 Full-Text Search**
  - Gmail-style query syntax (`from:`, `to:`, `subject:`, `after:`, `before:`)
  - BM25 ranking algorithm
  - Performance: 0.85ms for 1000 messages (118x faster than 100ms target)

- **Archive Import**
  - Import existing mbox archives into v1.1 database
  - Automatic offset calculation and metadata extraction
  - Support for gzip, lzma, zstd compression
  - Performance: 10,145 messages/second (60x faster than target)

- **Message Deduplication**
  - 100% precision via RFC Message-ID matching
  - Support for multiple strategies: `newest`, `largest`, `first`
  - Cross-archive duplicate detection

- **Archive Consolidation**
  - Merge multiple archives into one
  - Chronological sorting with integrated deduplication
  - Automatic offset recalculation
  - Performance: 3.57s for 10k messages (16x faster than 60s target)

- **Enhanced Validation**
  - `verify-offsets`: Validate mbox offset accuracy
  - `verify-consistency`: Deep database integrity checks
  - Orphaned record detection
  - FTS5 sync validation

#### New CLI Commands (11 total)

- `migrate` - Migrate database from v1.0 to v1.1 schema
- `db-info` - Display database schema version and statistics
- `rollback` - Restore database from backup
- `search` - Search archived messages with Gmail-style syntax
- `import` - Import existing mbox archives into database
- `dedupe-report` - Analyze duplicate messages across archives
- `dedupe` - Remove duplicate messages with configurable strategy
- `verify-offsets` - Validate mbox offset accuracy (v1.1 only)
- `verify-consistency` - Deep database consistency check
- `consolidate` - Merge multiple archives with sort/dedupe
- `retry-delete` - Retry deletion for already-archived messages

### Changed

- **Database Schema**: v1.0 → v1.1 (automatic migration on first run)
- **Performance**: Massive performance improvements across all operations:
  - Search: 0.85ms for 1000 messages (118x faster than target)
  - Import: 10,145 messages/second (60x faster than target)
  - Consolidate: 3.57s for 10k messages (16x faster than target)

### Fixed

- **Critical**: Fixed OAuth scope missing deletion permission
  - Previous scope `gmail.modify` did not include `messages.delete`
  - Users experienced HTTP 403 errors after 30+ minutes of archiving
  - Now uses full Gmail scope `https://mail.google.com/`
  - Added `retry-delete` command for failed deletions

### Performance

| Component | Target | Achieved | Improvement |
|-----------|--------|----------|-------------|
| Search (1000 msgs) | <100ms | 0.85ms | 118x faster |
| Import (10k msgs) | <60s | <1s | 60x faster |
| Consolidate (10k msgs) | <60s | 3.57s | 16x faster |

### Test Coverage

- Total tests: 435 (up from 283 in v1.0.3)
- New tests: 152
- Pass rate: 100%
- Coverage: 92%

[1.1.0-beta.1]: https://github.com/tumma72/GMailArchiver/compare/v1.0.3...v1.1.0-beta.1

## [1.0.3] - 2025-11-13

### Added
- Comprehensive test suite improving coverage from 30% to 96%
- CLAUDE.md documentation for codebase structure and development workflows
- Tests for input_validator.py (61 tests, 98% coverage)
- Tests for gmail_client.py (27 tests, 98% coverage)
- Tests for validator.py (18 tests, 92% coverage)
- Tests for archiver.py (22 tests, 95% coverage)
- Extended tests for auth.py with error handling scenarios (98% coverage)
- Total: 197 passing tests (up from 65)

### Fixed
- Python 3.14 compatibility: Use stdlib `compression.zstd` instead of `zstandard` package
- Linting errors in test files (unused imports, undefined types, line length)
- Code quality issues identified by ruff linter
- zstd compression now works correctly with level parameter

## [1.0.1] - 2025-11-13

### Added
- XDG Base Directory standard compliance for token storage
  - Linux/macOS: `~/.config/gmailarchiver/token.json`
  - Windows: `%APPDATA%/gmailarchiver/token.json`
- Automatic version management from Git tags using hatch-vcs
- Bundled OAuth2 credentials for simplified first-run experience
- Comprehensive security improvements (path validation, input sanitization)
- Transaction support for database operations with auto-commit/rollback

### Changed
- OAuth2 credentials now bundled in package (no manual setup required)
- Token storage moved from current directory to XDG-compliant paths
- Updated CLI to use bundled credentials by default
- Improved OAuth2 error messages for better user guidance
- Enhanced path validator to correctly handle custom base directories

### Fixed
- Critical mbox lock file bug causing `.lock.lock` file accumulation
- Lock files now properly cleaned up before and after archiving
- Defensive exception handling in mbox unlock/close operations
- Path traversal security vulnerability in file operations
- Pickle-based token storage replaced with secure JSON format
- Python 3.14 compatibility issues with zstd imports
- Version synchronization across project files
- mypy configuration for proper type checking
- All test suite failures (65 tests passing)

### Security
- Replaced insecure pickle token storage with JSON
- Implemented path traversal attack prevention
- Added input validation for Gmail queries, filenames, and age expressions
- Proper handling of OAuth2 credentials following Google's best practices

## [1.0.0] - 2025-11-13

### Added
- Initial release of Gmail Archiver
- Archive Gmail messages to local mbox files
- Support for zstd, gzip, and bzip2 compression
- Gmail API integration with OAuth2 authentication
- Incremental archiving with SQLite state tracking
- Rich terminal UI with progress tracking
- Dry-run mode for testing
- Comprehensive test suite

### Features
- Search by Gmail query syntax
- Archive messages older than specified age
- Exclude labels from archiving
- Message validation and deduplication
- Automatic retry logic for API failures
- Cross-platform support (macOS, Linux, Windows)

[1.0.3]: https://github.com/tumma72/GMailArchiver/compare/v1.0.1...v1.0.3
[1.0.1]: https://github.com/tumma72/GMailArchiver/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/tumma72/GMailArchiver/releases/tag/v1.0.0
