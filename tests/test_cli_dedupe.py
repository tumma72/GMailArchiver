"""Tests for CLI deduplication commands.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from gmailarchiver.__main__ import app


def create_v1_1_db_with_duplicates(tmp_path: Path) -> Path:
    """
    Helper to create v1.1 database with known duplicates.

    Creates:
    - 3 messages with RFC ID <dup1@test.com> (2 duplicates)
    - 2 messages with RFC ID <dup2@test.com> (1 duplicate)
    - 1 message with unique RFC ID

    Total: 6 messages, 3 duplicate instances, 2 unique Message-IDs with duplicates
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    # Create v1.1 schema WITHOUT UNIQUE constraint on rfc_message_id (for testing duplicates)
    # But WITH all the other tables including FTS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT NOT NULL,
            thread_id TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            date TIMESTAMP,
            archived_timestamp TIMESTAMP NOT NULL,
            archive_file TEXT NOT NULL,
            mbox_offset INTEGER NOT NULL,
            mbox_length INTEGER NOT NULL,
            body_preview TEXT,
            checksum TEXT,
            size_bytes INTEGER,
            labels TEXT,
            account_id TEXT DEFAULT 'default'
        )
    """)

    # Create indexes (but not unique on rfc_message_id)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rfc_message_id ON messages(rfc_message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_file ON messages(archive_file)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_id ON messages(thread_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON messages(date)")

    # Create FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            subject, from_addr, to_addr, body_preview,
            content=messages,
            content_rowid=rowid
        )
    """)

    # Create archive_runs table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            operation TEXT NOT NULL DEFAULT 'archive',
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL
        )
    """)

    # Create schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            migrated_at TIMESTAMP NOT NULL
        )
    """)

    # Insert messages with duplicates
    # Group 1: 3 copies of <dup1@test.com>
    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail1', '<dup1@test.com>', 'thread1', 'Duplicate 1 Copy 1', 'sender@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         'archive1.mbox', 100, 500, 'Body 1', 'checksum1', 500, NULL, 'default')
    """)

    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail2', '<dup1@test.com>', 'thread1', 'Duplicate 1 Copy 2', 'sender@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-02T12:00:00',
         'archive2.mbox', 200, 600, 'Body 2', 'checksum2', 600, NULL, 'default')
    """)

    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail3', '<dup1@test.com>', 'thread1', 'Duplicate 1 Copy 3', 'sender@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-03T12:00:00',
         'archive1.mbox', 300, 800, 'Body 3', 'checksum3', 800, NULL, 'default')
    """)

    # Group 2: 2 copies of <dup2@test.com>
    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail4', '<dup2@test.com>', 'thread2', 'Duplicate 2 Copy 1', 'sender2@example.com',
         'recipient@example.com', NULL, '2024-01-02 10:00:00', '2025-01-04T12:00:00',
         'archive2.mbox', 400, 1000, 'Body 4', 'checksum4', 1000, NULL, 'default')
    """)

    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail5', '<dup2@test.com>', 'thread2', 'Duplicate 2 Copy 2', 'sender2@example.com',
         'recipient@example.com', NULL, '2024-01-02 10:00:00', '2025-01-05T12:00:00',
         'archive2.mbox', 500, 1200, 'Body 5', 'checksum5', 1200, NULL, 'default')
    """)

    # Unique message (no duplicates)
    conn.execute("""
        INSERT INTO messages VALUES
        ('gmail6', '<unique@test.com>', 'thread3', 'Unique Message', 'unique@example.com',
         'recipient@example.com', NULL, '2024-01-03 10:00:00', '2025-01-06T12:00:00',
         'archive1.mbox', 600, 700, 'Body 6', 'checksum6', 700, NULL, 'default')
    """)

    # Set schema version
    conn.execute("INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return db_path


def create_v1_0_database(tmp_path: Path) -> Path:
    """Create a v1.0 database (no rfc_message_id field)."""
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    # Create v1.0 schema (archived_messages table)
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)

    conn.commit()
    conn.close()

    return db_path


def create_v1_1_db_no_duplicates(tmp_path: Path) -> Path:
    """Create v1.1 database with no duplicates.

    Uses sync sqlite3 to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    try:
        # Create v1.1 schema (must match production schema exactly!)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            );
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                upgraded_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content='messages', content_rowid='rowid'
            );
        """)

        # Insert unique messages only
        conn.execute("""
            INSERT INTO messages VALUES
            ('gmail1', '<unique1@test.com>', 'thread1', 'Message 1', 'sender@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             'archive1.mbox', 100, 500, 'Body 1', 'checksum1', 500, NULL, 'default')
        """)

        conn.execute("""
            INSERT INTO messages VALUES
            ('gmail2', '<unique2@test.com>', 'thread2', 'Message 2', 'sender@example.com',
             'recipient@example.com', NULL, '2024-01-02 10:00:00', '2025-01-02T12:00:00',
             'archive1.mbox', 200, 600, 'Body 2', 'checksum2', 600, NULL, 'default')
        """)

        # Set schema version
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        conn.commit()
    finally:
        conn.close()

    return db_path


class TestDedupeCommand:
    """Test 'gmailarchiver dedupe' command."""

    def test_dedupe_dry_run_default(self, runner, tmp_path):
        """Test dedupe defaults to dry-run mode (safe)."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        result = runner.invoke(app, ["utilities", "dedupe", "--state-db", str(db_path)])

        assert result.exit_code == 0
        # Should indicate dry run
        assert "dry" in result.stdout.lower() or "preview" in result.stdout.lower()

        # Verify no messages were actually removed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 6  # All messages still present

    def test_dedupe_with_no_dry_run(self, runner, tmp_path):
        """Test dedupe with --no-dry-run removes duplicates."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        result = runner.invoke(
            app, ["utilities", "dedupe", "--state-db", str(db_path), "--no-dry-run"]
        )

        assert result.exit_code == 0
        assert "removed" in result.stdout.lower() or "deleted" in result.stdout.lower()

        # Verify duplicates were removed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 3  # Should keep 1 per duplicate group + 1 unique = 3 total

    # NOTE: User confirmation is not implemented in current CLI
    # Tests for confirmation would go here when feature is added

    # NOTE: --strategy option is not exposed in CLI yet (only in workflow config)
    # Tests for strategy would go here when CLI is updated

    def test_dedupe_no_duplicates(self, runner, tmp_path):
        """Test dedupe with no duplicates (early exit)."""
        db_path = create_v1_1_db_no_duplicates(tmp_path)

        result = runner.invoke(app, ["utilities", "dedupe", "--state-db", str(db_path)])

        assert result.exit_code == 0
        assert "No duplicate" in result.stdout or "no duplicate" in result.stdout

    def test_dedupe_v1_0_database_error(self, runner, tmp_path):
        """Test dedupe shows error for v1.0 database (no messages table)."""
        db_path = create_v1_0_database(tmp_path)

        result = runner.invoke(app, ["utilities", "dedupe", "--state-db", str(db_path)])

        # Currently crashes with "no such table: messages" error
        assert result.exit_code == 1
        assert "table" in result.stdout.lower() or "error" in result.stdout.lower()

    # NOTE: --auto-verify option is not exposed in CLI yet
    # Tests for auto-verify would go here when CLI is updated
