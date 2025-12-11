"""Fixtures for CLI verification commands testing.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
"""

import sqlite3
from datetime import datetime

import pytest


@pytest.fixture
def v1_0_database(tmp_path):
    """Create a v1.0 database for testing."""
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

    # Insert sample data
    conn.execute("""
        INSERT INTO archived_messages VALUES
        ('msg1', '2025-01-01T12:00:00', 'test.mbox', 'Test 1', 'test@example.com',
         '2024-01-01T10:00:00', 'abc123')
    """)

    # Create archive_runs table
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def test_mbox(tmp_path):
    """Create a test mbox file with proper formatting."""
    import mailbox

    mbox_path = tmp_path / "test.mbox"

    # Create using mailbox library for proper formatting
    mbox = mailbox.mbox(str(mbox_path))

    msg_str = """From: test@example.com
To: recipient@example.com
Subject: Test 1
Message-ID: <msg1@test.com>

Test body
"""

    msg = mailbox.mboxMessage(msg_str)
    mbox.add(msg)
    mbox.close()

    return mbox_path


@pytest.fixture
def v1_1_database(tmp_path, test_mbox):
    """Create a v1.1 database for testing with accurate offsets.

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

        # Get actual message size from mbox
        message_size = test_mbox.stat().st_size

        # Insert sample data with accurate mbox_offset and length
        # Use the full path to archive file since validator uses self.archive_path
        conn.execute(
            """
            INSERT INTO messages VALUES
            ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             ?, 0, ?, 'Test body', 'abc123', ?, NULL, 'default')
        """,
            (str(test_mbox), message_size, message_size),
        )

        # Set schema version
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        conn.commit()
    finally:
        conn.close()

    return db_path
