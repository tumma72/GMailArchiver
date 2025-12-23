<img width="805" height="629" alt="GMailArchiver-logo" src="https://github.com/user-attachments/assets/cc41a36d-ca9e-46bb-a30a-727821e4427d" />

# GMailArchiver
[![PyPI version](https://img.shields.io/pypi/v/gmail-archiver-cli.svg)](https://pypi.org/project/gmail-archiver-cli/)
[![Version](https://img.shields.io/github/v/release/tumma72/GMailArchiver)](https://github.com/tumma72/GMailArchiver/releases)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://github.com/tumma72/GMailArchiver/workflows/Tests/badge.svg)](https://github.com/tumma72/GMailArchiver/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/bfb62663af32da529734c79e0e67fa23/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)

**A professional-grade email archival, search, and management solution for Gmail** - Archive, compress, search, extract, and maintain your email history with confidence.

## 🎉 What's New in v1.5.2 - Quality & Coverage

Version 1.5.2 raises the quality bar with comprehensive test coverage improvements:

- 🧪 **95% Test Coverage** - Enforced minimum threshold with 3,195 tests
- ✅ **Zero Warnings** - All deprecation warnings resolved
- 🔧 **Protocol Exclusions** - Interface-only code properly excluded from coverage
- 📝 **Error Path Testing** - Complete coverage of CLI error handling paths
- 🏗️ **Quality Gates** - Stricter coverage requirements in CI/CD

### Recent Major Features

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
- **Production-ready**: 3,195 automated tests, 95% code coverage, strict type safety

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

## 📖 Command Reference

For complete command documentation with all options, see **[docs/USAGE.md](docs/USAGE.md)**.

### Quick Reference

| Category | Commands |
|----------|----------|
| **Archiving** | `archive`, `import`, `consolidate`, `compress` |
| **Search** | `search`, `extract` |
| **Health** | `check`, `doctor`, `verify-integrity`, `repair` |
| **Maintenance** | `dedupe`, `status`, `schedule` |
| **Auth** | `auth-reset`, `migrate`, `rollback` |

### Key Commands

```bash
# Archive emails older than 3 years with compression
gmailarchiver archive 3y --compress zstd

# Search archived messages
gmailarchiver search "from:alice@example.com subject:meeting"

# Extract a specific message
gmailarchiver extract msg_123abc --output message.eml

# Run all health checks
gmailarchiver check

# Show status with database info
gmailarchiver status --verbose

# Full diagnostics
gmailarchiver doctor
```

All commands support `--json` for scripting and `--help` for detailed options.

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

- [Usage Guide](docs/USAGE.md) - Complete command reference with all options
- [Architecture Documentation](docs/ARCHITECTURE.md) - System design and technical details
- [Migration Guide](MIGRATION_GUIDE.md) - Upgrading from v1.0.x
- [Contributing Guide](CONTRIBUTING.md) - Development setup and guidelines
- [Changelog](CHANGELOG.md) - Version history and release notes

## 📜 Version History

### v1.5.2 (2025-12-23) - Quality & Coverage

**Test Coverage Improvements**:
- Raised minimum coverage threshold from 90% to 95%
- Added 59 new tests for CLI command coverage (schedule, verify, repair)
- Total: 3,195 tests passing with zero warnings
- Protocol classes excluded from coverage (interface-only code)

**Bug Fixes**:
- Fixed Python 3.14 deprecation warnings from mailbox module
- Resolved all linting and formatting issues

**Quality**: 3,195 tests, 95% coverage (enforced minimum)

### v1.5.0 (2025-12-21) - Architecture Modernization

**Internal Refactoring** (No user-facing changes):
- Refactored all 5 primary commands (archive, verify, migrate, repair, consolidate) to WorkflowComposer + Steps pattern
- Created 27 reusable step classes for single-responsibility component design
- Added 315+ new tests using TDD methodology
- Maintained 96% test coverage and 2,897 passing tests
- All quality gates passing (ruff, mypy, zero warnings)

**Benefits**:
- Foundation for future GUI/API interfaces
- Improved maintainability and debuggability
- Easier to add new features with composable steps
- Better error handling and reporting

**No Breaking Changes**:
- All CLI interfaces remain identical
- All commands work exactly as before
- Performance maintained (all async operations preserved)

### v1.4.5 (2025-12-05) - Performance Fix + CI/Publishing Repairs

**Complete Fix for O(n²) Performance Bottleneck** (from v1.4.3):
- 500-1000x faster for large archives (O(n) complexity instead of O(n²))
- Single mbox open/close cycle per batch (not per-message)
- Removed deprecated `archive_message()` method to prevent future misuse
- Progress callbacks for real-time tracking during batch operations
- Graceful interrupt handling (Ctrl+C saves progress for resumable operations)

**CI/Publishing Fixes**:
- Configured PyPI Trusted Publishing for secure releases
- Fixed doctor diagnostics test mock target
- Fixed session logger cleanup file ordering

**Quality**: 1569 tests, 94% coverage (all passing in CI)

### v1.4.2 (2025-12-01) - Performance & Architecture

**Performance**:
- 2x faster archiving (batch_delay: 1.0s → 0.5s)
- Optimized Gmail API batching for 10-15 msg/sec practical throughput

**Architecture**:
- Completed facade pattern migration for all CLI commands
- Removed 9 legacy module files
- All tests updated to use facade APIs

**Bug Fixes**:
- Fixed progress bars not updating during import and verify-integrity commands

**Quality**: 1570 tests, 94% coverage (+182 tests from v1.4.1)

### v1.3.2 (2024-11-24) - Critical Bug Fix

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
