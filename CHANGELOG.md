# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0-beta.1] - 2025-01-14

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

## [1.0.3] - 2025-01-13

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

## [1.0.1] - 2025-01-13

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

## [1.0.0] - 2025-01-13

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
