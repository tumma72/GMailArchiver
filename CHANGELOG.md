# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
