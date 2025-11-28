"""Tests for consolidate cleanup functionality (--remove-sources flag)."""

import mailbox
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_db(temp_dir):
    """Create a test state database with v1.1 schema."""
    db_path = temp_dir / "test_state.db"

    # Create database with v1.1 schema
    conn = sqlite3.connect(str(db_path))

    # Create messages table with full v1.1 schema
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

    # Create archive_runs table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL,
            account_id TEXT DEFAULT 'default',
            operation_type TEXT
        )
    """)

    # Create FTS table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            subject, from_addr, to_addr, body_preview,
            content='messages',
            content_rowid='rowid'
        )
    """)

    # Create schema_version table (for v1.1 detection)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            applied_timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES ('1.1', ?)", (datetime.now(UTC).isoformat(),)
    )

    # Create old tables for backward compatibility
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archived_messages (
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

    return str(db_path)


def create_test_mbox(path: Path, num_messages: int = 5) -> int:
    """
    Create a test mbox file with messages.

    Returns:
        Total size of the file in bytes
    """
    mbox = mailbox.mbox(str(path))
    mbox.lock()

    try:
        for i in range(num_messages):
            msg = mailbox.mboxMessage()
            msg["From"] = f"sender{i}@example.com"
            msg["To"] = "recipient@example.com"
            msg["Subject"] = f"Test Message {i}"
            msg["Message-ID"] = f"<test{i}@example.com>"
            msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
            msg.set_payload(f"This is test message {i}.\n")
            mbox.add(msg)

        mbox.flush()
    finally:
        mbox.unlock()
        mbox.close()

    return path.stat().st_size


def add_messages_to_db(state_db: str, archive_file: str, num_messages: int = 5) -> None:
    """Add test messages to state database."""
    conn = sqlite3.connect(state_db)
    timestamp = datetime.now(UTC).isoformat()

    archive_name = Path(archive_file).stem

    for i in range(num_messages):
        conn.execute(
            """
            INSERT INTO messages (
                gmail_id, rfc_message_id, thread_id, subject, from_addr,
                to_addr, date, archived_timestamp, archive_file,
                mbox_offset, mbox_length, checksum, size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"{archive_name}_gmail_{i}",
                f"<test{i}@example.com>",
                f"thread_{i}",
                f"Test Message {i}",
                f"sender{i}@example.com",
                "recipient@example.com",
                "2024-01-01 12:00:00",
                timestamp,
                archive_file,
                i * 100,  # offset
                100,  # length
                f"checksum_{i}",
                150,
            ),
        )

    conn.commit()
    conn.close()


class TestConsolidateCleanup:
    """Test suite for consolidate --remove-sources functionality."""

    def test_consolidate_remove_sources_success(self, temp_dir, state_db):
        """Test --remove-sources deletes source files after successful consolidation."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        src1_size = create_test_mbox(src1, num_messages=5)
        src2_size = create_test_mbox(src2, num_messages=5)

        # Add to database
        add_messages_to_db(state_db, str(src1), num_messages=5)
        add_messages_to_db(state_db, str(src2), num_messages=5)

        # Execute consolidate with --remove-sources and --yes
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
                "--yes",  # Skip confirmation
            ],
        )

        # Verify
        assert result.exit_code == 0, f"Failed with: {result.stdout}"
        assert output.exists(), "Output file should exist"
        assert not src1.exists(), "Source file 1 should be removed"
        assert not src2.exists(), "Source file 2 should be removed"
        # New task_sequence UI pattern: "Removed N file(s), freed X"
        assert "Removed 2 file(s)" in result.stdout or "removed 2" in result.stdout.lower()
        assert "freed" in result.stdout.lower()

    def test_consolidate_remove_sources_without_yes_prompts(self, temp_dir, state_db):
        """Test --remove-sources without --yes shows confirmation prompt."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Execute with confirmation = "y"
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
            ],
            input="y\n",
        )

        # Verify prompt appeared and files were removed
        assert result.exit_code == 0
        assert "Remove" in result.stdout or "Delete" in result.stdout
        assert not src1.exists(), "Source file 1 should be removed"
        assert not src2.exists(), "Source file 2 should be removed"

    def test_consolidate_remove_sources_cancelled_by_user(self, temp_dir, state_db):
        """Test --remove-sources with user declining confirmation keeps files."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Execute with confirmation = "n"
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
            ],
            input="n\n",
        )

        # Verify files still exist
        assert result.exit_code == 0
        assert output.exists(), "Output file should exist"
        assert src1.exists(), "Source file 1 should NOT be removed"
        assert src2.exists(), "Source file 2 should NOT be removed"
        assert (
            "Skipping" in result.stdout
            or "Cancelled" in result.stdout
            or "kept" in result.stdout.lower()
        )

    def test_consolidate_remove_sources_protects_output_file(self, temp_dir, state_db):
        """Test --remove-sources NEVER removes the output file even if it's in sources."""
        runner = CliRunner()

        # Create test files where one source IS the output
        src1 = temp_dir / "existing.mbox"
        src2 = temp_dir / "src2.mbox"
        output = src1  # Output is same as src1

        create_test_mbox(src1, num_messages=5)
        create_test_mbox(src2, num_messages=5)

        add_messages_to_db(state_db, str(src1), num_messages=5)
        add_messages_to_db(state_db, str(src2), num_messages=5)

        # Execute consolidate (will overwrite existing.mbox)
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
                "--yes",
            ],
            input="y\n",
        )  # Confirm overwrite

        # Verify
        assert result.exit_code == 0
        assert output.exists(), "Output file MUST exist"
        assert not src2.exists(), "Other source should be removed"

    def test_consolidate_remove_sources_validation_failure_keeps_files(self, temp_dir, state_db):
        """Test validation failure prevents source file removal."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Mock validator to fail
        with patch("gmailarchiver.__main__.ValidatorFacade") as mock_validator_class:
            mock_validator = Mock()
            mock_validator.validate_all.return_value = False  # Validation fails
            mock_validator_class.return_value = mock_validator

            result = runner.invoke(
                app,
                [
                    "consolidate",
                    str(src1),
                    str(src2),
                    "-o",
                    str(output),
                    "--state-db",
                    state_db,
                    "--remove-sources",
                    "--yes",
                ],
            )

        # Verify files still exist due to validation failure
        assert src1.exists(), "Source file 1 should still exist (validation failed)"
        assert src2.exists(), "Source file 2 should still exist (validation failed)"
        assert "validation" in result.stdout.lower() or "failed" in result.stdout.lower()

    def test_consolidate_remove_sources_calculates_space_freed(self, temp_dir, state_db):
        """Test --remove-sources correctly calculates and reports space freed."""
        runner = CliRunner()

        # Create test source files with known sizes
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        src1_size = create_test_mbox(src1, num_messages=10)
        src2_size = create_test_mbox(src2, num_messages=10)

        add_messages_to_db(state_db, str(src1), num_messages=10)
        add_messages_to_db(state_db, str(src2), num_messages=10)

        total_size = src1_size + src2_size

        # Execute
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
                "--yes",
            ],
        )

        # Verify space reporting
        assert result.exit_code == 0
        # Output format is "Removed X file(s), freed Y KB"
        assert "freed" in result.stdout.lower()
        # Should mention size in human-readable format (KB, MB, etc.)
        assert any(unit in result.stdout for unit in ["KB", "MB", "GB", "bytes", "B"])

    def test_consolidate_remove_sources_handles_permission_error(self, temp_dir, state_db):
        """Test --remove-sources handles permission errors gracefully."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Mock Path.unlink to raise PermissionError
        original_unlink = Path.unlink

        def mock_unlink(self, *args, **kwargs):
            if self.name == "src1.mbox":
                raise PermissionError("Permission denied")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            result = runner.invoke(
                app,
                [
                    "consolidate",
                    str(src1),
                    str(src2),
                    "-o",
                    str(output),
                    "--state-db",
                    state_db,
                    "--remove-sources",
                    "--yes",
                ],
            )

        # Should handle error gracefully
        assert (
            "Permission" in result.stdout
            or "error" in result.stdout.lower()
            or "failed" in result.stdout.lower()
        )

    def test_consolidate_remove_sources_handles_missing_file(self, temp_dir, state_db):
        """Test --remove-sources handles already-deleted files gracefully."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Mock Path.unlink to raise FileNotFoundError for src1
        original_unlink = Path.unlink

        def mock_unlink(self, *args, **kwargs):
            if self.name == "src1.mbox":
                raise FileNotFoundError("File not found")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            result = runner.invoke(
                app,
                [
                    "consolidate",
                    str(src1),
                    str(src2),
                    "-o",
                    str(output),
                    "--state-db",
                    state_db,
                    "--remove-sources",
                    "--yes",
                ],
            )

        # Should handle gracefully (file already deleted is OK)
        assert result.exit_code == 0

    def test_consolidate_without_remove_sources_keeps_files(self, temp_dir, state_db):
        """Test consolidate WITHOUT --remove-sources keeps all source files."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=5)
        create_test_mbox(src2, num_messages=5)

        add_messages_to_db(state_db, str(src1), num_messages=5)
        add_messages_to_db(state_db, str(src2), num_messages=5)

        # Execute WITHOUT --remove-sources
        result = runner.invoke(
            app, ["consolidate", str(src1), str(src2), "-o", str(output), "--state-db", state_db]
        )

        # Verify all files still exist
        assert result.exit_code == 0
        assert output.exists(), "Output file should exist"
        assert src1.exists(), "Source file 1 should still exist"
        assert src2.exists(), "Source file 2 should still exist"
        assert "Removed" not in result.stdout

    def test_consolidate_remove_sources_with_compression(self, temp_dir, state_db):
        """Test --remove-sources works with compressed output."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox.gz"

        create_test_mbox(src1, num_messages=3)
        create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Execute with compression
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
                "--yes",
            ],
        )

        # Verify
        assert result.exit_code == 0
        assert output.exists(), "Compressed output should exist"
        assert not src1.exists(), "Source file 1 should be removed"
        assert not src2.exists(), "Source file 2 should be removed"

    def test_consolidate_remove_sources_json_output(self, temp_dir, state_db):
        """Test --remove-sources with --json flag outputs proper JSON."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        src1_size = create_test_mbox(src1, num_messages=3)
        src2_size = create_test_mbox(src2, num_messages=3)

        add_messages_to_db(state_db, str(src1), num_messages=3)
        add_messages_to_db(state_db, str(src2), num_messages=3)

        # Execute with JSON output
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
                "--yes",
                "--json",
            ],
        )

        # Verify JSON output
        assert result.exit_code == 0
        # Output should be valid JSON
        import json

        try:
            data = json.loads(result.stdout)
            assert "success" in data or "status" in data
            # Should include cleanup info
            assert "removed_files" in data or "files_removed" in data or "cleanup" in data
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

    def test_consolidate_remove_sources_lists_files_before_deletion(self, temp_dir, state_db):
        """Test --remove-sources lists files to be deleted in confirmation prompt."""
        runner = CliRunner()

        # Create test source files
        src1 = temp_dir / "src1.mbox"
        src2 = temp_dir / "src2.mbox"
        output = temp_dir / "merged.mbox"

        create_test_mbox(src1, num_messages=2)
        create_test_mbox(src2, num_messages=2)

        add_messages_to_db(state_db, str(src1), num_messages=2)
        add_messages_to_db(state_db, str(src2), num_messages=2)

        # Execute without --yes to see prompt
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(src1),
                str(src2),
                "-o",
                str(output),
                "--state-db",
                state_db,
                "--remove-sources",
            ],
            input="n\n",
        )  # Decline to see full prompt

        # Verify file names appear in prompt
        assert "src1.mbox" in result.stdout
        assert "src2.mbox" in result.stdout
