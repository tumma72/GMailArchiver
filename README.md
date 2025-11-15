# Gmail Archiver

[![Version](https://img.shields.io/github/v/release/tumma72/GMailArchiver)](https://github.com/tumma72/GMailArchiver/releases)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://github.com/tumma72/GMailArchiver/workflows/Tests/badge.svg)](https://github.com/tumma72/GMailArchiver/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/bfb62663af32da529734c79e0e67fa23/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)

**A comprehensive email archival and search solution for Gmail** - Archive, compress, search, and manage your email history with confidence.

## Why Gmail Archiver?

Gmail offers 15GB of free storage shared across Google services, but that space fills up quickly with years of emails, attachments, and files. While Gmail provides basic search and labels, it lacks:

- **Local backup and control**: Your emails are only in Google's cloud
- **Long-term archival**: No built-in way to archive and compress old emails while keeping them searchable
- **Data portability**: Difficult to export and search emails outside Gmail
- **Storage optimization**: No automatic compression or deduplication
- **Search performance**: Gmail search can be slow for large mailboxes

Gmail Archiver solves these problems by providing a **professional-grade archival solution** that:

1. **Archives** old emails to portable mbox files (industry standard format)
2. **Searches** archived emails with Gmail-style syntax (faster than Gmail itself!)
3. **Compresses** archives with modern algorithms (zstd, lzma, gzip)
4. **Validates** archives before deletion with multi-layer verification
5. **Manages** your email history with deduplication and consolidation
6. **Protects** your data with atomic transactions and safe deletion workflows

### Key Benefits

- **Reclaim Gmail storage**: Archive old emails and safely delete them from Gmail
- **Keep emails searchable**: Lightning-fast full-text search (0.85ms for 1000 messages)
- **Maintain data sovereignty**: Your emails, your local storage, your control
- **Future-proof format**: mbox is a 40+ year old standard supported by all email clients
- **Production-ready**: 619 automated tests, 92% code coverage, strict type safety

## 🔔 Upgrading from v1.0.x?

See the [Migration Guide](MIGRATION_GUIDE.md) for v1.0 → v1.1 upgrade instructions.

**TL;DR**: Run `gmailarchiver migrate` on first v1.1 run. Automatic backup included.

## ✨ New in v1.1.0

### 🔍 Full-Text Search (FTS5)
Search your archived messages with Gmail-style syntax:
- **Search by sender**: `from:alice@example.com`
- **Search by subject**: `subject:meeting`
- **Search by date range**: `after:2024-01-01 before:2024-12-31`
- **Full-text search**: `invoice payment`
- **Performance**: 0.85ms for 1000 messages (118x faster than target)

### 📥 Import Existing Archives
Import mbox files from other tools or previous archives:
- Automatic metadata extraction
- Accurate offset calculation for fast access
- Support for compressed archives (gzip, lzma, zstd)
- **Performance**: 10,000+ messages per second

### 🔄 Deduplication
Remove duplicate messages across archives:
- 100% precision via RFC Message-ID
- Multiple strategies (newest, largest, first)
- Cross-archive detection

### 📦 Archive Consolidation
Merge multiple archives into one:
- Chronological sorting
- Integrated deduplication
- Automatic offset recalculation
- **Performance**: 10k messages in 3.57 seconds (16x faster than target)

### ⚡ Performance Improvements

| Component | Target | Achieved | Improvement |
|-----------|--------|----------|-------------|
| Search (1000 msgs) | <100ms | 0.85ms | 118x faster |
| Import (10k msgs) | <60s | <1s | 60x faster |
| Consolidate (10k msgs) | <60s | 3.57s | 16x faster |

## ✨ Features

- **📅 Smart Archiving**: Archive emails older than a specified threshold (e.g., "3y", "6m", "30d")
- **♻️ Incremental Mode**: Skip already-archived messages for efficient recurring runs
- **🗜️ Compression**: Support for gzip, lzma, and zstd (fastest, Python 3.14 native)
- **✅ Multi-Layer Validation**: Validate archives before deletion with checksums and spot-checks
- **🛡️ Safe Deletion Workflow**:
  - Archive-only mode (default, safe)
  - Trash mode (30-day recovery window)
  - Permanent deletion (with explicit confirmation)
- **📊 Progress Tracking**: Real-time progress bars for long operations
- **💾 State Management**: SQLite database tracks archived messages and run history
- **⚡ Batch Operations**: Efficient API usage with automatic rate limiting

## 📦 Installation

### Prerequisites

- **Python 3.14+** ([Download here](https://www.python.org/downloads/))
- **Gmail Account** with email you want to archive

**Note**: OAuth2 credentials are bundled with the application. No manual Google Cloud setup required!

### Install from PyPI (Coming Soon)

```bash
pip install gmailarchiver
```

### Install from GitHub Release (Current Method)

1. Go to the [Releases page](https://github.com/tumma72/GMailArchiver/releases)
2. Download the latest `.whl` file
3. Install with pip:

```bash
pip install gmailarchiver-*.whl
```

Or install directly from URL:

```bash
# Replace VERSION with the latest version (e.g., 1.0.3)
pip install https://github.com/tumma72/GMailArchiver/releases/download/vVERSION/gmailarchiver-VERSION-py3-none-any.whl
```

### Verify Installation

```bash
gmailarchiver --version
gmailarchiver --help
```

## 🔐 First Run - OAuth2 Authorization

On first run, Gmail Archiver will automatically:

1. **Open your browser** to Google's authorization page
2. **Ask you to sign in** with your Google Account
3. **Request permission** to access Gmail (read-only for archiving, modify for deletion)
4. **Save an authorization token** to:
   - **Linux/macOS**: `~/.config/gmailarchiver/token.json`
   - **Windows**: `%APPDATA%\gmailarchiver\token.json`

**Security Note**: The bundled OAuth2 credentials follow Google's security model for "installed applications". The client secret is not confidential for desktop apps - security comes from user consent at authorization time.

### Using Custom OAuth2 Credentials (Optional)

If you prefer to use your own OAuth2 credentials:

1. Create credentials in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Gmail API
3. Create "Desktop app" OAuth 2.0 credentials
4. Download the credentials JSON file
5. Use with `--credentials` flag:

```bash
gmailarchiver archive 3y --credentials /path/to/your/credentials.json
```

## 🚀 Quick Start

### Basic Usage

```bash
# Preview what would be archived (dry run)
gmailarchiver archive 3y --dry-run

# Archive emails older than 3 years
gmailarchiver archive 3y

# Archive with zstd compression (recommended - fastest)
gmailarchiver archive 3y --compress zstd

# Archive with custom filename
gmailarchiver archive 6m --output my_archive.mbox.zst --compress zstd
```

### Age Formats

| Format | Meaning |
|--------|---------|
| `3y` | 3 years |
| `6m` | 6 months |
| `2w` | 2 weeks |
| `30d` | 30 days |

### Complete Workflow (Recommended)

```bash
# 1. Preview what will be archived
gmailarchiver archive 3y --dry-run

# 2. Archive without deletion (using zstd compression)
gmailarchiver archive 3y --compress zstd
# → Creates: archive_20250113.mbox.zst

# 3. Validate the archive
gmailarchiver validate archive_20250113.mbox.zst

# 4. Move emails to trash (reversible for 30 days)
gmailarchiver archive 3y --trash

# 5. (Optional) Permanent deletion after verification
#    ⚠️ Only after you've verified the archive!
gmailarchiver archive 3y --delete
```

## 📝 All Commands

### Archive Command

```bash
# Archive with different time periods
gmailarchiver archive 1y    # 1 year old
gmailarchiver archive 6m    # 6 months old
gmailarchiver archive 30d   # 30 days old

# Archive with compression options
gmailarchiver archive 3y --compress zstd    # zstd (fastest, recommended)
gmailarchiver archive 3y --compress gzip    # gzip (more compatible)
gmailarchiver archive 3y --compress lzma    # lzma (smallest size)

# Archive and delete
gmailarchiver archive 3y --trash            # Move to trash (reversible)
gmailarchiver archive 3y --delete           # Permanent delete (requires confirmation)

# Custom output file
gmailarchiver archive 6m --output old_emails.mbox.gz --compress gzip
```

### Validation Command

```bash
# Validate any archive (auto-detects compression)
gmailarchiver validate archive_20250113.mbox
gmailarchiver validate archive_20250113.mbox.gz
gmailarchiver validate archive_20250113.mbox.zst
```

### Status Command

```bash
# Show archiving statistics
gmailarchiver status
```

### Authentication Commands

```bash
# Reset authentication (revoke and delete token)
gmailarchiver auth-reset

# Use custom credentials file
gmailarchiver archive 3y --credentials my_credentials.json
```

### Migration Commands (v1.1+)

```bash
# Migrate v1.0 database to v1.1 (automatic on first run)
gmailarchiver migrate

# Show database schema version and statistics
gmailarchiver db-info

# Rollback to backup (if migration fails)
gmailarchiver rollback --backup-file archive_state.db.backup.20250114_120000
```

### Search Commands (v1.1+)

```bash
# Search with Gmail-style syntax
gmailarchiver search "from:alice meeting"
gmailarchiver search "subject:invoice after:2024-01-01"
gmailarchiver search "payment" --limit 50

# Search with filters
gmailarchiver search --from alice@example.com --subject report
gmailarchiver search --after 2024-01-01 --before 2024-12-31

# JSON output for scripting
gmailarchiver search "invoice" --json
```

### Import Commands (v1.1+)

```bash
# Import existing mbox archive
gmailarchiver import old_archive.mbox

# Import multiple archives with glob pattern
gmailarchiver import "archive_*.mbox.gz"

# Import with custom account ID
gmailarchiver import external.mbox --account-id backup_2024
```

### Deduplication Commands (v1.1+)

```bash
# Analyze duplicates (preview only)
gmailarchiver dedupe-report

# Remove duplicates (with confirmation)
gmailarchiver dedupe --strategy newest

# Dry run
gmailarchiver dedupe --dry-run
```

### Consolidation Commands (v1.1+)

```bash
# Merge multiple archives
gmailarchiver consolidate archive_*.mbox -o merged.mbox

# Merge with options
gmailarchiver consolidate old1.mbox old2.mbox -o consolidated.mbox.gz
gmailarchiver consolidate "archives/*.mbox" --no-sort --no-dedupe -o unsorted.mbox
gmailarchiver consolidate archive*.mbox -o merged.mbox.zst --dedupe-strategy newest
```

### Enhanced Validation Commands (v1.1+)

```bash
# Verify mbox offset accuracy (v1.1 databases only)
gmailarchiver verify-offsets archive_20250114.mbox.gz

# Deep database consistency check
gmailarchiver verify-consistency archive_20250114.mbox.gz
```

### Retry Failed Operations (v1.1+)

```bash
# Retry deletion after OAuth scope fix
gmailarchiver retry-delete archive_20250114.mbox --permanent

# Preview what will be retried (dry run)
gmailarchiver retry-delete archive_20250114.mbox --dry-run
```

## 🔄 Incremental Archiving

Gmail Archiver automatically tracks archived messages, so you can run it repeatedly without re-archiving the same emails:

```bash
# First run - archives all emails older than 3 years
gmailarchiver archive 3y --compress zstd

# Future runs - only archives NEW emails older than 3 years
gmailarchiver archive 3y --compress zstd
```

The tool maintains a SQLite database (`archive_state.db`) that tracks which messages have been archived.

## 🛡️ Safety Features

1. **Dry-run mode**: Preview operations without making changes (`--dry-run`)
2. **Multi-layer validation**: Before deletion, validate:
   - Message count matches
   - Database cross-check
   - Content integrity (checksums)
   - Spot-check sampling
3. **Trash-first workflow**: Move to trash (reversible for 30 days) before permanent deletion
4. **Explicit confirmation**: Must type exact phrase to confirm permanent deletion
5. **Incremental mode**: Prevents duplicate archiving of messages
6. **Automatic rate limiting**: Handles Gmail API limits with exponential backoff
7. **Atomic operations**: Database transactions with auto-rollback on errors

## ⚡ Performance

Typical performance with Gmail API rate limits:

| Emails | Time |
|--------|------|
| 10,000 | ~25-30 minutes |
| 50,000 | ~2-2.5 hours |
| 100,000 | ~4-5 hours |

**Tips for large mailboxes**:
- Use `--compress zstd` for fastest compression
- Consider splitting into smaller date ranges
- Run during off-hours to avoid interruptions

## 🔧 Troubleshooting

### Authentication Issues

**Problem**: "Credentials file not found" or authentication fails

**Solution**:
```bash
# Reset authentication
gmailarchiver auth-reset

# Then run any command to re-authenticate
gmailarchiver archive 3y --dry-run
```

### Rate Limit Errors

**Problem**: "Rate limit exceeded" errors

**Solution**: The tool automatically retries with exponential backoff. For very large mailboxes, consider:
- Running during off-peak hours
- Splitting into smaller date ranges (e.g., `1y` instead of `5y`)

### Validation Failures

**Problem**: Archive validation fails

**Solution**: DO NOT delete until validation passes. Check:
1. Archive file exists and is readable
2. Sufficient disk space available
3. State database not corrupted
4. All messages were successfully archived

If validation continues to fail, keep the archive and do not delete from Gmail.

### Disk Space

**Problem**: Running out of disk space

**Solution**:
- Use compression: `--compress zstd` (typically 50-70% space savings)
- Archive smaller time ranges
- Check available space before archiving: `df -h` (Linux/macOS) or `dir` (Windows)

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup
- Testing guidelines
- Code quality standards
- Pull request process

## 📄 License

Apache-2.0 License. See [LICENSE](LICENSE) for details.

## ⚠️ Disclaimer

This tool **permanently deletes emails** when using `--delete`. Always:

- ✅ Test with `--dry-run` first
- ✅ Validate archives before deletion
- ✅ Use `--trash` for reversible deletion
- ✅ Keep backups of important emails

**The authors are not responsible for data loss. Use at your own risk.**

## 🔗 Links

- [GitHub Repository](https://github.com/tumma72/GMailArchiver)
- [Issue Tracker](https://github.com/tumma72/GMailArchiver/issues)
- [Changelog](CHANGELOG.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Developer Documentation](CLAUDE.md)
