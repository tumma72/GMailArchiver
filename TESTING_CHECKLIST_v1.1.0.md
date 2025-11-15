# Gmail Archiver v1.1.0 - End-to-End Testing Checklist

**Build Date**: 2025-11-15
**Version**: 1.1.0
**Build Files**:
- `dist/gmailarchiver-1.1.0-py3-none-any.whl` (75K)
- `dist/gmailarchiver-1.1.0.tar.gz` (227K)

## Pre-Testing Setup

### 1. Install from Wheel
```bash
# Install from built wheel
pip install dist/gmailarchiver-1.1.0-py3-none-any.whl

# Verify version
gmailarchiver db-info  # Should show schema version
python -c "import gmailarchiver._version; print(gmailarchiver._version.__version__)"
# Expected: 1.1.0
```

### 2. Verify Installation
- [ ] `gmailarchiver --version` shows `Gmail Archiver version 1.1.0`
- [ ] `gmailarchiver -v` also works (short flag)
- [ ] `gmailarchiver --help` shows all 17 commands
- [ ] OAuth credentials bundled at `gmailarchiver/config/oauth_credentials.json`
- [ ] No import errors when loading modules

---

## Core Functionality Tests

### 3. Authentication (auth.py)
```bash
# Test OAuth flow
gmailarchiver auth-reset  # Should revoke and delete token
gmailarchiver archive 1d --dry-run  # Should trigger OAuth flow

# Verify
ls ~/.config/gmailarchiver/token.json  # Should exist after auth
```

**Expected Behavior**:
- [ ] Browser opens for OAuth authorization
- [ ] Token saved to `~/.config/gmailarchiver/token.json`
- [ ] Subsequent runs use saved token (no browser)
- [ ] Token refresh works for expired tokens

### 4. Database Operations

#### 4.1 db-info Command
```bash
gmailarchiver db-info
```

**Expected Output**:
- [ ] Shows schema version (should be 1.1)
- [ ] Displays statistics (message count, archive count)
- [ ] Shows database path

#### 4.2 Migration (if you have v1.0 database)
```bash
# Backup your v1.0 database first!
cp ~/.local/share/gmailarchiver/archives.db ~/.local/share/gmailarchiver/archives.db.backup

# Trigger migration
gmailarchiver db-info  # Auto-migrates if v1.0 detected

# Verify
gmailarchiver verify-integrity  # Should pass
```

**Expected Behavior**:
- [ ] Automatic backup created at `archives.db.backup_v1.0`
- [ ] Migration completes successfully
- [ ] All message data preserved
- [ ] FTS5 index created and populated

#### 4.3 Rollback (test with caution!)
```bash
# Only if you have a backup
gmailarchiver rollback
```

---

## Archiving Workflow

### 5. Archive Command (Dry Run)
```bash
gmailarchiver archive 1w --dry-run --output /tmp/test_archive.mbox
```

**Expected Behavior**:
- [ ] Lists messages that would be archived
- [ ] Shows count and size estimates
- [ ] Does NOT actually archive or delete
- [ ] No changes to Gmail or local files

### 6. Archive Command (Actual)
```bash
# Archive messages older than 1 day (small test)
gmailarchiver archive 1d --output /tmp/test_archive.mbox
```

**Expected Behavior**:
- [ ] Fetches messages from Gmail
- [ ] Shows progress bar with Rich formatting
- [ ] Creates mbox file at specified path
- [ ] Records messages in database
- [ ] Does NOT delete (by default)

### 7. Archive with Compression
```bash
gmailarchiver archive 1d --output /tmp/test.mbox.gz --compression gzip
gmailarchiver archive 1d --output /tmp/test.mbox.xz --compression lzma
gmailarchiver archive 1d --output /tmp/test.mbox.zst --compression zstd
```

**Expected Behavior**:
- [ ] Creates compressed archives
- [ ] File sizes significantly smaller than uncompressed
- [ ] Database records correct archive file path (with extension)

---

## Validation

### 8. Validate Command
```bash
gmailarchiver validate /tmp/test_archive.mbox
```

**Expected Output**:
- [ ] Message count matches
- [ ] Database cross-check passes
- [ ] Content integrity verified
- [ ] Spot-check sampling passes

### 9. Verify-Integrity Command
```bash
gmailarchiver verify-integrity
```

**Expected Output**:
- [ ] Checks for orphaned FTS records
- [ ] Checks for missing FTS records
- [ ] Checks for invalid mbox offsets
- [ ] Checks for duplicate Message-IDs
- [ ] Checks for missing archive files
- [ ] Exit code 0 if clean, 1 if issues found

