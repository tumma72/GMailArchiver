"""Tests for archive consolidation functionality."""

import mailbox
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gmailarchiver.core.consolidator import ArchiveConsolidator, ConsolidationResult
from gmailarchiver.data.db_manager import DBManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_db(temp_dir):
    """Create a test state database with v1.1 schema."""
    db_path = temp_dir / "test_state.db"

    # Create database with v1.1 schema BEFORE ArchiveState initializes
    # This prevents ArchiveState from creating old schema tables
    conn = sqlite3.connect(str(db_path))

    # Create messages table with full v1.1 schema
    # NOTE: Removed UNIQUE constraint on rfc_message_id for testing deduplication
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

    # Create archive_runs table (match DBManager expectations)
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

    # Create old tables for backward compatibility (ArchiveState expects these)
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

    return db_path


@pytest.fixture
async def sample_mbox_1(temp_dir, state_db):
    """Create first sample mbox archive.

    Uses async fixture to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    mbox_path = temp_dir / "archive1.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Add 3 messages with different dates
    for i in range(3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test Message {i}"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg["Date"] = f"Wed, {10 + i} Jan 2024 12:00:00 +0000"
        msg.set_payload(f"Body of message {i}")
        mbox.add(msg)

    mbox.close()

    # Add to database with v1.1 schema using async DBManager
    async with DBManager(str(state_db), validate_schema=False) as db:
        for i in range(3):
            await db.record_archived_message(
                gmail_id=f"gmail{i}",
                rfc_message_id=f"<msg{i}@example.com>",
                archive_file=str(mbox_path),
                mbox_offset=0,  # placeholder offset
                mbox_length=100,  # placeholder length
                subject=f"Test Message {i}",
                from_addr=f"sender{i}@example.com",
                to_addr="recipient@example.com",
                date=f"2024-01-{10 + i}T12:00:00+00:00",
                thread_id=f"thread{i}",
                cc_addr=None,
                body_preview=f"Body of message {i}",
                checksum="abc123",
                size_bytes=100,
                labels="[]",
                record_run=False,
            )

    return mbox_path


@pytest.fixture
async def sample_mbox_2(temp_dir, state_db):
    """Create second sample mbox archive.

    Uses async fixture to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    mbox_path = temp_dir / "archive2.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Add 3 messages with different dates
    for i in range(3, 6):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test Message {i}"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg["Date"] = f"Wed, {10 + i} Jan 2024 12:00:00 +0000"
        msg.set_payload(f"Body of message {i}")
        mbox.add(msg)

    mbox.close()

    # Add to database with v1.1 schema using async DBManager
    async with DBManager(str(state_db), validate_schema=False) as db:
        for i in range(3, 6):
            await db.record_archived_message(
                gmail_id=f"gmail{i}",
                rfc_message_id=f"<msg{i}@example.com>",
                archive_file=str(mbox_path),
                mbox_offset=0,  # placeholder offset
                mbox_length=100,  # placeholder length
                subject=f"Test Message {i}",
                from_addr=f"sender{i}@example.com",
                to_addr="recipient@example.com",
                date=f"2024-01-{10 + i}T12:00:00+00:00",
                thread_id=f"thread{i}",
                cc_addr=None,
                body_preview=f"Body of message {i}",
                checksum="abc123",
                size_bytes=100,
                labels="[]",
                record_run=False,
            )

    return mbox_path


