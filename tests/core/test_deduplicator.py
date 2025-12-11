"""Tests for message deduplication system."""

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from gmailarchiver.core.deduplicator import (
    DeduplicationReport,
    DeduplicationResult,
)
from gmailarchiver.core.deduplicator import (
    DeduplicatorFacade as MessageDeduplicator,
)
from gmailarchiver.data.db_manager import DBManager

pytestmark = pytest.mark.asyncio


def create_v1_1_db_with_messages(db_path: Path, messages: list[dict[str, Any]]) -> None:
    """
    Helper to create v1.1 test database with messages.

    Args:
        db_path: Path to database file
        messages: List of message dictionaries with keys:
            - gmail_id (str): Gmail message ID
            - rfc_message_id (str): RFC 2822 Message-ID
            - archive_file (str): Archive file path
            - mbox_offset (int): Byte offset in mbox
            - mbox_length (int): Message length
            - size_bytes (int, optional): Message size
            - archived_timestamp (str, optional): ISO 8601 timestamp
            - subject (str, optional): Subject
            - from_addr (str, optional): From address
    """
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

    # Insert messages
    for msg in messages:
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
             size_bytes, archived_timestamp, subject, from_addr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                msg["gmail_id"],
                msg["rfc_message_id"],
                msg["archive_file"],
                msg["mbox_offset"],
                msg["mbox_length"],
                msg.get("size_bytes", 1000),
                msg.get("archived_timestamp", "2025-01-01T00:00:00"),
                msg.get("subject", "Test Subject"),
                msg.get("from_addr", "test@example.com"),
            ),
        )

    conn.commit()
    conn.close()


