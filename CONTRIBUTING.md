# Contributing to Gmail Archiver

Thank you for your interest in contributing to Gmail Archiver! This guide will help you get started with development.

## Table of Contents

- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Architecture](#architecture)
- [Database Schema](#database-schema)
- [Submitting Changes](#submitting-changes)
- [Release Process](#release-process)

## Development Setup

### Prerequisites

- Python 3.14 or higher
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- Git

### Clone and Install

```bash
# Clone the repository
git clone https://github.com/tumma72/GMailArchiver.git
cd GMailArchiver

# Install with development dependencies
uv sync --dev

# Verify installation
uv run gmailarchiver --help
```

### Development Commands

```bash
# Run from source (development)
uv run gmailarchiver <command>

# Example: Archive emails older than 3 years (dry run)
uv run gmailarchiver archive 3y --dry-run
```

## Development Workflow

### Running Tests

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

We maintain strict code quality standards with automated checks:

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

**Code Style Standards:**
- **Line length**: 100 characters maximum
- **Target version**: Python 3.14
- **Type checking**: Strict mypy (all functions must have type hints)
- **Linting rules**: E, F, I, N, W, UP (ruff)
- **Import order**: Enforced by ruff (I rules)

**Quality Gates:**
- All tests must pass (619 tests, 92% coverage)
- No linting errors (ruff)
- No type checking errors (mypy)
- Coverage should not decrease

## Testing

### Test Organization

Tests mirror the source structure:
- `tests/test_auth.py` → `src/gmailarchiver/auth.py`
- `tests/test_gmail_client.py` → `src/gmailarchiver/gmail_client.py`
- etc.

### Testing Patterns

```python
# Use unittest.mock for external dependencies
from unittest.mock import Mock, patch

# Mock Gmail API - no live API calls in tests
@patch('gmailarchiver.gmail_client.build')
def test_list_messages(self, mock_build: Mock) -> None:
    # ... test implementation
```

### Coverage Requirements

- Overall target: 96%+
- Critical modules should have 90%+ coverage
- New code should include comprehensive tests

## Architecture

### Core Components

```
src/gmailarchiver/
├── __init__.py           # Package initialization
├── __main__.py           # CLI entry point (Typer) - 17 commands
├── auth.py               # OAuth2 authentication (GmailAuthenticator)
├── gmail_client.py       # Gmail API wrapper (GmailClient)
├── archiver.py           # Core archiving logic (GmailArchiver)
├── validator.py          # Archive validation (ArchiveValidator)
├── state.py              # SQLite state tracking (ArchiveState) - v1.0 compatibility
├── db_manager.py         # Database manager (DBManager) - v1.1 schema
├── hybrid_storage.py     # Hybrid storage (HybridStorage) - atomic transactions
├── search.py             # FTS5 full-text search
├── importer.py           # Import existing mbox archives
├── deduplicator.py       # Deduplication logic
├── consolidator.py       # Archive consolidation
├── utils.py              # Utility functions
├── input_validator.py    # Input sanitization and validation
├── path_validator.py     # Path traversal prevention
└── config/
    ├── __init__.py
    └── oauth_credentials.json  # Bundled OAuth2 credentials
```

### Component Responsibilities

**`__main__.py`** - CLI Entry Point
- Defines all commands using Typer (17 commands in v1.1.0):
  - **Core**: `archive`, `validate`, `status`, `auth-reset`
  - **Search**: `search`
  - **Import**: `import`
  - **Deduplication**: `dedupe` (use `--dry-run` for preview)
  - **Consolidation**: `consolidate`
  - **Database**: `migrate`, `rollback`, `status` (includes db info)
  - **Verification**: `verify-offsets`, `verify-consistency`, `verify-integrity`
  - **Repair**: `repair`
  - **Utilities**: `retry-delete` (under `util` subcommand)
- Handles user interaction and Rich console output
- Orchestrates the archiving workflow

**`auth.py`** - GmailAuthenticator
- OAuth2 authentication flow
- Uses bundled credentials from `config/oauth_credentials.json`
- Stores tokens at XDG-compliant paths (`~/.config/gmailarchiver/token.json`)
- Handles token refresh and revocation

**`gmail_client.py`** - GmailClient
- Wrapper around Gmail API
- Implements retry logic with exponential backoff for rate limits
- Batch operations (default: 10 messages per batch)
- Methods: `list_messages()`, `get_message()`, `delete_message()`, `trash_message()`

**`archiver.py`** - GmailArchiver
- Main archiving orchestrator
- Coordinates between Gmail client, state tracking, and file I/O
- Supports compression: gzip, lzma, zstd (Python 3.14 native)
- Incremental mode: skips already-archived messages
- Handles mbox file creation and lock file management

**`state.py`** - ArchiveState
- SQLite database for tracking archived messages
- Context manager interface for automatic connection handling
- Transaction support with auto-commit/rollback
- Path validation to prevent path traversal attacks

**`validator.py`** - ArchiveValidator
- Multi-layer validation before deletion
- Validates: message count, database cross-check, content integrity, spot-check sampling
- Supports all compression formats

**`utils.py`** - Utility Functions
- Age parsing (`parse_age`)
- Date conversions (`datetime_to_gmail_query`)
- Format helpers: `format_bytes`, `chunk_list`

### Data Flow

**Authentication Flow:**
1. `GmailAuthenticator` checks for existing token at XDG path
2. If missing/invalid, launches OAuth2 flow with bundled credentials
3. Stores token for future runs

**Archive Flow:**
1. Parse age threshold → Generate Gmail query (e.g., "before:2022/01/01")
2. Query Gmail API via `GmailClient.list_messages()`
3. Filter out already-archived messages using `ArchiveState`
4. Fetch full messages in batches (default: 10 per batch)
5. Write to mbox file (with optional compression)
6. Record metadata in `ArchiveState` database
7. Validate archive with `ArchiveValidator`
8. Optionally trash/delete messages (with confirmation)

**Validation Flow:**
1. Load expected message IDs from `ArchiveState` database
2. Decompress archive if needed (to temp file)
3. Count messages in mbox
4. Cross-check against database
5. Perform checksum verification
6. Random spot-check sampling

### Safety Architecture

The tool implements multiple safety layers:
- **Dry-run mode**: Preview without changes
- **Incremental mode**: Prevents duplicate archiving via SQLite tracking
- **Validation**: Multi-layer checks before deletion
- **Trash-first workflow**: Reversible deletion (30-day recovery)
- **Explicit confirmation**: Type exact phrase for permanent deletion
- **Rate limiting**: Exponential backoff for API limits
- **Path validation**: Prevents path traversal attacks
- **Transaction safety**: Database operations with auto-rollback on errors

## Database Schema

The tool maintains state in `archive_state.db` with support for both v1.0 (legacy) and v1.1 (current) schemas:

### v1.1.0 Schema (Current)

**`messages` Table** (17 fields with FTS5 support):

| Column | Type | Description |
|--------|------|-------------|
| `message_id` | TEXT PRIMARY KEY | Gmail message ID |
| `thread_id` | TEXT | Gmail thread ID |
| `label_ids` | TEXT | JSON array of label IDs |
| `snippet` | TEXT | Email snippet |
| `history_id` | TEXT | Gmail history ID |
| `internal_date` | INTEGER | Unix timestamp (ms) |
| `size_estimate` | INTEGER | Message size in bytes |
| `raw` | TEXT | Raw email content |
| `from_header` | TEXT | From header |
| `to_header` | TEXT | To header |
| `subject` | TEXT | Email subject |
| `date_header` | TEXT | Date header |
| `mbox_offset` | INTEGER | Offset in mbox file |
| `account_id` | TEXT | Account identifier |
| `archive_file` | TEXT | Path to archive file |
| `archived_timestamp` | TEXT | ISO 8601 timestamp |
| `checksum` | TEXT | SHA256 for integrity |

**`messages_fts` Table** (FTS5 virtual table):
- Full-text search index on: `from_header`, `to_header`, `subject`, `snippet`
- Supports Gmail-style search syntax: `from:`, `to:`, `subject:`, `after:`, `before:`

**`archive_runs` Table**:

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | INTEGER PRIMARY KEY | Auto-increment |
| `run_timestamp` | TEXT | ISO 8601 timestamp |
| `query` | TEXT | Gmail search query used |
| `messages_archived` | INTEGER | Count of messages |
| `archive_file` | TEXT | Archive file path |

### v1.0 Schema (Legacy)

**`archived_messages` Table** (7 fields, maintained for backward compatibility):

| Column | Type | Description |
|--------|------|-------------|
| `gmail_id` | TEXT PRIMARY KEY | Gmail message ID |
| `archived_timestamp` | TEXT | ISO 8601 timestamp |
| `archive_file` | TEXT | Path to archive file |
| `subject` | TEXT | Email subject |
| `from_addr` | TEXT | From address |
| `message_date` | TEXT | Original email date |
| `checksum` | TEXT | SHA256 for integrity |

**Migration**: Run `gmailarchiver migrate` to upgrade from v1.0 to v1.1 schema. Automatic backup created.

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

## Submitting Changes

### Before Submitting

1. **Run all quality checks**:
   ```bash
   uv run ruff check . && uv run mypy gmailarchiver && uv run pytest
   ```

2. **Ensure tests pass**: All 619 tests should pass
3. **Verify coverage**: Overall coverage should be 92%+
4. **Update documentation**: Update README.md, CONTRIBUTING.md, or CLAUDE.md as needed
5. **Update CHANGELOG.md**: Add your changes to the "Unreleased" section

### Pull Request Process

1. Fork the repository
2. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. Make your changes with clear, atomic commits:
   ```bash
   git commit -m "feat: Add new feature"
   git commit -m "fix: Resolve bug in X"
   ```

4. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

5. Open a Pull Request with:
   - Clear description of changes
   - Link to any related issues
   - Test results
   - Screenshots (if UI changes)

### Commit Message Conventions

We follow conventional commits:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Adding or updating tests
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `chore:` - Maintenance tasks

## Release Process

### Version Management

Version is automatically determined from git tags using `hatch-vcs`:
- Git tag `v1.1.0` → package version `1.1.0`
- Between tags → `1.1.0.devN+gHASH`
- No tags → fallback version `0.0.0`

### Creating a Release

1. **Update CHANGELOG.md**:
   - Move changes from "Unreleased" to new version section
   - Follow [Keep a Changelog](https://keepachangelog.com/) format

2. **Commit the changelog**:
   ```bash
   git add CHANGELOG.md
   git commit -m "docs: Prepare v1.1.0 release"
   ```

3. **Tag the release**:
   ```bash
   git tag -a v1.1.0 -m "Release v1.1.0: First stable release"
   git push origin main --tags
   ```

4. **GitHub Actions automatically**:
   - Runs tests
   - Checks code coverage
   - Builds wheel and source distribution
   - Creates GitHub Release with CHANGELOG notes
   - Attaches built packages to the release

### Building Locally

```bash
# Build wheel and source distribution
uv build

# Version matches git tag (e.g., v1.1.0 → 1.1.0)
ls dist/
# gmailarchiver-1.1.0-py3-none-any.whl
# gmailarchiver-1.1.0.tar.gz
```

## Getting Help

- **Documentation**: Check [CLAUDE.md](CLAUDE.md) for detailed codebase documentation
- **Issues**: Browse [open issues](https://github.com/tumma72/GMailArchiver/issues)
- **Discussions**: Ask questions in [GitHub Discussions](https://github.com/tumma72/GMailArchiver/discussions)

## Code of Conduct

Please be respectful and constructive in all interactions. We aim to maintain a welcoming environment for all contributors.

## License

By contributing to Gmail Archiver, you agree that your contributions will be licensed under the Apache-2.0 License.
