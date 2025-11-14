# Gmail Archiver: Strategic Plan & Roadmap

**Last Updated:** 2025-11-14
**Status:** Active Development
**Current Version:** 1.0.3

---

## Executive Summary

Gmail Archiver is evolving from a focused CLI archival tool into a comprehensive email management platform. This document outlines the strategic direction, architectural decisions, and implementation roadmap based on extensive research and analysis of email archiving best practices.

### Core Strategic Pillars

1. **Archive Consolidation** - Import and manage existing mbox archives with deduplication
2. **Searchability** - Transform archives from write-only backups to searchable knowledge bases
3. **Accessibility** - Lower barriers to entry for non-technical users
4. **Multi-Account Support** - Enable professional users to manage multiple email accounts (future)

### Key Architectural Decision

**Hybrid Model: mbox Storage + SQLite Indexing**

After comprehensive analysis, we're adopting the "Thunderbird model":
- **mbox files** remain the authoritative source (RFC 4155 standard)
- **SQLite database** provides indexing, metadata, and full-text search
- Combines portability with searchability
- Zero vendor lock-in
- Standards-compliant for legal/archival requirements

---

## 🏗️ Architectural Decision: Hybrid Model

### Why Hybrid?

**✅ Advantages:**
- **Portability**: mbox is RFC 4155 standard, universally compatible
- **Searchability**: SQLite FTS5 enables fast full-text search
- **Safety**: Database corruption doesn't lose emails (rebuild from mbox)
- **Performance**: O(1) message access via `mbox_offset` in database
- **Zero lock-in**: Users can use mbox with any email client
- **Standards compliance**: Legal and archival acceptance

**❌ Rejected: Pure Database-First**
- Vendor lock-in risk
- Not a standard archival format
- Compliance concerns (binary database vs text files)
- Total loss if database corrupts without mbox fallback
- Harder to migrate away from tool

**❌ Rejected: Pure mbox-First**
- No native search capability
- Poor random access performance (linear scanning)
- Can't efficiently add advanced features (deduplication, threading)
- Feature ceiling limits growth potential

### Implementation Model

```
Storage Layer:        mbox files (compressed)
                      ↓
Index Layer:          SQLite database
                      ├─ Message metadata
                      ├─ mbox_offset (O(1) access)
                      └─ FTS5 full-text index
                      ↓
Application Layer:    CLI + Web UI
```

### Expert Validation

External expert analysis validated this approach:
> "The hybrid 'Thunderbird model' is spot on. It balances data portability with modern features and is the most resilient and future-proof architecture."

Key insight: Store `mbox_offset` for O(1) seeking instead of full mbox scans.

---

## 🗄️ Database Schema Design

### Enhanced Schema (v1.1.0)

