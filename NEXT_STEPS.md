# Next Steps: Gmail Archiver v1.2.0 "Ergonomics"

**Date**: 2025-11-19
**Status**: Planning Complete, Ready to Begin Implementation

---

## What Just Happened

### 1. ✅ Completed Phase 0 Documentation

**Phase 0 is DONE** (v1.1.0-beta.2 → v1.1.0):
- All architecture refactoring complete
- DBManager + HybridStorage implemented
- verify-integrity + repair commands working
- 619 tests passing (96% coverage)

**But**: The old PLAN.md was 1,239 lines with extensive unchecked boxes that made it look incomplete.

### 2. ✅ Conducted Comprehensive CLI Analysis

**Key Discoveries**:

1. **Search works perfectly with compressed archives** ✅
   - No decompression needed
   - Database-only queries
   - BUT users might not know this!

2. **Can't extract messages after searching** ❌
   - Search returns pointers (gmail_id, offset, file)
   - No command to retrieve the actual message
   - Workflow incomplete!

3. **Validation is manual** ❌
   - Import → must manually verify
   - Verify → must manually repair
   - Repair → must manually verify again
   - Requires 4+ commands for safe workflow

4. **No automation** ❌
   - No scheduled health checks
   - No cron job creation
   - Database issues may go unnoticed

**Full analysis**: [`docs/ERGONOMICS_ANALYSIS.md`](docs/ERGONOMICS_ANALYSIS.md)

### 3. ✅ Created New Streamlined Roadmap

**New document**: [`docs/PLAN_v2.md`](docs/PLAN_v2.md)

**Focus**: Ergonomics and usability improvements BEFORE adding new features.

**Key changes**:
- Condensed historical context (Phase 0) to ~50 lines
- Expanded v1.2.0 with detailed specifications
- Concrete acceptance criteria for each feature
- Week-by-week implementation plan

---

## Decision Point: What to Build Next?

### Proposed: v1.2.0 "Ergonomics" (3-4 weeks)

**Theme**: Complete existing workflows, automate maintenance, improve usability.

### Tier 1: Critical Gaps (Week 1-2)

#### 1. `extract` Command ⭐ TOP PRIORITY

**Why**: Completes the search workflow (currently broken).

**What**:
```bash
gmailarchiver extract <gmail-id>                    # to stdout
gmailarchiver extract <gmail-id> --output msg.eml  # to file
gmailarchiver search "query" --extract              # extract all results
```

**Impact**: HIGH - Users can actually USE search results
**Effort**: 3 days
**Status**: Fully specified in PLAN_v2.md

---

#### 2. `check` Meta-Command ⭐ HIGH PRIORITY

**Why**: Simplifies maintenance from 4+ commands to 1.

**What**:
```bash
gmailarchiver check              # runs all verifications
gmailarchiver check --auto-repair  # fixes issues automatically
```

**Impact**: HIGH - Makes maintenance trivial
**Effort**: 1 day
**Status**: Fully specified in PLAN_v2.md

---

#### 3. `--auto-verify` Flags

**Why**: Prevents corrupted imports/consolidations.

**What**:
```bash
gmailarchiver import archives/*.mbox.gz --auto-verify
gmailarchiver consolidate src/*.mbox -o merged.mbox --auto-verify
```

**Impact**: MEDIUM - Catches issues immediately
**Effort**: 1 day
**Status**: Fully specified in PLAN_v2.md

---

### Tier 2: Automation (Week 3)

#### 4. `schedule` Command

**Why**: Automated health checks prevent long-term issues.

**What**:
```bash
gmailarchiver schedule check --cron "0 2 * * *"  # nightly checks
gmailarchiver schedule logs                      # view results
```

**Impact**: HIGH - Zero-touch maintenance
**Effort**: 3-4 days

---

#### 5. `compress` Command

**Why**: Users can't compress archives after creation.

**What**:
```bash
gmailarchiver compress archive.mbox --format zstd
```

**Impact**: MEDIUM - User convenience
**Effort**: 2 days

---

#### 6. `doctor` Command

**Why**: Comprehensive diagnostics in one command.

**What**:
```bash
gmailarchiver doctor  # shows all health metrics + recommendations
```

**Impact**: MEDIUM - Easier troubleshooting
**Effort**: 2-3 days

---

## Your Input Needed

### Question 1: Do you agree with the "Ergonomics First" strategy?

**Options**:
- **A**: Yes, improve usability before adding features
- **B**: No, add new features first (e.g., Web UI, multi-account)
- **C**: Mix of both

**My recommendation**: **A** - The architecture is solid, but UX has gaps. Nail the CLI first.

---

### Question 2: Which Tier 1 features should we prioritize?

**Options**:
- **A**: All 3 (extract + check + auto-verify) - comprehensive
- **B**: Just extract (completes search workflow) - focused
- **C**: Extract + check (biggest impact) - balanced
- **D**: Different priorities entirely

**My recommendation**: **C** - Extract + check give immediate user value.

---

### Question 3: Should we update the old PLAN.md or keep both?

**Options**:
- **A**: Replace `docs/PLAN.md` with `PLAN_v2.md` (cleaner)
- **B**: Keep both (historical reference)
- **C**: Merge into single document

**My recommendation**: **A** - Rename old to `PLAN_HISTORICAL.md`, make v2 the canonical plan.

---

## Proposed Next Actions

### If you approve the ergonomics-first approach:

#### This Week:
1. **Finalize roadmap** based on your feedback
2. **Implement `extract` command** (3 days)
   - Core extraction logic
   - Decompression support
   - Integration with search
   - Tests

3. **Implement `check` command** (1 day)
   - Consolidate verify-* commands
   - Auto-repair flag
   - Tests

#### Next Week:
4. **Add `--auto-verify` flags** (1 day)
5. **Begin Tier 2**: schedule, compress, doctor
6. **Beta testing** with real users

#### This Month:
- Complete v1.2.0 Tier 1 + Tier 2
- Documentation updates
- Release candidate

---

## Files Created

1. **`docs/ERGONOMICS_ANALYSIS.md`** - Comprehensive CLI analysis (all findings)
2. **`docs/PLAN_v2.md`** - New streamlined roadmap (focus on next steps)
3. **`NEXT_STEPS.md`** (this file) - Decision summary

---

## What Do You Think?

Please review:
1. [`docs/ERGONOMICS_ANALYSIS.md`](docs/ERGONOMICS_ANALYSIS.md) - The research
2. [`docs/PLAN_v2.md`](docs/PLAN_v2.md) - The proposed plan

Let me know:
- ✅ Do you approve the ergonomics-first strategy?
- ✅ Which features should be prioritized?
- ✅ Any changes to the proposed roadmap?

Then we can dive into implementation!

---

**Ready to proceed when you are.** 🚀