@pytest.fixture
async def mbox_with_duplicates(temp_dir, state_db):
    """Create mbox archives with duplicate messages.

    Uses async fixture to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    mbox1_path = temp_dir / "dup_archive1.mbox"
    mbox2_path = temp_dir / "dup_archive2.mbox"

    # First archive with 2 messages
    mbox1 = mailbox.mbox(str(mbox1_path))
    for i in range(2):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Duplicate Test {i}"
        msg["Message-ID"] = f"<dup{i}@example.com>"
        msg["Date"] = f"Mon, {5 + i} Feb 2024 10:00:00 +0000"
        msg.set_payload(f"First version of message {i}")
        mbox1.add(msg)
    mbox1.close()

    # Second archive with 1 duplicate and 1 unique
    mbox2 = mailbox.mbox(str(mbox2_path))

    # Duplicate of message 1 (newer date)
    msg_dup = mailbox.mboxMessage()
    msg_dup["From"] = "sender1@example.com"
    msg_dup["To"] = "recipient@example.com"
    msg_dup["Subject"] = "Duplicate Test 1"
    msg_dup["Message-ID"] = "<dup1@example.com>"
    msg_dup["Date"] = "Tue, 7 Feb 2024 10:00:00 +0000"  # Newer
    msg_dup.set_payload("Second version of message 1 (newer)")
    mbox2.add(msg_dup)

    # Unique message
    msg_unique = mailbox.mboxMessage()
    msg_unique["From"] = "sender2@example.com"
    msg_unique["To"] = "recipient@example.com"
    msg_unique["Subject"] = "Unique Message"
    msg_unique["Message-ID"] = "<unique@example.com>"
    msg_unique["Date"] = "Wed, 8 Feb 2024 10:00:00 +0000"
    msg_unique.set_payload("This message is unique")
    mbox2.add(msg_unique)

    mbox2.close()

    # Add to database with v1.1 schema using async DBManager
    async with DBManager(str(state_db), validate_schema=False) as db:
        # From archive1
        for i in range(2):
            await db.record_archived_message(
                gmail_id=f"gmail_dup{i}",
                rfc_message_id=f"<dup{i}@example.com>",
                archive_file=str(mbox1_path),
                mbox_offset=0,
                mbox_length=100,
                subject=f"Duplicate Test {i}",
                from_addr=f"sender{i}@example.com",
                to_addr="recipient@example.com",
                date=f"2024-02-0{5 + i}T10:00:00+00:00",
                thread_id=f"thread_dup{i}",
                cc_addr=None,
                body_preview=f"First version of message {i}",
                checksum="abc123",
                size_bytes=100,
                labels="[]",
                record_run=False,
            )

        # From archive2 (duplicate has different gmail_id)
        await db.record_archived_message(
            gmail_id="gmail_dup1_v2",
            rfc_message_id="<dup1@example.com>",
            archive_file=str(mbox2_path),
            mbox_offset=0,
            mbox_length=100,
            subject="Duplicate Test 1",
            from_addr="sender1@example.com",
            to_addr="recipient@example.com",
            date="2024-02-07T10:00:00+00:00",
            thread_id="thread_dup1",
            cc_addr=None,
            body_preview="Second version of message 1 (newer)",
            checksum="abc123",
            size_bytes=100,
            labels="[]",
            record_run=False,
        )

        await db.record_archived_message(
            gmail_id="gmail_unique",
            rfc_message_id="<unique@example.com>",
            archive_file=str(mbox2_path),
            mbox_offset=0,
            mbox_length=100,
            subject="Unique Message",
            from_addr="sender2@example.com",
            to_addr="recipient@example.com",
            date="2024-02-08T10:00:00+00:00",
            thread_id="thread_unique",
            cc_addr=None,
            body_preview="This message is unique",
            checksum="abc123",
            size_bytes=100,
            labels="[]",
            record_run=False,
        )

    return mbox1_path, mbox2_path


class TestArchiveConsolidatorInit:
    """Tests for ArchiveConsolidator initialization."""

    async def test_init_with_valid_db(self, state_db):
        """Test initialization with valid database manager."""
        db_manager = DBManager(str(state_db), validate_schema=False)
        await db_manager.initialize()
        consolidator = ArchiveConsolidator(db_manager)
        assert consolidator.db_manager is db_manager
        await db_manager.close()

    async def test_init_with_nonexistent_db(self, temp_dir):
        """Test initialization with nonexistent database path."""
        db_path = temp_dir / "nonexistent.db"
        async with DBManager(str(db_path), validate_schema=False) as manager:
            consolidator = ArchiveConsolidator(manager)
            assert consolidator.db_manager is manager


class TestBasicConsolidation:
    """Tests for basic archive consolidation."""

    async def test_consolidate_two_archives(self, temp_dir, state_db, sample_mbox_1, sample_mbox_2):
        """Test consolidating two archives merges all messages."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2],
                output_archive=output_path,
                sort_by_date=False,
                deduplicate=False,
            )

            assert isinstance(result, ConsolidationResult)
            assert result.output_file == str(output_path)
            assert result.total_messages == 6
            assert result.messages_consolidated == 6
            assert result.duplicates_removed == 0
            assert output_path.exists()

            # Verify all messages in output
            mbox = mailbox.mbox(str(output_path))
            assert len(mbox) == 6
            mbox.close()

    async def test_consolidate_with_result_fields(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test ConsolidationResult contains all required fields."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2], output_archive=output_path
            )

            assert result.output_file == str(output_path)
            assert len(result.source_files) == 2
            assert result.total_messages > 0
            assert result.duplicates_removed >= 0
            assert result.messages_consolidated > 0
            assert result.execution_time_ms > 0
            assert isinstance(result.sort_applied, bool)
            assert result.compression_used is None or isinstance(result.compression_used, str)

    async def test_consolidate_empty_archives(self, temp_dir, state_db):
        """Test consolidating empty archives handles gracefully."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)

            # Create empty mbox files
            empty1 = temp_dir / "empty1.mbox"
            empty2 = temp_dir / "empty2.mbox"
            empty1.touch()
            empty2.touch()

            output_path = temp_dir / "consolidated.mbox"

            result = await consolidator.consolidate(
                source_archives=[empty1, empty2], output_archive=output_path
            )

            assert result.total_messages == 0
            assert result.messages_consolidated == 0

    async def test_consolidate_single_archive(self, temp_dir, state_db, sample_mbox_1):
        """Test consolidating single archive works."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path
            )

            assert result.total_messages == 3
            assert result.messages_consolidated == 3

    async def test_consolidate_preserves_message_content(self, temp_dir, state_db, sample_mbox_1):
        """Test consolidation preserves message headers and body."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path, sort_by_date=False
            )

            # Compare original and consolidated
            orig_mbox = mailbox.mbox(str(sample_mbox_1))
            cons_mbox = mailbox.mbox(str(output_path))

            orig_msg = orig_mbox[0]
            cons_msg = cons_mbox[0]

            assert orig_msg["Subject"] == cons_msg["Subject"]
            assert orig_msg["From"] == cons_msg["From"]
            assert orig_msg["Message-ID"] == cons_msg["Message-ID"]
            assert orig_msg.get_payload() == cons_msg.get_payload()

            orig_mbox.close()
            cons_mbox.close()


class TestSorting:
    """Tests for chronological sorting."""

    async def test_sort_by_date_chronological(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test sorting produces chronological order."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "sorted.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_2, sample_mbox_1],  # Reversed order
                output_archive=output_path,
                sort_by_date=True,
            )

            assert result.sort_applied is True

            # Verify chronological order
            mbox = mailbox.mbox(str(output_path))
            dates = []
            for msg in mbox:
                dates.append(msg["Date"])
            mbox.close()

            # Should be in ascending order by date
            assert dates[0].startswith("Wed, 10 Jan")
            assert dates[-1].startswith("Wed, 15 Jan")

    async def test_no_sort_preserves_order(self, temp_dir, state_db, sample_mbox_1, sample_mbox_2):
        """Test without sorting preserves original order."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "unsorted.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_2, sample_mbox_1],  # archive2 first
                output_archive=output_path,
                sort_by_date=False,
            )

            assert result.sort_applied is False

            # First 3 messages should be from archive2 (msg3, msg4, msg5)
            mbox = mailbox.mbox(str(output_path))
            first_msg = mbox[0]
            assert first_msg["Message-ID"] == "<msg3@example.com>"
            mbox.close()

    async def test_sort_handles_malformed_dates(self, temp_dir, state_db):
        """Test sorting handles messages with malformed dates."""
        # Create mbox with bad dates
        mbox_path = temp_dir / "bad_dates.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg1 = mailbox.mboxMessage()
        msg1["Message-ID"] = "<good@example.com>"
        msg1["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg1.set_payload("Good date")
        mbox.add(msg1)

        msg2 = mailbox.mboxMessage()
        msg2["Message-ID"] = "<bad@example.com>"
        msg2["Date"] = "INVALID DATE"
        msg2.set_payload("Bad date")
        mbox.add(msg2)

        mbox.close()

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "sorted_with_bad.mbox"

            # Should not crash
            result = await consolidator.consolidate(
                source_archives=[mbox_path], output_archive=output_path, sort_by_date=True
            )

            assert result.total_messages == 2


class TestDeduplication:
    """Tests for duplicate message handling."""

    async def test_deduplicate_removes_duplicates(self, temp_dir, state_db, mbox_with_duplicates):
        """Test deduplication removes duplicate messages."""
        mbox1, mbox2 = mbox_with_duplicates
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "deduped.mbox"

            result = await consolidator.consolidate(
                source_archives=[mbox1, mbox2],
                output_archive=output_path,
                deduplicate=True,
                dedupe_strategy="newest",
            )

            assert result.duplicates_removed == 1
            assert result.messages_consolidated == 3  # 2 from mbox1 + 2 from mbox2 - 1 dup

            # Verify only 3 messages in output
            mbox = mailbox.mbox(str(output_path))
            assert len(mbox) == 3
            mbox.close()

    async def test_deduplicate_newest_strategy(self, temp_dir, state_db, mbox_with_duplicates):
        """Test newest strategy keeps the newer message."""
        mbox1, mbox2 = mbox_with_duplicates
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "deduped_newest.mbox"

            await consolidator.consolidate(
                source_archives=[mbox1, mbox2],
                output_archive=output_path,
                deduplicate=True,
                dedupe_strategy="newest",
            )

            # Find the kept message with Message-ID <dup1@example.com>
            mbox = mailbox.mbox(str(output_path))
            kept_msg = None
            for msg in mbox:
                if msg["Message-ID"] == "<dup1@example.com>":
                    kept_msg = msg
                    break
            mbox.close()

            assert kept_msg is not None
            # Newer version has different body
            assert "newer" in kept_msg.get_payload()

    async def test_no_deduplicate_keeps_all(self, temp_dir, state_db, mbox_with_duplicates):
        """Test without deduplication keeps all messages."""
        mbox1, mbox2 = mbox_with_duplicates
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "no_dedup.mbox"

            result = await consolidator.consolidate(
                source_archives=[mbox1, mbox2], output_archive=output_path, deduplicate=False
            )

            assert result.duplicates_removed == 0
            assert result.total_messages == 4  # All messages kept

    async def test_deduplicate_largest_strategy(self, temp_dir, state_db):
        """Test largest strategy keeps the bigger message."""
        # Create archives with same Message-ID but different sizes
        mbox1_path = temp_dir / "small.mbox"
        mbox2_path = temp_dir / "large.mbox"

        mbox1 = mailbox.mbox(str(mbox1_path))
        msg_small = mailbox.mboxMessage()
        msg_small["Message-ID"] = "<same@example.com>"
        msg_small["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg_small.set_payload("Small body")
        mbox1.add(msg_small)
        mbox1.close()

        mbox2 = mailbox.mbox(str(mbox2_path))
        msg_large = mailbox.mboxMessage()
        msg_large["Message-ID"] = "<same@example.com>"
        msg_large["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg_large.set_payload("Large body with much more content here")
        mbox2.add(msg_large)
        mbox2.close()

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "deduped_largest.mbox"

            await consolidator.consolidate(
                source_archives=[mbox1_path, mbox2_path],
                output_archive=output_path,
                deduplicate=True,
                dedupe_strategy="largest",
            )

            # Verify larger message kept
            mbox = mailbox.mbox(str(output_path))
            kept_msg = mbox[0]
            assert "much more content" in kept_msg.get_payload()
            mbox.close()


class TestDatabaseUpdate:
    """Tests for database updates after consolidation."""

    async def test_database_updated_with_new_archive_file(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test database updated with new archive file path."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2], output_archive=output_path
            )

        # Check database
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("""
                SELECT DISTINCT archive_file FROM messages
            """)
            archive_files = [row[0] for row in cursor.fetchall()]

        # All messages should point to consolidated archive
        assert str(output_path) in archive_files

    async def test_database_updated_with_mbox_offsets(self, temp_dir, state_db, sample_mbox_1):
        """Test database updated with correct mbox offsets."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path
            )

        # Check offsets are updated
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT rfc_message_id, mbox_offset, mbox_length
                FROM messages
                WHERE archive_file = ?
            """,
                (str(output_path),),
            )
            rows = cursor.fetchall()

        assert len(rows) == 3
        for msg_id, offset, length in rows:
            assert offset is not None
            assert offset >= 0
            assert length > 0

    async def test_database_removes_duplicate_entries(
        self, temp_dir, state_db, mbox_with_duplicates
    ):
        """Test database removes entries for duplicate messages."""
        mbox1, mbox2 = mbox_with_duplicates

        # Count before
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages")
            count_before = cursor.fetchone()[0]

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "deduped.mbox"

            await consolidator.consolidate(
                source_archives=[mbox1, mbox2], output_archive=output_path, deduplicate=True
            )

        # Count after
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages")
            count_after = cursor.fetchone()[0]

        # Should have 1 less entry (duplicate removed)
        assert count_after == count_before - 1

    async def test_database_preserves_metadata(self, temp_dir, state_db, sample_mbox_1):
        """Test consolidation preserves message metadata in database."""
        # Get original metadata
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT rfc_message_id, subject, from_addr
                FROM messages
                WHERE archive_file = ?
            """,
                (str(sample_mbox_1),),
            )
            original_metadata = cursor.fetchall()

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path
            )

        # Get new metadata
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT rfc_message_id, subject, from_addr
                FROM messages
                WHERE archive_file = ?
            """,
                (str(output_path),),
            )
            new_metadata = cursor.fetchall()

        # Metadata should match (except archive_file)
        assert len(new_metadata) == len(original_metadata)
        for orig, new in zip(original_metadata, new_metadata):
            assert orig[0] == new[0]  # rfc_message_id
            assert orig[1] == new[1]  # subject
            assert orig[2] == new[2]  # from_addr


class TestCompression:
    """Tests for compression support."""

    async def test_consolidate_with_gzip_compression(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test consolidation with gzip compression."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox.gz"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2],
                output_archive=output_path,
                compress="gzip",
            )

            assert result.compression_used == "gzip"
            assert output_path.exists()

            # Verify it's actually compressed
            with open(output_path, "rb") as f:
                magic = f.read(2)
                assert magic == b"\x1f\x8b"  # gzip magic number

    async def test_consolidate_without_compression(self, temp_dir, state_db, sample_mbox_1):
        """Test consolidation without compression."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path, compress=None
            )

            assert result.compression_used is None
            assert output_path.exists()


class TestErrorHandling:
    """Tests for error handling."""

    async def test_consolidate_missing_source_file(self, temp_dir, state_db):
        """Test error when source file doesn't exist."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"
            missing_path = temp_dir / "nonexistent.mbox"

            with pytest.raises(FileNotFoundError):
                await consolidator.consolidate(
                    source_archives=[missing_path], output_archive=output_path
                )

    async def test_consolidate_empty_source_list(self, temp_dir, state_db):
        """Test error with empty source archives list."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            with pytest.raises(ValueError):
                await consolidator.consolidate(source_archives=[], output_archive=output_path)

    async def test_consolidate_invalid_dedupe_strategy(self, temp_dir, state_db, sample_mbox_1):
        """Test error with invalid deduplication strategy."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            with pytest.raises(ValueError):
                await consolidator.consolidate(
                    source_archives=[sample_mbox_1],
                    output_archive=output_path,
                    deduplicate=True,
                    dedupe_strategy="invalid_strategy",
                )