```sql
-- ============================================================================
-- MESSAGES TABLE (Core hybrid model)
-- ============================================================================
CREATE TABLE messages (
    -- Primary identifiers
    gmail_id TEXT PRIMARY KEY,              -- Gmail API ID
    rfc_message_id TEXT UNIQUE NOT NULL,    -- RFC 2822 Message-ID (dedup key!)
    thread_id TEXT,                         -- Gmail thread ID

    -- Email metadata
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    cc_addr TEXT,
    date TIMESTAMP,
    archived_timestamp TIMESTAMP,

    -- HYBRID MODEL: Reference to mbox storage
    archive_file TEXT NOT NULL,             -- Path to mbox file
    mbox_offset INTEGER NOT NULL,           -- Byte offset (O(1) access!)
    mbox_length INTEGER NOT NULL,           -- Message length in bytes

    -- Content preview for FTS and UI
    body_preview TEXT,                      -- First 1000 chars

    -- Integrity
    checksum TEXT,                          -- SHA256
    size_bytes INTEGER,

    -- Gmail-specific
    labels TEXT,                            -- JSON array

    -- Multi-account (future)
    account_id TEXT DEFAULT 'default',

    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

-- Performance indexes
CREATE INDEX idx_rfc_message_id ON messages(rfc_message_id);
CREATE INDEX idx_thread_id ON messages(thread_id);
CREATE INDEX idx_archive_file ON messages(archive_file);
CREATE INDEX idx_date ON messages(date);
CREATE INDEX idx_from ON messages(from_addr);
CREATE INDEX idx_subject ON messages(subject);

-- ============================================================================
-- FULL-TEXT SEARCH (FTS5)
-- ============================================================================
CREATE VIRTUAL TABLE messages_fts USING fts5(
    subject,
    from_addr,
    to_addr,
    body_preview,
    content='messages',
    content_rowid='rowid'
);

-- Auto-sync triggers
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
    VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
END;

CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages BEGIN
    UPDATE messages_fts
    SET subject = new.subject,
        from_addr = new.from_addr,
        to_addr = new.to_addr,
        body_preview = new.body_preview
    WHERE rowid = new.rowid;
END;

CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.rowid;
END;

-- ============================================================================
-- ACCOUNTS TABLE (Multi-account support - v3.0.0)
-- ============================================================================
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    provider TEXT DEFAULT 'gmail',          -- gmail, outlook, icloud
    added_timestamp TEXT,
    last_sync_timestamp TEXT
);

-- ============================================================================
-- ARCHIVE RUNS (Existing - keep for audit trail)
-- ============================================================================
CREATE TABLE archive_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT,
    query TEXT,
    messages_archived INTEGER,
    archive_file TEXT,
    account_id TEXT DEFAULT 'default'
);
```

### O(1) Message Access Implementation

```python
# During archiving: Capture offset before writing
mbox_file = mailbox.mbox(archive_path)
mbox_file.lock()

# Get current end-of-file position
with open(archive_path, 'rb') as f:
    f.seek(0, 2)  # Seek to end
    current_offset = f.tell()

# Write message
mbox_file.add(email_message)
mbox_file.flush()

# Calculate length
with open(archive_path, 'rb') as f:
    f.seek(0, 2)
    message_length = f.tell() - current_offset

# Store in database
state.record_message(
    gmail_id=msg_id,
    rfc_message_id=rfc_msg_id,
    mbox_offset=current_offset,
    mbox_length=message_length,
    ...
)

# Later: Retrieve specific message in O(1) time
with open(archive_path, 'rb') as f:
    f.seek(mbox_offset)
    raw_message = f.read(mbox_length)
    email_message = email.message_from_bytes(raw_message)
```

### Migration Strategy (v1.0.x → v1.1.0)

```python
# Auto-detect schema version
def migrate_database(db_path):
    """Migrate from v1.0.x to v1.1.0 schema"""

    # 1. Backup existing database
    shutil.copy(db_path, f"{db_path}.backup.{timestamp}")

    # 2. Check current schema version
    version = get_schema_version(db_path)

    if version == "1.0":
        # 3. Rename old table
        conn.execute("ALTER TABLE archived_messages RENAME TO archived_messages_old")

        # 4. Create new schema
        create_messages_table(conn)

        # 5. Migrate data
        for row in conn.execute("SELECT * FROM archived_messages_old"):
            # Parse mbox to get offset (one-time cost)
            offset, length = find_message_in_mbox(row['archive_file'], row['gmail_id'])

            conn.execute("""
                INSERT INTO messages
                (gmail_id, rfc_message_id, ..., mbox_offset, mbox_length)
                VALUES (?, ?, ..., ?, ?)
            """, (row['gmail_id'], extract_rfc_id(row), ..., offset, length))

        # 6. Drop old table
        conn.execute("DROP TABLE archived_messages_old")

        # 7. Update schema version
        set_schema_version(conn, "1.1")

        # 8. Vacuum to reclaim space
        conn.execute("VACUUM")
```

---

## 📅 Phased Roadmap

