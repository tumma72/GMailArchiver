# Gmail Archiver

[![Version](https://img.shields.io/github/v/release/tumma72/GMailArchiver)](https://github.com/tumma72/GMailArchiver/releases)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://github.com/tumma72/GMailArchiver/workflows/Tests/badge.svg)](https://github.com/tumma72/GMailArchiver/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/bfb62663af32da529734c79e0e67fa23/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)

A powerful CLI tool to archive old Gmail messages to local mbox files with validation, compression, and safe deletion.

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