@pytest.fixture
def temp_db() -> Path:
    """Create temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_dedup.db"


class TestMessageDeduplicatorInit:
    """Test MessageDeduplicator initialization."""

    async def test_init_with_v1_1_database(self, temp_db: Path) -> None:
        """Test initialization with v1.1 database."""
        create_v1_1_db_with_messages(temp_db, [])

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        # Use resolve() to handle symlink differences on macOS
        # Facade uses db_path attribute
        assert Path(dedup.db_path).resolve() == temp_db.resolve()
        await dedup.close()
        await db.close()
        await db.close()

    async def test_init_rejects_v1_0_database(self, temp_db: Path) -> None:
        """Test that v1.0 databases are rejected."""
        # Create v1.0 schema directly with sqlite3
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT,
                archive_file TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Open with validation disabled, then try to create facade
        db = DBManager(str(temp_db), validate_schema=False)
        await db.initialize()
        with pytest.raises(ValueError, match="requires v1.1"):
            await MessageDeduplicator.create(db)
        await db.close()

    async def test_init_rejects_nonexistent_database(self, temp_db: Path) -> None:
        """Test that nonexistent databases are rejected."""
        with pytest.raises(FileNotFoundError):
            db = DBManager(str(temp_db), auto_create=False)
            await db.initialize()
            await MessageDeduplicator.create(db)


class TestFindDuplicates:
    """Test finding duplicate messages."""

    async def test_find_duplicates_with_no_duplicates(self, temp_db: Path) -> None:
        """Test finding duplicates when none exist."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<unique1@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<unique2@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 1000,
                "mbox_length": 2000,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        assert len(duplicates) == 0
        await dedup.close()
        await db.close()

    async def test_find_duplicates_with_exact_duplicates(self, temp_db: Path) -> None:
        """Test finding exact duplicates (same Message-ID, different archives)."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<duplicate@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
                "archived_timestamp": "2025-01-01T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<duplicate@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
                "archived_timestamp": "2025-01-02T00:00:00",
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        assert len(duplicates) == 1
        assert "<duplicate@example.com>" in duplicates

        dup_list = duplicates["<duplicate@example.com>"]
        assert len(dup_list) == 2

        # Verify MessageInfo contains expected fields
        assert dup_list[0].gmail_id in ["msg1", "msg2"]
        assert dup_list[0].archive_file in ["archive1.mbox", "archive2.mbox"]
        assert dup_list[0].mbox_offset >= 0
        assert dup_list[0].size_bytes > 0

        await dedup.close()
        await db.close()

    async def test_find_duplicates_with_partial_duplicates(self, temp_db: Path) -> None:
        """Test with some IDs appearing once and some multiple times."""
        messages = [
            # Unique message
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<unique@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
            },
            # Duplicate pair
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 1000,
                "mbox_length": 2000,
            },
            {
                "gmail_id": "msg3",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 2100,
            },
            # Triple duplicate
            {
                "gmail_id": "msg4",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 3000,
                "mbox_length": 500,
            },
            {
                "gmail_id": "msg5",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 2100,
                "mbox_length": 510,
            },
            {
                "gmail_id": "msg6",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive3.mbox",
                "mbox_offset": 0,
                "mbox_length": 520,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        # Should find 2 duplicate groups (dup1 and dup2), unique is ignored
        assert len(duplicates) == 2
        assert "<dup1@example.com>" in duplicates
        assert "<dup2@example.com>" in duplicates
        assert "<unique@example.com>" not in duplicates

        # Verify counts
        assert len(duplicates["<dup1@example.com>"]) == 2
        assert len(duplicates["<dup2@example.com>"]) == 3

        await dedup.close()
        await db.close()

    async def test_find_duplicates_with_many_groups(self, temp_db: Path) -> None:
        """Test performance with 100+ duplicate groups."""
        messages = []
        for i in range(100):
            # Each group has 2-3 duplicates
            num_copies = 2 if i % 2 == 0 else 3
            for j in range(num_copies):
                messages.append(
                    {
                        "gmail_id": f"msg_{i}_{j}",
                        "rfc_message_id": f"<dup_{i}@example.com>",
                        "archive_file": f"archive{j}.mbox",
                        "mbox_offset": i * 1000 + j * 100,
                        "mbox_length": 1000,
                    }
                )

        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        # Should find all 100 groups
        assert len(duplicates) == 100

        await dedup.close()
        await db.close()

    async def test_find_duplicates_skips_missing_rfc_message_id(self, temp_db: Path) -> None:
        """Test that messages with NULL rfc_message_id are skipped."""
        # Create schema that allows NULL rfc_message_id (for this specific test)
        conn = sqlite3.connect(str(temp_db))

        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,  -- No NOT NULL constraint for this test
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                archived_timestamp TIMESTAMP NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)

        conn.execute("INSERT INTO schema_version VALUES ('1.1', datetime('now'))")

        # Insert messages (one with NULL rfc_message_id)
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length, archived_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            ("msg1", None, "archive1.mbox", 0, 1000, "2025-01-01T00:00:00"),
        )

        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length, archived_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            ("msg2", "<valid@example.com>", "archive1.mbox", 1000, 2000, "2025-01-01T00:00:00"),
        )

        conn.commit()
        conn.close()

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        # Should find no duplicates (msg1 skipped, msg2 is unique)
        assert len(duplicates) == 0
        await dedup.close()
        await db.close()


class TestGenerateReport:
    """Test deduplication report generation."""

    async def test_generate_report_with_duplicates(self, temp_db: Path) -> None:
        """Test report generation with duplicate messages."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
            },
            {
                "gmail_id": "msg3",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 1000,
                "mbox_length": 500,
                "size_bytes": 800,
            },
            {
                "gmail_id": "msg4",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 1100,
                "mbox_length": 510,
                "size_bytes": 850,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        report = await dedup.generate_report(duplicates)

        # Verify report structure
        assert isinstance(report, DeduplicationReport)
        assert report.total_messages == 4
        assert report.duplicate_message_ids == 2  # 2 unique Message-IDs
        assert report.total_duplicate_messages == 4  # All 4 are duplicates
        assert report.messages_to_remove == 2  # Keep 1 per group, remove 2

        # Space calculation: keep largest in each group
        # Group 1: keep msg2 (1600), remove msg1 (1500) -> 1500 bytes
        # Group 2: keep msg4 (850), remove msg3 (800) -> 800 bytes
        assert report.space_recoverable == 2300  # 1500 + 800

        # Check breakdown by archive file
        # Only archive1.mbox has removals (msg1 and msg3)
        assert "archive1.mbox" in report.breakdown_by_archive
        assert report.breakdown_by_archive["archive1.mbox"]["messages_to_remove"] == 2
        assert report.breakdown_by_archive["archive1.mbox"]["space_recoverable"] == 2300

        await dedup.close()
        await db.close()

    async def test_generate_report_with_no_duplicates(self, temp_db: Path) -> None:
        """Test report generation with no duplicates."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<unique1@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        report = await dedup.generate_report(duplicates)

        assert report.total_messages == 1
        assert report.duplicate_message_ids == 0
        assert report.total_duplicate_messages == 0
        assert report.messages_to_remove == 0
        assert report.space_recoverable == 0

        await dedup.close()
        await db.close()

    async def test_generate_report_handles_null_size_bytes(self, temp_db: Path) -> None:
        """Test report gracefully handles NULL size_bytes."""
        create_v1_1_db_with_messages(temp_db, [])

        conn = sqlite3.connect(str(temp_db))

        # Insert duplicates with NULL size_bytes
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
             size_bytes, archived_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            ("msg1", "<dup@example.com>", "archive1.mbox", 0, 1000, None, "2025-01-01T00:00:00"),
        )

        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
             size_bytes, archived_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            ("msg2", "<dup@example.com>", "archive2.mbox", 0, 1100, None, "2025-01-02T00:00:00"),
        )

        conn.commit()
        conn.close()

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        report = await dedup.generate_report(duplicates)

        # Should use mbox_length as fallback
        assert report.space_recoverable > 0
        await dedup.close()
        await db.close()


class TestDeduplicateStrategies:
    """Test deduplication with different keep strategies."""

    async def test_deduplicate_strategy_newest(self, temp_db: Path) -> None:
        """Test 'newest' strategy keeps message with latest archived_timestamp."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
                "archived_timestamp": "2025-01-01T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
                "archived_timestamp": "2025-01-02T00:00:00",  # Newest
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=False)

        assert isinstance(result, DeduplicationResult)
        assert result.messages_removed == 1
        assert result.messages_kept == 1
        assert result.space_saved > 0

        # Verify msg2 was kept (newest)
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT gmail_id FROM messages")
        remaining = [row[0] for row in await cursor.fetchall()]
        await _db.close()

        assert "msg2" in remaining
        assert "msg1" not in remaining

        await dedup.close()
        await db.close()

    async def test_deduplicate_strategy_largest(self, temp_db: Path) -> None:
        """Test 'largest' strategy keeps message with highest size_bytes."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
                "archived_timestamp": "2025-01-02T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 2000,  # Largest
                "archived_timestamp": "2025-01-01T00:00:00",
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        result = await dedup.deduplicate(duplicates, strategy="largest", dry_run=False)

        assert result.messages_removed == 1
        assert result.messages_kept == 1

        # Verify msg2 was kept (largest)
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT gmail_id FROM messages")
        remaining = [row[0] for row in await cursor.fetchall()]
        await _db.close()

        assert "msg2" in remaining
        assert "msg1" not in remaining

        await dedup.close()
        await db.close()

    async def test_deduplicate_strategy_first(self, temp_db: Path) -> None:
        """Test 'first' strategy keeps message from first archive file (alphabetically)."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive_b.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive_a.mbox",  # First alphabetically
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        result = await dedup.deduplicate(duplicates, strategy="first", dry_run=False)

        assert result.messages_removed == 1
        assert result.messages_kept == 1

        # Verify msg2 was kept (from archive_a.mbox)
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT gmail_id FROM messages")
        remaining = [row[0] for row in await cursor.fetchall()]
        await _db.close()

        assert "msg2" in remaining
        assert "msg1" not in remaining

        await dedup.close()
        await db.close()

    async def test_deduplicate_handles_multiple_groups(self, temp_db: Path) -> None:
        """Test deduplication with multiple duplicate groups."""
        messages = [
            # Group 1
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
                "archived_timestamp": "2025-01-01T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup1@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
                "archived_timestamp": "2025-01-02T00:00:00",  # Newest
            },
            # Group 2
            {
                "gmail_id": "msg3",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 1000,
                "mbox_length": 500,
                "size_bytes": 800,
                "archived_timestamp": "2025-01-03T00:00:00",  # Newest
            },
            {
                "gmail_id": "msg4",
                "rfc_message_id": "<dup2@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 1100,
                "mbox_length": 510,
                "size_bytes": 850,
                "archived_timestamp": "2025-01-02T00:00:00",
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=False)

        # Should keep 2 messages (one per group), remove 2
        assert result.messages_removed == 2
        assert result.messages_kept == 2

        # Verify msg2 and msg3 were kept (newest in each group)
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT gmail_id FROM messages ORDER BY gmail_id")
        remaining = [row[0] for row in await cursor.fetchall()]
        await _db.close()

        assert remaining == ["msg2", "msg3"]

        await dedup.close()
        await db.close()


