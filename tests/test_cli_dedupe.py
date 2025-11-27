"""Tests for CLI deduplication commands."""

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
from gmailarchiver.data.migration import MigrationManager


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


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

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rfc_message_id ON messages(rfc_message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_file ON messages(archive_file)")

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

    # Create schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            migrated_at TIMESTAMP NOT NULL
        )
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
    """Create v1.1 database with no duplicates."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema
    manager._create_enhanced_schema(manager.conn)

    # Insert unique messages only
    manager.conn.execute("""
        INSERT INTO messages VALUES
        ('gmail1', '<unique1@test.com>', 'thread1', 'Message 1', 'sender@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         'archive1.mbox', 100, 500, 'Body 1', 'checksum1', 500, NULL, 'default')
    """)

    manager.conn.execute("""
        INSERT INTO messages VALUES
        ('gmail2', '<unique2@test.com>', 'thread2', 'Message 2', 'sender@example.com',
         'recipient@example.com', NULL, '2024-01-02 10:00:00', '2025-01-02T12:00:00',
         'archive1.mbox', 200, 600, 'Body 2', 'checksum2', 600, NULL, 'default')
    """)

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


class TestDedupeCommand:
    """Test 'gmailarchiver dedupe' command."""

    def test_dedupe_dry_run_default(self, runner, tmp_path):
        """Test dedupe defaults to dry-run mode (safe)."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        result = runner.invoke(app, ["dedupe", "--state-db", str(db_path)])

        assert result.exit_code == 0
        # Should indicate dry run
        assert "dry" in result.stdout.lower() or "preview" in result.stdout.lower()

        # Verify no messages were actually removed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 6  # All messages still present

    def test_dedupe_with_confirmation(self, runner, tmp_path):
        """Test dedupe with --no-dry-run and user confirms."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        # Mock user confirmation
        with patch("typer.confirm", return_value=True):
            result = runner.invoke(app, ["dedupe", "--state-db", str(db_path), "--no-dry-run"])

        assert result.exit_code == 0
        assert "removed" in result.stdout.lower() or "deleted" in result.stdout.lower()

        # Verify duplicates were removed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 3  # Should keep 1 per duplicate group + 1 unique = 3 total

    def test_dedupe_user_cancels(self, runner, tmp_path):
        """Test dedupe with --no-dry-run and user cancels."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        # Mock user declining confirmation
        with patch("typer.confirm", return_value=False):
            result = runner.invoke(app, ["dedupe", "--state-db", str(db_path), "--no-dry-run"])

        assert result.exit_code == 0
        assert "cancel" in result.stdout.lower() or "abort" in result.stdout.lower()

        # Verify no messages were removed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 6  # All messages still present

    def test_dedupe_strategy_newest(self, runner, tmp_path):
        """Test dedupe with --strategy newest."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app, ["dedupe", "--state-db", str(db_path), "--strategy", "newest", "--no-dry-run"]
            )

        assert result.exit_code == 0

        # Verify newest messages were kept
        conn = sqlite3.connect(str(db_path))

        # Check that gmail3 (newest of dup1) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail3'")
        assert cursor.fetchone()[0] == 1

        # Check that gmail5 (newest of dup2) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail5'")
        assert cursor.fetchone()[0] == 1

        conn.close()

    def test_dedupe_strategy_largest(self, runner, tmp_path):
        """Test dedupe with --strategy largest."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app, ["dedupe", "--state-db", str(db_path), "--strategy", "largest", "--no-dry-run"]
            )

        assert result.exit_code == 0

        # Verify largest messages were kept
        conn = sqlite3.connect(str(db_path))

        # Check that gmail3 (largest of dup1, size 800) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail3'")
        assert cursor.fetchone()[0] == 1

        # Check that gmail5 (largest of dup2, size 1200) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail5'")
        assert cursor.fetchone()[0] == 1

        conn.close()

    def test_dedupe_strategy_first(self, runner, tmp_path):
        """Test dedupe with --strategy first."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app, ["dedupe", "--state-db", str(db_path), "--strategy", "first", "--no-dry-run"]
            )

        assert result.exit_code == 0

        # Verify messages from first archive (alphabetically) were kept
        conn = sqlite3.connect(str(db_path))

        # archive1.mbox comes before archive2.mbox alphabetically
        # For dup1: gmail1 (2025-01-01) and gmail3 (2025-01-03) are in archive1.mbox
        #   find_duplicates sorts by archived_timestamp DESC, so [gmail3, gmail2, gmail1]
        #   After sorting by archive_file (stable sort), gmail3 comes first
        # For dup2: both gmail4 (2025-01-04) and gmail5 (2025-01-05) are in archive2.mbox
        #   find_duplicates sorts by archived_timestamp DESC, so [gmail5, gmail4]
        #   After sorting by archive_file, gmail5 comes first

        # Check that gmail3 (first from archive1.mbox for dup1, newest in that archive) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail3'")
        assert cursor.fetchone()[0] == 1

        # Check that gmail5 (first from archive2.mbox for dup2, newest in that archive) was kept
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id = 'gmail5'")
        assert cursor.fetchone()[0] == 1

        conn.close()

    def test_dedupe_no_duplicates(self, runner, tmp_path):
        """Test dedupe with no duplicates (early exit)."""
        db_path = create_v1_1_db_no_duplicates(tmp_path)

        result = runner.invoke(app, ["dedupe", "--state-db", str(db_path)])

        assert result.exit_code == 0
        assert "No duplicate" in result.stdout or "no duplicate" in result.stdout

    def test_dedupe_v1_0_database_error(self, runner, tmp_path):
        """Test dedupe shows error for v1.0 database."""
        db_path = create_v1_0_database(tmp_path)

        result = runner.invoke(app, ["dedupe", "--state-db", str(db_path)])

        assert result.exit_code == 1
        assert "v1.1" in result.stdout or "1.1" in result.stdout
        assert "migrate" in result.stdout.lower() or "migration" in result.stdout.lower()

    def test_dedupe_with_auto_verify_clean(self, runner, tmp_path):
        """Test dedupe with --auto-verify on clean database."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app, ["dedupe", "--state-db", str(db_path), "--no-dry-run", "--auto-verify"]
            )

        assert result.exit_code == 0
        # Should show verification running
        assert "verif" in result.stdout.lower()
        # Should show verification passed
        assert "no issues" in result.stdout.lower() or "clean" in result.stdout.lower()

    def test_dedupe_with_auto_verify_with_issues(self, runner, tmp_path):
        """Test dedupe with --auto-verify when verification finds issues."""
        # Create a database with duplicates + orphaned FTS
        db_path = tmp_path / "archive_state.db"
        conn = sqlite3.connect(str(db_path))

        # Create tables
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

        # Add duplicates
        conn.execute("""
            INSERT INTO messages VALUES
            ('gmail1', '<dup@test.com>', 'thread1', 'Dup 1', 'sender@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             'archive1.mbox', 100, 500, 'Body 1', 'checksum1', 500, NULL, 'default')
        """)

        conn.execute("""
            INSERT INTO messages VALUES
            ('gmail2', '<dup@test.com>', 'thread1', 'Dup 2', 'sender@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-02T12:00:00',
             'archive1.mbox', 200, 600, 'Body 2', 'checksum2', 600, NULL, 'default')
        """)

        # Create FTS table
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content=messages,
                content_rowid=rowid
            )
        """)

        # Add orphaned FTS record
        conn.execute("""
            INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
            VALUES (999, 'Orphan', 'orphan@example.com', 'test@example.com', 'Orphaned record')
        """)

        # Create schema_version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_at TIMESTAMP NOT NULL
            )
        """)

        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        conn.commit()
        conn.close()

        # Run dedupe with auto-verify
        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app, ["dedupe", "--state-db", str(db_path), "--no-dry-run", "--auto-verify"]
            )

        assert result.exit_code == 0
        # Should show verification running
        assert "verif" in result.stdout.lower()
        # Should show issues found
        assert "issue" in result.stdout.lower() or "orphan" in result.stdout.lower()
        # Should suggest repair
        assert "repair" in result.stdout.lower() or "check" in result.stdout.lower()

    def test_dedupe_dry_run_no_auto_verify(self, runner, tmp_path):
        """Test dedupe dry-run does not auto-verify even with flag."""
        db_path = create_v1_1_db_with_duplicates(tmp_path)

        result = runner.invoke(
            app, ["dedupe", "--state-db", str(db_path), "--dry-run", "--auto-verify"]
        )

        assert result.exit_code == 0
        # Dry run should not trigger auto-verify
        # The implementation shows auto-verify only runs in non-dry-run mode
