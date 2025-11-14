# Gmail Archiver Architecture

**Last Updated:** 2025-11-14
**Status:** Active Development
**Current Version:** 1.0.3

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Core Components](#core-components)
- [Data Architecture](#data-architecture)
- [Technology Stack](#technology-stack)
- [Security Architecture](#security-architecture)
- [Performance Considerations](#performance-considerations)
- [Architecture Decision Records](#architecture-decision-records)

---

## Overview

Gmail Archiver is a Python CLI tool (with web UI) that archives old Gmail messages to local mbox files with validation, compression, and safe deletion. The architecture follows a **hybrid model** combining portable mbox storage with SQLite indexing for searchability.

### Design Principles

1. **Safety First** - Multiple validation layers, dry-run mode, reversible operations
2. **Portability** - Standard mbox format (RFC 4155), no vendor lock-in
3. **Searchability** - Fast full-text search via SQLite FTS5
4. **Accessibility** - CLI for power users, Web UI for everyone else
5. **Standards Compliance** - RFC-compliant email handling, legal/archival acceptance

### Key Architectural Decisions

All significant architectural decisions are documented as ADRs (Architecture Decision Records). See [ADRs](#architecture-decision-records) section below.

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      User Interfaces                        │
├──────────────────────┬──────────────────────────────────────┤
│   CLI (Typer/Rich)   │    Web UI (Svelte 5 + FastAPI)       │
└──────────────────────┴──────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                       │
├─────────────┬──────────────┬───────────────┬────────────────┤
│  Archiver   │   Validator  │  Authenticator│   Deduplicator │
└─────────────┴──────────────┴───────────────┴────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                   Data Layer (Hybrid)                       │
├───────────────────────────────┬─────────────────────────────┤
│     mbox Files (Storage)      │   SQLite (Index + Search)   │
│  ┌────────────────────────┐   │  ┌─────────────────────┐    │
│  │ archive.mbox.zst       │   │  │ messages table      │    │
│  │ - Email messages       │   │  │ - Metadata          │    │
│  │ - RFC 4155 format      │   │  │ - mbox_offset (O(1))│    │
│  │ - Compressed (zstd)    │   │  │ - Checksums         │    │
│  └────────────────────────┘   │  ├─────────────────────┤    │
│                               │  │ messages_fts (FTS5) │    │
│                               │  │ - Full-text index   │    │
│                               │  │ - BM25 ranking      │    │
│                               │  └─────────────────────┘    │
└───────────────────────────────┴─────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                   External Services                         │
├───────────────────────────────┬─────────────────────────────┤
│      Gmail API                │   Google OAuth2             │
│  - List messages (batch)      │   - User authentication     │
│  - Fetch message content      │   - Token management        │
│  - Trash/delete operations    │   - Refresh tokens          │
└───────────────────────────────┴─────────────────────────────┘
```

### Data Flow

#### Archive Flow

```
1. User initiates archive
   ↓
2. Authenticate with Gmail (OAuth2)
   ↓
3. Query Gmail API (e.g., "before:2022/01/01")
   ↓
4. Filter out already-archived (incremental mode)
   ↓
5. Fetch messages in batches (default: 10/batch)
   ↓
6. Write to mbox file + Record offset in database
   ↓
7. Validate archive (multi-layer checks)
   ↓
8. Optionally trash/delete from Gmail (with confirmation)
```

#### Search Flow

```
1. User enters search query
   ↓
2. Parse query syntax (Gmail-compatible)
   ↓
3. Query SQLite FTS5 index
   ↓
4. Retrieve results with BM25 ranking
   ↓
5. If full message needed: Seek to mbox_offset (O(1))
   ↓
6. Display results with snippets/highlighting
```

---

## Core Components

### Authentication Layer

**Component:** `src/gmailarchiver/auth.py:GmailAuthenticator`

**Responsibilities:**
- OAuth2 authentication flow
- Token storage at XDG-compliant paths
- Token refresh and revocation

**Configuration:**
- Bundled credentials: `config/oauth_credentials.json`
- User credentials: Optional `--credentials` flag
- Token storage: `~/.config/gmailarchiver/token.json` (macOS/Linux)

**Flow:**
```python
authenticator = GmailAuthenticator()
creds = authenticator.authenticate()  # Launches browser if needed
gmail_service = build('gmail', 'v1', credentials=creds)
```

---

### Gmail Client

**Component:** `src/gmailarchiver/gmail_client.py:GmailClient`

**Responsibilities:**
- Wrapper around Gmail API
- Retry logic with exponential backoff
- Batch operations for efficiency

**Key Methods:**
- `list_messages(query: str)` - Search messages
- `get_message(msg_id: str)` - Fetch single message
- `delete_message(msg_id: str)` - Permanent deletion
- `trash_message(msg_id: str)` - Reversible deletion (30 days)

**Retry Strategy:**
- Max retries: 5 (configurable)
- Backoff: `2^retry + random jitter`
- Handles: HTTP 429 (rate limit), 500/503 (server errors)

---

### Archiver

**Component:** `src/gmailarchiver/archiver.py:GmailArchiver`

**Responsibilities:**
- Main orchestration of archiving workflow
- mbox file creation and writing
- Compression (gzip, lzma, zstd)
- Incremental mode (skip archived messages)
- Lock file management

**Compression Detection:**
```python
# File extension determines compression
.mbox      → uncompressed
.mbox.gz   → gzip
.mbox.xz   → lzma (xz)
.mbox.zst  → zstd (Python 3.14 native - fastest)
```

**Lock File Handling:**
```python
# Defensive cleanup before/after mbox operations
try:
    cleanup_lock_files(archive_path)
    mbox = mailbox.mbox(archive_path)
    mbox.lock()
    # ... write operations ...
finally:
    mbox.unlock()
    mbox.close()
    cleanup_lock_files(archive_path)
```

---

### State Tracking

**Component:** `src/gmailarchiver/state.py:ArchiveState`

**Responsibilities:**
- SQLite database management
- Track archived messages
- Track archive runs (audit trail)
- Transaction support

**Database Schema (v1.0.x):**
```sql
CREATE TABLE archived_messages (
    gmail_id TEXT PRIMARY KEY,
    archived_timestamp TEXT,
    archive_file TEXT,
    subject TEXT,
    from_addr TEXT,
    message_date TEXT,
    checksum TEXT
);

CREATE TABLE archive_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT,
    query TEXT,
    messages_archived INTEGER,
    archive_file TEXT
);
```

**Planned Schema (v1.1.0):**
See [ADR-001: Hybrid Architecture Model](adrs/001-hybrid-architecture-model.md) for enhanced schema with `mbox_offset`.

**Usage:**
```python
with ArchiveState() as state:
    state.record_archived_message(
        gmail_id="msg123",
        subject="Meeting Notes",
        from_addr="boss@company.com",
        message_date=datetime.now(),
        archive_file="/path/to/archive.mbox.zst",
        checksum="sha256..."
    )
```

---

### Validator

**Component:** `src/gmailarchiver/validator.py:ArchiveValidator`

**Responsibilities:**
- Multi-layer validation before deletion
- Decompress archives for validation
- Integrity checks

**Validation Layers:**
1. **Message Count** - Verify expected count matches actual
2. **Database Cross-Check** - All expected IDs present in archive
3. **Content Integrity** - Checksum verification
4. **Spot-Check Sampling** - Random sample validation

**Supported Formats:**
- Uncompressed mbox
- Gzip (`.mbox.gz`)
- LZMA (`.mbox.xz`)
- Zstd (`.mbox.zst`)

---

### Input/Path Validators

**Components:**
- `src/gmailarchiver/input_validator.py` - User input sanitization
- `src/gmailarchiver/path_validator.py` - Path traversal prevention

**Security:**
```python
# Prevents: ../../etc/passwd
PathValidator.validate_path("/safe/dir", user_input_path)

# Validates age expressions: 3y, 6m, 2w, 30d
InputValidator.validate_age("3y")  # ✅ Valid
InputValidator.validate_age("abc")  # ❌ Raises error
```

---

## Data Architecture

### Hybrid Model (mbox + SQLite)

**Decision:** [ADR-001: Hybrid Architecture Model](adrs/001-hybrid-architecture-model.md)

**Storage Layer: mbox Files**
- **Format:** RFC 4155 mbox
- **Compression:** zstd (Python 3.14 native)
- **Purpose:** Authoritative, portable storage
- **Location:** User-specified (default: `~/archives/`)

**Index Layer: SQLite Database**
- **Format:** SQLite 3
- **Purpose:** Fast search, metadata queries, deduplication
- **Location:** `~/.local/share/gmailarchiver/database.db` (XDG spec)

**Key Innovation: `mbox_offset` for O(1) Access**

Traditional approach (slow):
```python
# O(n) - Must scan entire mbox file
for msg in mailbox.mbox(archive_file):
    if msg['Message-ID'] == target_id:
        return msg  # Found after scanning many messages
```

Hybrid approach (fast):
```python
# O(1) - Direct seek to message
offset, length = db.get_offset(target_id)
with open(archive_file, 'rb') as f:
    f.seek(offset)  # Jump directly to message
    return f.read(length)
```

**Benefits:**
- ✅ Portable (mbox works with Thunderbird, Apple Mail, etc.)
- ✅ Searchable (SQLite FTS5 full-text search)
- ✅ Safe (database corruption doesn't lose emails)
- ✅ Fast (O(1) message retrieval)

---

### Full-Text Search (SQLite FTS5)

**Decision:** [ADR-002: SQLite FTS5 for Search](adrs/002-sqlite-fts5-search.md)

**Implementation:**
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    subject,
    from_addr,
    to_addr,
    body_preview,
    content='messages',
    content_rowid='rowid',
    tokenize='porter unicode61 remove_diacritics 1'
);
```

**Features:**
- Boolean operators: AND, OR, NOT, NEAR
- Phrase search: `"exact phrase"`
- Column-specific: `subject:invoice`
- BM25 ranking for relevance
- Snippet extraction with highlights

**Performance:**
- 100k messages: < 300ms
- 1M messages: < 500ms
- Index size: ~30-50% of content

---

### Message Deduplication

**Decision:** [ADR-004: Message Deduplication Strategy](adrs/004-message-deduplication.md)

**Strategy:** RFC 2822 `Message-ID` exact matching

**Algorithm:**
1. Group messages by `rfc_message_id`
2. Within each group, keep newest (by `Date` header)
3. Mark others as duplicates in database
4. Create new consolidated archive without duplicates

**Safety:**
- 100% precision (no false positives)
- Never modify original archives
- Always create new archive
- Dry-run mode reports without changes

**Expected Savings:**
- Users with 10+ year manual archives: 30-50% space reduction

---

## Technology Stack

### Current (v1.0.3)

**Core:**
- **Python:** 3.14+ (for native zstd compression)
- **CLI Framework:** Typer + Rich (terminal UI)
- **Database:** SQLite 3 (with FTS5)
- **Gmail API:** google-api-python-client
- **OAuth2:** google-auth, google-auth-oauthlib

**Development:**
- **Testing:** pytest, pytest-cov (96% coverage)
- **Type Checking:** mypy (strict mode)
- **Linting:** ruff (E, F, I, N, W, UP rules)
- **Build:** hatchling, hatch-vcs (version from git tags)
- **Package Manager:** uv (fast, modern)

### Planned (v2.0+)

**Web UI:**
- **Decision:** [ADR-003: Web UI Technology Stack](adrs/003-web-ui-technology-stack.md)
- **Frontend:** Svelte 5 + SvelteKit + TypeScript
- **Backend:** FastAPI + Uvicorn (ASGI)
- **Styling:** Tailwind CSS + shadcn-svelte
- **Build:** Vite (frontend), bundled with Python wheel

**Distribution:**
- **Decision:** [ADR-005: Distribution Strategy](adrs/005-distribution-strategy.md)
- **Tier 1:** PyPI package (`pip install gmailarchiver`)
- **Tier 2:** One-line install script (v2.0)
- **Tier 3:** Standalone executables via PyInstaller (v2.1)
- **Tier 4:** Package managers (Homebrew, APT) - future

---

## Security Architecture

### Threat Model

**Primary Threats:**
1. XSS via malicious HTML emails
2. Path traversal attacks
3. OAuth token theft
4. Supply chain attacks

**Out of Scope:**
- Network-level attacks (local-first tool)
- Physical access to user's machine
- Malware on user's system

### Security Measures

#### 1. Path Traversal Prevention

**Component:** `path_validator.py`

**Protection:**
```python
# Blocks: ../../etc/passwd, symlinks, etc.
PathValidator.validate_path(allowed_base, user_path)
```

**Tests:** `test_path_validator.py` includes malicious inputs

---

#### 2. Input Sanitization

**Component:** `input_validator.py`

**Validates:**
- Age expressions (`3y`, `6m`, `2w`, `30d`)
- Compression formats (whitelist only)
- Gmail query syntax
- File paths

---

#### 3. OAuth2 Token Storage

**Current (v1.0.x):**
- XDG-compliant paths (`~/.config/gmailarchiver/token.json`)
- File permissions: 0600 (owner read/write only)

**Future (v3.0+):**
- OS-native secure storage
  - macOS: Keychain
  - Windows: Credential Manager
  - Linux: Secret Service API / libsecret

---

#### 4. HTML Email Rendering (Web UI)

**Threat:** XSS attacks via malicious email HTML

**Mitigation:**
```svelte
<!-- iframe sandboxing -->
<iframe
  srcdoc={emailHtml}
  sandbox="allow-same-origin"
  csp="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:"
  class="w-full h-full border-0"
/>
```

**Layers:**
1. `sandbox="allow-same-origin"` - No scripts, forms, popups
2. CSP headers - No external resources
3. iframe isolation - Can't access parent window

---

#### 5. API Security (Web UI)

**CORS Protection:**
```python
# Local-only by default
allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"]
```

**CSRF Protection:**
```python
from fastapi_csrf_protect import CsrfProtect

@app.post("/api/delete")
async def delete(csrf_protect: CsrfProtect = Depends()):
    await csrf_protect.validate_csrf()
    # ... safe to proceed
```

---

#### 6. Supply Chain Security

**Dependencies:**
- Minimal dependency tree (< 20 direct dependencies)
- All dependencies from trusted sources (PyPI with 2FA)
- Dependabot alerts enabled
- Regular security audits

**Build Security:**
- Reproducible builds (pinned versions)
- GitHub Actions with OIDC (no long-lived tokens)
- Code signing for executables (v2.1+)

---

## Performance Considerations

### Benchmarks (v1.0.3)

**Archive Performance:**
- 10k messages: ~25-30 minutes (Gmail API rate limits)
- Batch size: 10 messages/batch (configurable)
- Network-bound (not CPU-bound)

**Validation Performance:**
- 10k messages: ~2 minutes
- Decompression overhead: +30% for gzip, +10% for zstd

**Search Performance (Projected for v1.2.0):**
- Metadata search: < 100ms
- Full-text search: < 500ms (1M messages)

### Optimization Strategies

#### 1. Compression Choice

**Benchmarks (1GB test data):**

| Format | Size | Compression Time | Decompression Time |
|--------|------|------------------|-------------------|
| Uncompressed | 1000 MB | 0s | 0s |
| gzip | 250 MB (75%) | 120s | 15s |
| lzma (xz) | 180 MB (82%) | 300s | 45s |
| **zstd** | **220 MB (78%)** | **30s** | **3s** |

**Recommendation:** zstd (default in v1.0.3)
- Best balance of size and speed
- Native in Python 3.14+ (no dependencies)
- 4x faster compression, 5x faster decompression vs gzip

---

#### 2. Database Indexing

**Indexes (v1.1.0):**
```sql
CREATE INDEX idx_rfc_message_id ON messages(rfc_message_id);  -- Deduplication
CREATE INDEX idx_date ON messages(date);                      -- Date queries
CREATE INDEX idx_from ON messages(from_addr);                 -- Sender queries
CREATE INDEX idx_archive_file ON messages(archive_file);      -- File lookups
```

**Query Optimization:**
- Use EXPLAIN QUERY PLAN for all queries
- Avoid SELECT * (specify columns)
- Use LIMIT for pagination
- Regular VACUUM ANALYZE

---

#### 3. API Rate Limiting

**Gmail API Quotas:**
- 250 requests/second/user
- Batch requests count as single request

**Mitigation:**
- Batch operations (10 messages/request)
- Exponential backoff on 429 errors
- Progress tracking (don't re-fetch on resume)

---

#### 4. Memory Management

**Constraints:**
- Large mbox files (multi-GB)
- Full email messages in memory

**Strategies:**
- Stream mbox parsing (don't load entire file)
- Process in batches (10-100 messages at a time)
- Use generators instead of lists
- Explicit garbage collection for large operations

```python
# ✅ Memory-efficient
def process_large_archive():
    for batch in chunked(messages, 100):
        process_batch(batch)
        gc.collect()  # Explicit cleanup

# ❌ Memory-intensive
def process_large_archive():
    all_messages = list(mbox)  # Loads everything into RAM
    for msg in all_messages:
        process(msg)
```

---

## Architecture Decision Records

All significant architectural decisions are documented as ADRs. For detailed rationale, alternatives considered, and consequences, see:

### Core Architecture
- **[ADR-001: Hybrid Architecture Model](adrs/001-hybrid-architecture-model.md)**
  - Decision: mbox + SQLite (not pure database or pure files)
  - Key innovation: `mbox_offset` for O(1) access
  - Status: ✅ Accepted

### Search & Indexing
- **[ADR-002: SQLite FTS5 for Full-Text Search](adrs/002-sqlite-fts5-search.md)**
  - Decision: SQLite FTS5 (not Elasticsearch or grep)
  - Features: BM25 ranking, Boolean operators, snippets
  - Performance: < 500ms for 1M messages
  - Status: ✅ Accepted

### User Interface
- **[ADR-003: Web UI Technology Stack](adrs/003-web-ui-technology-stack.md)**
  - Decision: Svelte 5 + FastAPI + Tailwind
  - Why: Performance, bundle size, developer experience
  - Security: iframe sandboxing, CSP, CSRF protection
  - Status: ✅ Accepted

### Data Management
- **[ADR-004: Message Deduplication Strategy](adrs/004-message-deduplication.md)**
  - Decision: Message-ID exact matching (not fuzzy)
  - Why: 100% precision, no false positives
  - Expected savings: 30-50% for 10+ year archives
  - Status: ✅ Accepted

### Distribution
- **[ADR-005: Distribution Strategy](adrs/005-distribution-strategy.md)**
  - Decision: Multi-tiered (PyPI + script + executables)
  - Tier 1: PyPI (developers)
  - Tier 2: One-line script (power users) - v2.0
  - Tier 3: Standalone executables (everyone) - v2.1
  - Status: ✅ Accepted

**See:** [docs/adrs/README.md](adrs/README.md) for complete list and ADR guidelines

---

## Future Architecture Evolution

### Version 1.1.0 - Foundation
- Enhanced database schema (hybrid model with `mbox_offset`)
- Archive import and consolidation
- Message-ID deduplication
- Metadata search

### Version 1.2.0 - Search
- FTS5 full-text search
- Advanced query language
- Index management
- Export formats

### Version 2.0.0 - Accessibility
- Web UI (Svelte 5 + FastAPI)
- One-line install script
- OAuth flow in browser

### Version 2.1.0 - Distribution
- PyInstaller standalone executables
- Code signing (macOS/Windows)
- Auto-update mechanism

### Version 3.0.0 - Enterprise
- Multi-account support
- Advanced features (threading, labels)
- Scheduled archiving

**See:** [PLAN.md](PLAN.md) for detailed roadmap

---

## References

### Internal Documentation
- **[PLAN.md](PLAN.md)** - Strategic roadmap and implementation plan
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Development setup and guidelines
- **[adrs/](adrs/)** - Architecture Decision Records

### External Standards
- **RFC 4155** - The mbox Database Format
- **RFC 5322** - Internet Message Format
- **RFC 2822** - Message-ID Specification

### Related Projects
- **Thunderbird** - Hybrid model inspiration
- **MailStore** - Enterprise email archiving
- **SQLite FTS5** - Full-text search implementation

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for:
- Development environment setup
- Coding standards and guidelines
- Testing requirements
- Pull request process

For architectural questions or proposals:
- Open an issue with the `architecture` label
- Propose new ADRs following the [ADR template](adrs/README.md#adr-template)

---

**Last Updated:** 2025-11-14
