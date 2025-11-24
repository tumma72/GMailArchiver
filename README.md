# Gmail Archiver

[![PyPI version](https://img.shields.io/pypi/v/gmail-archiver-cli.svg)](https://pypi.org/project/gmail-archiver-cli/)
[![Version](https://img.shields.io/github/v/release/tumma72/GMailArchiver)](https://github.com/tumma72/GMailArchiver/releases)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://github.com/tumma72/GMailArchiver/workflows/Tests/badge.svg)](https://github.com/tumma72/GMailArchiver/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/bfb62663af32da529734c79e0e67fa23/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)

**A professional-grade email archival, search, and management solution for Gmail** - Archive, compress, search, extract, and maintain your email history with confidence.

## 🎉 What's New in v1.3.2 - Critical Bug Fix

Version 1.3.2 fixes a **critical bug** that caused archiving failures:

- 🐛 **Fixed UNIQUE Constraint Errors** - Messages with duplicate RFC Message-IDs (same email in multiple folders) no longer cause database errors
- 🛡️ **Improved Duplicate Handling** - Duplicates are now skipped gracefully with proper logging
- ✅ **Enhanced Stability** - Eliminates orphaned messages in mbox files

### Recent Major Features (v1.2.0)

- 🎨 **Unified Rich Output** - Beautiful terminal output with progress bars, ETA, and rate tracking
- 📤 **Message Extraction** - Retrieve messages from search results
- 🏥 **Health Check Command** - One command to check everything
- ⏰ **Automated Scheduling** - Set up periodic health checks
- 🗜️ **Post-hoc Compression** - Compress existing archives anytime
- 🩺 **Doctor Command** - Comprehensive diagnostics
- 🔍 **Search Enhancements** - Preview and interactive modes
- 📊 **JSON Mode** - All commands support `--json` for scripting

[See full changelog](#-version-history)

## Why Gmail Archiver?

Gmail offers 15GB of free storage shared across Google services, but that space fills up quickly with years of emails, attachments, and files. While Gmail provides basic search and labels, it lacks:

- **Local backup and control**: Your emails are only in Google's cloud
- **Long-term archival**: No built-in way to archive and compress old emails while keeping them searchable
- **Data portability**: Difficult to export and search emails outside Gmail
- **Storage optimization**: No automatic compression or deduplication
- **Fast local search**: Gmail search can be slow for large mailboxes

Gmail Archiver solves these problems by providing a **professional-grade archival solution** that:

1. **Archives** old emails to portable mbox files (industry standard format)
2. **Searches** archived emails with Gmail-style syntax (faster than Gmail itself!)
3. **Extracts** individual messages from compressed archives
4. **Compresses** archives with modern algorithms (zstd, lzma, gzip)
5. **Validates** archives before deletion with multi-layer verification
6. **Manages** your email history with deduplication and consolidation
7. **Automates** maintenance with scheduled health checks
8. **Protects** your data with atomic transactions and safe deletion workflows

### Key Benefits

- **Reclaim Gmail storage**: Archive old emails and safely delete them from Gmail
- **Keep emails searchable**: Lightning-fast full-text search (0.85ms for 1000 messages)
- **Extract on demand**: Retrieve individual messages from compressed archives
- **Maintain data sovereignty**: Your emails, your local storage, your control
- **Automate maintenance**: Set-and-forget health checks
- **Future-proof format**: mbox is a 40+ year old standard supported by all email clients
- **Production-ready**: 989 automated tests, 93% code coverage, strict type safety

## ✨ Core Features

### 📥 Archiving & Deletion
- **Smart Archiving**: Archive emails older than a specified threshold (e.g., "3y", "6m", "30d")
- **Incremental Mode**: Skip already-archived messages for efficient recurring runs
- **Safe Deletion Workflow**: Archive-only (default) → Trash (reversible) → Permanent (confirmed)
- **Batch Operations**: Efficient API usage with automatic rate limiting
- **Progress Tracking**: Real-time progress bars with ETA and processing rate

### 🔍 Search & Retrieval
- **Full-Text Search (FTS5)**: Gmail-style query syntax with BM25 ranking
- **Lightning Fast**: 0.85ms for 1000 messages (118x faster than target)
- **Message Extraction**: Extract individual messages by ID or from search results
- **Interactive Search**: Browse search results with a menu interface
- **Preview Mode**: See message snippets in search results
- **JSON Output**: All commands support `--json` for scripting

### 🗜️ Compression & Storage
- **Modern Compression**: zstd (fastest), lzma (smallest), gzip (compatible)
- **Post-hoc Compression**: Compress existing archives anytime
- **Transparent Decompression**: Read compressed archives without extraction
- **Smart Deduplication**: Remove duplicates across archives (100% precision)
- **Archive Consolidation**: Merge multiple archives with automatic sorting

### 🛡️ Safety & Validation
- **Multi-Layer Validation**: Message count, database cross-check, content integrity, spot-checks
- **Unified Health Check**: One command checks database, archives, auth, performance
- **Auto-Repair**: Automatic database repair with rollback support
- **Atomic Operations**: All writes are transactional (succeed or rollback)
- **Audit Trail**: Complete history of all operations

### ⚙️ Automation & Maintenance
- **Scheduled Health Checks**: Platform-native cron/Task Scheduler integration
- **Automatic Migration**: v1.0 → v1.1 → v1.2 schema upgrades with backup
- **Comprehensive Diagnostics**: Doctor command analyzes everything
- **Auto-Verification**: Optional validation after import/consolidate/dedupe
- **Performance Metrics**: Track search latency, database size, vacuum status

## 📦 Installation

### Prerequisites

- **Python 3.14+** ([Download here](https://www.python.org/downloads/))
- **Gmail Account** with email you want to archive

**Note**: OAuth2 credentials are bundled with the application. No manual Google Cloud setup required!

### Install from PyPI (Recommended)

```bash
pip install gmail-archiver-cli
```

Or use pipx for isolated installation:

```bash
pipx install gmail-archiver-cli
```

### Verify Installation

```bash
gmailarchiver --version
gmailarchiver --help
```

## 🚀 Quick Start

### First Run - OAuth2 Authorization

On first run, Gmail Archiver will automatically:

1. Open your browser to Google's authorization page
2. Ask you to sign in with your Google Account
3. Request permission to access Gmail
4. Save an authorization token to `~/.config/gmailarchiver/token.json`

### Basic Workflow

```bash
# 1. Preview what will be archived (dry run)
gmailarchiver archive 3y --dry-run

# 2. Archive emails older than 3 years with compression
gmailarchiver archive 3y --compress zstd
# → Creates: archive_20250123.mbox.zst

# Or use exact dates (v1.3.0+)
gmailarchiver archive 2024-01-01 --compress zstd
# → Archives all emails before January 1, 2024

# 3. Validate the archive
gmailarchiver validate archive_20250123.mbox.zst

# 4. Search your archives
gmailarchiver search "from:alice@example.com meeting"

# 5. Extract a message
gmailarchiver extract msg_123abc --output message.eml

# 6. Check overall health
gmailarchiver check

# 7. (Optional) Delete from Gmail after verification
gmailarchiver archive 3y --trash  # Reversible (30 days)
```

## 📖 Complete Command Reference

### 🗄️ Archive Management

#### Archive Command
Archive emails older than a specified age.

```bash
# Basic archiving
gmailarchiver archive 3y              # Archive emails older than 3 years
gmailarchiver archive 6m              # Archive emails older than 6 months
gmailarchiver archive 30d --dry-run   # Preview without archiving

# With compression (recommended)
gmailarchiver archive 3y --compress zstd    # zstd (fastest, best ratio)
gmailarchiver archive 3y --compress gzip    # gzip (most compatible)
gmailarchiver archive 3y --compress lzma    # lzma (smallest size)

# With deletion
gmailarchiver archive 3y --trash      # Move to trash (reversible for 30 days)
gmailarchiver archive 3y --delete     # Permanent delete (requires confirmation)

# Custom output
gmailarchiver archive 6m --output my_archive.mbox.zst --compress zstd

# JSON output for scripting
gmailarchiver archive 3y --json
```

**Age formats**: `3y` (years), `6m` (months), `2w` (weeks), `30d` (days)

#### Import Command
Import existing mbox archives into the database.

```bash
# Import single archive
gmailarchiver import old_archive.mbox

# Import compressed archives (auto-detected)
gmailarchiver import archive.mbox.gz
gmailarchiver import archive.mbox.zst

# Import multiple archives with glob
gmailarchiver import "archives/*.mbox.gz"

# Import with auto-verification
gmailarchiver import archive.mbox --auto-verify

# Import with custom account ID
gmailarchiver import external.mbox --account-id backup_2024

# JSON output
gmailarchiver import archive.mbox --json
```

**Performance**: 10,000+ messages per second

#### Consolidate Command
Merge multiple archives into one.

```bash
# Merge archives
gmailarchiver consolidate archive1.mbox archive2.mbox -o merged.mbox

# Merge with deduplication and compression
gmailarchiver consolidate *.mbox -o merged.mbox.zst \
  --dedupe-strategy newest --compress zstd

# Merge and remove source files after success
gmailarchiver consolidate src/*.mbox -o merged.mbox --remove-sources

# Merge with auto-verification
gmailarchiver consolidate *.mbox -o merged.mbox --auto-verify

# No sorting or deduplication
gmailarchiver consolidate *.mbox -o merged.mbox --no-sort --no-dedupe

# JSON output
gmailarchiver consolidate *.mbox -o merged.mbox --json
```

**Features**: Chronological sorting, deduplication, compression, atomic operations

#### Compress Command (v1.2.0+)
Compress existing archives with automatic database updates.

```bash
# Compress an archive
gmailarchiver compress archive.mbox --format zstd
# → Creates archive.mbox.zst and updates database

# Compress multiple archives
gmailarchiver compress archives/*.mbox --format zstd

# Keep original files
gmailarchiver compress archive.mbox --format gzip --keep-original

# Dry run (preview)
gmailarchiver compress archive.mbox --format zstd --dry-run

# JSON output
gmailarchiver compress archive.mbox --format zstd --json
```

**Compression formats**: `zstd` (recommended), `gzip`, `lzma`

### 🔍 Search & Retrieval

#### Search Command
Search archived messages with Gmail-style syntax.

```bash
# Basic search
gmailarchiver search "meeting notes"
gmailarchiver search "from:alice@example.com"
gmailarchiver search "subject:invoice after:2024-01-01"

# Search with filters
gmailarchiver search --from alice@example.com --subject report
gmailarchiver search --after 2024-01-01 --before 2024-12-31

# Limit results
gmailarchiver search "payment" --limit 50

# Show body preview (v1.2.0+)
gmailarchiver search "contract" --with-preview

# Interactive mode (v1.2.0+)
gmailarchiver search --interactive
# → Browse results, select messages, extract on demand

# Extract directly from search
gmailarchiver search "important email" --extract --output messages/

# JSON output
gmailarchiver search "invoice" --json
```

**Query syntax**:
- `from:user@example.com` - Search by sender
- `to:user@example.com` - Search by recipient
- `subject:meeting` - Search in subject
- `after:2024-01-01` - Messages after date
- `before:2024-12-31` - Messages before date
- Free text - Full-text search in body

**Performance**: 0.85ms for 1000 messages

#### Extract Command (v1.2.0+)
Extract individual messages from archives.

```bash
# Extract by Gmail ID
gmailarchiver extract msg_123abc
# → Outputs to stdout

# Extract to file
gmailarchiver extract msg_123abc --output message.eml

# Extract by RFC Message-ID
gmailarchiver extract "<abc123@example.com>" --output message.eml

# Extract from specific archive
gmailarchiver extract msg_123abc --archive archive.mbox.zst

# Batch extract
gmailarchiver extract msg_001 msg_002 msg_003 --output-dir messages/

# JSON output (includes message metadata)
gmailarchiver extract msg_123abc --json
```

**Features**: Works with compressed archives, supports batch operations

### 🏥 Health & Maintenance

#### Check Command (v1.2.0+)
Unified health check - runs all verification checks.

```bash
# Run all health checks
gmailarchiver check

# With auto-repair
gmailarchiver check --auto-repair

# JSON output
gmailarchiver check --json
```

**Checks performed**:
- ✓ Database integrity (schema, foreign keys, constraints)
- ✓ Database-mbox consistency (all messages accessible)
- ✓ Mbox offset accuracy (v1.1+ databases)
- ✓ FTS synchronization (search index up-to-date)

**Exit codes**: 0 = healthy, 1 = issues found, 2 = repair failed

#### Doctor Command (v1.2.0+)
Comprehensive diagnostics and health report.

```bash
# Full diagnostic report
gmailarchiver doctor

# JSON output
gmailarchiver doctor --json
```

**Diagnostics**:
- 📊 Database health (schema, size, vacuum status)
- 📦 Archive status (files, compression, accessibility)
- 🔐 Authentication (token validity, scopes, expiration)
- ⚡ Performance metrics (search latency)
- 💾 Disk space monitoring
- ✅ Actionable recommendations

#### Verification Commands

```bash
# Verify database integrity
gmailarchiver verify-integrity

# Verify database-mbox consistency
gmailarchiver verify-consistency archive.mbox.zst

# Verify mbox offset accuracy (v1.1+ only)
gmailarchiver verify-offsets archive.mbox.zst

# Validate archive file
gmailarchiver validate archive.mbox.zst

# All support --json
gmailarchiver verify-integrity --json
```

#### Repair Command

```bash
# Repair database (dry run - preview only)
gmailarchiver repair

# Actually repair database
gmailarchiver repair --no-dry-run

# Repair with offset backfilling (for migration issues)
gmailarchiver repair --backfill --no-dry-run

# JSON output
gmailarchiver repair --json
```

### 🔄 Deduplication

```bash
# Analyze duplicates (report only)
gmailarchiver dedupe-report

# Remove duplicates with strategy
gmailarchiver dedupe --strategy newest    # Keep newest copy
gmailarchiver dedupe --strategy largest   # Keep largest copy
gmailarchiver dedupe --strategy first     # Keep first found

# With auto-verification (v1.2.0+)
gmailarchiver dedupe --auto-verify --no-dry-run

# Dry run (preview)
gmailarchiver dedupe --dry-run

# JSON output
gmailarchiver dedupe-report --json
```

**Deduplication**: 100% precision via RFC Message-ID matching

### ⏰ Automation (v1.2.0+)

#### Schedule Command
Set up automated maintenance with platform-native scheduling.

```bash
# Schedule nightly health checks (2 AM daily)
gmailarchiver schedule check --cron "0 2 * * *"

# Schedule weekly checks (Sunday 3 AM)
gmailarchiver schedule check --cron "0 3 * * 0"

# List scheduled jobs
gmailarchiver schedule list

# View logs
gmailarchiver schedule logs
gmailarchiver schedule logs --tail 50

# Disable scheduling
gmailarchiver schedule disable check

# JSON output
gmailarchiver schedule list --json
```

**Platform support**:
- **Linux/macOS**: Uses cron
- **Windows**: Uses Task Scheduler
- Logs to: `~/.gmailarchiver/logs/check-YYYY-MM-DD.log`

### 📊 Status & Information

```bash
# Show archiving statistics
gmailarchiver status

# Show database schema and stats
gmailarchiver db-info

# Both support --json
gmailarchiver status --json
gmailarchiver db-info --json
```

### 🔐 Authentication

```bash
# Reset authentication (revoke and delete token)
gmailarchiver auth-reset

# Use custom credentials file
gmailarchiver archive 3y --credentials my_credentials.json
```

### 📈 Migration

```bash
# Migrate v1.0 → v1.1 (automatic on first v1.1+ run)
gmailarchiver migrate

# Rollback to backup (if migration fails)
gmailarchiver rollback --backup-file archive_state.db.backup.YYYYMMDD_HHMMSS
```

## 🎨 JSON Mode for Scripting

All commands support `--json` flag for machine-readable output:

```bash
# Get status as JSON
gmailarchiver status --json

# Search and process results
gmailarchiver search "invoice" --json | jq '.results[] | .subject'

# Check health and parse results
gmailarchiver check --json | jq '.checks[] | select(.status == "failed")'

# Extract and parse message metadata
gmailarchiver extract msg_123 --json | jq '.headers'
```

## 🎯 Common Workflows

### Complete Archival Workflow

```bash
# 1. Preview
gmailarchiver archive 3y --dry-run

# 2. Archive with compression
gmailarchiver archive 3y --compress zstd

# 3. Verify health
gmailarchiver check

# 4. Search to verify
gmailarchiver search "after:2024-01-01"

# 5. Delete from Gmail (after verification)
gmailarchiver archive 3y --trash
```

### Import and Consolidate

```bash
# 1. Import multiple archives
gmailarchiver import "old_archives/*.mbox.gz" --auto-verify

# 2. Check for duplicates
gmailarchiver dedupe-report

# 3. Consolidate with deduplication
gmailarchiver consolidate *.mbox -o master.mbox.zst \
  --dedupe-strategy newest --remove-sources

# 4. Verify final archive
gmailarchiver check
```

### Search and Extract

```bash
# 1. Search with preview
gmailarchiver search "contract" --with-preview

# 2. Extract specific message
gmailarchiver extract msg_123abc --output contract.eml

# 3. Or use interactive mode
gmailarchiver search --interactive
```

### Automated Maintenance

```bash
# 1. Set up nightly health checks
gmailarchiver schedule check --cron "0 2 * * *"

# 2. View scheduled jobs
gmailarchiver schedule list

# 3. Check logs
gmailarchiver schedule logs --tail 50

# 4. Run manual diagnostics
gmailarchiver doctor
```

## 📊 Performance

| Operation | Dataset | Time | Rate |
|-----------|---------|------|------|
| Search (metadata) | 1,000 messages | 0.85ms | 1.2M msg/s |
| Search (full-text) | 1,000 messages | 45ms | 22K msg/s |
| Import | 10,000 messages | <1s | 10K+ msg/s |
| Consolidate | 10,000 messages | 3.57s | 2.8K msg/s |
| Extract | Single message | <10ms | N/A |

## 🔒 Security & Privacy

- **OAuth2 Flow**: Industry-standard authentication
- **Scopes**: Minimum required permissions (gmail.modify for deletion)
- **Token Storage**: XDG-compliant paths (`~/.config/gmailarchiver/`)
- **Local Storage**: All data stored locally, no cloud dependencies
- **Audit Trail**: Complete operation history in database
- **Safe Deletion**: Trash-first workflow with 30-day recovery window

## 📚 Additional Documentation

- [Architecture Documentation](docs/ARCHITECTURE.md) - System design and technical details
- [Migration Guide](MIGRATION_GUIDE.md) - Upgrading from v1.0.x
- [Contributing Guide](CONTRIBUTING.md) - Development setup and guidelines
- [Changelog](CHANGELOG.md) - Version history and release notes

## 📜 Version History

### v1.3.2 (2025-11-24) - Critical Bug Fix

**Bug Fixes**:
- Fixed UNIQUE constraint failures during archiving (messages with duplicate RFC Message-IDs)
- Improved duplicate detection to check `rfc_message_id` before writing to mbox
- Eliminated orphaned messages in mbox files

**Quality**: 1072 tests, 93% coverage maintained

### v1.3.1 (2025-11-24) - Live Layout Infrastructure

**Internal Features**:
- Added LogBuffer, SessionLogger, and LiveLayoutContext for flicker-free progress tracking
- Enhanced OutputManager with live layout support

**Quality**: 1071 tests, 93% coverage

### v1.2.0 (2025-11-23) - Ergonomics & Automation

**Major Features**:
- Unified OutputManager with Rich output and JSON mode
- 5 new commands: extract, check, schedule, compress, doctor
- Progress bars with ETA and rate tracking
- Search enhancements (--with-preview, --interactive)
- Auto-verification flags (--auto-verify)
- Cleanup options (--remove-sources)

**Test Coverage**: 989 tests, 93% coverage

### v1.1.0 (2025-11-15) - Search & Management

**Major Features**:
- FTS5 full-text search with Gmail-style syntax
- Import existing archives (10K+ msg/s)
- Deduplication (100% precision)
- Archive consolidation
- Enhanced database schema (v1.1)

**Test Coverage**: 650 tests, 96% coverage

### v1.0.x - Initial Releases

- Core archiving functionality
- Multi-layer validation
- Safe deletion workflows
- Compression support (gzip, lzma, zstd)

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development environment setup
- Testing guidelines
- Code quality standards
- Pull request process

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with Python 3.14 and modern type checking
- Uses Gmail API for email access
- Rich library for beautiful terminal output
- SQLite FTS5 for full-text search
- Python mbox for email archive handling

## 📧 Support

- **Issues**: [GitHub Issues](https://github.com/tumma72/GMailArchiver/issues)
- **Documentation**: [docs/](docs/)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)

---

**Made with ❤️ for email power users who value privacy, control, and local data ownership.**