### Version 1.1.0 - "Foundation" 🔴 CRITICAL

**Timeline:** 4-6 weeks
**Theme:** Archive consolidation with enhanced indexing
**Status:** Planned

#### Features

1. **Enhanced Database Schema**
   - Implement hybrid model with `mbox_offset`
   - Add `rfc_message_id` for deduplication
   - Add FTS5 virtual table
   - Migration from v1.0.x schema

2. **Archive Import** (`gmailarchiver import`)
   ```bash
   gmailarchiver import ~/Documents/Mail\ Archives/old-archive.mbox.gz
   gmailarchiver import ~/Documents/Mail\ Archives/*.mbox --account personal
   ```
   - Parse existing mbox files (all compression formats)
   - Extract metadata and index in database
   - Record `mbox_offset` for each message
   - Progress tracking with Rich progress bars
   - Handle malformed messages gracefully

3. **Message-ID Deduplication** (`gmailarchiver dedupe`)
   ```bash
   gmailarchiver dedupe --dry-run
   gmailarchiver dedupe --consolidate-to archive.mbox.zst
   ```
   - Exact matching via RFC 2822 Message-ID
   - Cross-archive deduplication
   - Preserve newest copy (by date)
   - Report space savings
   - Safety: Always create new archive (never modify in-place)

4. **Archive Consolidation** (`gmailarchiver consolidate`)
   ```bash
   gmailarchiver consolidate ~/Documents/Mail\ Archives/*.mbox \
       --output consolidated.mbox.zst \
       --dedupe
   ```
   - Merge multiple archives into one
   - Optional deduplication during merge
   - Progress tracking
   - Maintains chronological order

5. **Enhanced Search - Metadata** (`gmailarchiver search`)
   ```bash
   gmailarchiver search --from "boss@company.com"
   gmailarchiver search --subject "invoice" --after 2023-01-01
   gmailarchiver search --before 2020-12-31 --has-attachment
   ```
   - SQL queries against indexed metadata
   - Gmail-style query syntax
   - Rich table output with highlighting
   - Export results to various formats

6. **Archive Verification** (`gmailarchiver verify`)
   ```bash
   gmailarchiver verify archive.mbox.zst --deep
   gmailarchiver verify --all
   ```
   - Count messages vs database expectations
   - Checksum verification (spot-check or deep)
   - Report corruption or inconsistencies
   - Suggest repair actions

#### Success Criteria

- ✅ Import 10,000 messages in < 60 seconds
- ✅ 100% Message-ID deduplication accuracy
- ✅ Zero data loss during migration
- ✅ Maintain 95%+ test coverage
- ✅ All existing functionality preserved

#### Implementation Checklist

**Week 1-2: Schema & Migration**
- [ ] Design migration script with rollback
- [ ] Implement enhanced schema
- [ ] Add `mbox_offset` tracking to archiver
- [ ] Write comprehensive migration tests
- [ ] Test with real user data (10k+ messages)

**Week 3-4: Import & Deduplication**
- [ ] Implement mbox parser for import
- [ ] Add RFC Message-ID extraction
- [ ] Implement deduplication logic
- [ ] Add progress tracking
- [ ] Test with malformed mbox files

**Week 5-6: Search & Polish**
- [ ] Implement metadata search
- [ ] Add query syntax parser
- [ ] Create Rich UI for results
- [ ] Documentation updates
- [ ] Release candidate testing

---

### Version 1.2.0 - "Search" 🟡 HIGH

**Timeline:** 2-3 weeks
**Theme:** Advanced search and discovery
**Status:** Planned

#### Features

1. **Full-Text Search (FTS5)**
   ```bash
   gmailarchiver search "project timeline" --fuzzy
   gmailarchiver search "important AND meeting" --highlight
   ```
   - Index email body content (not just metadata)
   - Boolean operators: AND, OR, NOT, parentheses
   - Fuzzy matching (stemming, synonyms)
   - Relevance ranking
   - Snippet extraction with highlights

