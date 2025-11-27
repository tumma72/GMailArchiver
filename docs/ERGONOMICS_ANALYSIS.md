# Gmail Archiver: Ergonomics & Usability Analysis

**Date**: 2025-11-19
**Status**: Analysis Complete
**Purpose**: Identify usability improvements to existing CLI before adding new features

---

## Executive Summary

Gmail Archiver v1.1.0 has **excellent technical architecture** (atomic operations, data integrity, comprehensive validation), but has **ergonomic gaps** that make it harder to use than necessary. This analysis identifies high-impact improvements that enhance user experience without adding complexity.

### Key Findings

1. ✅ **Search works perfectly with compressed archives** (database-only, no decompression needed)
2. ❌ **No way to retrieve/extract full messages** after searching (search returns pointers only)
3. ❌ **Validation is manual** (users must remember to run verify commands)
4. ❌ **No automatic maintenance** (no cron jobs, no scheduled checks)
5. ❌ **Multiple commands needed for common workflows** (import → verify → repair requires 3+ commands)

---

## Current Command Architecture

### Complete Workflows (✅ Well-Designed)

These commands handle entire workflows start-to-finish:

**`archive`**: Gmail → mbox → database → validate → (optional) delete/compress
- Atomic via HybridStorage
- Auto-validation built-in
- Clear user prompts for destructive actions
- **This is the gold standard**

**`import`**: mbox file(s) → parse → database → summary
- Auto-migration v1.0 → v1.1
- Handles glob patterns
- Deduplication support
- ⚠️ Missing: Auto-verification after import

**`consolidate`**: multiple mbox → single mbox → database update
- Atomic operations
- Optional sort + dedupe
- ⚠️ Missing: Option to remove source files after success

### Atomic Operations (✅ Single Purpose)

These do one thing well:

**Search & Query**:
- `search`: Query database (metadata + FTS5)
- `status`: Show statistics (includes schema version and database size)

**Validation** (All manual, no automation):
- `verify-integrity`: Check database health
- `verify-consistency`: Deep consistency check
- `verify-offsets`: Verify mbox offset accuracy
- `repair`: Fix database issues

**Data Operations**:
- `dedupe`: Remove duplicates
- `validate`: Verify archive file
- `retry-delete`: Retry Gmail deletion

**Maintenance**:
- `migrate`: v1.0 → v1.1 schema upgrade
- `rollback`: Restore from backup
- `auth-reset`: Clear OAuth token

### Missing Commands

**Critical Gap**: No message extraction/retrieval
- Search returns `(gmail_id, mbox_offset, archive_file)` but can't extract message
- User must manually decompress + seek with external tools

---

## Detailed Analysis

### 1. Search Works with Compressed Archives ✅

**How it works**:
```python
# search.py only queries SQLite, never touches mbox files
SELECT m.gmail_id, m.subject, m.from_addr, m.to_addr,
       m.body_preview, m.archive_file, m.mbox_offset
FROM messages m
JOIN messages_fts fts ON m.rowid = fts.rowid
WHERE messages_fts MATCH ?
```

**Implications**:
- ✅ Compressed archives (`archive.mbox.gz`, `archive.mbox.zst`) work perfectly
- ✅ No decompression needed for search
- ✅ Database is independent of archive format
- ❌ But users might think they need to decompress to search

**Documentation needed**: Clarify that compression doesn't affect search performance.

### 2. No Message Retrieval After Search ❌

**Current workflow breaks down**:
```bash
# User searches successfully
$ gmailarchiver search "important contract"

# Results show:
# gmail_id: abc123
# subject: "Important contract - sign today"
# archive_file: /archives/2024.mbox.zst
# mbox_offset: 1234567

# Now what? User can't:
# - View the full message
# - Extract to .eml file
# - Forward to email client
```

**Required**: `extract` command to complete the workflow.

### 3. Validation Not Automatic ❌

**Current manual workflow**:
```bash
# User imports archives
$ gmailarchiver import archives/*.mbox.gz
# ✓ Import complete: 10,000 messages

# Must manually verify (easy to forget!)
$ gmailarchiver verify-integrity
# ❌ Found 150 messages with invalid offsets

# Must manually repair
$ gmailarchiver repair --no-dry-run
# ✓ Repaired 150 records

# Should verify repair worked
$ gmailarchiver verify-integrity
# ✓ No issues found
```

**Problem**: Requires user to remember 4 separate commands.

**Solution**: Auto-verification flags or meta-commands.

### 4. No Scheduled Maintenance ❌

**Current state**:
- Users must remember to run `verify-integrity` periodically
- No cron job creation
- No logging of check results
- Database issues may go unnoticed for months

