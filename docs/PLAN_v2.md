# Gmail Archiver: Development Roadmap

**Last Updated**: 2025-11-19
**Current Version**: 1.1.0 (Stable Release)
**Status**: Phase 0 Complete, Planning v1.2

---

## Quick Context: What's Been Built

### ✅ Phase 0: Architecture Refactoring (COMPLETE)

**Delivered** (v1.1.0-beta.2 → v1.1.0):
- `DBManager`: Centralized database operations (213 LOC, 95%+ coverage)
- `HybridStorage`: Atomic mbox + database coordinator (499 LOC, 87% coverage)
- `verify-integrity` + `repair` commands with `--backfill` support
- Migration system: v1.0 → v1.1 auto-upgrade
- All modules refactored to use DBManager/HybridStorage
- **619 tests passing** (96% coverage)

**Success Criteria Met**:
- ✅ 100% SQL centralized in DBManager
- ✅ All write operations atomic
- ✅ Complete audit trail (archive_runs)
- ✅ Migration backfills real data (no placeholders)
- ✅ Comprehensive validation commands

**Outcome**: Solid architectural foundation for future features.

### ✅ Version 1.1.0 - "Foundation" (COMPLETE)

**Delivered**:
- Enhanced database schema (v1.1) with mbox offset tracking
- FTS5 full-text search with BM25 ranking
- Import existing archives (glob patterns, all compression formats)
- Message deduplication (RFC Message-ID based, 100% precision)
- Archive consolidation (merge + sort + dedupe)
- Search with Gmail-style syntax
- Comprehensive validation suite

**Key Metrics Achieved**:
- Import: 10,145 messages/second
- Search: 0.85ms for 1000 messages (118x faster than target)
- Consolidation: 3.57s for 10k messages
- Test coverage: 96%

**Status**: Released, stable, production-ready

---

## Strategic Direction: Ergonomics First

**Key Insight from User Feedback**:
> "It's becoming complicated to figure out which commands to run in which sequence and what their effect will be."

**New Focus**: Enhance usability of existing features before adding new ones.

### The Problem

**Current state**:
- ✅ `archive`: Complete workflow (Gmail → mbox → database → validate → compress)
- ❌ `search`: Returns pointers but can't extract messages
- ❌ `import`: No auto-verification (users must remember to run verify commands)
- ❌ Maintenance: Requires 4+ manual commands (verify-integrity → repair → verify again)

**Example of poor ergonomics**:
```bash
# User wants to search and read an email
$ gmailarchiver search "important contract"
# Shows: gmail_id=abc123, offset=1234567, file=archive.mbox.zst
# Now what? Can't extract the message! 😞

# User wants to import safely
$ gmailarchiver import archives/*.mbox.gz
$ gmailarchiver verify-integrity    # Easy to forget
$ gmailarchiver repair --no-dry-run  # If issues found
$ gmailarchiver verify-integrity    # Verify repair worked
# Too many manual steps! 😞
```

---

## Version 1.2.0 - "Ergonomics" 🔴 ACTIVE

**Timeline**: 3-4 weeks
**Theme**: Complete workflows, automation, user convenience
**Goal**: Make existing features easier to use

### Tier 1: Critical Gaps (Week 1-2)

#### 1. `extract` Command - Complete the Search Workflow

**Problem**: Search returns pointers (gmail_id, offset, archive_file) but no way to retrieve full message.

**Solution**:
```bash
# Extract single message
gmailarchiver extract <gmail-id>                    # to stdout
gmailarchiver extract <gmail-id> --output msg.eml  # to file

# Extract from search results
gmailarchiver search "query" --extract --output folder/

# Works with compressed archives (transparent decompression)
gmailarchiver extract abc123 --archive archive.mbox.zst
```

**Implementation**:
- Read `mbox_offset` + `mbox_length` from database
- Seek to position in mbox file
- Transparently handle all compression formats (gzip, lzma, zstd)
- Output formats: raw email (default), .eml, JSON

**Effort**: 3 days
**Impact**: HIGH (completes essential workflow)

**Acceptance Criteria**:
- [ ] Extract by gmail_id works
- [ ] Extract by rfc_message_id works
- [ ] Handles compressed archives (all formats)
- [ ] Output to stdout or file
- [ ] Integration with search (--extract flag)
- [ ] Batch extraction support
- [ ] Tests: 95%+ coverage

---

#### 2. `check` Meta-Command - Unified Health Check

**Problem**: Users must run 3-4 separate verify commands manually.