2. **Advanced Query Language**
   ```bash
   gmailarchiver search 'from:boss@company.com "quarterly review"'
   gmailarchiver search 'after:2023-01-01 before:2024-01-01 has:attachment'
   gmailarchiver search 'larger:5MB subject:invoice'
   ```
   - Gmail-compatible syntax
   - Date range queries
   - Size filters
   - Attachment queries
   - Label/tag filtering (future)

3. **Indexing Infrastructure**
   ```bash
   gmailarchiver index --rebuild
   gmailarchiver index --archive archive.mbox.zst
   gmailarchiver index --optimize
   ```
   - Background indexing for new archives
   - Manual indexing for imported archives
   - Index optimization (VACUUM, ANALYZE)
   - Progress tracking

4. **Export Formats**
   ```bash
   gmailarchiver export --search "project timeline" --format mbox
   gmailarchiver export --search "invoices" --format maildir
   gmailarchiver export <gmail-id> --format eml
   gmailarchiver export --all --format json
   ```
   - mbox (standard)
   - Maildir (alternative standard)
   - EML (individual messages)
   - JSON (programmatic access)

#### Success Criteria

- ✅ Search response < 100ms for metadata
- ✅ Search response < 500ms for full-text
- ✅ Support 1M+ indexed messages
- ✅ Export maintains data integrity
- ✅ Index rebuild < 10 minutes for 100k messages

---

### Version 2.0.0 - "Accessibility" 🟡 HIGH

**Timeline:** 4-6 weeks
**Theme:** Web UI and improved installation
**Status:** Planned

#### Features

1. **Installation Script** (Priority Score: 72.0)
   ```bash
   # One-liner installation
   curl -sSL https://install.gmailarchiver.io/install.sh | bash

   # Or for PowerShell on Windows
   irm https://install.gmailarchiver.io/install.ps1 | iex
   ```
   - Auto-detects OS and architecture
   - Installs uv if needed
   - Creates dedicated venv at `~/.gmailarchiver/venv`
   - Adds launcher to PATH
   - Reduces installation from 5+ steps to 1 command

2. **Web UI Backend (FastAPI)**
   - RESTful API for all operations
   - WebSocket for real-time progress
   - OAuth2 flow handling
   - CORS protection (local-only by default)
   - Auto-generated API docs (Swagger/ReDoc)

3. **Web UI Frontend (Svelte 5 + SvelteKit)**
   - **Technology Stack:**
     - Svelte 5 with SvelteKit for routing
     - Tailwind CSS for styling
     - shadcn-svelte for UI components
     - TypeScript for type safety

   - **Features:**
     - Search interface with real-time results
     - Email list view (virtualized for performance)
     - Email detail view with HTML rendering
     - Attachment preview and download
     - Dark mode support
     - Mobile-responsive design

4. **Serve Command** (`gmailarchiver serve`)
   ```bash
   gmailarchiver serve
   # Opens http://localhost:8080 in browser

   gmailarchiver serve --port 3000 --no-browser
   ```
   - Single command to start web UI
   - Auto-opens default browser
   - Background process management
   - Graceful shutdown (Ctrl+C)

5. **OAuth Flow in Web UI**
   - Browser-based OAuth consent
   - No manual credential file needed
   - Secure token storage
   - Multi-account support UI (future)

#### Architecture

```
src/gmailarchiver/web/
├── backend/
│   ├── api.py              # FastAPI app
│   ├── routes/
│   │   ├── auth.py
│   │   ├── search.py
│   │   ├── messages.py
│   │   └── archives.py
│   └── websocket.py        # Real-time updates
│
├── frontend/               # SvelteKit app (build-time only)
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte           # Search
│   │   │   ├── message/[id]/+page.svelte
│   │   │   └── settings/+page.svelte
│   │   ├── lib/
│   │   │   ├── components/
│   │   │   │   ├── EmailList.svelte
│   │   │   │   ├── EmailViewer.svelte
│   │   │   │   └── SearchBar.svelte
│   │   │   └── api.ts
│   │   └── app.html
│   └── package.json
│
└── static/                 # Built assets (included in wheel)
    ├── _app/
    ├── index.html
    └── favicon.png
```

