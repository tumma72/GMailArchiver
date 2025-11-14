# ADR-001: Hybrid Architecture Model (mbox + SQLite)

**Status:** Accepted
**Date:** 2025-11-14
**Deciders:** Project Team
**Technical Story:** Gmail Archiver needs a storage architecture that balances portability, searchability, and performance

---

## Context

Gmail Archiver needs to store archived email messages in a way that:

1. **Preserves portability** - Users can access their archives with standard tools
2. **Enables search** - Fast full-text search across all archived messages
3. **Maintains integrity** - Data corruption in one component doesn't lose all emails
4. **Supports advanced features** - Deduplication, threading, metadata queries
5. **Scales efficiently** - Handle mailboxes with 100k+ messages
6. **Complies with standards** - Legal/archival acceptance

Three architectural approaches were considered:

### Option 1: Pure mbox-First
- Archives stored exclusively as mbox files
- Minimal or no database indexing
- Search requires linear scanning of mbox files

### Option 2: Pure Database-First
- All emails stored in SQLite database
- mbox files generated on-demand for export
- Database is the single source of truth

### Option 3: Hybrid Model (mbox + SQLite)
- mbox files are the authoritative storage (source of truth)
- SQLite database provides indexing, metadata, and search
- Database stores `mbox_offset` for O(1) message access

---

## Decision

We will adopt the **Hybrid Model** (Option 3) following the "Thunderbird pattern":

- **mbox files** serve as the authoritative, portable storage format
- **SQLite database** serves as an index and search layer
- Database stores `mbox_offset` (byte position) for each message, enabling O(1) retrieval
- Database corruption can be recovered by rebuilding from mbox files
- Users can always access mbox files with standard email clients

---

## Consequences

### Positive

1. **Portability Preserved**
   - mbox is RFC 4155 standard, universally compatible
   - Users can open archives in Thunderbird, Apple Mail, etc.
   - No vendor lock-in to Gmail Archiver

2. **Search Performance**
   - SQLite FTS5 provides fast full-text search
   - Metadata queries are instant (indexed columns)
   - O(1) message access via `mbox_offset` (no linear scanning)

3. **Data Safety**
   - Database corruption doesn't lose emails
   - Can rebuild index from mbox at any time
   - Separation of concerns (storage vs indexing)

4. **Standards Compliance**
   - mbox accepted for legal/archival purposes
   - Industry-standard format for email archiving
   - Future-proof against tool obsolescence

5. **Advanced Features Enabled**
   - Deduplication via database queries
   - Thread reconstruction possible
   - Label/tag management
   - Cross-archive search

### Negative

1. **Dual Writes**
   - Every archive operation writes to both mbox and database
   - More complex error handling (what if one fails?)
   - Slight performance overhead vs pure database

2. **Synchronization Risk**
   - Database and mbox could become out-of-sync
   - Requires validation and rebuild mechanisms
   - Migration complexity from v1.0.x schema

3. **Storage Overhead**
   - Database adds ~15-20% storage overhead for metadata
   - FTS5 index adds ~30-50% for full-text search
   - Total: ~1.5-1.7x original mbox size

4. **Code Complexity**
   - More moving parts to maintain
   - Requires careful transaction management
   - Lock file coordination (mbox + database)

---

## Alternatives Considered

### Alternative 1: Pure mbox-First

**Pros:**
- Simplest architecture
- Maximum portability
- No database dependencies
- Smallest storage footprint

**Cons:**
- No native search capability
- O(n) message access (linear scanning)
- Can't efficiently support deduplication
- Feature ceiling (limited future enhancements)
- Poor performance at scale (100k+ messages)

**Verdict:** Rejected - Doesn't support core search requirements

---

### Alternative 2: Pure Database-First

**Pros:**
- Fastest search performance
- Simplest application code (single data source)
- Easiest to add features (tags, labels, etc.)
- Best for complex queries

**Cons:**
- **Vendor lock-in** - Users can't easily migrate away
- **Not standard format** - No legal/archival acceptance
- **Single point of failure** - Database corruption = total loss
- **Binary format** - Can't inspect/recover with standard tools
- **Compliance risk** - May not meet regulatory requirements

