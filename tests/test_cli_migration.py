"""Tests for CLI migration commands."""

import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
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
    """Create a v1.1 database for testing."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema
    manager._create_enhanced_schema(manager.conn)

    # Insert sample data
    manager.conn.execute("""
        INSERT INTO messages VALUES
        ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         'archive1.mbox', 100, 500, 'Test body', 'abc123', 500, NULL, 'default')
    """)

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


@pytest.fixture
def v1_2_database(tmp_path):
    """Create a v1.2 database (current version) for testing."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema (v1.2 uses same structure)
    manager._create_enhanced_schema(manager.conn)

    # Insert sample data
    manager.conn.execute("""
        INSERT INTO messages VALUES
        ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         'archive1.mbox', 100, 500, 'Test body', 'abc123', 500, NULL, 'default')
    """)

    # Set schema version to current (1.2)
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.2", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


class TestMigrateCommand:
    """Test 'gmailarchiver migrate' command."""

    def test_migrate_v1_0_database(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test migrating a v1.0 database."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Mock user confirmation
        with patch("typer.confirm", return_value=True):
            result = runner.invoke(app, ["migrate", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        assert "Migration completed successfully" in result.stdout
        assert "Backup created" in result.stdout

        # Verify database was migrated to current version (1.2)
        manager = MigrationManager(v1_0_database)
        version = manager.detect_schema_version()
        assert version == "1.2"

    def test_migrate_already_migrated_database(self, runner, v1_2_database, tmp_path, monkeypatch):
        """Test migrating an already-migrated database."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["migrate", "--state-db", str(v1_2_database)])

        assert result.exit_code == 0
        assert "already at version 1.2" in result.stdout or "up to date" in result.stdout

    def test_migrate_nonexistent_database(self, runner, tmp_path, monkeypatch):
        """Test migrating a nonexistent database."""
        monkeypatch.chdir(tmp_path)
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(app, ["migrate", "--state-db", str(nonexistent_db)])

        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "does not exist" in result.stdout.lower()

    def test_migrate_user_cancels_confirmation(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test migration cancelled by user."""
        monkeypatch.chdir(tmp_path)

        # Mock user declining confirmation
        with patch("typer.confirm", return_value=False):
            result = runner.invoke(app, ["migrate", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        assert "cancelled" in result.stdout.lower() or "aborted" in result.stdout.lower()

        # Verify database was NOT migrated
        manager = MigrationManager(v1_0_database)
        version = manager.detect_schema_version()
        assert version == "1.0"

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
            result = runner.invoke(app, ["migrate"])

        assert result.exit_code == 0
        assert "Migration completed successfully" in result.stdout


class TestStatusCommand:
    """Test 'gmailarchiver status' command with database information."""

    def test_status_v1_0_database(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test status with v1.0 database shows schema version."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        assert "1.0" in result.stdout
        assert "2" in result.stdout  # Message count
        assert "archive1.mbox" in result.stdout

    def test_status_v1_1_database(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test status with v1.1 database shows schema version."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        assert "1.1" in result.stdout
        assert "1" in result.stdout  # Message count

    def test_status_empty_database(self, runner, tmp_path, monkeypatch):
        """Test status with non-existent database."""
        monkeypatch.chdir(tmp_path)
        empty_db = tmp_path / "empty.db"

        result = runner.invoke(app, ["status", "--state-db", str(empty_db)])

        assert result.exit_code == 0
        assert "no archive" in result.stdout.lower() or "not found" in result.stdout.lower()

    def test_status_shows_recent_runs(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test status displays recent archive runs."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        assert "Recent Archive Runs" in result.stdout or "Archive Runs" in result.stdout

    def test_status_shows_database_size(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test status displays database file size."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        # Should show size in bytes/KB/MB
        assert "bytes" in result.stdout.lower() or "KB" in result.stdout or "MB" in result.stdout

    def test_status_verbose_shows_more_detail(self, runner, v1_0_database, tmp_path, monkeypatch):
        """Test status --verbose shows additional details."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["status", "--verbose", "--state-db", str(v1_0_database)])

        assert result.exit_code == 0
        # Verbose mode should include Query column
        assert "Query" in result.stdout or "Last 10" in result.stdout


class TestRollbackCommand:
    """Test 'gmailarchiver rollback' command."""

    def test_rollback_with_backup_file(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test rollback with valid backup file."""
        monkeypatch.chdir(tmp_path)

        # Create a backup file (simulating v1.0 database)
        backup_path = tmp_path / "archive_state.db.backup.20250114_120000"
        conn = sqlite3.connect(str(backup_path))
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

        # Mock user confirmation
        with patch("typer.confirm", return_value=True):
            result = runner.invoke(
                app,
                ["rollback", "--state-db", str(v1_1_database), "--backup-file", str(backup_path)],
            )

        assert result.exit_code == 0
        assert "Rollback completed successfully" in result.stdout

        # Verify database was restored
        manager = MigrationManager(v1_1_database)
        version = manager.detect_schema_version()
        assert version == "1.0"

    def test_rollback_missing_backup(self, runner, tmp_path, monkeypatch):
        """Test rollback with missing backup file."""
        monkeypatch.chdir(tmp_path)
        nonexistent_backup = tmp_path / "nonexistent_backup.db"

        result = runner.invoke(app, ["rollback", "--backup-file", str(nonexistent_backup)])

        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_rollback_user_cancels(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test rollback cancelled by user."""
        monkeypatch.chdir(tmp_path)

        backup_path = tmp_path / "archive_state.db.backup.20250114_120000"
        backup_path.touch()

        # Mock user declining confirmation
        with patch("typer.confirm", return_value=False):
            result = runner.invoke(
                app,
                ["rollback", "--state-db", str(v1_1_database), "--backup-file", str(backup_path)],
            )

        assert result.exit_code == 0
        assert "cancelled" in result.stdout.lower() or "aborted" in result.stdout.lower()

    def test_rollback_lists_available_backups(self, runner, tmp_path, monkeypatch):
        """Test rollback lists available backup files when none specified."""
        monkeypatch.chdir(tmp_path)

        # Create multiple backup files
        backup1 = tmp_path / "archive_state.db.backup.20250114_120000"
        backup2 = tmp_path / "archive_state.db.backup.20250114_130000"
        backup1.touch()
        backup2.touch()

        result = runner.invoke(app, ["rollback"])

        assert result.exit_code == 0
        # Should list available backups
        assert "backup.20250114_120000" in result.stdout
        assert "backup.20250114_130000" in result.stdout

    def test_rollback_no_backups_available(self, runner, tmp_path, monkeypatch):
        """Test rollback when no backups are available."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["rollback"])

        assert result.exit_code == 1
        assert "No backup files found" in result.stdout
