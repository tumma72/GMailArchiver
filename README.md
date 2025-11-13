# Gmail Archiver

[![Version](https://img.shields.io/github/v/release/tumma72/GMailArchiver)](https://github.com/tumma72/GMailArchiver/releases)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://github.com/tumma72/GMailArchiver/workflows/Tests/badge.svg)](https://github.com/tumma72/GMailArchiver/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/bfb62663af32da529734c79e0e67fa23/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

A powerful CLI tool to archive old Gmail messages to local mbox files with validation, compression, and safe deletion.

## Features

- **Smart Archiving**: Archive emails older than a specified threshold (e.g., "3y", "6m")
- **Incremental Mode**: Skip already-archived messages for efficient recurring runs
- **Compression**: Support for gzip, lzma, and zstd (Python 3.14 native) compression
- **Multi-Layer Validation**: Validate archives before deletion with checksums and spot-checks
- **Safe Deletion Workflow**:
  - Archive-only mode (default, safe)
  - Trash mode (30-day recovery)
  - Permanent deletion (with explicit confirmation)
- **Progress Tracking**: Real-time progress bars for long operations
- **State Management**: SQLite database tracks archived messages and runs
- **Batch Operations**: Efficient API usage with automatic rate limiting

## Installation

### Prerequisites

- Python 3.14 or higher
- Google Account with Gmail access

**Note**: OAuth2 credentials are now bundled with the application. No manual Google Cloud setup required!

### Option 1: Install from GitHub Release (Recommended)

Download the latest wheel file from the [releases page](https://github.com/tumma72/GMailArchiver/releases) and install with pip:

```bash
# Download the latest .whl file from releases, then:
pip install gmailarchiver-*.whl

# Or install directly from the latest release URL (replace VERSION with latest):
pip install https://github.com/tumma72/GMailArchiver/releases/download/vVERSION/gmailarchiver-VERSION-py3-none-any.whl
```

### Option 2: Install with pip + UV (For Development)

```bash
# Clone the repository
git clone https://github.com/tumma72/GMailArchiver.git
cd GMailArchiver

# Install with pip in editable mode
pip install -e .

# Or install dependencies with UV
uv sync

# Or install in development mode with UV
uv sync --dev
```

### Option 3: Build from Source

```bash
# Clone the repository
git clone https://github.com/tumma72/GMailArchiver.git
cd GMailArchiver

# Build the wheel
uv build

# Install the built wheel (version will match your git tag)
pip install dist/gmailarchiver-*.whl
```

### First Run - OAuth2 Authorization

On first run, Gmail Archiver will automatically:
1. Open your browser to Google's authorization page
2. Ask you to sign in with your Google Account
3. Request permission to access Gmail (read-only for archiving, modify for deletion)
4. Save an authorization token to `~/.config/gmailarchiver/token.json` (Linux/macOS) or `%APPDATA%/gmailarchiver/token.json` (Windows)

**Note**: The bundled OAuth2 credentials are for "installed applications" and follow Google's security model. The client secret is not truly confidential for desktop apps - security comes from user consent at authorization time.

#### Advanced: Custom OAuth2 Credentials (Optional)

If you prefer to use your own OAuth2 credentials:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click "Enable"
4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client ID"
   - Select "Desktop app" as application type
   - Download the credentials JSON file
5. Use the `--credentials` flag to specify your custom credentials file:
   ```bash
   gmailarchiver archive 3y --credentials /path/to/your/credentials.json
   ```

## Usage

**Note**: If you installed via pip/wheel, use `gmailarchiver` directly. If running from source with UV, use `uv run gmailarchiver`.

### Basic Commands

```bash
# Archive emails older than 3 years (dry run by default for safety)
gmailarchiver archive 3y --dry-run

# Actually archive (creates archive_YYYYMMDD.mbox)
gmailarchiver archive 3y

# Archive with compression (zstd is fastest and recommended)
gmailarchiver archive 3y --compress zstd

# Or use gzip for compatibility
gmailarchiver archive 3y --compress gzip

# Archive and move to trash (reversible, 30-day recovery)
gmailarchiver archive 3y --trash

# Archive with custom output file
gmailarchiver archive 6m --output old_emails.mbox.gz --compress gzip

# Permanent deletion (requires explicit confirmation)
gmailarchiver archive 3y --delete
```

### Age Threshold Formats

- `3y` - 3 years
- `6m` - 6 months
- `2w` - 2 weeks
- `30d` - 30 days

### Additional Commands

```bash
# Validate an existing archive (works with all compression formats)
gmailarchiver validate archive_20250113.mbox.zst

# Show archiving status and statistics
gmailarchiver status

# Reset authentication (revoke token)
gmailarchiver auth-reset

# Get help
gmailarchiver --help
gmailarchiver archive --help
```

## Workflow

### Recommended Safe Workflow

```bash
# 1. Dry run to preview
gmailarchiver archive 3y --dry-run

# 2. Archive without deletion (using zstd for best performance)
gmailarchiver archive 3y --compress zstd

# 3. Validate the archive
gmailarchiver validate archive_20250113.mbox.zst

# 4. Move to trash (reversible for 30 days)
gmailarchiver archive 3y --trash

# 5. (Optional) After verification, permanent delete
#    Only run this after you've verified the archive!
gmailarchiver archive 3y --delete
```

### Incremental Archiving

The tool tracks archived messages in a SQLite database (`archive_state.db`). Subsequent runs automatically skip already-archived messages:

```bash
# First run - archives all emails older than 3 years
gmailarchiver archive 3y

# Future runs - only archives new emails matching criteria
gmailarchiver archive 3y  # Skips previously archived messages
```

## Architecture

```
gmailarchiver/
   auth.py          # OAuth2 authentication
   gmail_client.py  # Gmail API wrapper with retry logic
   archiver.py      # Core archiving logic
   validator.py     # Archive validation
   state.py         # SQLite state tracking
   utils.py         # Utility functions (date parsing, etc.)
   main.py          # CLI interface (Typer)
```

## Safety Features

1. **Dry-run mode**: Preview operations without making changes
2. **Archive validation**: Multi-layer validation before deletion
   - Count verification
   - Database cross-check
   - Content integrity check
   - Spot-check sampling
3. **Trash first**: Move to trash (reversible) before permanent deletion
4. **Explicit confirmation**: Type exact phrase to confirm permanent deletion
5. **Incremental mode**: Prevents duplicate archiving
6. **Rate limiting**: Automatic exponential backoff for API limits

## Performance

Typical performance with Gmail API rate limits:

- 10,000 emails: ~25-30 minutes
- 50,000 emails: ~2-2.5 hours
- 100,000 emails: ~4-5 hours (or split into multiple runs)

The tool uses batch operations and automatically handles rate limiting with exponential backoff.

## Database Schema

The tool maintains state in `archive_state.db`:

### archived_messages table
- `gmail_id` (PRIMARY KEY): Gmail message ID
- `archived_timestamp`: When message was archived
- `archive_file`: Path to archive file
- `subject`: Email subject
- `from_addr`: From address
- `message_date`: Original email date
- `checksum`: SHA256 checksum

### archive_runs table
- `run_id` (PRIMARY KEY): Auto-incrementing run ID
- `run_timestamp`: When archive run occurred
- `query`: Gmail query used
- `messages_archived`: Count of messages archived
- `archive_file`: Archive file path

## Troubleshooting

### "Credentials file not found"

Download credentials from Google Cloud Console and save as `credentials.json`.

### "Rate limit exceeded"

The tool automatically retries with exponential backoff. For very large mailboxes, consider splitting into smaller date ranges.

### "Validation failed"

The archive may be incomplete. DO NOT delete until validation passes. Check:
- Archive file exists and is readable
- State database is not corrupted
- Sufficient disk space

### Authentication issues

Reset authentication:
```bash
gmailarchiver auth-reset
```

Then re-run any command to re-authenticate.

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Run tests: `uv run pytest`
4. Run linter: `uv run ruff check .`
5. Run type checker: `uv run mypy gmailarchiver`
6. Submit a pull request

## License

Apache-2.0

## Disclaimer

This tool permanently deletes emails when using `--delete`. Always:
- Test with `--dry-run` first
- Validate archives before deletion
- Use `--trash` for reversible deletion
- Keep backups of important emails

The authors are not responsible for data loss.