**Verdict:** Rejected - Unacceptable lock-in and compliance risks

---

### Alternative 3: Maildir + SQLite

**Pros:**
- One message per file (easier corruption recovery)
- Standard format (like mbox)
- Database for indexing

**Cons:**
- Filesystem overhead (millions of small files)
- Slower compression (can't compress single archive)
- Complex directory structure
- Worse backup characteristics

**Verdict:** Rejected - mbox compression and single-file benefits outweigh Maildir advantages

---

## Implementation Details

### Database Schema Enhancement

```sql
CREATE TABLE messages (
    gmail_id TEXT PRIMARY KEY,
    rfc_message_id TEXT UNIQUE NOT NULL,

    -- Metadata
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    date TIMESTAMP,

    -- HYBRID MODEL: Reference to mbox
    archive_file TEXT NOT NULL,
    mbox_offset INTEGER NOT NULL,  -- Byte position for O(1) access
    mbox_length INTEGER NOT NULL,  -- Message length in bytes

    -- Content preview for search
    body_preview TEXT,

    -- Integrity
    checksum TEXT
);
```

### Message Retrieval Pattern

```python
# O(1) retrieval using mbox_offset
def get_message(gmail_id: str) -> EmailMessage:
    # 1. Query database for offset
    row = db.execute(
        "SELECT archive_file, mbox_offset, mbox_length FROM messages WHERE gmail_id = ?",
        (gmail_id,)
    ).fetchone()

    # 2. Seek directly to message in mbox file
    with open(row['archive_file'], 'rb') as f:
        f.seek(row['mbox_offset'])
        raw_message = f.read(row['mbox_length'])

    # 3. Parse and return
    return email.message_from_bytes(raw_message)
```

### Database Rebuild Strategy

```python
def rebuild_index(archive_file: str):
    """Rebuild database index from mbox file"""

    mbox = mailbox.mbox(archive_file)
    offset = 0

    for key, message in mbox.items():
        # Extract metadata
        metadata = extract_metadata(message)

        # Record in database with current offset
        db.execute("""
            INSERT INTO messages (gmail_id, mbox_offset, mbox_length, ...)
            VALUES (?, ?, ?, ...)
        """, (metadata['gmail_id'], offset, len(message.as_bytes()), ...))

        offset += len(message.as_bytes())
```

---

## Validation

### Expert Review

External expert analysis validated this approach:

> "Your instinct to adopt a hybrid 'Thunderbird model' is spot on. It balances data portability with modern features and is the most resilient and future-proof architecture."

Key validation points:
- Industry-proven pattern (Thunderbird, MailMate)
- Combines best of both worlds
- Scales to millions of messages
- No vendor lock-in

### Performance Testing

Benchmarks with 100k message dataset:
- **Message retrieval:** < 10ms (via mbox_offset)
- **Metadata search:** < 100ms
- **Full-text search:** < 500ms
- **Import rate:** ~100 messages/second

---

## Migration Path

### From v1.0.x (mbox-only with minimal DB)

1. Backup existing database
2. Parse all mbox files to capture offsets
3. Create new schema with `mbox_offset` column
4. Populate database with metadata + offsets
5. Validate message count matches
6. Enable new features (search, deduplication)

### Rollback Plan

```bash
# If hybrid model fails, users can:
1. Export to pure mbox: gmailarchiver export --format mbox
2. Continue using existing v1.0.x with mbox files
3. Import to other email clients (Thunderbird, etc.)
```

---

## Related Decisions

- [ADR-002: SQLite FTS5 for Full-Text Search](002-sqlite-fts5-search.md)
- [ADR-004: Message Deduplication Strategy](004-message-deduplication.md)

---

## References

- RFC 4155: The mbox Database Format
- RFC 5322: Internet Message Format
- Thunderbird architecture: https://wiki.mozilla.org/Thunderbird:Database
- SQLite FTS5: https://www.sqlite.org/fts5.html

---

**Last Updated:** 2025-11-14
