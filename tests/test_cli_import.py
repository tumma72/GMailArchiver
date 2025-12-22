"""Tests for CLI import command.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
- v1_1_database: v1.1 database path
- sample_mbox: mbox file with 3 test messages
- sample_mbox_with_duplicates: mbox file with duplicate Message-IDs
"""

import mailbox
import sqlite3
from datetime import datetime

from gmailarchiver.__main__ import app


class TestImportCommand:
    """Test 'gmailarchiver utilities import' command."""

    def test_import_single_file_success(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test importing a single mbox file shows success message."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["utilities", "import", str(sample_mbox), "--state-db", str(v1_1_database)]
        )

        assert result.exit_code == 0
        assert "imported" in result.stdout.lower()
        assert "3" in result.stdout  # 3 messages imported

    def test_import_with_skip_duplicates(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test import with --deduplicate (default) shows skipped count."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "utilities",
                "import",
                str(sample_mbox_with_duplicates),
                "--state-db",
                str(v1_1_database),
                "--deduplicate",
            ],
        )

        assert result.exit_code == 0
        assert "skipped" in result.stdout.lower() or "duplicate" in result.stdout.lower()

    def test_import_with_no_skip_duplicates(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test import with --no-deduplicate attempts to import all messages."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "utilities",
                "import",
                str(sample_mbox_with_duplicates),
                "--state-db",
                str(v1_1_database),
                "--no-deduplicate",
            ],
        )

        # Import succeeds but second duplicate might fail or be handled
        assert result.exit_code == 0
        # With no-deduplicate, it tries to import all but might encounter errors
        assert "imported" in result.stdout.lower()

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

        result = runner.invoke(
            app, ["utilities", "import", "archive*.mbox", "--state-db", str(v1_1_database)]
        )

        assert result.exit_code == 0
        assert "2" in result.stdout  # 2 messages total

    def test_import_missing_file_error(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test import with missing file shows warning and imports 0 files."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["utilities", "import", "nonexistent.mbox", "--state-db", str(v1_1_database)]
        )

        # Import succeeds but with 0 files (no matching files found)
        assert result.exit_code == 0
        # Should show warning that no files were found
        assert "no files found" in result.stdout.lower() or "0" in result.stdout

    def test_import_database_error_handling(self, runner, tmp_path, monkeypatch):
        """Test import fails when database doesn't exist."""
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

        # Database doesn't exist
        v1_0_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app, ["utilities", "import", str(mbox_path), "--state-db", str(v1_0_db)]
        )

        # Should fail with database not found error
        assert result.exit_code == 1
        assert "database" in result.stdout.lower() and "not found" in result.stdout.lower()

    def test_import_shows_progress_and_statistics(
        self, runner, v1_1_database, sample_mbox, tmp_path, monkeypatch
    ):
        """Test import shows progress bar and summary statistics."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["utilities", "import", str(sample_mbox), "--state-db", str(v1_1_database)]
        )

        assert result.exit_code == 0
        # Should show summary statistics
        assert "imported" in result.stdout.lower()
        # Should show message count
        assert "3" in result.stdout

    def test_import_default_state_db_path(self, runner, sample_mbox, tmp_path, monkeypatch):
        """Test import uses default database path when not specified."""
        monkeypatch.chdir(tmp_path)

        # Create v1.1 database at default location using sync sqlite3
        default_db = tmp_path / "archive_state.db"
        conn = sqlite3.connect(str(default_db))
        try:
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
                    migrated_timestamp TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject, from_addr, to_addr, body_preview,
                    content='messages', content_rowid='rowid'
                );
            """)
            conn.execute(
                "INSERT INTO schema_version VALUES (?, ?)", ("1.2", datetime.now().isoformat())
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["utilities", "import", str(sample_mbox)])

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

        result = runner.invoke(
            app, ["utilities", "import", "test*.mbox", "--state-db", str(v1_1_database)]
        )

        assert result.exit_code == 0
        # Should show import results
        assert "imported" in result.stdout.lower()
        assert "2" in result.stdout  # 2 messages
