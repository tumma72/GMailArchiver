"""Tests for CLI verification commands."""

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, Mock

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
from gmailarchiver.migration import MigrationManager


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
    conn.execute('''
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    ''')

    # Insert sample data
    conn.execute('''
        INSERT INTO archived_messages VALUES
        ('msg1', '2025-01-01T12:00:00', 'test.mbox', 'Test 1', 'test@example.com',
         '2024-01-01T10:00:00', 'abc123')
    ''')

    # Create archive_runs table
    conn.execute('''
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL
        )
    ''')

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

    # Insert sample data with mbox_offset
    manager.conn.execute('''
        INSERT INTO messages VALUES
        ('msg1', '<msg1@test.com>', 'thread1', 'Test 1', 'test@example.com',
         'recipient@example.com', NULL, '2024-01-01 10:00:00', '2025-01-01T12:00:00',
         'test.mbox', 100, 500, 'Test body', 'abc123', 500, NULL, 'default')
    ''')

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)",
        ('1.1', datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


@pytest.fixture
def test_mbox(tmp_path):
    """Create a test mbox file."""
    mbox_path = tmp_path / "test.mbox"
    with open(mbox_path, 'w') as f:
        f.write("""From test@example.com Mon Jan 1 10:00:00 2024
From: test@example.com
To: recipient@example.com
Subject: Test 1
Message-ID: <msg1@test.com>

Test body
""")
    return mbox_path


class TestVerifyOffsetsCommand:
    """Tests for verify-offsets command."""

    def test_verify_offsets_perfect_archive(
        self, runner, v1_1_database, test_mbox, tmp_path
    ):
        """Test verify-offsets with perfect archive (exit 0)."""
        result = runner.invoke(app, [
            "verify-offsets",
            str(test_mbox),
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code == 0
        assert "verified successfully" in result.stdout.lower()

    @patch('gmailarchiver.validator.ArchiveValidator.verify_offsets')
    def test_verify_offsets_corrupted_offsets(
        self, mock_verify, runner, v1_1_database, test_mbox
    ):
        """Test verify-offsets with corrupted offsets (exit 1)."""
        from gmailarchiver.validator import OffsetVerificationResult

        # Mock corrupted offset result
        mock_verify.return_value = OffsetVerificationResult(
            total_checked=10,
            successful_reads=8,
            failed_reads=2,
            accuracy_percentage=80.0,
            failures=['msg1: offset mismatch', 'msg2: failed to read']
        )

        result = runner.invoke(app, [
            "verify-offsets",
            str(test_mbox),
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code == 1
        assert "80.0%" in result.stdout or "80%" in result.stdout
        assert "failed" in result.stdout.lower() or "accuracy" in result.stdout.lower()

    def test_verify_offsets_missing_archive(self, runner, v1_1_database):
        """Test verify-offsets with missing archive file (error)."""
        result = runner.invoke(app, [
            "verify-offsets",
            "/nonexistent/archive.mbox",
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_verify_offsets_v1_0_database(self, runner, v1_0_database, test_mbox):
        """Test verify-offsets with v1.0 database (shows skipped message)."""
        result = runner.invoke(app, [
            "verify-offsets",
            str(test_mbox),
            "--state-db", str(v1_0_database)
        ])

        assert result.exit_code == 0
        assert "skipped" in result.stdout.lower() or "v1.0" in result.stdout.lower()

    def test_verify_offsets_missing_database(self, runner, test_mbox, tmp_path):
        """Test verify-offsets with missing database file."""
        result = runner.invoke(app, [
            "verify-offsets",
            str(test_mbox),
            "--state-db", str(tmp_path / "nonexistent.db")
        ])

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()


class TestVerifyConsistencyCommand:
    """Tests for verify-consistency command."""

    def test_verify_consistency_perfect_database(
        self, runner, v1_1_database, test_mbox
    ):
        """Test verify-consistency with perfect database (exit 0)."""
        result = runner.invoke(app, [
            "verify-consistency",
            str(test_mbox),
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code == 0
        assert "passed" in result.stdout.lower() or "success" in result.stdout.lower()

    @patch('gmailarchiver.validator.ArchiveValidator.verify_consistency')
    def test_verify_consistency_with_orphaned_records(
        self, mock_verify, runner, v1_1_database, test_mbox
    ):
        """Test verify-consistency with orphaned records (exit 1, shows details)."""
        from gmailarchiver.validator import ConsistencyReport

        # Mock consistency issues
        mock_verify.return_value = ConsistencyReport(
            schema_version="1.1",
            orphaned_records=5,
            missing_records=0,
            duplicate_gmail_ids=0,
            duplicate_rfc_message_ids=0,
            fts_synced=True,
            passed=False,
            errors=["Found 5 orphaned records"]
        )

        result = runner.invoke(app, [
            "verify-consistency",
            str(test_mbox),
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code == 1
        assert "orphaned" in result.stdout.lower() or "5" in result.stdout

    def test_verify_consistency_missing_archive(self, runner, v1_1_database):
        """Test verify-consistency with missing archive file (error)."""
        result = runner.invoke(app, [
            "verify-consistency",
            "/nonexistent/archive.mbox",
            "--state-db", str(v1_1_database)
        ])

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_verify_consistency_v1_0_database(self, runner, v1_0_database, test_mbox):
        """Test verify-consistency with v1.0 database (limited checks)."""
        result = runner.invoke(app, [
            "verify-consistency",
            str(test_mbox),
            "--state-db", str(v1_0_database)
        ])

        # Should still run but with limited checks
        assert result.exit_code in [0, 1]
        assert "v1.0" in result.stdout.lower() or "schema" in result.stdout.lower()

    def test_verify_consistency_missing_database(self, runner, test_mbox, tmp_path):
        """Test verify-consistency with missing database file."""
        result = runner.invoke(app, [
            "verify-consistency",
            str(test_mbox),
            "--state-db", str(tmp_path / "nonexistent.db")
        ])

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()
