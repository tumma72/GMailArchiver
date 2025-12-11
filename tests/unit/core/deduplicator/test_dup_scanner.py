"""Tests for duplicate scanner module (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.deduplicator._scanner import DuplicateScanner
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
    """Create test database with duplicates."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = Path(f.name)

    # Create v1.1 schema (gmail_id as PK, allows duplicate rfc_message_ids)
    create_v1_1_schema(db_path)

    # Now insert data using a connection
    conn = sqlite3.connect(str(db_path))

    # Insert test data with duplicates
    # Duplicate group 1: <msg1@test> appears 3 times
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid1', '<msg1@test>', 'archive1.mbox', 0, 1024, 1024, '2024-01-01T10:00:00')
    """)
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid2', '<msg1@test>', 'archive2.mbox', 0, 1024, 1024, '2024-01-02T10:00:00')
    """)
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid3', '<msg1@test>', 'archive3.mbox', 0, 1024, 1024, '2024-01-03T10:00:00')
    """)

    # Duplicate group 2: <msg2@test> appears 2 times
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid4', '<msg2@test>', 'archive1.mbox', 1024, 2048, 2048, '2024-01-01T11:00:00')
    """)
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid5', '<msg2@test>', 'archive2.mbox', 1024, 2048, 2048, '2024-01-02T11:00:00')
    """)

    # Unique message: <msg3@test>
    conn.execute("""
        INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                             size_bytes, archived_timestamp)
        VALUES ('gid6', '<msg3@test>', 'archive1.mbox', 3072, 512, 512, '2024-01-01T12:00:00')
    """)

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


@pytest.mark.unit
class TestDuplicateScanner:
    """Test duplicate scanning functionality."""

    @pytest.mark.asyncio
    async def test_find_duplicates(self, test_db: Path) -> None:
        """Test finding duplicate messages."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)

        duplicates = await scanner.find_duplicates()

        # Should find 2 duplicate groups
        assert len(duplicates) == 2
        assert "<msg1@test>" in duplicates
        assert "<msg2@test>" in duplicates

        await db.close()

    @pytest.mark.asyncio
    async def test_duplicate_group_sizes(self, test_db: Path) -> None:
        """Test that duplicate groups have correct sizes."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)

        duplicates = await scanner.find_duplicates()

        # msg1 appears 3 times
        assert len(duplicates["<msg1@test>"]) == 3

        # msg2 appears 2 times
        assert len(duplicates["<msg2@test>"]) == 2

        await db.close()

    @pytest.mark.asyncio
    async def test_unique_messages_not_included(self, test_db: Path) -> None:
        """Test that unique messages are not included in results."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)

        duplicates = await scanner.find_duplicates()

        # msg3 is unique, should not be in results
        assert "<msg3@test>" not in duplicates

        await db.close()

    @pytest.mark.asyncio
    async def test_messages_sorted_by_timestamp(self, test_db: Path) -> None:
        """Test that messages are sorted by archived_timestamp DESC."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)

        duplicates = await scanner.find_duplicates()

        # msg1 group should be sorted newest first
        msg1_group = duplicates["<msg1@test>"]
        assert msg1_group[0].gmail_id == "gid3"  # 2024-01-03
        assert msg1_group[1].gmail_id == "gid2"  # 2024-01-02
        assert msg1_group[2].gmail_id == "gid1"  # 2024-01-01

        await db.close()

    @pytest.mark.asyncio
    async def test_message_info_fields(self, test_db: Path) -> None:
        """Test that MessageInfo contains all required fields."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)

        duplicates = await scanner.find_duplicates()

        msg = duplicates["<msg1@test>"][0]
        assert msg.gmail_id == "gid3"
        assert msg.archive_file == "archive3.mbox"
        assert msg.mbox_offset == 0
        assert msg.mbox_length == 1024
        assert msg.size_bytes == 1024
        assert msg.archived_timestamp == "2024-01-03T10:00:00"

        await db.close()

    @pytest.mark.asyncio
    async def test_no_duplicates_returns_empty(self) -> None:
        """Test that database with no duplicates returns empty dict."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = Path(f.name)

        create_v1_1_schema(db_path)
        conn = sqlite3.connect(str(db_path))

        # Insert only unique messages
        conn.execute("""
            INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                                 size_bytes, archived_timestamp)
            VALUES ('gid1', '<msg1@test>', 'archive.mbox', 0, 1024, 1024, '2024-01-01T10:00:00')
        """)
        conn.execute("""
            INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                                 size_bytes, archived_timestamp)
            VALUES ('gid2', '<msg2@test>', 'archive.mbox', 1024, 1024, 1024, '2024-01-01T11:00:00')
        """)
        conn.commit()
        conn.close()

        db = DBManager(str(db_path), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)
        duplicates = await scanner.find_duplicates()

        assert len(duplicates) == 0

        await db.close()
        db_path.unlink()

    @pytest.mark.asyncio
    async def test_null_size_bytes_uses_mbox_length(self, test_db: Path) -> None:
        """Test that NULL size_bytes falls back to mbox_length."""
        # Insert message with NULL size_bytes
        conn = sqlite3.connect(str(test_db))
        conn.execute("""
            INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                                 size_bytes, archived_timestamp)
            VALUES ('gid7', '<msg4@test>', 'archive.mbox', 4096, 2000, NULL, '2024-01-01T13:00:00')
        """)
        conn.execute("""
            INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                                 size_bytes, archived_timestamp)
            VALUES ('gid8', '<msg4@test>', 'archive.mbox', 6096, 2000, NULL, '2024-01-02T13:00:00')
        """)
        conn.commit()
        conn.close()

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        scanner = DuplicateScanner(db)
        duplicates = await scanner.find_duplicates()

        # Should have msg4 group
        assert "<msg4@test>" in duplicates
        # Size should fallback to mbox_length
        assert duplicates["<msg4@test>"][0].size_bytes == 2000

        await db.close()
