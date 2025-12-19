"""Tests for CLI migration commands.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
"""

import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest

from gmailarchiver.__main__ import app


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
        ('msg1', '2025-01-01T12:00:00', 'archive1.mbox', 'Test 1', 'test@example.com',
         '2024-01-01T10:00:00', 'abc123')
    """)
    conn.execute("""
        INSERT INTO archived_messages VALUES
        ('msg2', '2025-01-02T12:00:00', 'archive1.mbox', 'Test 2', 'test2@example.com',
         '2024-01-02T10:00:00', 'def456')
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

    conn.execute("""
        INSERT INTO archive_runs VALUES
        (1, '2025-01-01T12:00:00', 'before:2024/01/01', 2, 'archive1.mbox')
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def v1_1_database(tmp_path):
    """Create a v1.1 database for testing.

    Uses sync sqlite3 to avoid event loop conflicts with pytest-asyncio.
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    try:
        # Create v1.1 schema (messages table with all columns)
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER,
                mbox_length INTEGER,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        # Create FTS table
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content=messages, content_rowid=rowid
            )
        """)

        # Create archive_runs table
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
        """)

        # Create schema_version table
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)

        # Insert sample data
        conn.execute("""
            INSERT INTO messages VALUES
            ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             'archive1.mbox', 100, 500, 'Test body', 'abc123', 500, NULL, 'default')
        """)

        # Set schema version
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        conn.commit()
    finally:
        conn.close()

    return db_path


@pytest.fixture
def v1_2_database(tmp_path):
    """Create a v1.2 database (current version) for testing.

    Uses sync sqlite3 to avoid event loop conflicts with pytest-asyncio.
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    try:
        # Create v1.2 schema (same structure as v1.1)
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER,
                mbox_length INTEGER,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        # Create FTS table
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content=messages, content_rowid=rowid
            )
        """)

        # Create archive_runs table
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
        """)

        # Create schema_version table
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)

        # Insert sample data
        conn.execute("""
            INSERT INTO messages VALUES
            ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             'archive1.mbox', 100, 500, 'Test body', 'abc123', 500, NULL, 'default')
        """)

        # Set schema version to current (1.2)
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.2", datetime.now().isoformat())
        )

        conn.commit()
    finally:
        conn.close()

    return db_path


class TestMigrateCommand:
    """Test 'gmailarchiver migrate' command."""

    def test_migrate_v1_0_database(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test migrating a v1.0 database."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Mock user confirmation
        with patch("typer.confirm", return_value=True):
            result = runner.invoke(app, ["utilities", "migrate", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        assert "migrated" in result.stdout.lower()
        assert "backup" in result.stdout.lower()

        # Verify database was migrated to current version (1.3)
        # Use sync sqlite3 to avoid event loop conflicts with pytest-asyncio
        conn = sqlite3.connect(str(v1_0_database))
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        version = cursor.fetchone()[0]
        conn.close()
        assert version == "1.3"

    def test_migrate_already_migrated_database(self, runner, v1_2_database, tmp_path, monkeypatch):
        """Test migrating an already-migrated database."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["utilities", "migrate", "--state-db", str(v1_2_database)])

        assert result.exit_code == 0
        # Should either say it's at v1.3 (if migrated from v1.2) or already at latest
        assert (
            "v1.3" in result.stdout.lower()
            or "up to date" in result.stdout.lower()
            or "latest" in result.stdout.lower()
        )

    def test_migrate_nonexistent_database(self, runner, tmp_path, monkeypatch):
        """Test migrating a nonexistent database."""
        monkeypatch.chdir(tmp_path)
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(app, ["utilities", "migrate", "--state-db", str(nonexistent_db)])

        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "does not exist" in result.stdout.lower()

    # NOTE: User confirmation is not currently implemented in migrate command
    # Tests for confirmation would go here when feature is added

    def test_migrate_default_database_path(self, runner, tmp_path, monkeypatch):
        """Test migrate command uses default database path."""
        monkeypatch.chdir(tmp_path)

        # Create v1.0 database at default location
        default_db = tmp_path / "archive_state.db"
        conn = sqlite3.connect(str(default_db))
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

        with patch("typer.confirm", return_value=True):
            result = runner.invoke(app, ["utilities", "migrate"])

        assert result.exit_code == 0
        assert "migrated" in result.stdout.lower()


class TestStatusCommand:
    """Test 'gmailarchiver status' command with database information."""

    def test_status_v1_0_database_requires_migration(
        self, runner, v1_0_database, tmp_path, monkeypatch
    ):
        """Test status with v1.0 database shows migration required error."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_0_database)])

        # v1.0 database requires migration - status requires schema 1.1+
        assert result.exit_code == 1
        assert "migration" in result.stdout.lower() or "migrate" in result.stdout.lower()

    def test_status_v1_1_database(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test status with v1.1 database shows schema version."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        assert "1.1" in result.stdout
        assert "1" in result.stdout  # Message count

    def test_status_nonexistent_database(self, runner, tmp_path, monkeypatch):
        """Test status with non-existent database shows error."""
        monkeypatch.chdir(tmp_path)
        empty_db = tmp_path / "empty.db"

        result = runner.invoke(app, ["status", "--state-db", str(empty_db)])

        # Non-existent database should fail with appropriate error
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "database" in result.stdout.lower()

    def test_status_shows_database_size(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test status displays database file size."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        # Should show size in bytes/KB/MB
        assert "bytes" in result.stdout.lower() or "KB" in result.stdout or "MB" in result.stdout

    def test_status_verbose_shows_more_detail(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test status --verbose shows additional details."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--verbose", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        # Verbose mode shows "latest:" prefix for archive files
        assert "latest:" in result.stdout


# NOTE: rollback command is not implemented yet
# Tests for rollback would go here when command is added