#### Security

- **Binding:** 127.0.0.1 only (no remote access by default)
- **CSP Headers:** Prevent XSS attacks
- **HTML Email Rendering:** iframe with sandbox attribute
  ```html
  <iframe
    srcdoc="{emailHtml}"
    sandbox="allow-same-origin"
    style="width:100%;border:none;">
  </iframe>
  ```
- **CSRF Protection:** Token-based
- **Authentication:** None initially (local trust model)
- **Future:** Optional password for remote access

#### Success Criteria

- ✅ Installation reduced from 5+ steps to 1 command
- ✅ Web UI accessible to non-technical users
- ✅ Page load < 100ms
- ✅ Search results render < 200ms
- ✅ Pass security audit (no XSS, CSRF vulnerabilities)
- ✅ Mobile-responsive design

---

### Version 2.1.0 - "Distribution" 🟢 MEDIUM

**Timeline:** 2-3 weeks
**Theme:** Standalone executables
**Status:** Planned

#### Features

1. **PyInstaller Builds**
   ```bash
   # Build process (automated via GitHub Actions)
   pyinstaller gmailarchiver.spec
   ```
   - Standalone executables for:
     - macOS (Intel + Apple Silicon)
     - Windows (x64)
     - Linux (x64)
   - No Python installation required
   - Bundles all dependencies
   - Target size: < 100MB per platform

2. **Code Signing**
   - **macOS:** Apple Developer ID signing + notarization
   - **Windows:** Authenticode signing (prevents SmartScreen warnings)
   - Builds trust with users
   - Passes OS security checks

3. **Auto-Update Mechanism**
   ```python
   # Check for updates on startup
   if newer_version_available():
       prompt_user_to_update()
   ```
   - GitHub Releases API for version checking
   - One-click update process
   - Rollback capability

4. **GitHub Actions CI/CD**
   ```yaml
   # .github/workflows/release.yml
   - Build for macOS/Windows/Linux
   - Code signing
   - Upload to GitHub Releases
   - Publish to PyPI
   - Update download links
   ```

#### Success Criteria

- ✅ Executable size < 100MB
- ✅ Startup time < 2 seconds
- ✅ Pass macOS Gatekeeper
- ✅ No Windows SmartScreen warnings
- ✅ Auto-update success rate > 95%

---

### Version 3.0.0 - "Enterprise" 🔵 LOW

**Timeline:** Future (3-6 months)
**Theme:** Multi-account and advanced features
**Status:** Deferred

#### Features

1. **Multi-Account Support**
   ```bash
   gmailarchiver account add work@company.com
   gmailarchiver account add personal@gmail.com
   gmailarchiver account list
   gmailarchiver account default work@company.com

   # Use with any command
   gmailarchiver archive 1y --account personal
   gmailarchiver search "project" --account work
   ```

2. **Web UI Write Operations**
   - Archive triggering from UI
   - Schedule archiving
   - Configuration management
   - Delete/trash operations

3. **Thread Reconstruction**
   - Group emails by thread
   - Maintain conversation integrity
   - Visualize thread relationships

4. **Advanced Deduplication** (Optional)
   - Content-based fuzzy matching
   - Near-duplicate detection
   - User review before deletion

5. **Labels and Tags**
   - Preserve Gmail labels
   - User-defined tags
   - Filter by label/tag

6. **Scheduled Archiving**
   ```bash
   gmailarchiver schedule --every month --threshold 1y
   gmailarchiver schedule list
   gmailarchiver schedule disable
   ```