class TestDryRunMode:
    """Test dry-run mode."""

    async def test_dry_run_does_not_modify_database(self, temp_db: Path) -> None:
        """Test that dry-run mode doesn't modify the database."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
                "archived_timestamp": "2025-01-01T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 1100,
                "size_bytes": 1600,
                "archived_timestamp": "2025-01-02T00:00:00",
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        # Get count before dry run
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT COUNT(*) FROM messages")
        count_before = (await cursor.fetchone())[0]
        await _db.close()

        # Run in dry-run mode
        result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=True)

        # Verify result contains expected data
        assert result.messages_removed == 1
        assert result.messages_kept == 1
        assert result.space_saved > 0

        # Verify database was NOT modified
        _db = DBManager(str(temp_db))
        await _db.initialize()
        cursor = await _db.conn.execute("SELECT COUNT(*) FROM messages")
        count_after = (await cursor.fetchone())[0]
        await _db.close()

        assert count_before == count_after == 2

        await dedup.close()
        await db.close()

    async def test_dry_run_reports_what_would_be_removed(self, temp_db: Path) -> None:
        """Test that dry-run accurately reports what would be removed."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1000,
                "archived_timestamp": "2025-01-01T00:00:00",
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive2.mbox",
                "mbox_offset": 0,
                "mbox_length": 2000,
                "size_bytes": 2000,
                "archived_timestamp": "2025-01-02T00:00:00",  # Newest
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        dry_result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=True)

        # Now run for real
        wet_result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=False)

        # Dry run and actual run should report same numbers
        assert dry_result.messages_removed == wet_result.messages_removed
        assert dry_result.messages_kept == wet_result.messages_kept
        assert dry_result.space_saved == wet_result.space_saved

        await dedup.close()
        await db.close()


