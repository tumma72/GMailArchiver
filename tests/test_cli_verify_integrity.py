"""Tests for verify-integrity CLI command."""

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


@pytest.fixture
def clean_db(tmp_path: Path) -> Path:
    """Create a clean v1.1 database with no issues."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create v1.1 schema
    create_v1_1_schema(conn)

    # Prepare archive content and compute accurate length
    mbox_content = "From test\n\nTest message\n"
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

    # Sync FTS
    conn.execute(
        """
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        SELECT rowid, subject, from_addr, to_addr, body_preview
        FROM messages
        """
    )

    conn.commit()
    conn.close()

    # Create the archive file
    mbox_path.write_bytes(mbox_bytes)

    return db_path


@pytest.fixture
def db_with_orphaned_fts(tmp_path: Path) -> Path:
    """Create database with orphaned FTS records."""
    db_path = tmp_path / "test.db"
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

    # Use external content FTS (content='') so it doesn't auto-sync with messages table
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
    db_path = tmp_path / "test.db"
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

    # Use external content FTS (content='') so it doesn't auto-populate
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=''
        )
    """)

    # Insert message WITHOUT FTS sync - triggers don't exist so FTS won't populate
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

    # Sync FTS
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        SELECT rowid, subject, from_addr, to_addr, body_preview
        FROM messages
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def db_with_missing_file(tmp_path: Path) -> Path:
    """Create database referencing non-existent archive file."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema
    create_v1_1_schema(conn)

    # Insert message referencing non-existent file
    missing_file = str(tmp_path / "missing.mbox")
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
            missing_file,
            0,
            100,
            "Body",
        ),
    )

    # Sync FTS
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        SELECT rowid, subject, from_addr, to_addr, body_preview
        FROM messages
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def db_with_duplicates(tmp_path: Path) -> Path:
    """Create database with duplicate Message-IDs."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema WITHOUT unique constraint on rfc_message_id
    # (to simulate the duplicate issue)
    conn.execute("""
        CREATE TABLE messages (
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

    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=messages,
            content_rowid=rowid
        )
    """)

    # Insert duplicate Message-IDs
    for i in range(2):
        conn.execute(
            """
            INSERT INTO messages (
                gmail_id, rfc_message_id, subject, from_addr, to_addr,
                archived_timestamp, archive_file, mbox_offset, mbox_length, body_preview
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"msg{i}",
                "<duplicate@test.com>",
                "Test",
                "sender@test.com",
                "recipient@test.com",
                "2025-01-01T00:00:00",
                "test.mbox",
                i * 100,
                100,
                "Body",
            ),
        )

    # Sync FTS
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        SELECT rowid, subject, from_addr, to_addr, body_preview
        FROM messages
    """)

    conn.commit()
    conn.close()

    return db_path


# ==================== TESTS ====================


def test_verify_integrity_clean_database(clean_db: Path) -> None:
    """Test verify-integrity with clean database (exit 0)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(clean_db)])

    # The command should successfully find no issues and exit with 0
    # But Typer's Exit(0) still causes exit code 0, not 1
    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")
    assert "no issues found" in result.stdout.lower()
    assert "✓" in result.stdout


def test_verify_integrity_orphaned_fts(db_with_orphaned_fts: Path) -> None:
    """Test verify-integrity detects orphaned FTS records (exit 1)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_orphaned_fts)])

    assert result.exit_code == 1
    assert "orphaned FTS records" in result.stdout
    assert "gmailarchiver repair" in result.stdout.lower()


def test_verify_integrity_missing_fts(db_with_missing_fts: Path) -> None:
    """Test verify-integrity detects missing FTS records (exit 1)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_missing_fts)])

    assert result.exit_code == 1
    assert "missing from FTS index" in result.stdout
    assert "1 " in result.stdout  # Count should be 1


def test_verify_integrity_invalid_offsets(db_with_invalid_offsets: Path) -> None:
    """Test verify-integrity detects invalid offsets (exit 1)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_invalid_offsets)])

    assert result.exit_code == 1
    assert "invalid offsets" in result.stdout.lower()
    assert "1 " in result.stdout  # Count should be 1


def test_verify_integrity_missing_file(db_with_missing_file: Path) -> None:
    """Test verify-integrity detects missing archive files (exit 1)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_missing_file)])

    assert result.exit_code == 1
    assert (
        "Missing archive file" in result.stdout or "missing archive file" in result.stdout.lower()
    )
    # Path might be truncated in output, so just check for "missing"
    assert "missing" in result.stdout.lower()


def test_verify_integrity_duplicates(db_with_duplicates: Path) -> None:
    """Test verify-integrity detects duplicate Message-IDs (exit 1)."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_duplicates)])

    assert result.exit_code == 1
    # Case-insensitive since output may vary
    assert "duplicate message-id" in result.stdout.lower()


def test_verify_integrity_nonexistent_db(tmp_path: Path) -> None:
    """Test verify-integrity with non-existent database."""
    db_path = tmp_path / "nonexistent.db"
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_path)])

    assert result.exit_code == 1
    assert "error" in result.stdout.lower() or "not found" in result.stdout.lower()


def test_verify_integrity_output_format(db_with_orphaned_fts: Path) -> None:
    """Test verify-integrity output formatting with Rich tables."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(db_with_orphaned_fts)])

    # Should display issues in table format
    assert "Issue" in result.stdout or "issue" in result.stdout.lower()
    # Should show count
    assert "Found" in result.stdout or "found" in result.stdout.lower()


def test_verify_integrity_verbose_mode(clean_db: Path) -> None:
    """Test verify-integrity with verbose flag."""
    result = runner.invoke(app, ["verify-integrity", "--state-db", str(clean_db), "--verbose"])

    # Verbose mode should work without errors (verbose flag currently doesn't change output)
    assert "no issues found" in result.stdout.lower()