#### Note

Multi-account support is deferred per user request: "Can wait until search is implemented."

---

## 📊 Feature Prioritization Matrix

All proposed features ranked by ROI score:

**Formula:** `(User Value × Strategic Importance) / (Effort × Risk)`

| Feature | User Value | Strategic | Effort | Risk | **Score** | Priority |
|---------|-----------|-----------|--------|------|-----------|----------|
| Install script | 9 | 8 | 1 | 1 | **72.0** | 🔴 CRITICAL |
| Message-ID dedup | 10 | 9 | 2 | 1 | **45.0** | 🔴 CRITICAL |
| Metadata search | 9 | 9 | 3 | 1 | **27.0** | 🟡 HIGH |
| Enhanced index | 8 | 10 | 4 | 2 | **10.0** | 🔴 CRITICAL |
| Full-text search (FTS5) | 10 | 9 | 5 | 2 | **9.0** | 🟡 HIGH |
| Archive verification | 8 | 7 | 2 | 1 | **28.0** | 🟡 HIGH |
| Archive import | 10 | 10 | 3 | 2 | **16.7** | 🔴 CRITICAL |
| Web UI (Read-only) | 9 | 8 | 7 | 3 | **3.4** | 🟡 HIGH |
| Multi-account | 7 | 8 | 6 | 3 | **3.1** | 🔵 LOW |
| PyInstaller | 8 | 6 | 6 | 4 | **2.0** | 🟢 MEDIUM |
| Consolidate archives | 8 | 7 | 3 | 2 | **9.3** | 🟡 HIGH |
| Export formats | 7 | 6 | 3 | 2 | **7.0** | 🟢 MEDIUM |
| Thread preservation | 6 | 7 | 5 | 3 | **2.8** | 🔵 LOW |
| Fuzzy dedup | 5 | 4 | 6 | 8 | **0.4** | ⚪ AVOID |

### Priority Legend

- 🔴 **CRITICAL** - Must have for v1.1.0
- 🟡 **HIGH** - Important for v1.2.0 or v2.0.0
- 🟢 **MEDIUM** - Nice to have, schedule based on capacity
- 🔵 **LOW** - Defer to future versions
- ⚪ **AVOID** - High risk, low ROI

---

## ⚠️ Risk Assessment & Mitigation

### Critical Risks

#### 1. Data Loss During Migration (v1.0.x → v1.1.0)

**Probability:** Low
**Impact:** Critical
**Risk Score:** High

**Mitigation:**
- ✅ Automatic backup before migration (`.backup.{timestamp}`)
- ✅ Dry-run mode for testing migration
- ✅ Comprehensive test suite with real user data
- ✅ 2-week beta testing period with opt-in users
- ✅ Documented rollback procedure
- ✅ Migration validation step (verify counts match)

**Rollback Plan:**
```bash
# If migration fails
gmailarchiver rollback
# Restores from .backup file, drops new schema
```

#### 2. SQLite Performance at Scale

**Probability:** Medium
**Impact:** High
**Risk Score:** Medium-High

**Concerns:**
- Large mailboxes (1M+ messages)
- Database size growth
- Query performance degradation

**Mitigation:**
- ✅ Proper indexing strategy (see schema)
- ✅ Pagination everywhere (never load all results)
- ✅ Regular VACUUM ANALYZE
- ✅ Performance testing with 1M+ message dataset
- ✅ Query optimization (EXPLAIN QUERY PLAN)
- ✅ Consider sharding by year for very large archives (future)

**Performance Benchmarks:**
```python
# Target benchmarks
- Search (metadata): < 100ms
- Search (full-text): < 500ms
- Import: 100 messages/second
- Message retrieval (via mbox_offset): < 10ms
```

#### 3. XSS via HTML Email Rendering

**Probability:** Medium
**Impact:** High
**Risk Score:** Medium-High

