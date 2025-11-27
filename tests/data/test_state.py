"""Tests for state tracking module."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.data.state import ArchiveState


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_archive_state.db"
        yield str(db_path)


class TestArchiveState:
    """Tests for ArchiveState class."""

    def test_init_creates_database(self, temp_db):
        """Test that initializing ArchiveState creates database and tables."""
        state = ArchiveState(temp_db, validate_path=False)

        assert Path(temp_db).exists()

        # Check tables exist
        cursor = state.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "archived_messages" in tables
        assert "archive_runs" in tables

        state.close()

    def test_mark_archived(self, temp_db):
        """Test marking a message as archived."""
        state = ArchiveState(temp_db, validate_path=False)

        state.mark_archived(
            gmail_id="msg123",
            archive_file="test.mbox",
            subject="Test Email",
            from_addr="test@example.com",
            message_date="2025-01-01",
            checksum="abc123",
        )

        # Verify message was stored
        cursor = state.conn.execute(
            "SELECT * FROM archived_messages WHERE gmail_id = ?", ("msg123",)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "msg123"  # gmail_id
        assert row[2] == "test.mbox"  # archive_file
        assert row[3] == "Test Email"  # subject
        assert row[4] == "test@example.com"  # from_addr
        assert row[5] == "2025-01-01"  # message_date
        assert row[6] == "abc123"  # checksum

        state.close()

    def test_is_archived(self, temp_db):
        """Test checking if message is archived."""
        state = ArchiveState(temp_db, validate_path=False)

        # Initially not archived
        assert not state.is_archived("msg123")

        # Mark as archived
        state.mark_archived("msg123", "test.mbox")

        # Now should be archived
        assert state.is_archived("msg123")

        state.close()

    def test_get_archived_count(self, temp_db):
        """Test getting count of archived messages."""
        state = ArchiveState(temp_db, validate_path=False)

        assert state.get_archived_count() == 0

        state.mark_archived("msg1", "test.mbox")
        assert state.get_archived_count() == 1

        state.mark_archived("msg2", "test.mbox")
        assert state.get_archived_count() == 2

        # Updating same message shouldn't increase count
        state.mark_archived("msg1", "test.mbox", subject="Updated")
        assert state.get_archived_count() == 2

        state.close()

    def test_record_archive_run(self, temp_db):
        """Test recording an archive run."""
        state = ArchiveState(temp_db, validate_path=False)

        run_id = state.record_archive_run(
            query="older_than:3y", messages_archived=100, archive_file="test.mbox"
        )

        assert run_id > 0

        # Verify run was stored
        cursor = state.conn.execute("SELECT * FROM archive_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()

        assert row is not None
        assert row[2] == "older_than:3y"  # query
        assert row[3] == 100  # messages_archived
        assert row[4] == "test.mbox"  # archive_file

        state.close()

    def test_get_archive_runs(self, temp_db):
        """Test getting recent archive runs."""
        state = ArchiveState(temp_db, validate_path=False)

        # Add multiple runs
        state.record_archive_run("older_than:1y", 50, "run1.mbox")
        state.record_archive_run("older_than:2y", 100, "run2.mbox")
        state.record_archive_run("older_than:3y", 150, "run3.mbox")

        # Get all runs
        runs = state.get_archive_runs(limit=10)
        assert len(runs) == 3

        # Should be in reverse chronological order
        assert runs[0]["archive_file"] == "run3.mbox"
        assert runs[0]["messages_archived"] == 150

        # Test limit
        runs = state.get_archive_runs(limit=2)
        assert len(runs) == 2

        state.close()

    def test_get_archived_message_ids(self, temp_db):
        """Test getting all archived message IDs."""
        state = ArchiveState(temp_db, validate_path=False)

        assert state.get_archived_message_ids() == set()

        state.mark_archived("msg1", "test.mbox")
        state.mark_archived("msg2", "test.mbox")
        state.mark_archived("msg3", "test.mbox")

        ids = state.get_archived_message_ids()
        assert ids == {"msg1", "msg2", "msg3"}

        state.close()

    def test_get_archived_message_ids_for_file(self, temp_db):
        """Test getting message IDs for specific archive file."""
        state = ArchiveState(temp_db, validate_path=False)

        # Add messages to different archives
        state.mark_archived("msg1", "archive1.mbox")
        state.mark_archived("msg2", "archive1.mbox")
        state.mark_archived("msg3", "archive2.mbox")
        state.mark_archived("msg4", "archive2.mbox")

        # Get IDs for specific file
        ids1 = state.get_archived_message_ids_for_file("archive1.mbox")
        assert ids1 == {"msg1", "msg2"}

        ids2 = state.get_archived_message_ids_for_file("archive2.mbox")
        assert ids2 == {"msg3", "msg4"}

        # Non-existent file
        ids3 = state.get_archived_message_ids_for_file("nonexistent.mbox")
        assert ids3 == set()

        state.close()

    def test_context_manager(self, temp_db):
        """Test using ArchiveState as context manager."""
        with ArchiveState(temp_db, validate_path=False) as state:
            state.mark_archived("msg1", "test.mbox")
            assert state.is_archived("msg1")

        # Connection should be closed after context
        # Verify by creating new connection
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM archived_messages")
        count = cursor.fetchone()[0]
        assert count == 1
        conn.close()

    def test_mark_archived_replace(self, temp_db):
        """Test that mark_archived replaces existing records."""
        state = ArchiveState(temp_db, validate_path=False)

        # Add initial message
        state.mark_archived(
            "msg1", "old_archive.mbox", subject="Old Subject", checksum="old_checksum"
        )

        # Update same message
        state.mark_archived(
            "msg1", "new_archive.mbox", subject="New Subject", checksum="new_checksum"
        )

        # Should only have one record
        assert state.get_archived_count() == 1

        # Should have updated values
        cursor = state.conn.execute(
            "SELECT archive_file, subject, checksum FROM archived_messages WHERE gmail_id = ?",
            ("msg1",),
        )
        row = cursor.fetchone()
        assert row[0] == "new_archive.mbox"
        assert row[1] == "New Subject"
        assert row[2] == "new_checksum"

        state.close()


class TestV11SchemaOperations:
    """Tests for v1.1 schema-specific operations."""

    def test_mark_archived_v1_1_requires_offsets(self, temp_db):
        """Test that v1.1 schema requires mbox_offset and mbox_length."""
        import sqlite3

        # Create v1.1 database
        conn = sqlite3.connect(temp_db)
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
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        state = ArchiveState(temp_db, validate_path=False)

        # Should raise ValueError when offsets missing
        with pytest.raises(ValueError, match="mbox_offset and mbox_length required"):
            state.mark_archived(
                "msg1",
                "archive.mbox",
                subject="Test",
                # Missing mbox_offset and mbox_length
            )

        state.close()

    def test_mark_archived_v1_1_with_all_fields(self, temp_db):
        """Test mark_archived with all v1.1 fields."""
        import json
        import sqlite3

        # Create v1.1 database
        conn = sqlite3.connect(temp_db)
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
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        state = ArchiveState(temp_db, validate_path=False)

        # Mark archived with all v1.1 fields
        state.mark_archived(
            gmail_id="msg123",
            archive_file="test.mbox",
            subject="Test Subject",
            from_addr="from@example.com",
            message_date="2024-01-01",
            checksum="abc123",
            rfc_message_id="<unique@example.com>",
            mbox_offset=0,
            mbox_length=1234,
            body_preview="Test body preview",
            to_addr="to@example.com",
            cc_addr="cc@example.com",
            thread_id="thread123",
            size_bytes=5000,
            labels=json.dumps(["INBOX", "IMPORTANT"]),
            account_id="test_account",
        )

        # Verify all fields were stored
        cursor = state.conn.execute(
            "SELECT rfc_message_id, mbox_offset, mbox_length, "
            "body_preview, to_addr, cc_addr, thread_id, "
            "size_bytes, labels, account_id FROM messages WHERE gmail_id = 'msg123'"
        )
        row = cursor.fetchone()

        assert row[0] == "<unique@example.com>"
        assert row[1] == 0
        assert row[2] == 1234
        assert row[3] == "Test body preview"
        assert row[4] == "to@example.com"
        assert row[5] == "cc@example.com"
        assert row[6] == "thread123"
        assert row[7] == 5000
        assert row[8] == json.dumps(["INBOX", "IMPORTANT"])
        assert row[9] == "test_account"

        state.close()

    def test_schema_version_property(self, temp_db):
        """Test schema_version property."""
        import sqlite3

        # Create v1.1 database
        conn = sqlite3.connect(temp_db)
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        state = ArchiveState(temp_db, validate_path=False)
        assert state.schema_version == "1.1"
        state.close()

    def test_needs_migration(self, temp_db):
        """Test needs_migration method."""
        import sqlite3

        # Create v1.0 database
        conn = sqlite3.connect(temp_db)
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        state = ArchiveState(temp_db, validate_path=False)
        assert state.needs_migration() is True
        state.close()

    def test_context_manager_rollback_on_exception(self, temp_db):
        """Test that context manager rolls back on exception."""
        state = ArchiveState(temp_db, validate_path=False)
        state.close()

        # Test rollback on exception
        try:
            with ArchiveState(temp_db, validate_path=False) as state:
                state.mark_archived("msg1", "test.mbox", subject="Test")
                # Force an exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Verify no data was committed
        with ArchiveState(temp_db, validate_path=False) as state:
            assert state.get_archived_count() == 0


class TestStateEdgeCases:
    """Test edge cases for ArchiveState."""

    def test_validate_path_true_calls_validator(self, tmp_path, monkeypatch):
        """Test that validate_path=True uses path validator (line 26).

        When validate_path=True, the path is validated against traversal attacks.
        """
        # Change to tmp_path directory so path validation passes
        monkeypatch.chdir(tmp_path)

        db_path = tmp_path / "test.db"

        # Should work without exception (valid path within CWD)
        state = ArchiveState(str(db_path), validate_path=True)
        state.close()

        assert db_path.exists()

    def test_schema_detection_v1_1_without_schema_version_table(self, tmp_path):
        """Test schema detection returns '1.1' for messages table without schema_version.

        This covers line 54: return '1.1' when messages table exists but no schema_version.
        """
        import sqlite3

        db_path = tmp_path / "v1_1_style.db"

        # Create database with messages table but no schema_version table
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        state = ArchiveState(str(db_path), validate_path=False)
        # The schema detection happens in __init__ -> _detect_schema_version
        assert state._schema_version == "1.1"
        state.close()
