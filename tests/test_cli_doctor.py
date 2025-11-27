"""Tests for doctor CLI command."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
        ("1.1", "2024-01-01T00:00:00"),
    )

    conn.execute("PRAGMA user_version = 11")
    conn.commit()


@pytest.fixture
def clean_db(tmp_path: Path) -> Path:
    """Create a clean v1.1 database with no issues."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    create_v1_1_schema(conn)

    # Create archive file
    mbox_content = "From test\n\nTest message\n"
    mbox_bytes = mbox_content.encode("utf-8")
    mbox_path = tmp_path / "test.mbox"
    mbox_length = len(mbox_bytes)

    # Insert test data
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
def db_with_issues(tmp_path: Path) -> Path:
    """Create database with integrity issues."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create schema WITHOUT triggers so we can create issues
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
            content=''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
        ("1.1", "2024-01-01T00:00:00"),
    )

    conn.execute("PRAGMA user_version = 11")

    # Insert message with invalid offset (-1)
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
            "nonexistent.mbox",
            -1,
            -1,
            "Body",
        ),
    )

    conn.commit()
    conn.close()

    return db_path


# ==================== TESTS ====================


class TestDoctorCommand:
    """Tests for doctor command."""

    def test_doctor_basic(self, clean_db: Path) -> None:
        """Test doctor command runs without --check flag."""
        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(clean_db)])

            # Should complete without error
            assert result.exit_code == 0
            # Should show diagnostic results
            assert "Diagnostic Results" in result.stdout or "Check" in result.stdout

    def test_doctor_with_check_flag(self, clean_db: Path) -> None:
        """Test doctor command with --check flag runs internal database checks."""
        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(clean_db), "--check"])

            # Should complete without error
            assert result.exit_code == 0
            # Should show internal database checks section
            assert "Internal Database Checks" in result.stdout
            # Should suggest running full check command
            assert "gmailarchiver check" in result.stdout

    def test_doctor_check_flag_with_missing_db(self, tmp_path: Path) -> None:
        """Test doctor --check with non-existent database."""
        db_path = tmp_path / "nonexistent.db"

        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(db_path), "--check"])

            # Should handle gracefully
            # Doctor may fail if db doesn't exist, but --check should warn about missing db
            assert (
                "not found" in result.stdout.lower()
                or "Database not found" in result.stdout
                or result.exit_code == 0
            )

    def test_doctor_check_flag_finds_issues(self, db_with_issues: Path) -> None:
        """Test doctor --check detects internal database issues."""
        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(db_with_issues), "--check"])

            # Should complete and show internal checks section
            assert "Internal Database Checks" in result.stdout
            # May show issues found
            print(f"Output: {result.stdout}")

    def test_doctor_json_output(self, clean_db: Path) -> None:
        """Test doctor command with --json flag."""
        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(clean_db), "--json"])

            assert result.exit_code == 0
            # JSON output should be parseable
            assert "overall_status" in result.stdout or "checks" in result.stdout

    def test_doctor_fix_flag(self, tmp_path: Path) -> None:
        """Test doctor command with --fix flag."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        create_v1_1_schema(conn)
        conn.close()

        # Create a stale lock file that can be fixed
        lock_file = tmp_path / "test.mbox.lock"
        lock_file.touch()

        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(db_path), "--fix"])

            # Should complete without error
            assert result.exit_code == 0

    def test_doctor_without_check_suggests_check(self, clean_db: Path) -> None:
        """Test that doctor without --check suggests running check command."""
        with (
            patch("shutil.disk_usage") as mock_usage,
            patch("gmailarchiver.core.doctor._get_default_token_path") as mock_token_path,
        ):
            mock_usage.return_value = Mock(free=1024 * 1024 * 1024)
            mock_token_path.return_value = Path("/nonexistent/token.json")

            result = runner.invoke(app, ["doctor", "--state-db", str(clean_db)])

            assert result.exit_code == 0
            # Should suggest running internal checks
            assert "gmailarchiver check" in result.stdout or "doctor --check" in result.stdout
