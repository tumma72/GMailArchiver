"""Tests for duplicate remover module (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.deduplicator._remover import DuplicateRemover
from gmailarchiver.core.deduplicator._scanner import MessageInfo


@pytest.fixture
def test_db() -> Path:
    """Create test database with messages."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(str(db_path))

    # Create messages table
    conn.execute("""
        CREATE TABLE messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            mbox_offset INTEGER NOT NULL,
            mbox_length INTEGER NOT NULL,
            size_bytes INTEGER,
            archived_timestamp TIMESTAMP
        )
    """)

    # Insert test messages
    for i in range(1, 6):
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (f"gid{i}", f"<msg{i}@test>", "archive.mbox", i * 1024, 1024, 1024, f"2024-01-0{i}"),
        )

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


class TestDuplicateRemover:
    """Test duplicate message removal."""

    def test_remove_messages_dry_run(self, test_db: Path) -> None:
        """Test dry run mode doesn't actually delete."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01"),
            MessageInfo("gid2", "archive.mbox", 1024, 1024, 1024, "2024-01-02"),
        ]

        remover = DuplicateRemover(str(test_db))
        count = remover.remove_messages(messages, dry_run=True)

        assert count == 2

        # Verify messages still exist
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id IN (?, ?)", ("gid1", "gid2")
        )
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_remove_messages_actual(self, test_db: Path) -> None:
        """Test actual removal deletes from database."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01"),
            MessageInfo("gid2", "archive.mbox", 1024, 1024, 1024, "2024-01-02"),
        ]

        remover = DuplicateRemover(str(test_db))
        count = remover.remove_messages(messages, dry_run=False)

        assert count == 2

        # Verify messages were deleted
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id IN (?, ?)", ("gid1", "gid2")
        )
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_remove_empty_list(self, test_db: Path) -> None:
        """Test removing empty list returns 0."""
        remover = DuplicateRemover(str(test_db))
        count = remover.remove_messages([], dry_run=False)

        assert count == 0

    def test_remove_single_message(self, test_db: Path) -> None:
        """Test removing single message."""
        messages = [
            MessageInfo("gid3", "archive.mbox", 2048, 1024, 1024, "2024-01-03"),
        ]

        remover = DuplicateRemover(str(test_db))
        count = remover.remove_messages(messages, dry_run=False)

        assert count == 1

        # Verify only gid3 was deleted
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 4  # 5 - 1 = 4
        conn.close()

    def test_remove_uses_parameterized_query(self, test_db: Path) -> None:
        """Test that removal uses parameterized queries (SQL injection safe)."""
        # This test ensures the remover doesn't build SQL strings manually
        malicious_id = "gid1'; DROP TABLE messages; --"
        messages = [
            MessageInfo(malicious_id, "archive.mbox", 0, 1024, 1024, "2024-01-01"),
        ]

        remover = DuplicateRemover(str(test_db))
        # Returns count of messages in list, even if they don't exist
        count = remover.remove_messages(messages, dry_run=False)

        # Count reflects messages in the list (even if not in DB)
        assert count == 1

        # Verify table still exists and has all 5 messages
        # (malicious ID doesn't exist, so nothing was deleted)
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_close_connection(self, test_db: Path) -> None:
        """Test that close() closes the database connection."""
        remover = DuplicateRemover(str(test_db))
        remover.close()

        # Should not be able to query after close
        # (This is hard to test directly, but we can verify no error on double-close)
        remover.close()  # Should not raise