### 10. Verify-Offsets Command (v1.1 only)
```bash
gmailarchiver verify-offsets /tmp/test_archive.mbox
```

**Expected Output**:
- [ ] Validates mbox offset accuracy
- [ ] Shows pass/fail for each message
- [ ] Reports statistics

---

## Search Functionality

### 11. Search Command
```bash
# Basic search
gmailarchiver search "from:example.com"

# Date range search
gmailarchiver search "after:2024/01/01 before:2024/12/31"

# Subject search
gmailarchiver search "subject:important"

# Combined filters
gmailarchiver search "from:boss@company.com subject:urgent"
```

**Expected Behavior**:
- [ ] Returns matching messages
- [ ] Shows subject, from, to, date
- [ ] Results sorted by relevance (BM25)
- [ ] Fast performance (<10ms for 1000 messages)

---

## Import & Consolidation

### 12. Import Command
```bash
# Create a test mbox file first (or use existing archive)
gmailarchiver import /tmp/existing_archive.mbox
gmailarchiver import /tmp/*.mbox  # Glob pattern support
```

**Expected Behavior**:
- [ ] Scans mbox file
- [ ] Extracts metadata (Message-ID, offsets, etc.)
- [ ] Records in database
- [ ] Handles compressed archives (.gz, .xz, .zst)
- [ ] Reports import statistics

### 13. Deduplication
```bash
# Analyze duplicates
gmailarchiver dedupe-report

# Remove duplicates (dry run first!)
gmailarchiver dedupe --strategy newest --dry-run
gmailarchiver dedupe --strategy newest  # Actual removal
```

**Expected Behavior**:
- [ ] Identifies duplicates by RFC Message-ID
- [ ] Shows space savings estimate
- [ ] Dry run shows what would be removed
- [ ] Actual run removes duplicates from database (NOT mbox)

### 14. Consolidate Command
```bash
# Merge multiple archives (dry run)
gmailarchiver consolidate /tmp/archive1.mbox /tmp/archive2.mbox \
  --output /tmp/consolidated.mbox \
  --dedupe \
  --dry-run

# Actual consolidation
gmailarchiver consolidate /tmp/archive*.mbox \
  --output /tmp/consolidated.mbox \
  --dedupe
```

**Expected Behavior**:
- [ ] Merges archives chronologically
- [ ] Removes duplicates (if --dedupe flag)
- [ ] Creates new mbox file
- [ ] Updates database with new offsets
- [ ] Shows progress and statistics

---

## Deletion Workflow

### 15. Delete After Archive (Trash)
```bash
gmailarchiver archive 1w --output /tmp/test.mbox --trash
```

**Expected Behavior**:
- [ ] Archives messages first
- [ ] Validates archive
- [ ] Moves messages to Gmail Trash (30-day recovery)
- [ ] Asks for confirmation

### 16. Permanent Delete
```bash
# CAUTION: Permanent deletion!
gmailarchiver archive 1w --output /tmp/test.mbox --delete
```

**Expected Behavior**:
- [ ] Archives messages
- [ ] Validates archive
- [ ] Requires typing exact phrase: "permanently delete"
- [ ] Permanently deletes from Gmail (no recovery)

### 17. Retry-Delete Command (for 403 auth errors)
```bash
# If archive succeeded but delete failed with 403
gmailarchiver retry-delete /tmp/test_archive.mbox --permanent
```

**Expected Behavior**:
- [ ] Retrieves Gmail IDs from database
- [ ] Re-authenticates if needed
- [ ] Retries deletion
- [ ] Reports success/failure

---

## Repair & Recovery

### 18. Repair Command
```bash
# Preview repairs (dry run by default)
gmailarchiver repair

# With backfill for beta.1 migration bug
gmailarchiver repair --backfill

# Apply repairs
gmailarchiver repair --backfill --no-dry-run
```

**Expected Behavior**:
- [ ] Dry run shows what would be repaired
- [ ] Fixes orphaned FTS records
- [ ] Fixes missing FTS records
- [ ] Backfill option scans mbox files to fix invalid offsets
- [ ] Shows repair summary

### 19. Status Command
```bash
gmailarchiver status
```

**Expected Output**:
- [ ] Shows archive statistics
- [ ] Displays message counts
- [ ] Shows disk usage
- [ ] Lists archive files

---

## Edge Cases & Error Handling

### 20. Error Scenarios to Test

