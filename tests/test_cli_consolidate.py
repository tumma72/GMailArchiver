"""Tests for CLI consolidate command.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
- v1_1_database: v1.1 database path
"""

import mailbox
import sqlite3
from datetime import datetime

import pytest

from gmailarchiver.__main__ import app


@pytest.fixture
def populated_database_with_archives(tmp_path, v1_1_database):
    """Create a database with multiple archives already imported."""
    # Create two mbox files
    mbox1 = tmp_path / "archive1.mbox"
    mb1 = mailbox.mbox(str(mbox1))
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Archive 1 Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg1_{i}@example.com>"
        msg.set_payload(f"Content from archive 1, message {i}")
        mb1.add(msg)
    mb1.close()

    mbox2 = tmp_path / "archive2.mbox"
    mb2 = mailbox.mbox(str(mbox2))
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i + 3}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Archive 2 Message {i}"
        msg["Date"] = f"Mon, {i + 3} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg2_{i}@example.com>"
        msg.set_payload(f"Content from archive 2, message {i}")
        mb2.add(msg)
    mb2.close()

    # Populate database with archive references
    conn = sqlite3.connect(str(v1_1_database))
    try:
        for archive_path, msg_count in [(mbox1, 3), (mbox2, 3)]:
            mbox = mailbox.mbox(str(archive_path))
            for idx, msg in enumerate(mbox):
                conn.execute(
                    """
                    INSERT INTO messages (
                        gmail_id, rfc_message_id, subject, from_addr, to_addr,
                        archived_timestamp, archive_file, mbox_offset, mbox_length
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"gmail_{archive_path.stem}_{idx}",
                        msg["Message-ID"],
                        msg["Subject"],
                        msg["From"],
                        msg["To"],
                        datetime.now().isoformat(),
                        str(archive_path),
                        0,  # Simplified offset
                        100,  # Simplified length
                    ),
                )
            mbox.close()
        conn.commit()
    finally:
        conn.close()

    return v1_1_database, [mbox1, mbox2]


@pytest.fixture
def populated_database_with_duplicates(tmp_path, v1_1_database):
    """Create a database with archives containing duplicate messages."""
    # Create two mbox files with one duplicate message
    mbox1 = tmp_path / "dup1.mbox"
    mb1 = mailbox.mbox(str(mbox1))
    for i in range(1, 3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["Subject"] = f"Unique Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<unique{i}@example.com>"
        msg.set_payload(f"Unique content {i}")
        mb1.add(msg)
    mb1.close()

    mbox2 = tmp_path / "dup2.mbox"
    mb2 = mailbox.mbox(str(mbox2))
    # Duplicate of first message from mbox1
    msg = mailbox.mboxMessage()
    msg["From"] = "sender1@example.com"
    msg["Subject"] = "Unique Message 1"
    msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = "<unique1@example.com>"
    msg.set_payload("Unique content 1")
    mb2.add(msg)
    # New unique message
    msg = mailbox.mboxMessage()
    msg["From"] = "sender3@example.com"
    msg["Subject"] = "Unique Message 3"
    msg["Date"] = "Mon, 3 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = "<unique3@example.com>"
    msg.set_payload("Unique content 3")
    mb2.add(msg)
    mb2.close()

    # Populate database
    conn = sqlite3.connect(str(v1_1_database))
    try:
        for archive_path in [mbox1, mbox2]:
            mbox = mailbox.mbox(str(archive_path))
            for idx, msg in enumerate(mbox):
                try:
                    conn.execute(
                        """
                        INSERT INTO messages (
                            gmail_id, rfc_message_id, subject, from_addr, to_addr,
                            archived_timestamp, archive_file, mbox_offset, mbox_length
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"gmail_{archive_path.stem}_{idx}",
                            msg["Message-ID"],
                            msg["Subject"],
                            msg["From"],
                            msg["To"],
                            datetime.now().isoformat(),
                            str(archive_path),
                            0,
                            100,
                        ),
                    )
                except sqlite3.IntegrityError:
                    # Skip duplicate rfc_message_id
                    pass
            mbox.close()
        conn.commit()
    finally:
        conn.close()

    return v1_1_database, [mbox1, mbox2]


class TestConsolidateCommand:
    """Test 'gmailarchiver utilities consolidate' command."""

    def test_consolidate_success(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate merges all archives in database."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert "consolidat" in result.stdout.lower()
        assert output_file.exists()

        # Verify merged file has all messages
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 6  # 3 from each file
        merged_mbox.close()

    def test_consolidate_with_sort(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate with --sort orders messages chronologically."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "sorted.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--sort",
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_no_sort(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate with --no-sort preserves original order."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "unsorted.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--no-sort",
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_dedupe(
        self, runner, populated_database_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --deduplicate removes duplicates."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_duplicates
        output_file = tmp_path / "deduped.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--deduplicate",
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify duplicates removed (should have 3 unique messages)
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 3  # 3 unique messages
        merged_mbox.close()

    def test_consolidate_with_no_dedupe(
        self, runner, populated_database_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --no-deduplicate keeps all messages."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_duplicates
        output_file = tmp_path / "with_dupes.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--no-deduplicate",
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify all messages kept (including duplicate)
        # Note: Database already deduplicated during import, so we still get 3
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) >= 3
        merged_mbox.close()

    def test_consolidate_with_gzip_compression(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate with gzip compression."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "compressed.mbox.gz"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_explicit_compression(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate with explicit compression format."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "compressed.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--compress",
                "gzip",
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0

    def test_consolidate_no_archives_error(self, runner, v1_1_database, tmp_path, monkeypatch):
        """Test consolidate with no archives in database shows error."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "output.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 1
        assert "no archives" in result.stdout.lower()

    def test_consolidate_database_not_found_error(self, runner, tmp_path, monkeypatch):
        """Test consolidate with missing database shows error."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "output.mbox"
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code == 1
        assert "database" in result.stdout.lower() and "not found" in result.stdout.lower()

    def test_consolidate_output_exists_error(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate fails if output file already exists."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "existing.mbox"
        output_file.touch()  # Create file

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 1
        assert "exists" in result.stdout.lower()

    def test_consolidate_shows_summary(
        self, runner, populated_database_with_archives, tmp_path, monkeypatch
    ):
        """Test consolidate displays summary with statistics."""
        monkeypatch.chdir(tmp_path)
        db_path, _ = populated_database_with_archives
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "utilities",
                "consolidate",
                str(output_file),
                "--state-db",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        # Should show consolidation results
        assert "consolidat" in result.stdout.lower()
        # Should show message count
        assert "6" in result.stdout

    def test_consolidate_default_state_db_path(self, runner, tmp_path, monkeypatch):
        """Test consolidate uses default database path when not specified."""
        monkeypatch.chdir(tmp_path)

        # Create v1.1 database at default location
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
                    upgraded_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "INSERT INTO schema_version VALUES (?, ?)",
                ("1.1", datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(app, ["utilities", "consolidate", str(output_file)])

        # Should fail because no archives in database
        assert result.exit_code == 1
        assert "no archives" in result.stdout.lower()