**Attack Vectors:**
- Malicious JavaScript in HTML emails
- External resource loading (tracking pixels, fonts)
- CSS-based attacks

**Mitigation:**
- ✅ iframe sandboxing: `sandbox="allow-same-origin"`
- ✅ CSP headers: `script-src 'none'`
- ✅ No external resource loading
- ✅ DOMPurify or similar HTML sanitization (optional)
- ✅ Security audit before v2.0.0 release
- ✅ Plaintext fallback option

**Example Implementation:**
```html
<!-- Safe HTML email rendering -->
<iframe
  srcdoc="{sanitizedHtml}"
  sandbox="allow-same-origin"
  csp="default-src 'none'; style-src 'unsafe-inline'"
  style="width:100%;border:none;">
</iframe>
```

### Medium Risks

#### 4. Installation Complexity (Web UI)

**Probability:** Medium
**Impact:** Medium
**Risk Score:** Medium

**Concerns:**
- Web UI requires Node.js at build time
- Frontend bundling complexity
- Cross-platform compatibility

**Mitigation:**
- ✅ Pre-built static assets included in wheel (no Node.js at runtime)
- ✅ Fallback to CLI if web UI fails
- ✅ Clear error messages for missing dependencies
- ✅ One-line install script handles all setup

#### 5. mbox Lock File Management

**Probability:** Low
**Impact:** Medium
**Risk Score:** Low-Medium

**Known Issue:** `.lock.lock` files can accumulate if process crashes

**Mitigation:**
- ✅ Defensive cleanup before/after mbox operations
- ✅ Exception handling with finally blocks
- ✅ Lock file detection and removal on startup

### Low Risks

#### 6. Malformed mbox Files During Import

**Probability:** High
**Impact:** Low
**Risk Score:** Low

**Mitigation:**
- ✅ Robust parser with error recovery
- ✅ Skip malformed messages with warning
- ✅ Report skipped messages to user
- ✅ Continue import rather than fail completely

---

## 📈 Success Metrics

### Version 1.1.0 Metrics

**Performance:**
- ✅ Import: 10,000 messages in < 60 seconds
- ✅ Deduplication: 100% accuracy on Message-ID matching
- ✅ Search (metadata): < 100ms response time
- ✅ Database migration: < 2 minutes for 100k messages

**Quality:**
- ✅ Test coverage: Maintain 95%+ (currently 96%)
- ✅ Migration success rate: 100% (zero data loss)
- ✅ Type checking: 100% mypy strict compliance
- ✅ Linting: Zero ruff violations

**User Experience:**
- ✅ CLI responsiveness: All commands feel instant (< 500ms perceived)
- ✅ Progress tracking: Real-time updates for long operations
- ✅ Error messages: Clear, actionable guidance

### Version 1.2.0 Metrics

**Performance:**
- ✅ Full-text search: < 500ms for 1M messages
- ✅ Index building: < 10 minutes for 100k messages
- ✅ Export: 1000 messages/second

**Functionality:**
- ✅ Search recall: > 95% (find expected results)
- ✅ Search precision: > 90% (relevant results only)
- ✅ Export integrity: 100% (no data corruption)

### Version 2.0.0 Metrics

**Accessibility:**
- ✅ Installation time: < 2 minutes (from 10+ minutes)
- ✅ Installation success rate: > 95% (first-try success)
- ✅ Web UI adoption: > 50% of users try web UI

**Performance:**
- ✅ Web UI page load: < 100ms
- ✅ Search results render: < 200ms
- ✅ Email viewer load: < 500ms

**Security:**
- ✅ Security audit: Zero high/critical vulnerabilities
- ✅ XSS tests: 100% pass rate
- ✅ CSRF protection: Enabled and tested

### Version 2.1.0 Metrics

**Distribution:**
- ✅ Executable size: < 100MB per platform
- ✅ Startup time: < 2 seconds cold start
- ✅ Gatekeeper pass rate: 100% (macOS)
- ✅ SmartScreen warnings: 0% (Windows with signing)