**Solution**:
```bash
# Run all health checks in one command
gmailarchiver check

# Output (example):
# ✓ Database integrity: OK
# ✓ Database consistency: OK
# ✓ Offset accuracy: 100% (16,132/16,132)
# ✓ FTS synchronization: OK
# Overall: HEALTHY

# With auto-repair
gmailarchiver check --auto-repair
# Automatically fixes issues found
```

**Runs**:
1. `verify-integrity` (database health)
2. `verify-consistency` (database ↔ mbox sync)
3. `verify-offsets` (if v1.1 schema)
4. FTS synchronization check

**Features**:
- Single consolidated report
- Optional `--auto-repair` flag
- Exit codes: 0 = healthy, 1 = issues, 2 = repair failed

**Effort**: 1 day
**Impact**: HIGH (simplifies maintenance)

**Acceptance Criteria**:
- [ ] Runs all 4 verification checks
- [ ] Consolidated output (single report)
- [ ] --auto-repair flag works
- [ ] Correct exit codes
- [ ] Tests: 95%+ coverage

---

#### 3. Auto-Verification Flags

**Problem**: Import/consolidate/dedupe don't verify automatically.

**Solution**:
```bash
# Import with automatic verification
gmailarchiver import archives/*.mbox.gz --auto-verify

# Consolidate with verification
gmailarchiver consolidate src/*.mbox -o merged.mbox --auto-verify

# Dedupe with verification
gmailarchiver dedupe --no-dry-run --auto-verify
```

**Behavior**:
- Runs appropriate verification after operation
- Shows results
- Offers auto-repair if issues found

**Effort**: 1 day
**Impact**: MEDIUM (prevents issues)

**Acceptance Criteria**:
- [ ] --auto-verify on import command
- [ ] --auto-verify on consolidate command
- [ ] --auto-verify on dedupe command
- [ ] Verification runs automatically
- [ ] User sees results
- [ ] Tests: 95%+ coverage

---

### Tier 2: Automation & Convenience (Week 3)

#### 4. `schedule` Command - Automated Maintenance

**Problem**: No automated health checks, users must remember to run manually.

**Solution**:
```bash
# Schedule nightly checks
gmailarchiver schedule check --cron "0 2 * * *"

# View scheduled jobs
gmailarchiver schedule list

# View logs
gmailarchiver schedule logs --tail 50

# Disable scheduling
gmailarchiver schedule disable check
```

**Features**:
- Creates cron job (Linux/macOS) or Task Scheduler (Windows)
- Logs to `~/.gmailarchiver/logs/check-YYYY-MM-DD.log`
- Optional email notifications on failure
- Graceful handling if cron unavailable

**Effort**: 3-4 days
**Impact**: HIGH (long-term data integrity)

**Acceptance Criteria**:
- [ ] Creates platform-specific scheduled task
- [ ] Logging to file
- [ ] List/disable commands work
- [ ] Handles missing cron gracefully
- [ ] Tests: 90%+ coverage (platform-dependent)

---

#### 5. `compress` Command - Post-Hoc Compression

**Problem**: Users must choose compression at archive time, can't compress later.

**Solution**:
```bash
# Compress existing archive
gmailarchiver compress archive.mbox --format zstd

# Output:
# Compressing archive.mbox → archive.mbox.zst
# Original: 2.3 GB, Compressed: 487 MB (78.8% savings)
# Updating database paths...
# ✓ Complete

# Batch compress
gmailarchiver compress archives/*.mbox --format zstd --keep-original
```

**Features**:
- Atomically updates database `archive_file` paths
- Validates before deleting original
- Optional `--keep-original` flag
- Supports: gzip, lzma, zstd

**Effort**: 2 days
**Impact**: MEDIUM (user convenience)

**Acceptance Criteria**:
- [ ] Compresses mbox files
- [ ] Updates database paths atomically
- [ ] Validates before deletion
- [ ] --keep-original flag works
- [ ] Batch processing support
- [ ] Tests: 95%+ coverage

---

#### 6. `doctor` Command - Comprehensive Diagnostics

**Problem**: Hard to troubleshoot issues, no unified diagnostics.

**Solution**:
```bash
gmailarchiver doctor

# Output:
# 🔍 Gmail Archiver Health Check
#
# Database:
#   ✓ Schema: v1.1
#   ✓ Integrity: OK
#   ✓ Size: 245 MB
#
# Archives:
#   ✓ Total: 3 files
#   ⚠ Missing: old.mbox (150 messages affected)
#
# Authentication:
#   ✓ OAuth token: Valid (expires 2025-12-15)
#
# Performance:
#   ✓ Search: 12ms (metadata), 45ms (FTS)
#
# Recommendations:
#   • Restore old.mbox from backup
#   • Run vacuum (last: 5 days ago)
```