class TestAtomicConsolidation:
    """Tests for atomic consolidation using HybridStorage."""

    async def test_atomic_consolidation_both_succeed(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test that both mbox and database are updated atomically."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            # Perform consolidation
            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2],
                output_archive=output_path,
                sort_by_date=False,
                deduplicate=False,
            )

        # Verify mbox exists and has correct count
        assert output_path.exists()
        mbox = mailbox.mbox(str(output_path))
        assert len(mbox) == 6
        mbox.close()

        # Verify database updated
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE archive_file = ?", (str(output_path),)
            )
            db_count = cursor.fetchone()[0]

        # Both should match
        assert db_count == 6

    async def test_atomic_consolidation_updates_offsets(self, temp_dir, state_db, sample_mbox_1):
        """Test that database offsets are updated correctly."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            # Perform consolidation
            await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path
            )

        # Verify offsets are updated and valid
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT rfc_message_id, mbox_offset, mbox_length
                FROM messages
                WHERE archive_file = ?
                ORDER BY mbox_offset
                """,
                (str(output_path),),
            )
            rows = cursor.fetchall()

        assert len(rows) == 3

        # All offsets should be non-negative and lengths positive
        for msg_id, offset, length in rows:
            assert offset >= 0, f"Invalid offset for {msg_id}"
            assert length > 0, f"Invalid length for {msg_id}"

        # Offsets should be sequential (no overlap)
        for i in range(len(rows) - 1):
            _, offset1, length1 = rows[i]
            _, offset2, _ = rows[i + 1]
            assert offset1 + length1 <= offset2, "Overlapping offsets detected"

    async def test_consolidation_creates_audit_trail(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test that consolidation is recorded in archive_runs."""
        # Count archive_runs before
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM archive_runs")
            runs_before = cursor.fetchone()[0]

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            # Perform consolidation
            await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2], output_archive=output_path
            )

        # Verify audit trail created
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM archive_runs")
            runs_after = cursor.fetchone()[0]

        # Should have at least one new entry
        assert runs_after > runs_before

    async def test_consolidation_with_compression_atomic(
        self, temp_dir, state_db, sample_mbox_1, sample_mbox_2
    ):
        """Test atomic consolidation with compression."""
        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox.gz"

            result = await consolidator.consolidate(
                source_archives=[sample_mbox_1, sample_mbox_2],
                output_archive=output_path,
                compress="gzip",
            )

        # Verify compressed file exists
        assert output_path.exists()
        assert result.compression_used == "gzip"

        # Verify database points to compressed file
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                "SELECT DISTINCT archive_file FROM messages WHERE archive_file = ?",
                (str(output_path),),
            )
            db_files = [row[0] for row in cursor.fetchall()]

        assert str(output_path) in db_files

    async def test_deduplication_updates_database_atomically(
        self, temp_dir, state_db, mbox_with_duplicates
    ):
        """Test that deduplication updates database correctly."""
        mbox1, mbox2 = mbox_with_duplicates

        # Count messages before
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages")
            count_before = cursor.fetchone()[0]

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "deduped.mbox"

            # Perform consolidation with deduplication
            result = await consolidator.consolidate(
                source_archives=[mbox1, mbox2], output_archive=output_path, deduplicate=True
            )

        # Count messages after
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages")
            count_after = cursor.fetchone()[0]

        # Should have removed 1 duplicate
        assert count_before - count_after == result.duplicates_removed
        assert result.duplicates_removed == 1

    async def test_consolidation_preserves_metadata(self, temp_dir, state_db, sample_mbox_1):
        """Test that consolidation preserves all message metadata."""
        # Get original metadata
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT gmail_id, rfc_message_id, subject, from_addr
                FROM messages
                WHERE archive_file = ?
                """,
                (str(sample_mbox_1),),
            )
            original_metadata = {row[0]: row for row in cursor.fetchall()}

        async with DBManager(str(state_db), validate_schema=False) as db:
            consolidator = ArchiveConsolidator(db)
            output_path = temp_dir / "consolidated.mbox"

            # Perform consolidation
            await consolidator.consolidate(
                source_archives=[sample_mbox_1], output_archive=output_path
            )

        # Get new metadata
        with sqlite3.connect(str(state_db)) as conn:
            cursor = conn.execute(
                """
                SELECT gmail_id, rfc_message_id, subject, from_addr
                FROM messages
                WHERE archive_file = ?
                """,
                (str(output_path),),
            )
            new_metadata = {row[0]: row for row in cursor.fetchall()}

        # All metadata should match (except archive_file)
        assert set(original_metadata.keys()) == set(new_metadata.keys())
        for gmail_id in original_metadata:
            orig = original_metadata[gmail_id]
            new = new_metadata[gmail_id]
            assert orig[1] == new[1]  # rfc_message_id
            assert orig[2] == new[2]  # subject
            assert orig[3] == new[3]  # from_addr
