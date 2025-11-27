# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Structure

- **README.md**: User-focused documentation for installing and using Gmail Archiver
- **CONTRIBUTING.md**: Comprehensive developer guide (setup, testing, pull requests)
- **ARCHITECTURE.md**: **Single source of truth** for system architecture, design decisions, and technical details
- **CLAUDE.md** (this file): Quick reference for AI assistants working on the codebase
- **CHANGELOG.md**: Version history and release notes
- **docs/PLAN.md**: Development roadmap and feature planning
- **docs/OUTPUT_SYSTEM.md**: Unified output system documentation

For detailed architecture, database schema, and design decisions, see [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Project Overview

Gmail Archiver is a Python CLI tool that archives old Gmail messages to local mbox files with validation, compression, and safe deletion. The project uses Python 3.14+ and follows strict type checking with mypy and linting with ruff.

## Development Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --dev
```

### Running the Application
```bash
# Run from source (development)
uv run gmailarchiver <command>

# Example: Archive emails older than 3 years (dry run)
uv run gmailarchiver archive 3y --dry-run
```

### Testing
```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/test_auth.py

# Run specific test function
uv run pytest tests/test_auth.py::test_authenticate_success

# Run tests with verbose output
uv run pytest -v

# Run tests without coverage
uv run pytest --no-cov
```

### Code Quality
```bash
# Lint with ruff (check only)
uv run ruff check .

# Lint and auto-fix issues
uv run ruff check . --fix

# Format code with ruff
uv run ruff format .

# Type check with mypy
uv run mypy gmailarchiver

# Run all quality checks (recommended before commit)
uv run ruff check . && uv run mypy gmailarchiver && uv run pytest
```

### Building and Packaging
```bash
# Build wheel and source distribution
uv build

# Install built wheel locally
pip install dist/gmailarchiver-*.whl

# Version is automatically managed from git tags via hatch-vcs
```

### Git Workflow
```bash
# Create a new release tag
git tag v1.0.2
git push origin v1.0.2

# The version in pyproject.toml is managed by hatch-vcs
# It reads from git tags automatically during build
```

## Architecture

**Note:** This section provides a quick reference only. For complete architectural details, see [ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Core Components

**src/gmailarchiver/__main__.py**
- CLI entry point using Typer
- Defines 17+ commands (see Commands section below)
- Uses OutputManager for consistent Rich/JSON output
- Orchestrates workflows via DBManager and HybridStorage

**src/gmailarchiver/auth.py** (`GmailAuthenticator`)
- OAuth2 authentication flow
- Uses bundled credentials from `config/oauth_credentials.json` by default
- Stores tokens at XDG-compliant paths (`~/.config/gmailarchiver/token.json` on Linux/macOS)
- Handles token refresh and revocation
- SCOPES: Uses full Gmail access (`https://mail.google.com/`) for deletion support
- `validate_scopes()` method checks if credentials have required permissions

**src/gmailarchiver/gmail_client.py** (`GmailClient`)
- Wrapper around Gmail API
- Implements retry logic with exponential backoff for rate limits
- Batch operations for efficient API usage (default: 10 messages per batch)
- Methods: `list_messages()`, `get_message()`, `delete_message()`, `trash_message()`

**src/gmailarchiver/db_manager.py** (`DBManager`) **(v1.1.0+)**
- **Single source of truth** for all database operations
- Centralized SQL queries (no direct SQL in other modules)
- Transaction management with automatic rollback
- Audit trail recording for all operations
- Built-in integrity validation and repair utilities
- Prevents SQL injection via parameterized queries

**src/gmailarchiver/hybrid_storage.py** (`HybridStorage`) **(v1.1.0+)**
- **Transactional coordinator** for mbox + database operations
- Ensures atomic writes (both succeed or both rollback)
- Two-phase commit pattern with staging area
- Automatic validation after every write
- Prevents database/mbox divergence

**src/gmailarchiver/output.py** (`OutputManager`) **(v1.2.0+)**
- **Unified output system** for all commands
- Rich terminal output with progress bars and status indicators
- JSON output mode for scripting (`--json` flag)
- Actionable next-steps suggestions on errors
- uv-style progress tracking

**src/gmailarchiver/archiver.py** (`GmailArchiver`)
- Gmail archiving orchestrator
- Uses HybridStorage for atomic operations
- Supports compression: gzip, lzma, zstd (Python 3.14 native)
- Incremental mode via DBManager
- Lock file management for mbox safety

**src/gmailarchiver/importer.py** (`ArchiveImporter`) **(v1.1.0+)**
- Import existing mbox archives into database
- Supports glob patterns and all compression formats
- Deduplication support during import
- Progress tracking via OutputManager

**src/gmailarchiver/consolidator.py** (`ArchiveConsolidator`) **(v1.1.0+)**
- Merge multiple archives into one
- Optional deduplication and sorting
- Atomic operations via HybridStorage
- Updates all database offsets transactionally

**src/gmailarchiver/deduplicator.py** (`MessageDeduplicator`) **(v1.1.0+)**
- Message-ID based deduplication (100% precision)
- Cross-archive duplicate detection
- Preserves newest copy by date
- Safety: never modifies in-place, creates new archive

**src/gmailarchiver/search.py** (`MessageSearcher`) **(v1.1.0+)**
- Full-text search via SQLite FTS5
- Gmail-style query syntax
- BM25 ranking for relevance
- Returns metadata + mbox offsets for O(1) retrieval

**src/gmailarchiver/validator.py** (`ArchiveValidator`)
- Multi-layer validation before deletion
- Validates: message count, database cross-check, content integrity, spot-check sampling
- Supports all compression formats (gzip, lzma, zstd)
- Decompresses to temporary files for validation

**src/gmailarchiver/migration.py** (`MigrationManager`) **(v1.1.0+)**
- Automatic schema migration (v1.0 → v1.1)
- Scans mbox files to backfill offsets and Message-IDs
- Automatic backups before migration
- Rollback support if migration fails

**src/gmailarchiver/utils.py**
- Utility functions: age parsing (`parse_age`), date conversions (`datetime_to_gmail_query`)
- Format helpers: `format_bytes`, `chunk_list`
- Age formats: `3y`, `6m`, `2w`, `30d`

**src/gmailarchiver/input_validator.py**
- Input sanitization and validation
- Validates: age expressions, compression formats, Gmail queries, file paths

**src/gmailarchiver/path_validator.py**
- Security: path traversal prevention
- Ensures file operations stay within allowed directories
- Used by state tracking and file operations

**src/gmailarchiver/config/oauth_credentials.json**
- Bundled OAuth2 credentials (installed application type)
- Eliminates need for manual Google Cloud Console setup

### Available Commands

**Core Archiving:**
- `archive` - Archive Gmail messages older than threshold
- `validate` - Validate archive file integrity
- `retry-delete` - Retry deletion of archived messages
- `auth-reset` - Clear OAuth token and re-authenticate

**Archive Management (v1.1.0+):**
- `import` - Import existing mbox files into database
- `consolidate` - Merge multiple archives into one
- `dedupe` - Find and remove duplicate messages (use `--dry-run` for preview)
- `search` - Search archived messages (metadata + full-text)

**Database Operations (v1.1.0+):**
- `verify-integrity` - Check database health
- `verify-consistency` - Deep consistency check (database ↔ mbox)
- `verify-offsets` - Validate mbox offset accuracy
- `repair` - Fix database issues (with `--backfill` for migration repairs)
- `status` - Show archiving statistics, schema version, database size (use `--verbose` for more detail)

**Schema Management (v1.1.0+):**
- `migrate` - Upgrade database schema (v1.0 → v1.1)
- `rollback` - Restore from backup

**All commands support:**
- `--json` flag for JSON output (scripting/automation) *(v1.2.0+)*
- Rich terminal output with progress bars
- Clear error messages with next-steps suggestions

### Data Flow

1. **Authentication Flow**:
   - `GmailAuthenticator` checks for existing token at XDG path
   - If missing/invalid, launches OAuth2 flow with bundled credentials
   - Stores token for future runs

2. **Archive Flow** (via HybridStorage):
   - Parse age threshold → Generate Gmail query (e.g., "before:2022/01/01")
   - Query Gmail API via `GmailClient.list_messages()`
   - Filter out already-archived messages via `DBManager` (incremental mode)
   - Fetch full messages in batches (default: 10 per batch)
   - **Atomic write via HybridStorage**:
     1. Write to staging area
     2. Append to mbox + capture offset
     3. Record in database via `DBManager` (with audit trail)
     4. Automatic validation
     5. Rollback if any step fails
   - Optionally trash/delete messages (with confirmation)

3. **Search Flow** (v1.1.0+):
   - Parse query syntax (Gmail-compatible)
   - Query SQLite FTS5 index via `DBManager`
   - Return results with mbox_offset for O(1) message retrieval
   - No mbox access needed for search (database-only)

4. **Validation Flow**:
   - Load expected message IDs from database via `DBManager`
   - Decompress archive if needed (to temp file)
   - Count messages in mbox
   - Cross-check against database
   - Perform checksum verification
   - Random spot-check sampling

### Database Schema

**Note:** This shows the v1.1.0 schema. For complete schema details and migration strategy, see [ARCHITECTURE.md](docs/ARCHITECTURE.md#data-architecture).

**messages** (v1.1.0+ - replaces `archived_messages`):
- `gmail_id` (PK): Gmail message ID
- `rfc_message_id` (UNIQUE): RFC 2822 Message-ID (for deduplication)
- `thread_id`: Gmail thread ID
- `mbox_offset`, `mbox_length`: For O(1) message retrieval
- `archive_file`: Path to mbox file
- `subject`, `from_addr`, `to_addr`, `message_date`: Email metadata
- `body_preview`: First 1000 chars (for FTS and UI)
- `checksum`: SHA256 for integrity

**messages_fts** (v1.1.0+ - FTS5 virtual table):
- Full-text search index with BM25 ranking
- Indexes: subject, from_addr, to_addr, body_preview
- Auto-synced with messages table via triggers

**archive_runs**:
- `run_id` (PK): Auto-increment
- `run_timestamp`: ISO 8601 timestamp
- `operation`: Type of operation (archive, import, consolidate, dedupe, repair)
- `query`: Gmail search query or operation notes
- `messages_archived`: Count of messages
- `archive_file`: Archive file path

### Safety Architecture

**Note:** For detailed integrity architecture, see [ARCHITECTURE.md](docs/ARCHITECTURE.md#data-integrity-architecture).

The tool implements multiple safety layers:
- **Atomic operations**: HybridStorage ensures mbox + database both succeed or both rollback
- **Automatic validation**: After every write operation, consistency is verified
- **Audit trail**: All operations recorded in archive_runs (archive, import, consolidate, dedupe, repair)
- **Dry-run mode**: Preview without changes
- **Incremental mode**: Prevents duplicate archiving via DBManager
- **Validation commands**: verify-integrity, verify-consistency, verify-offsets
- **Repair command**: Fix database issues with --backfill for migration repairs
- **Trash-first workflow**: Reversible deletion (30-day recovery)
- **Explicit confirmation**: Type exact phrase for permanent deletion
- **Rate limiting**: Exponential backoff for API limits
- **Path validation**: Prevents path traversal attacks
- **Transaction safety**: DBManager handles all database operations with auto-rollback

## Testing Strategy

**Current status**: 650+ tests, 96% coverage

- Tests use `pytest` with coverage reporting
- Mocking pattern: Use unittest.mock for Gmail API (no live API calls in tests)
- Test organization matches source structure (`test_auth.py` → `auth.py`)
- Path validators tested with both valid and malicious inputs
- DBManager tested with temporary databases and rollback scenarios
- HybridStorage tested for atomicity (kill during write, corrupt database)
- OutputManager tested for Rich output, JSON mode, progress tracking
- Auth tests mock OAuth2 flow components (`Flow`, `Credentials`, etc.)

**Key test modules:**
- `test_db_manager.py` - Database operations, transactions, integrity checks
- `test_hybrid_storage.py` - Atomic operations, two-phase commit, validation
- `test_output.py` - OutputManager modes, progress bars, JSON output
- `test_migration.py` - Schema migrations, backfill, rollback
- `test_deduplicator.py` - Message-ID deduplication logic
- `test_search.py` - FTS5 queries, Gmail syntax parsing

## Code Style and Quality

- **Line length**: 100 characters (ruff)
- **Target version**: Python 3.14
- **Type checking**: Strict mypy (all functions must have type hints)
- **Linting**: ruff with rules: E, F, I, N, W, UP
- **Test exceptions**: `N806` (naming), `F841` (unused) allowed in tests
- **Import order**: Enforced by ruff (I rules)

## Important Patterns

### Context Manager Pattern
State tracking uses context managers:
```python
with ArchiveState() as state:
    state.record_archived_message(...)
```

### Compression Detection
File extensions determine compression:
- `.mbox` → uncompressed
- `.mbox.gz` → gzip
- `.mbox.xz` → lzma
- `.mbox.zst` → zstd (fastest, Python 3.14 native)

### Retry Logic
Gmail API calls use exponential backoff:
- Max retries: 5 (configurable)
- Backoff: `2^retry + random jitter`
- Handles HTTP 429 (rate limit) and 500/503 (server errors)

### Lock File Management
Mbox operations require careful lock file cleanup:
- Clean lock files before opening mbox
- Clean lock files after closing mbox
- Defensive exception handling in unlock/close

## Version Management

Version is automatically determined from git tags using `hatch-vcs`:
- Git tag `v1.0.2` → package version `1.0.2`
- Between tags → `1.0.2.devN+gHASH`
- No tags → fallback version `0.0.0`
- Version written to `src/gmailarchiver/_version.py` during build

To create a new release:
1. Tag the commit: `git tag v1.0.2`
2. Push tag: `git push origin v1.0.2`
3. Build: `uv build`
4. The wheel will have version `1.0.2`

## OAuth2 Flow and Scope Changes

**BREAKING CHANGE (v1.0.4+)**: OAuth scope changed from `gmail.modify` to full Gmail access.

The bundled credentials are "installed application" type (per Google's model):
- Client secret is not confidential for desktop apps
- Security comes from user consent at authorization time
- Users can optionally provide their own credentials via `--credentials` flag

**Scope Requirements**:
- Previous scope: `gmail.readonly` + `gmail.modify` (insufficient for permanent deletion)
- Current scope: `https://mail.google.com/` (full Gmail access, includes deletion)
- Reason: The `gmail.modify` scope does NOT include the `messages.delete` API endpoint
- Users must re-authenticate: Run `gmailarchiver auth-reset` and archive again

**retry-delete Command**:
If archiving succeeds but deletion fails with 403 error:
1. Run: `gmailarchiver auth-reset`
2. Run: `gmailarchiver utilities retry-delete <archive_file> [--permanent]`
3. The command retrieves message IDs from database and retries deletion

## Common Debugging Scenarios

### "Credentials file not found"
- Bundled credentials should exist at `src/gmailarchiver/config/oauth_credentials.json`
- Check that config directory is included in package build

### "Rate limit exceeded"
- Tool automatically retries with exponential backoff
- For very large mailboxes, split into smaller date ranges

### "Validation failed"
- Check archive file exists and is readable
- Verify state database not corrupted
- Ensure sufficient disk space
- DO NOT delete until validation passes

### Lock file issues
- Pattern: `.lock.lock` files accumulating
- Root cause: mbox library doesn't clean up on exceptions
- Solution: Defensive cleanup in archiver.py before/after mbox operations

### "403 Insufficient Permission" error during deletion
- Cause: User authenticated with old OAuth scope (missing deletion permission)
- Solution: Re-authenticate with `gmailarchiver auth-reset`, then retry
- Alternative: Use `gmailarchiver utilities retry-delete <archive_file>` to retry deletion for already-archived messages

## Dependencies

**Runtime:**
- `google-api-python-client` - Gmail API
- `google-auth`, `google-auth-oauthlib`, `google-auth-httplib2` - OAuth2
- `typer[all]` - CLI framework
- `rich` - Terminal formatting and progress bars
- `python-dateutil` - Date parsing

**Development:**
- `pytest`, `pytest-cov` - Testing
- `ruff` - Linting and formatting
- `mypy` - Type checking
- `types-python-dateutil` - Type stubs

**Build:**
- `hatchling` - Build backend
- `hatch-vcs` - Version from git tags