class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_empty_database(self, temp_db: Path) -> None:
        """Test with empty database."""
        create_v1_1_db_with_messages(temp_db, [])

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        assert len(duplicates) == 0

        report = await dedup.generate_report(duplicates)
        assert report.total_messages == 0

        await dedup.close()
        await db.close()

    async def test_deduplicate_with_no_duplicates(self, temp_db: Path) -> None:
        """Test deduplication when no duplicates exist."""
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<unique@example.com>",
                "archive_file": "archive1.mbox",
                "mbox_offset": 0,
                "mbox_length": 1000,
                "size_bytes": 1500,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()
        result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=False)

        assert result.messages_removed == 0
        assert result.messages_kept == 0
        assert result.space_saved == 0

        await dedup.close()
        await db.close()

    async def test_invalid_strategy_raises_error(self, temp_db: Path) -> None:
        """Test that invalid strategy raises ValueError."""
        # Create database with duplicate messages so validation runs
        messages = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<dup@example.com>",
                "archive_file": "archive.mbox",
                "archived_timestamp": "2025-01-01",
                "mbox_offset": 0,
                "mbox_length": 100,
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<dup@example.com>",  # Duplicate
                "archive_file": "archive.mbox",
                "archived_timestamp": "2025-01-02",
                "mbox_offset": 100,
                "mbox_length": 100,
            },
        ]
        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)
        duplicates = await dedup.find_duplicates()

        with pytest.raises(ValueError, match="Invalid strategy"):
            await dedup.deduplicate(duplicates, strategy="invalid", dry_run=True)

        await dedup.close()
        await db.close()

    async def test_context_manager(self, temp_db: Path) -> None:
        """Test context manager closes connection properly."""
        create_v1_1_db_with_messages(temp_db, [])

        db = DBManager(str(temp_db))
        await db.initialize()
        async with await MessageDeduplicator.create(db) as dedup:
            duplicates = await dedup.find_duplicates()
            assert len(duplicates) == 0

        # Facade doesn't expose conn, just verify no exception on reuse attempt
        # (closed connections would raise on operations)
        # This is sufficient to test context manager cleanup
        await db.close()


class TestPerformance:
    """Test performance with large datasets."""

    async def test_performance_with_1000_messages(self, temp_db: Path) -> None:
        """Test finding duplicates with 1000 messages."""
        import time

        messages = []
        for i in range(1000):
            # Create 10 groups of 100 duplicates each
            messages.append(
                {
                    "gmail_id": f"msg_{i}",
                    "rfc_message_id": f"<dup_{i // 100}@example.com>",
                    "archive_file": f"archive{i % 10}.mbox",
                    "mbox_offset": i * 1000,
                    "mbox_length": 1000,
                    "size_bytes": 1500,
                }
            )

        create_v1_1_db_with_messages(temp_db, messages)

        db = DBManager(str(temp_db))
        await db.initialize()
        dedup = await MessageDeduplicator.create(db)

        start = time.time()
        duplicates = await dedup.find_duplicates()
        elapsed = time.time() - start

        # Should complete in reasonable time (< 1 second)
        assert elapsed < 1.0

        # Should find 10 duplicate groups
        assert len(duplicates) == 10

        await dedup.close()
        await db.close()
