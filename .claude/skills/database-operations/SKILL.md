---
name: database-operations
description: >-
  SQLite database, DBManager, HybridStorage, and schema operations for GMailArchiver.
  Use when working with database queries, transactions, mbox offsets, FTS5 search,
  or data integrity. Triggers on: database, SQLite, DBManager, HybridStorage,
  schema, transaction, mbox offset, FTS5, integrity, migration.
---

# Database Operations in GMailArchiver

This skill provides guidance on database operations for GMailArchiver.

## Source Documentation

**Always read the authoritative sources for current database design:**

1. **`src/gmailarchiver/data/ARCHITECTURE.md`** - Data layer architecture:
   - DBManager responsibilities and interface
   - HybridStorage atomic write patterns
   - SchemaManager version handling
   - Transaction management
   - Integrity validation

2. **`docs/ARCHITECTURE.md`** - System-wide data architecture:
   - Database schema (tables, columns, relationships)
   - FTS5 search index configuration
   - Data integrity architecture
   - Safety guarantees

3. **`CLAUDE.md`** - Quick reference:
   - Database schema summary
   - Key interfaces overview
   - CLI commands for database operations

## Key Components

Read these files for implementation details:
- `src/gmailarchiver/data/db_manager.py` - DBManager class
- `src/gmailarchiver/data/hybrid_storage.py` - HybridStorage class
- `src/gmailarchiver/data/schema_manager.py` - SchemaManager class

## Database CLI Commands

```bash
uv run gmailarchiver db-info           # Show database statistics
uv run gmailarchiver verify-integrity  # Check schema and constraints
uv run gmailarchiver verify-consistency # Check DB ↔ mbox sync
uv run gmailarchiver verify-offsets    # Validate mbox offsets
uv run gmailarchiver repair --backfill # Fix issues
```

## Usage

When working with database code:
1. Read `src/gmailarchiver/data/ARCHITECTURE.md` for current design
2. Check `docs/ARCHITECTURE.md` for schema details
3. If schema or patterns change, update the documentation (not this skill)

The source documentation is the **single source of truth** - this skill just points you there.
