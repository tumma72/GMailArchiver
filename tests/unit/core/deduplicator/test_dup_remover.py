"""Tests for duplicate remover module (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.deduplicator._remover import DuplicateRemover
from gmailarchiver.core.deduplicator._scanner import MessageInfo
from gmailarchiver.data.db_manager import DBManager


def create_v1_1_schema(db_path: Path) -> None:
    """Create v1.1 schema which allows duplicate rfc_message_ids."""
    conn = sqlite3.connect(str(db_path))

    # v1.1 schema has gmail_id as PK, allowing duplicate rfc_message_ids
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
        CREATE TABLE schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT NOT NULL
        )
    """)

    conn.execute("INSERT INTO schema_version VALUES ('1.1', datetime('now'))")
    conn.commit()
    conn.close()


@pytest.fixture
def test_db() -> Path:
    """Create test database with messages."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = Path(f.name)

    create_v1_1_schema(db_path)
    conn = sqlite3.connect(str(db_path))

    # Insert test messages
    for i in range(1, 6):
        conn.execute(
            """
            INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                                 size_bytes, archived_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (f"gid{i}", f"<msg{i}@test>", "archive.mbox", i * 1024, 1024, 1024, f"2024-01-0{i}"),
        )

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


@pytest.mark.unit
class TestDuplicateRemover:
    """Test duplicate message removal."""

    @pytest.mark.asyncio
    async def test_remove_messages_dry_run(self, test_db: Path) -> None:
        """Test dry run mode doesn't actually delete."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01"),
            MessageInfo("gid2", "archive.mbox", 1024, 1024, 1024, "2024-01-02"),
        ]

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        remover = DuplicateRemover(db)
        count = await remover.remove_messages(messages, dry_run=True)

        assert count == 2

        # Verify messages still exist
        cursor = await db.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id IN (?, ?)", ("gid1", "gid2")
        )
        row = await cursor.fetchone()
        assert row[0] == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_remove_messages_actual(self, test_db: Path) -> None:
        """Test actual removal deletes from database."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01"),
            MessageInfo("gid2", "archive.mbox", 1024, 1024, 1024, "2024-01-02"),
        ]

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        remover = DuplicateRemover(db)
        count = await remover.remove_messages(messages, dry_run=False)

        assert count == 2

        # Verify messages were deleted
        cursor = await db.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id IN (?, ?)", ("gid1", "gid2")
        )
        row = await cursor.fetchone()
        assert row[0] == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_remove_empty_list(self, test_db: Path) -> None:
        """Test removing empty list returns 0."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        remover = DuplicateRemover(db)
        count = await remover.remove_messages([], dry_run=False)

        assert count == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_remove_single_message(self, test_db: Path) -> None:
        """Test removing single message."""
        messages = [
            MessageInfo("gid3", "archive.mbox", 2048, 1024, 1024, "2024-01-03"),
        ]

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        remover = DuplicateRemover(db)
        count = await remover.remove_messages(messages, dry_run=False)

        assert count == 1

        # Verify only gid3 was deleted
        cursor = await db.conn.execute("SELECT COUNT(*) FROM messages")
        row = await cursor.fetchone()
        assert row[0] == 4  # 5 - 1 = 4
        await db.close()

    @pytest.mark.asyncio
    async def test_remove_uses_parameterized_query(self, test_db: Path) -> None:
        """Test that removal uses parameterized queries (SQL injection safe)."""
        # This test ensures the remover doesn't build SQL strings manually
        malicious_id = "gid1'; DROP TABLE messages; --"
        messages = [
            MessageInfo(malicious_id, "archive.mbox", 0, 1024, 1024, "2024-01-01"),
        ]

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        remover = DuplicateRemover(db)
        # Returns count of messages in list, even if they don't exist
        count = await remover.remove_messages(messages, dry_run=False)

        # Count reflects messages in the list (even if not in DB)
        assert count == 1

        # Verify table still exists and has all 5 messages
        # (malicious ID doesn't exist, so nothing was deleted)
        cursor = await db.conn.execute("SELECT COUNT(*) FROM messages")
        row = await cursor.fetchone()
        assert row[0] == 5
        await db.close()