**Needed**: Scheduled health checks with logging.

### 5. No Workflow Shortcuts ❌

**Common user workflows that require multiple commands**:

#### Workflow A: Import + Verify
```bash
gmailarchiver import archives/*.mbox.gz
gmailarchiver verify-integrity
gmailarchiver repair --no-dry-run  # if issues found
gmailarchiver verify-integrity     # verify fix
```
**Should be**: `gmailarchiver import archives/*.mbox.gz --auto-verify`

#### Workflow B: Periodic Health Check
```bash
gmailarchiver verify-integrity
gmailarchiver verify-consistency archive.mbox
gmailarchiver verify-offsets archive.mbox
```
**Should be**: `gmailarchiver check` (runs all verifications)

#### Workflow C: Search + Extract
```bash
gmailarchiver search "important contract"
# Copy gmail_id from results
gmailarchiver extract abc123 > message.eml
```
**Should be**: `gmailarchiver search "important contract" --extract`

---

## Proposed Improvements

### Tier 1: Critical (Complete Essential Workflows)

#### 1. `extract` Command - Message Retrieval

**Priority**: 🔴 CRITICAL
**Effort**: Medium (2-3 days)
**Impact**: High (completes search workflow)

```bash
# Extract single message by gmail_id
gmailarchiver extract <gmail-id>
# Output: Full message to stdout (can pipe to email client)

# Extract to file
gmailarchiver extract <gmail-id> --output message.eml

# Extract all search results
gmailarchiver search "query" | gmailarchiver extract --batch --output folder/

# Extract with decompression support
gmailarchiver extract abc123 --archive archive.mbox.zst
# Transparently handles compressed archives
```

**Implementation notes**:
- Use `mbox_offset` and `mbox_length` from database
- Support all compression formats (gzip, lzma, zstd)
- Output formats: raw email, .eml, JSON
- Handles decompression automatically

#### 2. `check` Meta-Command - One-Stop Health Check

**Priority**: 🔴 CRITICAL
**Effort**: Low (1 day)
**Impact**: High (simplifies maintenance)

```bash
# Run all verification checks
gmailarchiver check

# Output:
# ✓ Database integrity: OK
# ✓ Database consistency: OK
# ✓ Offset accuracy: 100% (16,132/16,132)
# ✓ FTS index: Synchronized
# Overall: HEALTHY

# With issues found:
gmailarchiver check

# Output:
# ❌ Database integrity: 150 invalid offsets
# ✓ Database consistency: OK
# ❌ Offset accuracy: 99.1% (15,982/16,132)
#
# Run 'gmailarchiver repair --backfill --no-dry-run' to fix
# Or run with --auto-repair to fix automatically

# Auto-repair mode
gmailarchiver check --auto-repair
```

**Runs**:
1. `verify-integrity`
2. `verify-consistency` (if archive file exists)
3. `verify-offsets` (if v1.1 database)
4. FTS synchronization check

**Features**:
- Consolidated output (single health report)
- Optional `--auto-repair` flag
- Exit codes: 0 = healthy, 1 = issues found, 2 = repair failed

#### 3. Auto-Verification Flags

**Priority**: 🟡 HIGH
**Effort**: Low (1 day)
**Impact**: Medium (prevents issues)

```bash
# Import with auto-verification
gmailarchiver import archives/*.mbox.gz --auto-verify

# Consolidate with auto-verification
gmailarchiver consolidate src/*.mbox -o merged.mbox --auto-verify

# Dedupe with auto-verification
gmailarchiver dedupe --no-dry-run --auto-verify
```

**Behavior**:
- Runs appropriate verification after operation
- Shows verification results
- Offers to auto-repair if issues found

---

### Tier 2: High Value (Convenience & Automation)

#### 4. `schedule` Command - Automated Maintenance

**Priority**: 🟡 HIGH
**Effort**: Medium (3-4 days)
**Impact**: High (prevents long-term issues)

```bash
# Schedule nightly checks
gmailarchiver schedule check --cron "0 2 * * *"

# Output:
# ✓ Created cron job: Daily health check at 2:00 AM
# Logs: ~/.gmailarchiver/logs/check-YYYY-MM-DD.log
#
# To view schedule: gmailarchiver schedule list
# To disable: gmailarchiver schedule disable check

# List scheduled jobs
gmailarchiver schedule list

# View recent logs
gmailarchiver schedule logs --tail 50
```

**Implementation**:
- Platform-specific: crontab (Linux/macOS), Task Scheduler (Windows)
- Logs to `~/.gmailarchiver/logs/`
- Email notifications on failure (optional)
- Graceful handling if cron not available

