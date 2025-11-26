"""Tests for CLI import command."""

import mailbox
import sqlite3
from datetime import datetime

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
from gmailarchiver.data.migration import MigrationManager


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def v1_1_database(tmp_path):
    """Create a v1.1 database for testing."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema
    manager._create_enhanced_schema(manager.conn)

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


@pytest.fixture
def sample_mbox(tmp_path):
    """Create a sample mbox file with test messages."""
    mbox_path = tmp_path / "test_archive.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Add 3 test messages
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg.set_payload(f"This is test message {i}")
        mbox.add(msg)

    mbox.close()
    return mbox_path


@pytest.fixture
def sample_mbox_with_duplicates(tmp_path):
    """Create mbox file with duplicate Message-IDs."""
    mbox_path = tmp_path / "duplicates.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Add 2 messages with same Message-ID
    for i in range(1, 3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Duplicate Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = "<duplicate@example.com>"
        msg.set_payload(f"Duplicate message {i}")
        mbox.add(msg)

    mbox.close()
    return mbox_path


class TestImportCommand:
    """Test 'gmailarchiver import' command."""

    def test_import_single_file_success(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test importing a single mbox file shows success message."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["import", str(sample_mbox), "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        assert "imported" in result.stdout.lower()
        assert "3" in result.stdout  # 3 messages imported

    def test_import_with_skip_duplicates(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test import with --skip-duplicates shows skipped count."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "import",
                str(sample_mbox_with_duplicates),
                "--state-db",
                str(v1_1_database),
                "--skip-duplicates",
            ],
        )

        assert result.exit_code == 0
        assert "skipped" in result.stdout.lower() or "1" in result.stdout

    def test_import_with_no_skip_duplicates(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test import with --no-skip-duplicates imports all messages."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "import",
                str(sample_mbox_with_duplicates),
                "--state-db",
                str(v1_1_database),
                "--no-skip-duplicates",
            ],
        )

        assert result.exit_code == 0
        # Should import first message, but second will fail on unique constraint
        assert "imported" in result.stdout.lower()

    def test_import_with_account_id(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test import with --account-id verifies in database."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "import",
                str(sample_mbox),
                "--state-db",
                str(v1_1_database),
                "--account-id",
                "work_account",
            ],
        )

        assert result.exit_code == 0

        # Verify account_id was stored correctly
        conn = sqlite3.connect(str(v1_1_database))
        cursor = conn.execute("SELECT account_id FROM messages")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) > 0
        assert all(row[0] == "work_account" for row in rows)

    def test_import_glob_pattern_multiple_files(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test import with glob pattern imports multiple files."""
        monkeypatch.chdir(tmp_path)

        # Create multiple mbox files
        for i in range(1, 3):
            mbox_path = tmp_path / f"archive{i}.mbox"
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg["From"] = f"sender{i}@example.com"
            msg["Subject"] = f"Message {i}"
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg.set_payload(f"Content {i}")
            mbox.add(msg)
            mbox.close()

        result = runner.invoke(app, ["import", "archive*.mbox", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        assert "archive1.mbox" in result.stdout or "2" in result.stdout  # 2 files

    def test_import_missing_file_error(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test import with missing file shows error message."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["import", "nonexistent.mbox", "--state-db", str(v1_1_database)]
        )

        assert result.exit_code == 1
        assert (
            "error" in result.stdout.lower()
            or "not found" in result.stdout.lower()
            or "no files match" in result.stdout.lower()
        )

    def test_import_database_error_handling(self, runner, tmp_path, monkeypatch):
        """Test import auto-migrates v1.0 databases."""
        monkeypatch.chdir(tmp_path)

        # Create mbox but no database
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["From"] = "test@example.com"
        msg["Subject"] = "Test"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test")
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database to test auto-migration
        v1_0_db = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(v1_0_db))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        result = runner.invoke(app, ["import", str(mbox_path), "--state-db", str(v1_0_db)])

        # Should succeed with auto-migration
        assert result.exit_code == 0
        assert (
            "auto-migrating" in result.stdout.lower()
            or "migration completed" in result.stdout.lower()
        )

    def test_import_shows_progress_and_statistics(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test import shows progress bar and summary statistics."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["import", str(sample_mbox), "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        # Should show summary statistics
        assert "imported" in result.stdout.lower()
        # Should show performance metrics or time
        assert "ms" in result.stdout.lower() or "second" in result.stdout.lower()

    def test_import_default_state_db_path(self, runner, sample_mbox, tmp_path, monkeypatch):
        """Test import uses default database path when not specified."""
        monkeypatch.chdir(tmp_path)

        # Create v1.1 database at default location
        default_db = tmp_path / "archive_state.db"
        manager = MigrationManager(default_db)
        manager._connect()
        manager._create_enhanced_schema(manager.conn)
        manager.conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )
        manager.conn.commit()
        manager._close()

        result = runner.invoke(app, ["import", str(sample_mbox)])

        assert result.exit_code == 0
        assert "imported" in result.stdout.lower()

    def test_import_shows_summary_table(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test import displays rich summary table with per-file stats."""
        monkeypatch.chdir(tmp_path)

        # Create 2 mbox files
        for i in range(1, 3):
            mbox_path = tmp_path / f"test{i}.mbox"
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg["From"] = f"sender{i}@example.com"
            msg["Subject"] = f"Message {i}"
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg.set_payload(f"Content {i}")
            mbox.add(msg)
            mbox.close()

        result = runner.invoke(app, ["import", "test*.mbox", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
        # Should show table with file names
        assert "test1.mbox" in result.stdout
        assert "test2.mbox" in result.stdout

    def test_import_with_auto_verify_clean(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test import with --auto-verify on clean database."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["import", str(sample_mbox), "--state-db", str(v1_1_database), "--auto-verify"]
        )

        assert result.exit_code == 0
        # Should show verification running
        assert "verif" in result.stdout.lower()
        # Should show verification passed
        assert "no issues" in result.stdout.lower() or "clean" in result.stdout.lower()

    def test_import_with_auto_verify_with_issues(self, runner, tmp_path, monkeypatch):
        """Test import with --auto-verify when verification finds issues."""
        monkeypatch.chdir(tmp_path)

        # Create a database with orphaned FTS records
        db_path = tmp_path / "archive_state.db"
        manager = MigrationManager(db_path)
        manager._connect()
        manager._create_enhanced_schema(manager.conn)

        # Add message to messages table
        manager.conn.execute("""
            INSERT INTO messages VALUES
            ('gmail1', '<msg1@example.com>', 'thread1', 'Message 1', 'sender@example.com',
             'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
             'archive1.mbox', 100, 500, 'Body 1', 'checksum1', 500, NULL, 'default')
        """)

        # Add orphaned FTS record (rowid that doesn't exist in messages)
        manager.conn.execute("""
            INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
            VALUES (999, 'Orphan', 'orphan@example.com', 'test@example.com', 'Orphaned record')
        """)

        manager.conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        manager.conn.commit()
        manager._close()

        # Create mbox to import
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["From"] = "test@example.com"
        msg["Subject"] = "Test"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test")
        mbox.add(msg)
        mbox.close()

        result = runner.invoke(
            app, ["import", str(mbox_path), "--state-db", str(db_path), "--auto-verify"]
        )

        assert result.exit_code == 0  # Import itself succeeds
        # Should show verification running
        assert "verif" in result.stdout.lower()
        # Should show issues found
        assert "issue" in result.stdout.lower() or "orphan" in result.stdout.lower()
        # Should suggest repair
        assert "repair" in result.stdout.lower() or "check" in result.stdout.lower()
