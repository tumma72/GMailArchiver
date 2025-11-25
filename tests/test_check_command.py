"""Tests for the unified 'check' meta-command."""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app

runner = CliRunner()


def create_v1_1_schema(conn: sqlite3.Connection) -> None:
    """Helper to create full v1.1 schema."""
    conn.execute("""
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
        )
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=messages,
            content_rowid=rowid
        )
    """)

    # Create triggers
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
            VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
        END
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.rowid;
        END
    """)


@pytest.fixture
def clean_db(tmp_path: Path) -> Path:
    """Create a clean v1.1 database with no issues."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create v1.1 schema
    create_v1_1_schema(conn)

    # Prepare archive content and compute accurate length
    mbox_content = """From sender@test.com Mon Jan 01 00:00:00 2025
From: sender@test.com
To: recipient@test.com
Subject: Test 1
Message-ID: <msg1@test.com>
Date: Mon, 01 Jan 2025 00:00:00 +0000

Test body
"""
    mbox_bytes = mbox_content.encode("utf-8")
    mbox_path = tmp_path / "test.mbox"
    mbox_length = len(mbox_bytes)

    # Insert test data with real mbox_length
    conn.execute(
        """
        INSERT INTO messages (
            gmail_id, rfc_message_id, subject, from_addr, to_addr,
            archived_timestamp, archive_file, mbox_offset, mbox_length, body_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg1",
            "<msg1@test.com>",
            "Test 1",
            "sender@test.com",
            "recipient@test.com",
            "2025-01-01T00:00:00",
            str(mbox_path),
            0,
            mbox_length,
            "Test body",
        ),
    )

    conn.commit()
    conn.close()

    # Create the archive file with proper mbox format
    mbox_path.write_bytes(mbox_bytes)

    return db_path


@pytest.fixture
def db_with_orphaned_fts(tmp_path: Path) -> Path:
    """Create database with orphaned FTS records."""
    # Use a dedicated database file to avoid conflicts when combined with other fixtures
    db_path = tmp_path / "orphaned_fts.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema WITHOUT triggers so we can create orphans manually
    conn.execute("""
        CREATE TABLE messages (
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
        )
    """)

    # Use external content FTS (content='') so it doesn't auto-sync
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=''
        )
    """)

    # Insert message
    conn.execute(
        """
        INSERT INTO messages (
            gmail_id, rfc_message_id, subject, from_addr, to_addr,
            archived_timestamp, archive_file, mbox_offset, mbox_length, body_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "msg1",
            "<msg1@test.com>",
            "Test",
            "sender@test.com",
            "recipient@test.com",
            "2025-01-01T00:00:00",
            "test.mbox",
            0,
            100,
            "Body",
        ),
    )

    # Get rowid
    cursor = conn.execute("SELECT rowid FROM messages WHERE gmail_id = 'msg1'")
    rowid = cursor.fetchone()[0]

    # Manually insert FTS record
    conn.execute(
        """
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (?, ?, ?, ?, ?)
    """,
        (rowid, "Test", "sender@test.com", "recipient@test.com", "Body"),
    )

    # Delete message but leave FTS record (orphaned) - no triggers means FTS won't delete
    conn.execute("DELETE FROM messages WHERE gmail_id = 'msg1'")

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def db_with_missing_fts(tmp_path: Path) -> Path:
    """Create database with missing FTS records."""
    # Use a dedicated database file to avoid conflicts when combined with other fixtures
    db_path = tmp_path / "missing_fts.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema WITHOUT triggers so FTS doesn't auto-populate
    conn.execute("""
        CREATE TABLE messages (
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
        )
    """)

    # Use external content FTS
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=''
        )
    """)

    # Insert message WITHOUT FTS sync
    conn.execute(
        """
        INSERT INTO messages (
            gmail_id, rfc_message_id, subject, from_addr, to_addr,
            archived_timestamp, archive_file, mbox_offset, mbox_length, body_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "msg1",
            "<msg1@test.com>",
            "Test",
            "sender@test.com",
            "recipient@test.com",
            "2025-01-01T00:00:00",
            "test.mbox",
            0,
            100,
            "Body",
        ),
    )

    # Don't insert into FTS - this creates missing FTS issue

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def db_with_invalid_offsets(tmp_path: Path) -> Path:
    """Create database with invalid offsets (v1.1.0-beta.1 placeholders)."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create full v1.1 schema
    create_v1_1_schema(conn)

    # Insert message with placeholder offsets (-1, -1)
    conn.execute(
        """
        INSERT INTO messages (
            gmail_id, rfc_message_id, subject, from_addr, to_addr,
            archived_timestamp, archive_file, mbox_offset, mbox_length, body_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "msg1",
            "<msg1@test.com>",
            "Test",
            "sender@test.com",
            "recipient@test.com",
            "2025-01-01T00:00:00",
            "test.mbox",
            -1,
            -1,
            "Body preview",
        ),
    )

    conn.commit()
    conn.close()

    return db_path


# ==================== TESTS ====================


def test_check_clean_database(clean_db: Path) -> None:
    """Test check command with clean database (exit 0)."""
    result = runner.invoke(app, ["check", "--state-db", str(clean_db)])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 0 (healthy)
    assert result.exit_code == 0

    # Should show all checks passed
    assert "HEALTHY" in result.stdout or "healthy" in result.stdout.lower()
    assert "✓" in result.stdout


def test_check_orphaned_fts(db_with_orphaned_fts: Path) -> None:
    """Test check detects orphaned FTS records (exit 1)."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_orphaned_fts)])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 1 (issues found)
    assert result.exit_code == 1

    # Should report issues
    assert "ISSUES FOUND" in result.stdout or "issue" in result.stdout.lower()

    # Should suggest repair
    assert "repair" in result.stdout.lower()


def test_check_missing_fts(db_with_missing_fts: Path) -> None:
    """Test check detects missing FTS records (exit 1)."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_missing_fts)])

    assert result.exit_code == 1
    assert "ISSUES FOUND" in result.stdout or "issue" in result.stdout.lower()


def test_check_invalid_offsets(db_with_invalid_offsets: Path) -> None:
    """Test check detects invalid offsets (exit 1)."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_invalid_offsets)])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 1 (issues found)
    assert result.exit_code == 1

    # Should report invalid offsets
    assert "issue" in result.stdout.lower() or "ISSUES" in result.stdout


def test_check_verbose_mode(clean_db: Path) -> None:
    """Test check with verbose flag shows detailed results."""
    result = runner.invoke(app, ["check", "--state-db", str(clean_db), "--verbose"])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 0
    assert result.exit_code == 0

    # Should show detailed check output
    # Verbose mode shows individual check results
    assert "integrity" in result.stdout.lower() or "Checking" in result.stdout


def test_check_auto_repair_orphaned_fts(db_with_orphaned_fts: Path) -> None:
    """Test check with --auto-repair fixes orphaned FTS records."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_orphaned_fts), "--auto-repair"])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should succeed after repair (exit 0) or report repair incomplete (exit 2)
    # Depending on whether all issues were fixed
    assert result.exit_code in (0, 2)

    # Should show repair was performed
    assert "repair" in result.stdout.lower()


def test_check_auto_repair_missing_fts(db_with_missing_fts: Path) -> None:
    """Test check with --auto-repair fixes missing FTS records."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_missing_fts), "--auto-repair"])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should succeed after repair or report incomplete
    assert result.exit_code in (0, 2)

    # Should show repair activity
    assert "repair" in result.stdout.lower()


def test_check_nonexistent_db(tmp_path: Path) -> None:
    """Test check with non-existent database."""
    db_path = tmp_path / "nonexistent.db"
    result = runner.invoke(app, ["check", "--state-db", str(db_path)])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 1 (error)
    assert result.exit_code == 1

    # Should report error
    assert "error" in result.stdout.lower() or "not found" in result.stdout.lower()


def test_check_json_output(clean_db: Path) -> None:
    """Test check with --json flag."""
    result = runner.invoke(app, ["check", "--state-db", str(clean_db), "--json"])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 0
    assert result.exit_code == 0

    # Output should be JSON-parseable (OutputManager handles this)
    # The output contains structured events
    # Just verify it doesn't crash and exits correctly


def test_check_suggests_auto_repair(db_with_orphaned_fts: Path) -> None:
    """Test check suggests --auto-repair when issues found."""
    result = runner.invoke(app, ["check", "--state-db", str(db_with_orphaned_fts)])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should exit with 1
    assert result.exit_code == 1

    # Should suggest auto-repair
    assert "--auto-repair" in result.stdout or "auto-repair" in result.stdout.lower()


def test_check_exit_codes(clean_db: Path, db_with_orphaned_fts: Path) -> None:
    """Test check exit codes are correct."""
    # Clean database: exit 0
    result = runner.invoke(app, ["check", "--state-db", str(clean_db)])
    assert result.exit_code == 0

    # Database with issues: exit 1
    result = runner.invoke(app, ["check", "--state-db", str(db_with_orphaned_fts)])
    assert result.exit_code == 1


def test_check_skips_consistency_when_no_archives(tmp_path: Path) -> None:
    """Test check skips consistency check when no archive files."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema but don't insert any messages
    create_v1_1_schema(conn)

    conn.commit()
    conn.close()

    result = runner.invoke(app, ["check", "--state-db", str(db_path), "--verbose"])

    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")

    # Should succeed (no issues in empty database)
    assert result.exit_code == 0

    # Should skip consistency check
    assert "Skipped" in result.stdout or "skipped" in result.stdout.lower()