**User Experience:**
- ✅ Auto-update success: > 95%
- ✅ User satisfaction: Post-launch survey (target: 4.5/5)

---

## 🛠️ Implementation Guidelines

### Development Standards

All code must adhere to existing quality standards:

- **Line length:** 100 characters (ruff)
- **Target version:** Python 3.14+
- **Type checking:** Strict mypy (all functions typed)
- **Test coverage:** 95%+ (currently 96%)
- **Linting:** ruff with rules E, F, I, N, W, UP
- **Documentation:** All public APIs documented

### Testing Strategy

**Unit Tests:**
- All business logic functions
- Mock external dependencies (Gmail API, filesystem)
- Parameterized tests for edge cases

**Integration Tests:**
- Database migrations
- mbox import/export workflows
- Search functionality end-to-end

**Security Tests:**
- Path traversal attempts
- XSS attack vectors
- SQL injection (via FTS5 queries)

**Performance Tests:**
- Import 100k messages
- Search 1M message database
- Concurrent operations

### Code Review Checklist

Before merging any feature:

- [ ] All tests pass (pytest)
- [ ] Test coverage maintained (95%+)
- [ ] Type checking passes (mypy)
- [ ] Linting passes (ruff)
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Security considerations reviewed
- [ ] Performance impact assessed

---

## 🎯 Next Steps

### Immediate Actions (Week 1)

1. **Review and Approve Plan**
   - Validate architectural decisions
   - Confirm roadmap priorities
   - Approve technology choices

2. **Set Up Project Board**
   - Create GitHub project for v1.1.0
   - Break down features into issues
   - Assign initial tasks

3. **Begin v1.1.0 Sprint 1**
   - Design migration script
   - Implement enhanced schema
   - Write migration tests

### First Sprint Checklist (Week 1-2)

**Schema & Migration:**
- [ ] Design comprehensive migration script
- [ ] Add `mbox_offset` tracking to archiver.py
- [ ] Implement FTS5 table creation
- [ ] Write migration tests (happy path + edge cases)
- [ ] Test with real user data (10k+ messages)
- [ ] Document rollback procedure

**Tooling:**
- [ ] Add migration command: `gmailarchiver migrate`
- [ ] Add schema inspection: `gmailarchiver db info`
- [ ] Add backup command: `gmailarchiver backup`

**Documentation:**
- [ ] Update CONTRIBUTING.md with new schema
- [ ] Document migration process
- [ ] Add troubleshooting guide

---

## 📚 References

### Industry Research

- **Email Archiving Best Practices:** RFC 4155 (mbox), RFC 5322 (Internet Message Format)
- **Competing Tools:** MailStore, Thunderbird, Aid4Mail
- **User Pain Points:** Lack of search (#1), difficult installation, poor performance at scale

### Technology Stack

- **SQLite FTS5:** https://www.sqlite.org/fts5.html
- **FastAPI:** https://fastapi.tiangolo.com/
- **Svelte 5:** https://svelte.dev/
- **shadcn-svelte:** https://www.shadcn-svelte.com/
- **PyInstaller:** https://pyinstaller.org/

### Standards Compliance

- **RFC 4155:** mbox format specification
- **RFC 5322:** Internet Message Format
- **RFC 2822:** Message-ID specification (deduplication key)

---

## 📝 Changelog

### 2025-11-14
- Initial strategic plan created
- Architectural decision: Hybrid model (mbox + SQLite)
- Roadmap defined: v1.1.0 → v1.2.0 → v2.0.0 → v2.1.0 → v3.0.0
- Prioritization matrix completed
- Risk assessment documented
- Success metrics defined

---

## 🤝 Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup and contribution guidelines.

For questions or discussions about this plan, open an issue on GitHub with the `planning` label.

---

**End of Strategic Plan**