#### 5. `compress` Command - Post-Hoc Compression

**Priority**: 🟡 HIGH
**Effort**: Medium (2 days)
**Impact**: Medium (user convenience)

```bash
# Compress existing archive
gmailarchiver compress archive.mbox --format zstd

# Output:
# Compressing archive.mbox → archive.mbox.zst
# Original: 2.3 GB
# Compressed: 487 MB (78.8% savings)
# Updating database paths...
# ✓ Compression complete

# Batch compress
gmailarchiver compress archives/*.mbox --format zstd
```

**Features**:
- Updates database `archive_file` paths atomically
- Validates before deleting original
- Supports all formats: gzip, lzma, zstd
- Optional `--keep-original` flag

#### 6. `doctor` Command - Comprehensive Diagnostics

**Priority**: 🟢 MEDIUM
**Effort**: Medium (2-3 days)
**Impact**: Medium (troubleshooting)

```bash
gmailarchiver doctor

# Output:
# 🔍 Gmail Archiver Health Check
#
# Database:
#   ✓ Schema version: 1.1
#   ✓ Integrity: OK
#   ✓ FTS index: Synchronized
#   ✓ Size: 245 MB
#
# Archives:
#   ✓ Total: 3 files
#   ⚠ Missing: /archives/old.mbox (referenced by 150 messages)
#   ✓ Disk space: 1.2 TB available
#
# Authentication:
#   ✓ OAuth token: Valid
#   ✓ Scopes: Full Gmail access
#   ✓ Expires: 2025-12-15
#
# Performance:
#   ✓ Search (metadata): 12ms
#   ✓ Search (FTS): 45ms
#   ✓ Database vacuum: Last run 5 days ago
#
# Recommendations:
#   • Run 'gmailarchiver verify-integrity' to check for orphaned records
#   • Archive file 'old.mbox' is missing - restore from backup or run repair
```

**Checks**:
- Database health (integrity, size, vacuum status)
- Archive files (existence, accessibility, compression)
- Authentication (token validity, scopes)
- Disk space
- Performance metrics
- Orphaned records

---

### Tier 3: Polish (Nice-to-Have)

#### 7. Search Enhancements

```bash
# Show body preview in results
gmailarchiver search "query" --with-preview

# Extract all results
gmailarchiver search "query" --extract --output folder/

# Interactive search
gmailarchiver search --interactive
# Prompts for query, shows results, allows extraction
```

#### 8. Cleanup Options

```bash
# Remove source files after consolidation
gmailarchiver consolidate src/*.mbox -o merged.mbox --remove-sources

# Vacuum database after operations
gmailarchiver dedupe --no-dry-run --vacuum
```

#### 9. Progress Estimation

```bash
gmailarchiver archive 3y
# Archiving: 1234/5678 messages (21%, ETA: 8m 42s)
# Speed: 2.5 messages/second
```

---

## Implementation Priority

### Phase 1: Complete Essential Workflows (1-2 weeks)
1. `extract` command (3 days)
2. `check` meta-command (1 day)
3. `--auto-verify` flags (1 day)

**Outcome**: Users can search → extract, and maintain database health easily.

### Phase 2: Automation & Convenience (1-2 weeks)
4. `schedule` command (4 days)
5. `compress` command (2 days)
6. `doctor` command (3 days)

**Outcome**: Maintenance is automated, users get comprehensive diagnostics.

### Phase 3: Polish (ongoing)
7. Search enhancements
8. Cleanup options
9. Progress estimation

**Outcome**: Incremental UX improvements.

---

## Success Metrics

### User Experience
- ✅ Complete search → extract workflow in < 3 commands (currently impossible)
- ✅ Maintenance reduced from 4+ commands to 1 (`check`)
- ✅ Zero-configuration scheduled checks (set once, forget)

### Error Prevention
- ✅ Auto-verification prevents corrupted imports
- ✅ Scheduled checks catch issues early
- ✅ `doctor` command helps troubleshoot faster

### Documentation Clarity
- ✅ Users understand compressed archives work with search
- ✅ Clear "getting started" workflow
- ✅ Troubleshooting guide references `doctor` command

---

## Next Steps

1. **Review & Prioritize**: Confirm which improvements to implement first
2. **Update PLAN.md**: Reflect completed Phase 0, add ergonomic improvements as v1.2
3. **Implement Phase 1**: Extract, check, auto-verify (highest ROI)
4. **User Testing**: Get feedback on new commands
5. **Iterate**: Refine based on real-world usage

---

**End of Ergonomics Analysis**