**Checks**:
- Database (integrity, size, vacuum status)
- Archives (existence, compression, accessibility)
- Authentication (token validity, scopes)
- Disk space
- Performance metrics

**Effort**: 2-3 days
**Impact**: MEDIUM (troubleshooting)

**Acceptance Criteria**:
- [ ] All diagnostic checks implemented
- [ ] Clear, actionable output
- [ ] Suggestions for issues found
- [ ] Tests: 90%+ coverage

---

### Tier 3: Polish (Week 4, as time allows)

#### 7. Search Enhancements

```bash
# Show body preview
gmailarchiver search "query" --with-preview

# Interactive search
gmailarchiver search --interactive
```

#### 8. Cleanup Options

```bash
# Remove sources after consolidation
gmailarchiver consolidate src/*.mbox -o merged.mbox --remove-sources
```

#### 9. Progress Estimation

```bash
gmailarchiver archive 3y
# Archiving: 1234/5678 (21%, ETA: 8m 42s)
```

---

## Implementation Plan: v1.2.0

### Week 1: Core Workflows
- **Day 1-3**: Implement `extract` command
  - Day 1: Core extraction logic (offset seeking, decompression)
  - Day 2: Integration with search, output formats
  - Day 3: Tests, documentation, edge cases

- **Day 4**: Implement `check` meta-command
  - Consolidate verify-* commands
  - Single report output
  - --auto-repair flag

- **Day 5**: Implement `--auto-verify` flags
  - Add to import, consolidate, dedupe
  - Integration tests

### Week 2: Automation
- **Day 1-3**: Implement `schedule` command
  - Day 1: Cron job creation (Linux/macOS)
  - Day 2: Task Scheduler (Windows), logging
  - Day 3: Tests, cross-platform validation

- **Day 4-5**: Implement `compress` command
  - Compression logic, database updates
  - Atomic operations, validation
  - Tests

### Week 3: Diagnostics & Polish
- **Day 1-2**: Implement `doctor` command
  - All diagnostic checks
  - Report formatting, recommendations

- **Day 3-5**: Polish & testing
  - Search enhancements
  - Cleanup options
  - Comprehensive integration tests
  - Documentation updates

### Week 4: Release Preparation
- Beta testing period
- Documentation review
- CHANGELOG.md update
- Release v1.2.0

---

## Success Metrics: v1.2.0

### User Experience
- ✅ Search → extract workflow: < 2 commands (was: impossible)
- ✅ Health check: 1 command (was: 4+ commands)
- ✅ Import → verify → repair: 1 command (was: 3+ commands)

### Automation
- ✅ Zero-touch scheduled checks (set once, forget)
- ✅ Automatic repair suggestions
- ✅ Comprehensive diagnostics in 1 command

### Quality
- ✅ Test coverage: 95%+
- ✅ All new commands documented
- ✅ Zero regressions

---

## Future Considerations (v2.0+)

**Deferred until v1.2 ergonomics complete**:

### v2.0 - Accessibility
- Web UI (read-only)
- One-line installation script
- GUI for non-technical users

### v2.1 - Distribution
- Standalone executables (PyInstaller)
- Code signing (macOS/Windows)
- Auto-update mechanism

### v3.0 - Enterprise
- Multi-account support
- Thread reconstruction
- Advanced features

**Rationale for deferral**: Perfect the CLI experience first. Web UI and executables amplify existing UX (good or bad).

---

## Development Standards

All code must meet:
- **Line length**: 100 characters (ruff)
- **Python version**: 3.14+
- **Type checking**: Strict mypy
- **Test coverage**: 95%+
- **Linting**: ruff (rules: E, F, I, N, W, UP)

---

## Code Review Checklist

Before merging:
- [ ] All tests pass (pytest)
- [ ] Coverage maintained (95%+)
- [ ] Type checking passes (mypy)
- [ ] Linting passes (ruff)
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] User testing completed

---

## Next Steps

### Immediate (This Week)
1. **Review this plan** with user
2. **Get approval** on v1.2 priorities
3. **Start Week 1**: Implement `extract` command

### This Month
- Complete v1.2.0 Tier 1 (extract, check, auto-verify)
- Beta testing with real users
- Gather feedback on ergonomics

### This Quarter
- Complete v1.2.0 (all tiers)
- Release v1.2.0 stable
- Plan v2.0 based on user feedback

---

**For detailed technical analysis, see**: [ERGONOMICS_ANALYSIS.md](./ERGONOMICS_ANALYSIS.md)

**For architectural details, see**: [ARCHITECTURE.md](./ARCHITECTURE.md)

**For contribution guidelines, see**: [CONTRIBUTING.md](../CONTRIBUTING.md)

---

**End of Roadmap**