#### Rate Limiting
```bash
# Archive large batch to trigger rate limits
gmailarchiver archive 1y --output /tmp/large.mbox
```
- [ ] Handles 429 errors gracefully
- [ ] Implements exponential backoff
- [ ] Shows progress during retries
- [ ] Eventually completes

#### Network Errors
- [ ] Disconnect network during archive
- [ ] Reconnect and retry
- [ ] Verify no data corruption

#### Interrupted Operations
```bash
# Start archive, then Ctrl+C
gmailarchiver archive 1m --output /tmp/test.mbox
# ^C (interrupt)
```
- [ ] Cleanup happens gracefully
- [ ] No corrupt mbox files left
- [ ] Database transaction rolled back
- [ ] Lock files cleaned up

#### Invalid Input
```bash
# Test validation
gmailarchiver archive invalid_age  # Should error
gmailarchiver search "query;rm -rf /"  # Should reject dangerous chars
gmailarchiver validate /nonexistent/file  # Should error
```
- [ ] Clear error messages
- [ ] Validates age expressions
- [ ] Sanitizes Gmail queries
- [ ] Checks file existence

---

## Performance Validation

### 21. Performance Benchmarks

**Search Performance** (target: <100ms for 1000 messages):
```bash
# Run search multiple times, observe timing
gmailarchiver search "from:example.com" --limit 1000
```
- [ ] Should complete in <100ms
- [ ] Results should be ranked by relevance

**Import Performance** (target: >166 msgs/sec):
```bash
# Import 1000 messages, measure time
time gmailarchiver import /path/to/large_archive.mbox
```
- [ ] Should process >166 messages/second
- [ ] Progress bar updates smoothly

**Consolidation Performance** (target: <60s for 10k messages):
```bash
# Consolidate 10k messages, measure time
time gmailarchiver consolidate /tmp/archive*.mbox --output /tmp/merged.mbox
```
- [ ] Should complete in <60 seconds for 10k messages

---

## Compatibility Tests

### 22. v1.0 → v1.1 Migration
If you have a v1.0 database:
- [ ] Backup v1.0 database
- [ ] Run `gmailarchiver db-info` to trigger migration
- [ ] Verify all messages migrated
- [ ] Test search on migrated data
- [ ] Run `verify-integrity` to check

### 23. Beta.1 → v1.1.0 Upgrade
If you have a beta.1 database with migration bug:
- [ ] Run `gmailarchiver verify-integrity` (should find invalid offsets)
- [ ] Run `gmailarchiver repair --backfill --no-dry-run`
- [ ] Run `verify-integrity` again (should be clean)
- [ ] Test search and import

---

## Checklist Summary

### Critical (Must Pass)
- [ ] OAuth authentication works
- [ ] Archive command works (dry run + actual)
- [ ] Validation passes for archived messages
- [ ] Search returns accurate results
- [ ] Database integrity checks pass
- [ ] No data loss during operations

### Important (Should Pass)
- [ ] Compression formats work (gzip, lzma, zstd)
- [ ] Import existing archives
- [ ] Deduplication works correctly
- [ ] Consolidation merges archives properly
- [ ] Repair command fixes issues
- [ ] Migration from v1.0 works

### Nice to Have (Can Defer)
- [ ] Performance meets targets
- [ ] Error handling is graceful
- [ ] Progress bars display correctly
- [ ] Help messages are clear

---

## Reporting Issues

If you find any issues, please report:

1. **Command that failed**: Full command with arguments
2. **Error message**: Complete output and stack trace
3. **Expected vs actual behavior**: What should happen vs what happened
4. **Environment**:
   - Python version: `python --version`
   - OS: macOS/Linux/Windows
   - gmailarchiver version: `1.1.0`
5. **Steps to reproduce**: Minimal example to trigger the bug
6. **Logs**: If applicable, run with verbose logging

---

## When All Tests Pass

After all critical and important tests pass, we can proceed with:

1. **Push to GitHub**:
   ```bash
   git push origin main
   git push origin v1.1.0
   ```

2. **Create GitHub Release**:
   - Upload `dist/gmailarchiver-1.1.0-py3-none-any.whl`
   - Upload `dist/gmailarchiver-1.1.0.tar.gz`
   - Copy CHANGELOG v1.1.0 section to release notes

3. **Publish to PyPI**:
   ```bash
   twine upload dist/gmailarchiver-1.1.0*
   ```

---

## Additional Notes

- **Database location**: `~/.local/share/gmailarchiver/archives.db`
- **Token location**: `~/.config/gmailarchiver/token.json`
- **Backup strategy**: Always backup database before major operations
- **Recovery**: Use `rollback` command if migration fails

Happy testing! 🚀
