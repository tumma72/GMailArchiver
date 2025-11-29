"""Tests for CLI verification commands."""

import sqlite3
from datetime import datetime

import pytest
from typer.testing import CliRunner

from gmailarchiver.data.migration import MigrationManager


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


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
    """Create a v1.1 database for testing with accurate offsets."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema
    manager._create_enhanced_schema(manager.conn)

    # Get actual message size from mbox
    message_size = test_mbox.stat().st_size

    # Insert sample data with accurate mbox_offset and length
    # Use the full path to archive file since validator uses self.archive_path
    manager.conn.execute(
        """
        INSERT INTO messages VALUES
        ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         ?, 0, ?, 'Test body', 'abc123', ?, NULL, 'default')
    """,
        (str(test_mbox), message_size, message_size),
    )

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path
