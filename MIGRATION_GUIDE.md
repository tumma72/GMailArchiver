# Migration Guide: v1.0 → v1.1

This guide helps you upgrade from Gmail Archiver v1.0.x to v1.1.0.

## What's New in v1.1?

### Major Features
- **FTS5 Full-Text Search**: Search archived messages with Gmail-style syntax
- **Import Existing Archives**: Import mbox files from other tools
- **Deduplication**: Remove duplicates with 100% precision
- **Consolidation**: Merge multiple archives
- **Enhanced Performance**: 60-118x faster than targets

### Breaking Changes

#### 1. OAuth Scope Change (IMPORTANT)

**What changed**: OAuth scope changed from `gmail.modify` to full Gmail access (`https://mail.google.com/`)

**Why**: Previous scope did not include `messages.delete` permission, causing HTTP 403 errors when attempting permanent deletion

**Action Required**:
```bash
# Reset authentication
gmailarchiver auth-reset

# Re-authenticate on next command
gmailarchiver db-info
# → Browser will open for re-authorization
```

**If you already archived but deletion failed**:
```bash
# Reset auth first
gmailarchiver auth-reset

# Retry deletion for already-archived messages
gmailarchiver retry-delete archive_20250114.mbox --permanent
```

#### 2. Database Schema Change

**What changed**: Database schema upgraded from v1.0 (7 fields) to v1.1 (17 fields)

**Why**: Enables FTS5 search, O(1) message access, and enhanced metadata

**Action Required**: Migration happens automatically on first v1.1 run

## Migration Process

### Automatic Migration (Recommended)

The migration process is **fully automatic** when you first run v1.1:

```bash
# Any v1.1 command triggers migration check
gmailarchiver db-info

# You'll see:
# "Detected v1.0 database schema. Migration to v1.1 required."
# "Would you like to migrate now? [Y/n]"
```

**What happens during migration**:
1. ✅ Automatic backup created (`archive_state.db.backup.TIMESTAMP`)
2. ✅ Schema upgraded (v1.0 → v1.1)
3. ✅ All existing data preserved
4. ✅ Validation checks run
5. ✅ Old schema cleaned up

**Time**: ~1 second per 1000 messages

### Manual Migration

If you want explicit control:

```bash
# Check current schema version
gmailarchiver db-info

# Manually trigger migration
gmailarchiver migrate

# Verify migration succeeded
gmailarchiver db-info
```

### Rollback (If Needed)

If migration fails or you want to rollback:

```bash
# List available backups
gmailarchiver rollback

# Restore from backup
gmailarchiver rollback --backup-file archive_state.db.backup.20250114_120000

# Verify rollback
gmailarchiver db-info
```

## Post-Migration Features

Once migrated, you can use all v1.1 features:

### Search Your Archives

```bash
# Search by sender
gmailarchiver search "from:alice@example.com"

# Search by subject and date
gmailarchiver search "subject:invoice after:2024-01-01"

# Full-text search
gmailarchiver search "payment receipt"
```

### Import Existing Archives

If you have old mbox files:

```bash
# Import single file
gmailarchiver import old_backup.mbox

# Import multiple files
gmailarchiver import "archive_*.mbox.gz"
```

### Deduplicate Messages

Remove duplicates across all archives:

```bash
# Preview duplicates
gmailarchiver dedupe-report

# Remove duplicates (keeps newest)
gmailarchiver dedupe --strategy newest
```

### Consolidate Archives

Merge multiple archives into one:

```bash
# Merge all archives
gmailarchiver consolidate archive_*.mbox -o merged.mbox.zst
```

## Troubleshooting

### "HTTP 403 Insufficient Permission" Error

**Symptom**: Archiving succeeds but deletion fails with 403 error

**Solution**:
```bash
# 1. Reset authentication
gmailarchiver auth-reset

# 2. Re-authenticate (browser will open)
gmailarchiver db-info

# 3. Retry deletion
gmailarchiver retry-delete archive_YYYYMMDD.mbox --permanent
```

### Migration Fails

**Symptom**: Migration errors during upgrade

**Solution**:
```bash
# Rollback to v1.0 schema
gmailarchiver rollback --backup-file <BACKUP_FILE>

# Report issue with error message
# https://github.com/tumma72/GMailArchiver/issues
```

### Missing Features After Migration

**Symptom**: Search/import commands not working

**Solution**:
```bash
# Verify schema version
gmailarchiver db-info
# Should show: "Schema version: 1.1"

# If still v1.0, manually migrate:
gmailarchiver migrate
```

## FAQ

**Q: Will migration delete my archived messages?**
A: No. Migration only updates the database schema. Your mbox files are NOT touched.

**Q: Can I use v1.0 and v1.1 at the same time?**
A: No. Once migrated to v1.1, you cannot use v1.0. But you can rollback if needed.

**Q: Do I need to re-archive my messages?**
A: No. All existing archives work with v1.1. However, v1.1-specific features (search, offset-based access) require re-importing or consolidating old archives.

**Q: What if I have multiple databases?**
A: Each database migrates independently. Run v1.1 commands with `--state-db` flag for each database.

**Q: Can I skip migration?**
A: You can delay it, but v1.1 features won't work until migration completes.

**Q: How long does migration take?**
A: ~1 second per 1000 messages. A database with 100k messages takes ~100 seconds.

## Getting Help

- **Issues**: https://github.com/tumma72/GMailArchiver/issues
- **Discussions**: https://github.com/tumma72/GMailArchiver/discussions
- **Documentation**: https://github.com/tumma72/GMailArchiver

## Summary

1. ✅ Upgrade to v1.1 (pip install)
2. ✅ Run `gmailarchiver auth-reset` and re-authenticate
3. ✅ Run any command to trigger automatic migration
4. ✅ Enjoy 60-118x performance improvements and new features!
