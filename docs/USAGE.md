# Gmail Archiver Usage Guide

Complete reference documentation for all Gmail Archiver commands, options, and workflows.

## Table of Contents

- [Archive Management](#archive-management)
- [Search & Retrieval](#search--retrieval)
- [Health & Maintenance](#health--maintenance)
- [Deduplication](#deduplication)
- [Automation](#automation)
- [Status & Information](#status--information)
- [Authentication](#authentication)
- [Migration](#migration)
- [JSON Mode for Scripting](#json-mode-for-scripting)
- [Common Workflows](#common-workflows)

---

## Archive Management

### archive - Archive Gmail Messages

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

**Age formats**: `3y` (years), `6m` (months), `2w` (weeks), `30d` (days), or ISO date `2024-01-01`

---

### import - Import Existing Archives

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

---

### consolidate - Merge Archives

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

---

### compress - Post-hoc Compression

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

---

## Search & Retrieval

### search - Search Messages

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

# Show body preview
gmailarchiver search "contract" --with-preview

# Interactive mode
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

---

### extract - Extract Messages

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

---

## Health & Maintenance

### check - Unified Health Check

Runs all verification checks in one command.

```bash
# Run all health checks
gmailarchiver check

# With verbose output
gmailarchiver check --verbose

# With auto-repair
gmailarchiver check --auto-repair

# JSON output
gmailarchiver check --json
```

**Checks performed**:
- Database integrity (schema, foreign keys, constraints)
- Database-mbox consistency (all messages accessible)
- Mbox offset accuracy (v1.1+ databases)
- FTS synchronization (search index up-to-date)

**Exit codes**: 0 = healthy, 1 = issues found, 2 = repair failed

---

### doctor - Comprehensive Diagnostics

Full system diagnostics and health report focusing on external environment.

```bash
# Full diagnostic report
gmailarchiver doctor

# Include internal database checks (same as 'gmailarchiver check')
gmailarchiver doctor --check

# Automatically fix fixable issues
gmailarchiver doctor --fix

# JSON output
gmailarchiver doctor --json
```

**Diagnostics**:
- Database health (schema, size, vacuum status)
- Archive status (files, compression, accessibility)
- Authentication (token validity, scopes, expiration)
- Performance metrics (search latency)
- Disk space monitoring
- Actionable recommendations

**Note**: `doctor` focuses on external/environment checks. For internal database health, use `check` or add `--check` flag.

---

### Verification Commands

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

---

### repair - Database Repair

```bash
# Repair database (dry run - preview only, default)
gmailarchiver repair

# Actually repair database (requires explicit flag)
gmailarchiver repair --no-dry-run

# Preview repairs without making changes
gmailarchiver repair --dry-run

# Repair with offset backfilling (for migration issues)
gmailarchiver repair --backfill --no-dry-run

# Dry-run with verbose output
gmailarchiver repair --dry-run --verbose

# JSON output
gmailarchiver repair --json
```

---

## Deduplication

```bash
# Analyze duplicates (preview mode, no changes)
gmailarchiver dedupe --dry-run

# Remove duplicates with strategy
gmailarchiver dedupe --strategy newest --no-dry-run    # Keep newest copy
gmailarchiver dedupe --strategy largest --no-dry-run   # Keep largest copy
gmailarchiver dedupe --strategy first --no-dry-run     # Keep first found

# With auto-verification
gmailarchiver dedupe --auto-verify --no-dry-run

# JSON output
gmailarchiver dedupe --dry-run --json
```

**Deduplication**: 100% precision via RFC Message-ID matching

---

## Automation

### schedule - Automated Maintenance

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

---

## Status & Information

```bash
# Show archiving statistics (includes schema version and database size)
gmailarchiver status

# Show more detail with verbose mode
gmailarchiver status --verbose

# JSON output for scripting
gmailarchiver status --json
```

The `--verbose` flag shows additional detail:
- Full query column in archive runs table
- 10 most recent runs (instead of 5)
- More detailed statistics

---

## Authentication

```bash
# Reset authentication (revoke and delete token)
gmailarchiver auth-reset

# Use custom credentials file
gmailarchiver archive 3y --credentials my_credentials.json
```

---

## Migration

```bash
# Migrate v1.0 → v1.1 (automatic on first v1.1+ run)
gmailarchiver migrate

# Rollback to backup (if migration fails)
gmailarchiver rollback --backup-file archive_state.db.backup.YYYYMMDD_HHMMSS
```

---

## Utilities

Maintenance tools accessible via the `utilities` subcommand:

```bash
# Retry deletion for archived messages
gmailarchiver utilities retry-delete archive_20250123.mbox.zst

# Permanent deletion (requires confirmation)
gmailarchiver utilities retry-delete archive.mbox.zst --permanent
```

---

## JSON Mode for Scripting

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

---

## Common Workflows

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
gmailarchiver dedupe --dry-run

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

---

## Performance Reference

| Operation | Dataset | Time | Rate |
|-----------|---------|------|------|
| Search (metadata) | 1,000 messages | 0.85ms | 1.2M msg/s |
| Search (full-text) | 1,000 messages | 45ms | 22K msg/s |
| Import | 10,000 messages | <1s | 10K+ msg/s |
| Consolidate | 10,000 messages | 3.57s | 2.8K msg/s |
| Extract | Single message | <10ms | N/A |

---

## Related Documentation

- [README.md](../README.md) - Quick start and installation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design and technical details
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development setup and guidelines
- [CHANGELOG.md](../CHANGELOG.md) - Version history and release notes
