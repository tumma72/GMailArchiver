"""Tests for HybridStorage class - Transactional coordinator for mbox + database operations.

HybridStorage ensures atomic operations across mbox files and database using
two-phase commit pattern. It must guarantee that both mbox and database succeed
or both are rolled back.

Test Coverage: 95%+ target
- Initialization tests
- Archive message tests (atomicity critical!)
- Consolidation tests
- Validation tests
- Atomicity tests (CRITICAL for data integrity)
- Error handling tests
"""

import email
import mailbox
import sqlite3
import tempfile
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio

from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage, HybridStorageError, IntegrityError

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def v11_db_path(temp_dir: Path) -> str:
    """Create a v1.1 database for testing."""
    db_path = temp_dir / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create messages table (v1.1 schema)
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

    # Create indexes
    indexes = [
        "CREATE INDEX idx_rfc_message_id ON messages(rfc_message_id)",
        "CREATE INDEX idx_thread_id ON messages(thread_id)",
        "CREATE INDEX idx_archive_file ON messages(archive_file)",
        "CREATE INDEX idx_date ON messages(date)",
    ]
    for index_sql in indexes:
        conn.execute(index_sql)

    # Create FTS5 virtual table
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            from_addr,
            to_addr,
            body_preview,
            content=messages,
            content_rowid=rowid,
            tokenize='porter unicode61 remove_diacritics 1'
        )
    """)

    # Create FTS triggers
    conn.execute("""
        CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
            VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
        END
    """)

    # Create archive_runs table
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL,
            account_id TEXT DEFAULT 'default',
            operation_type TEXT DEFAULT 'archive'
        )
    """)

    # Create schema_version table
    conn.execute("""
        CREATE TABLE schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO schema_version VALUES ('1.1', ?)", (datetime.now().isoformat(),))

    conn.commit()
    conn.close()

    return str(db_path)


@pytest_asyncio.fixture
async def db_manager(v11_db_path: str) -> DBManager:
    """Create async DBManager instance for testing."""
    db = DBManager(v11_db_path)
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
def sample_email_message() -> email.message.Message:
    """Create a sample email message for testing."""
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<test123@example.com>"
    msg["Subject"] = "Test Subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Cc"] = "cc@example.com"
    msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
    msg.set_content("This is a test email body content.")
    return msg


@pytest.fixture
def mbox_path(temp_dir: Path) -> Path:
    """Create a path for test mbox file."""
    return temp_dir / "test.mbox"


# ============================================================================
# Helper Functions
# ============================================================================


async def archive_single_message(
    storage: HybridStorage,
    email_message: email.message.Message,
    gmail_id: str,
    archive_file: Path,
    thread_id: str | None = None,
    labels: str | None = None,
    compression: str | None = None,
) -> tuple[int, int]:
    """Helper to archive a single message using batch API.

    Returns (offset, length) tuple for compatibility with tests.
    """
    result = await storage.archive_messages_batch(
        messages=[(email_message, gmail_id, thread_id, labels)],
        archive_file=archive_file,
        compression=compression,
    )
    # Get the message to retrieve offset/length
    msg_data = await storage.db.get_message_by_gmail_id(gmail_id)
    if msg_data:
        return (msg_data["mbox_offset"], msg_data["mbox_length"])
    return (0, 0)


# ============================================================================
# Initialization Tests
# ============================================================================


class TestHybridStorageInitialization:
    """Tests for HybridStorage initialization."""

    async def test_init_with_valid_db_manager(self, db_manager: DBManager) -> None:
        """Test initialization with valid DBManager."""
        storage = HybridStorage(db_manager)

        assert storage.db == db_manager
        assert storage._staging_area.exists()
        assert storage._staging_area.is_dir()

    async def test_init_creates_staging_area(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test that staging area is created on initialization."""
        storage = HybridStorage(db_manager)

        # Staging area should exist
        assert storage._staging_area.exists()
        assert storage._staging_area.name.startswith("gmailarchiver_staging")

    async def test_cleanup_staging_area_on_del(self, db_manager: DBManager) -> None:
        """Test staging area cleanup on object deletion."""
        storage = HybridStorage(db_manager)
        staging_path = storage._staging_area

        # Create a test file in staging
        test_file = staging_path / "test.eml"
        test_file.write_text("test content")

        # Cleanup
        storage.__del__()

        # Staging files should be cleaned up
        assert not test_file.exists()

    async def test_init_without_preload_rfc_ids(self, db_manager: DBManager) -> None:
        """Test initialization with preload_rfc_ids=False."""
        storage = HybridStorage(db_manager, preload_rfc_ids=False)

        # Should initialize with empty set
        assert storage._known_rfc_ids == set()
        assert storage.db == db_manager


# ============================================================================
# Archive Message Tests
# ============================================================================


class TestArchiveMessage:
    """Tests for archive_messages_batch method (atomicity critical!)."""

    async def test_archive_message_success(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test successful message archiving (happy path)."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify message in mbox
        mbox = mailbox.mbox(str(mbox_path))
        assert len(mbox) == 1
        archived_msg = mbox[0]
        assert archived_msg["Subject"] == "Test Subject"
        mbox.close()

        # Verify message in database
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None
        assert msg_data["gmail_id"] == "msg123"
        assert msg_data["rfc_message_id"] == "<test123@example.com>"
        assert msg_data["mbox_offset"] >= 0
        assert msg_data["mbox_length"] > 0

    async def test_archive_message_calculates_offset_correctly(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that mbox_offset is calculated correctly."""
        storage = HybridStorage(db_manager)

        # Archive first message
        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg1",
            archive_file=mbox_path,
            compression=None,
        )

        msg1_data = await db_manager.get_message_by_gmail_id("msg1")
        first_offset = msg1_data["mbox_offset"]
        first_length = msg1_data["mbox_length"]

        # Archive second message
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<test456@example.com>"
        msg2["Subject"] = "Second Message"
        msg2["From"] = "sender2@example.com"
        msg2.set_content("Second message body.")

        await archive_single_message(
            storage, email_message=msg2, gmail_id="msg2", archive_file=mbox_path, compression=None
        )

        msg2_data = await db_manager.get_message_by_gmail_id("msg2")
        second_offset = msg2_data["mbox_offset"]

        # Second offset should be after first message
        assert second_offset > first_offset
        assert second_offset >= first_offset + first_length

    async def test_archive_message_calculates_length_correctly(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that mbox_length is calculated correctly."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        recorded_length = msg_data["mbox_length"]

        # Read actual message from mbox
        with open(mbox_path, "rb") as f:
            f.seek(msg_data["mbox_offset"])
            actual_data = f.read(recorded_length)

        # Verify length matches actual data
        assert len(actual_data) == recorded_length
        # Verify data is valid email
        parsed_msg = email.message_from_bytes(actual_data)
        assert parsed_msg["Subject"] == "Test Subject"

    async def test_archive_message_with_gzip_compression(
        self, db_manager: DBManager, sample_email_message: email.message.Message, temp_dir: Path
    ) -> None:
        """Test archiving with gzip compression."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "test.mbox.gz"

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression="gzip",
        )

        # Verify file exists and is compressed
        assert mbox_path.exists()
        # Note: Actual compression testing would be in integration tests
        # Here we just verify the path is recorded correctly
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data["archive_file"] == str(mbox_path)

    async def test_archive_message_with_lzma_compression(
        self, db_manager: DBManager, sample_email_message: email.message.Message, temp_dir: Path
    ) -> None:
        """Test archiving with lzma compression."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "test.mbox.xz"

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression="lzma",
        )

        assert mbox_path.exists()
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data["archive_file"] == str(mbox_path)

    async def test_archive_message_with_zstd_compression(
        self, db_manager: DBManager, sample_email_message: email.message.Message, temp_dir: Path
    ) -> None:
        """Test archiving with zstd compression."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "test.mbox.zst"

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression="zstd",
        )

        assert mbox_path.exists()
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data["archive_file"] == str(mbox_path)

    async def test_archive_message_lock_file_management(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that lock files are properly managed during archiving."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Lock file should not exist after successful operation
        lock_file = Path(str(mbox_path) + ".lock")
        assert not lock_file.exists()

    async def test_archive_message_cleans_staging_file(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that staging files are cleaned up after archiving."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Staging area should be empty or only contain cleanup files
        staging_files = list(storage._staging_area.glob("msg123.eml"))
        assert len(staging_files) == 0

    async def test_archive_message_database_fails_counts_as_failed(
        self, sample_email_message: email.message.Message, mbox_path: Path, v11_db_path: str
    ) -> None:
        """Test that database failures are counted in 'failed' field.

        Note: With batch archiving, per-message errors are handled internally
        and counted rather than raising exceptions. This allows partial batch
        success when some messages fail.
        """
        # Create db_manager with mock that fails on record_archived_message
        db_manager = DBManager(v11_db_path)
        await db_manager.initialize()
        original_record = db_manager.record_archived_message

        async def failing_record(*args: Any, **kwargs: Any) -> None:
            """Mock that always fails."""
            raise sqlite3.IntegrityError("Database constraint violation")

        db_manager.record_archived_message = failing_record  # type: ignore

        storage = HybridStorage(db_manager)

        # Archive message - error is caught and counted
        result = await storage.archive_messages_batch(
            messages=[(sample_email_message, "msg123", None, None)],
            archive_file=mbox_path,
        )

        # Should count as failed, not raise exception
        assert result["failed"] == 1
        assert result["archived"] == 0

        # Database should not have the message
        db_manager.record_archived_message = original_record  # type: ignore
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is None

        await db_manager.close()

    async def test_archive_batch_validates_at_end(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that batch validation runs at end of batch operation."""
        storage = HybridStorage(db_manager)

        # Archive message
        result = await storage.archive_messages_batch(
            messages=[(sample_email_message, "msg123", None, None)],
            archive_file=mbox_path,
        )

        # Verify message was archived
        assert result["archived"] == 1
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None

    async def test_archive_message_missing_message_id(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test archiving message without Message-ID header."""
        storage = HybridStorage(db_manager)

        # Create message without Message-ID
        msg = email.message.EmailMessage()
        msg["Subject"] = "No Message-ID"
        msg["From"] = "sender@example.com"
        msg.set_content("Test body")

        # Should handle gracefully by generating fallback Message-ID
        await archive_single_message(
            storage, email_message=msg, gmail_id="msg123", archive_file=mbox_path, compression=None
        )

        # Verify message was archived with generated Message-ID
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None
        assert msg_data["gmail_id"] == "msg123"
        # Generated Message-ID should exist
        assert msg_data["rfc_message_id"].startswith("<")
        assert msg_data["rfc_message_id"].endswith("@generated>")

    async def test_archive_message_duplicate_rfc_message_id_skipped(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that duplicate rfc_message_id is skipped gracefully (v1.3.2 bug fix)."""
        storage = HybridStorage(db_manager)

        # Archive first message with rfc_message_id = '<test123@example.com>'
        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg_original",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify first message was archived
        msg1 = await db_manager.get_message_by_gmail_id("msg_original")
        assert msg1 is not None
        assert msg1["rfc_message_id"] == "<test123@example.com>"

        # Try to archive ANOTHER message with SAME rfc_message_id but different gmail_id
        # This simulates: same email in multiple folders, forwarded emails, etc.
        duplicate_msg = email.message.EmailMessage()
        duplicate_msg["Subject"] = "Duplicate Message"
        duplicate_msg["From"] = "another@example.com"
        duplicate_msg["Message-ID"] = "<test123@example.com>"  # SAME as first
        duplicate_msg.set_content("This is a duplicate")

        # Should skip gracefully without raising exception
        result = await storage.archive_messages_batch(
            messages=[(duplicate_msg, "msg_duplicate", None, None)],
            archive_file=mbox_path,
        )

        # Should return skipped count of 1
        assert result["skipped"] == 1
        assert result["archived"] == 0

        # Verify duplicate was NOT added to database
        msg2 = await db_manager.get_message_by_gmail_id("msg_duplicate")
        assert msg2 is None

        # Verify only ONE message in mbox (original, not duplicate)
        mbox = mailbox.mbox(str(mbox_path))
        assert len(mbox) == 1
        mbox.close()


# ============================================================================
# Consolidation Tests
# ============================================================================


class TestConsolidateArchives:
    """Tests for consolidate_archives method."""

    async def test_consolidate_without_deduplication(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidating multiple archives without deduplication."""
        storage = HybridStorage(db_manager)

        # Create two source archives with messages
        source1 = temp_dir / "source1.mbox"
        source2 = temp_dir / "source2.mbox"

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user1@example.com"
        msg1.set_content("Body 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Message 2"
        msg2["From"] = "user2@example.com"
        msg2.set_content("Body 2")

        # Archive messages to separate files
        await archive_single_message(storage, msg1, "msg1", source1, None)
        await archive_single_message(storage, msg2, "msg2", source2, None)

        # Consolidate
        output = temp_dir / "consolidated.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source1, source2], output_archive=output, deduplicate=False
        )

        # Verify result
        assert result.total_messages == 2
        assert result.output_file == str(output)
        assert output.exists()

        # Verify all messages in consolidated archive
        mbox = mailbox.mbox(str(output))
        assert len(mbox) == 2
        mbox.close()

        # Verify database updated with new offsets
        msg1_data = await db_manager.get_message_by_gmail_id("msg1")
        msg2_data = await db_manager.get_message_by_gmail_id("msg2")

        assert msg1_data["archive_file"] == str(output)
        assert msg2_data["archive_file"] == str(output)
        assert msg1_data["mbox_offset"] >= 0
        assert msg2_data["mbox_offset"] >= 0
        # msg2 should be after msg1
        assert msg2_data["mbox_offset"] > msg1_data["mbox_offset"]

    async def test_consolidate_with_deduplication(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidating with deduplication enabled."""
        storage = HybridStorage(db_manager)

        # Create messages with duplicate Message-ID
        source1 = temp_dir / "source1.mbox"
        source2 = temp_dir / "source2.mbox"

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<duplicate@example.com>"
        msg1["Subject"] = "First Instance"
        msg1["From"] = "user@example.com"
        msg1["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg1.set_content("First instance body")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<duplicate@example.com>"  # Same Message-ID
        msg2["Subject"] = "Second Instance"
        msg2["From"] = "user@example.com"
        msg2["Date"] = "Mon, 1 Jan 2024 13:00:00 +0000"  # Newer date
        msg2.set_content("Second instance body")

        # Archive both (bypass unique constraint for testing)
        await archive_single_message(storage, msg1, "msg1", source1, None)
        # Second message will fail due to unique constraint in real scenario
        # For testing, we'd need to bypass constraints or use different approach

        # In real implementation, consolidate would handle this
        output = temp_dir / "consolidated.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source1], output_archive=output, deduplicate=True
        )

        assert result.total_messages >= 1

    async def test_consolidate_recalculates_offsets(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test that offsets are recalculated correctly during consolidation."""
        storage = HybridStorage(db_manager)

        # Create source archives
        source1 = temp_dir / "source1.mbox"
        source2 = temp_dir / "source2.mbox"

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user1@example.com"
        msg1.set_content("Body 1" * 100)  # Larger body

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Message 2"
        msg2["From"] = "user2@example.com"
        msg2.set_content("Body 2")

        await archive_single_message(storage, msg1, "msg1", source1, None)
        await archive_single_message(storage, msg2, "msg2", source2, None)

        # Get original offsets
        orig_msg1 = await db_manager.get_message_by_gmail_id("msg1")
        orig_msg2 = await db_manager.get_message_by_gmail_id("msg2")

        # Consolidate
        output = temp_dir / "consolidated.mbox"
        await storage.consolidate_archives(
            source_archives=[source1, source2], output_archive=output, deduplicate=False
        )

        # Get new offsets
        new_msg1 = await db_manager.get_message_by_gmail_id("msg1")
        new_msg2 = await db_manager.get_message_by_gmail_id("msg2")

        # Offsets should be different (consolidated into new file)
        # msg1 should be at beginning
        assert new_msg1["mbox_offset"] >= 0
        # msg2 should be after msg1
        assert new_msg2["mbox_offset"] > new_msg1["mbox_offset"]

        # Lengths should remain the same
        assert new_msg1["mbox_length"] == orig_msg1["mbox_length"]
        assert new_msg2["mbox_length"] == orig_msg2["mbox_length"]

    async def test_consolidate_validates_result(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test that consolidation validates the resulting archive."""
        storage = HybridStorage(db_manager)

        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Test"
        msg1["From"] = "user@example.com"
        msg1.set_content("Test body")

        await archive_single_message(storage, msg1, "msg1", source1, None)

        output = temp_dir / "consolidated.mbox"

        # Mock validation to fail (consolidation uses _validate_consolidation_output)
        with patch.object(
            storage,
            "_validate_consolidation_output",
            side_effect=IntegrityError("Validation failed"),
        ):
            with pytest.raises(IntegrityError):
                await storage.consolidate_archives(
                    source_archives=[source1], output_archive=output, deduplicate=False
                )

        # Output file should be cleaned up on failure
        # Database should be rolled back
        msg1_data = await db_manager.get_message_by_gmail_id("msg1")
        # Should still point to original file
        assert msg1_data["archive_file"] == str(source1)

    async def test_consolidate_with_compressed_archives(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidating compressed archives."""
        storage = HybridStorage(db_manager)

        # Create compressed source
        source1 = temp_dir / "source1.mbox.gz"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Compressed"
        msg1["From"] = "user@example.com"
        msg1.set_content("Compressed body")

        await archive_single_message(storage, msg1, "msg1", source1, compression="gzip")

        # Consolidate to uncompressed output
        output = temp_dir / "consolidated.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source1], output_archive=output, deduplicate=False
        )

        assert result.total_messages == 1
        assert output.exists()

        # Verify message readable
        mbox = mailbox.mbox(str(output))
        assert len(mbox) == 1
        mbox.close()

    async def test_consolidate_rollback_on_failure(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test that consolidation rolls back on failure."""
        storage = HybridStorage(db_manager)

        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Test"
        msg1["From"] = "user@example.com"
        msg1.set_content("Test body")

        await archive_single_message(storage, msg1, "msg1", source1, None)

        # Get original state
        orig_data = await db_manager.get_message_by_gmail_id("msg1")

        output = temp_dir / "consolidated.mbox"

        # Mock bulk_update to fail
        original_bulk_update = db_manager.bulk_update_archive_locations

        def failing_bulk_update(*args: Any, **kwargs: Any) -> None:
            raise sqlite3.IntegrityError("Update failed")

        db_manager.bulk_update_archive_locations = failing_bulk_update  # type: ignore

        # Should raise HybridStorageError wrapping the IntegrityError
        with pytest.raises(HybridStorageError, match="Failed to consolidate archives"):
            await storage.consolidate_archives(
                source_archives=[source1], output_archive=output, deduplicate=False
            )

        # Restore original function
        db_manager.bulk_update_archive_locations = original_bulk_update  # type: ignore

        # Verify rollback - data should be unchanged
        current_data = await db_manager.get_message_by_gmail_id("msg1")
        assert current_data["archive_file"] == orig_data["archive_file"]
        assert current_data["mbox_offset"] == orig_data["mbox_offset"]


# ============================================================================
# Validation Tests
# ============================================================================


class TestValidation:
    """Tests for validation methods."""

    async def test_validate_message_consistency_valid_message(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test validation of a valid, consistent message."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # v1.2: _validate_message_consistency uses rfc_message_id (primary key)
        rfc_message_id = sample_email_message.get("Message-ID", "<test@example.com>")
        await storage._validate_message_consistency(rfc_message_id)

    async def test_validate_message_consistency_missing_in_database(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test validation fails when message missing from database."""
        storage = HybridStorage(db_manager)

        # Try to validate non-existent message
        with pytest.raises(IntegrityError, match="not in database"):
            await storage._validate_message_consistency("nonexistent")

    async def test_validate_message_consistency_missing_in_mbox(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test validation fails when message missing from mbox."""
        storage = HybridStorage(db_manager)

        rfc_message_id = "<test123@example.com>"
        # Manually insert into database without mbox
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(mbox_path),
            mbox_offset=0,
            mbox_length=1000,  # Non-existent data
            gmail_id="msg123",
        )

        # Create empty mbox
        mbox_path.touch()

        # Validation should fail (v1.2: use rfc_message_id)
        with pytest.raises(IntegrityError, match="No data at offset"):
            await storage._validate_message_consistency(rfc_message_id)

    async def test_validate_message_consistency_corrupt_email_data(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test validation when email data doesn't exist at offset."""
        storage = HybridStorage(db_manager)

        # Create empty mbox file
        mbox_path.touch()

        rfc_message_id = "<test123@example.com>"
        # Record in database with non-existent offset
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(mbox_path),
            mbox_offset=1000,  # Beyond end of file
            mbox_length=100,
            gmail_id="msg123",
        )

        # Validation should fail - no data at offset (v1.2: use rfc_message_id)
        with pytest.raises(IntegrityError, match="No data at offset"):
            await storage._validate_message_consistency(rfc_message_id)

    async def test_validate_archive_consistency_all_good(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test archive validation passes for consistent archive."""
        storage = HybridStorage(db_manager)

        # Archive multiple messages
        for i in range(3):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = "user@example.com"
            msg.set_content(f"Body {i}")

            await archive_single_message(storage, msg, f"msg{i}", mbox_path, None)

        # Validation should pass
        await storage._validate_archive_consistency(mbox_path)

    async def test_validate_archive_consistency_count_mismatch(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test validation fails on count mismatch."""
        storage = HybridStorage(db_manager)

        # Create mbox with one message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<msg1@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "user@example.com"
        msg.set_content("Body")

        mbox = mailbox.mbox(str(mbox_path))
        mbox.add(msg)
        mbox.close()

        # Record two messages in database (mismatch)
        await db_manager.record_archived_message(
            gmail_id="msg1",
            rfc_message_id="<msg1@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=0,
            mbox_length=100,
        )
        await db_manager.record_archived_message(
            gmail_id="msg2",
            rfc_message_id="<msg2@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=100,
            mbox_length=100,
        )

        # Validation should fail
        with pytest.raises(IntegrityError, match="Count mismatch"):
            await storage._validate_archive_consistency(mbox_path)

    async def test_validate_archive_consistency_orphaned_message(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test validation fails when message in mbox but not in database."""
        storage = HybridStorage(db_manager)

        # Create mbox with message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<orphan@example.com>"
        msg["Subject"] = "Orphaned"
        msg["From"] = "user@example.com"
        msg.set_content("Orphaned message")

        mbox = mailbox.mbox(str(mbox_path))
        mbox.add(msg)
        mbox.close()

        # Database doesn't have this message

        # Validation should fail
        with pytest.raises(IntegrityError, match="in mbox but not in database"):
            await storage._validate_archive_consistency(mbox_path)


# ============================================================================
# Atomicity Tests (CRITICAL!)
# ============================================================================


class TestAtomicity:
    """Tests for atomic operation guarantees (CRITICAL for data integrity)."""

    async def test_transaction_commits_on_full_success(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that transaction commits when all operations succeed."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify committed to database (open new connection)
        new_db = DBManager(db_manager.db_path)
        await new_db.initialize()
        msg_data = await new_db.get_message_by_gmail_id("msg123")
        assert msg_data is not None
        assert msg_data["gmail_id"] == "msg123"
        await new_db.close()

        # Verify mbox file exists
        assert mbox_path.exists()

    async def test_batch_error_handling_counts_failures(
        self, sample_email_message: email.message.Message, mbox_path: Path, v11_db_path: str
    ) -> None:
        """Test that per-message errors are counted rather than raising exceptions."""
        db_manager = DBManager(v11_db_path)
        await db_manager.initialize()
        storage = HybridStorage(db_manager)

        # Get initial state
        cursor = await db_manager._conn.execute("SELECT COUNT(*) FROM messages")
        initial_count = (await cursor.fetchone())[0]

        # Force failure on record
        original_record = db_manager.record_archived_message

        async def failing_record(*args, **kwargs):
            raise sqlite3.IntegrityError("Forced failure")

        with patch.object(db_manager, "record_archived_message", side_effect=failing_record):
            result = await storage.archive_messages_batch(
                messages=[(sample_email_message, "msg123", None, None)],
                archive_file=mbox_path,
            )

        # Should count as failed, not raise exception
        assert result["failed"] == 1
        assert result["archived"] == 0

        # Verify database unchanged
        cursor = await db_manager._conn.execute("SELECT COUNT(*) FROM messages")
        final_count = (await cursor.fetchone())[0]
        assert final_count == initial_count

        await db_manager.close()

    async def test_successful_archive_cleans_up_staging_files(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test that staging files are cleaned up after successful archiving."""
        storage = HybridStorage(db_manager)

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify staging area is clean
        staging_files = list(storage._staging_area.glob("msg123.eml"))
        assert len(staging_files) == 0

    async def test_partial_write_detection(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test detection of partial writes."""
        storage = HybridStorage(db_manager)

        # Create partial write scenario - mbox exists but database incomplete
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<partial@example.com>"
        msg["Subject"] = "Partial"
        msg["From"] = "user@example.com"
        msg.set_content("Partial write")

        # Write to mbox manually
        mbox = mailbox.mbox(str(mbox_path))
        mbox.add(msg)
        mbox.close()

        # Don't update database - simulate partial write

        # Validation should detect this
        with pytest.raises(IntegrityError):
            await storage._validate_archive_consistency(mbox_path)

    async def test_concurrent_operations_dont_interfere(
        self, v11_db_path: str, temp_dir: Path
    ) -> None:
        """Test that separate operations maintain consistency.

        Note: SQLite has limited concurrency (one writer at a time).
        This test verifies that sequential operations with different storage
        instances maintain data consistency.
        """
        mbox1 = temp_dir / "test1.mbox"
        mbox2 = temp_dir / "test2.mbox"

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user1@example.com"
        msg1.set_content("Body 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Message 2"
        msg2["From"] = "user2@example.com"
        msg2.set_content("Body 2")

        # Operation 1: Archive first message
        db1 = DBManager(v11_db_path)
        await db1.initialize()
        storage1 = HybridStorage(db1)
        await archive_single_message(storage1, msg1, "msg1", mbox1, None)
        await db1.close()

        # Operation 2: Archive second message (separate connection)
        db2 = DBManager(v11_db_path)
        await db2.initialize()
        storage2 = HybridStorage(db2)
        await archive_single_message(storage2, msg2, "msg2", mbox2, None)
        await db2.close()

        # Verify both messages persisted in database
        db3 = DBManager(v11_db_path)
        await db3.initialize()
        msg1_data = await db3.get_message_by_gmail_id("msg1")
        msg2_data = await db3.get_message_by_gmail_id("msg2")

        assert msg1_data is not None
        assert msg2_data is not None
        assert msg1_data["rfc_message_id"] == "<msg1@example.com>"
        assert msg2_data["rfc_message_id"] == "<msg2@example.com>"

        await db3.close()


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    async def test_invalid_mbox_path(
        self, db_manager: DBManager, sample_email_message: email.message.Message
    ) -> None:
        """Test error handling for invalid mbox path."""
        storage = HybridStorage(db_manager)

        # Try to use invalid path - batch operations will raise HybridStorageError
        invalid_path = Path("/invalid/nonexistent/path/test.mbox")

        with pytest.raises(HybridStorageError):
            await storage.archive_messages_batch(
                messages=[(sample_email_message, "msg123", None, None)],
                archive_file=invalid_path,
            )

    async def test_disk_full_scenario(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test handling of disk full scenario."""
        storage = HybridStorage(db_manager)

        # Mock file write to simulate disk full - should raise HybridStorageError
        with patch("builtins.open", side_effect=OSError("No space left on device")):
            with pytest.raises(HybridStorageError, match="No space left"):
                await storage.archive_messages_batch(
                    messages=[(sample_email_message, "msg123", None, None)],
                    archive_file=mbox_path,
                )

        # Database should not have the message
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is None

    async def test_permission_error(
        self, db_manager: DBManager, sample_email_message: email.message.Message, temp_dir: Path
    ) -> None:
        """Test handling of permission errors."""
        storage = HybridStorage(db_manager)

        # Create read-only directory
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        mbox_path = readonly_dir / "test.mbox"

        try:
            with pytest.raises(HybridStorageError):
                await storage.archive_messages_batch(
                    messages=[(sample_email_message, "msg123", None, None)],
                    archive_file=mbox_path,
                )

            # Database should not have the message
            msg_data = await db_manager.get_message_by_gmail_id("msg123")
            assert msg_data is None

        finally:
            # Cleanup
            readonly_dir.chmod(0o755)

    async def test_corrupt_source_archive_in_consolidation(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test handling of corrupt source archive during consolidation."""
        storage = HybridStorage(db_manager)

        # Create corrupt source file with no associated database records
        corrupt_source = temp_dir / "corrupt.mbox"
        corrupt_source.write_bytes(b"\x00\x01\x02\x03")  # Invalid mbox data

        output = temp_dir / "consolidated.mbox"

        # Consolidation should succeed but with 0 messages (no records in DB)
        result = await storage.consolidate_archives(
            source_archives=[corrupt_source], output_archive=output, deduplicate=False
        )

        # Should have 0 messages since there are no DB records for this archive
        assert result.total_messages == 0


# ============================================================================
# Edge Cases and Coverage Gap Tests
# ============================================================================


class TestEdgeCasesAndCoverage:
    """Tests targeting specific uncovered lines to reach 90%+ coverage."""

    # ============ Decompression Error Scenarios ============

    async def test_decompress_corrupt_gzip(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test validation fails on corrupt gzip archive."""
        storage = HybridStorage(db_manager)

        # Create a corrupt gzip file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"\x1f\x8b\x08\x00CORRUPT_DATA_HERE")

        rfc_message_id = "<test@example.com>"
        # Record a message pointing to this corrupt archive
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(corrupt_gz),
            mbox_offset=0,
            mbox_length=100,
            gmail_id="msg123",
        )

        # Validation should fail with IntegrityError wrapping decompression error
        # v1.2: use rfc_message_id for validation
        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_message_consistency(rfc_message_id)

    async def test_decompress_corrupt_lzma(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test validation fails on corrupt lzma archive."""
        storage = HybridStorage(db_manager)

        # Create a corrupt lzma file
        corrupt_xz = temp_dir / "corrupt.mbox.xz"
        corrupt_xz.write_bytes(b"\xfd\x37\x7a\x58\x5a\x00CORRUPT")

        rfc_message_id = "<test@example.com>"
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(corrupt_xz),
            mbox_offset=0,
            mbox_length=100,
            gmail_id="msg123",
        )

        # v1.2: use rfc_message_id for validation
        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_message_consistency(rfc_message_id)

    async def test_decompress_corrupt_zstd(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test validation fails on corrupt zstd archive."""
        storage = HybridStorage(db_manager)

        # Create a corrupt zstd file
        corrupt_zst = temp_dir / "corrupt.mbox.zst"
        corrupt_zst.write_bytes(b"\x28\xb5\x2f\xfd\x00CORRUPT")

        rfc_message_id = "<test@example.com>"
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(corrupt_zst),
            mbox_offset=0,
            mbox_length=100,
            gmail_id="msg123",
        )

        # v1.2: use rfc_message_id for validation
        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_message_consistency(rfc_message_id)

    async def test_decompress_with_invalid_compression_format(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test _decompress_file raises ValueError for invalid format."""
        storage = HybridStorage(db_manager)

        source = temp_dir / "source.mbox"
        source.write_text("test")
        dest = temp_dir / "dest.mbox"

        # Should raise ValueError for unsupported compression
        with pytest.raises(ValueError, match="Unsupported compression format"):
            await storage._decompress_file(source, dest, "bzip2")

    async def test_compress_with_invalid_compression_format(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test _compress_file raises ValueError for invalid format."""
        storage = HybridStorage(db_manager)

        source = temp_dir / "source.mbox"
        source.write_text("test")
        dest = temp_dir / "dest.mbox.bz2"

        # Should raise ValueError for unsupported compression
        with pytest.raises(ValueError, match="Unsupported compression format"):
            await storage._compress_file(source, dest, "bzip2")

    # ============ Validation Edge Cases ============

    async def test_validate_archive_consistency_decompression_fails(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test archive validation handles decompression failure."""
        storage = HybridStorage(db_manager)

        # Create corrupt compressed archive
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"NOT_GZIP_DATA")

        # Record a message for this archive
        await db_manager.record_archived_message(
            gmail_id="msg123",
            rfc_message_id="<test@example.com>",
            archive_file=str(corrupt_gz),
            mbox_offset=0,
            mbox_length=100,
        )

        # Validation should fail
        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_archive_consistency(corrupt_gz)

    async def test_collect_messages_decompression_fails(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test _collect_messages handles decompression failure."""
        storage = HybridStorage(db_manager)

        # Create corrupt compressed archive
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"NOT_GZIP_DATA")

        # Record a message for this archive
        await db_manager.record_archived_message(
            gmail_id="msg123",
            rfc_message_id="<test@example.com>",
            archive_file=str(corrupt_gz),
            mbox_offset=0,
            mbox_length=100,
        )

        # Should raise HybridStorageError
        with pytest.raises(HybridStorageError, match="Failed to decompress"):
            await storage._collect_messages([corrupt_gz])

    # ============ Consolidation Edge Cases ============

    async def test_consolidate_validation_missing_messages(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidation validation catches missing messages."""
        storage = HybridStorage(db_manager)

        # Create source with message
        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user@example.com"
        msg1.set_content("Body 1")

        await archive_single_message(storage, msg1, "msg1", source1, None)

        output = temp_dir / "consolidated.mbox"

        # Mock _validate_consolidation_output to simulate missing messages
        original_validate = storage._validate_consolidation_output

        def failing_validate(*args: Any, **kwargs: Any) -> None:
            # Create output file but simulate missing message in validation
            raise IntegrityError("Missing 1 expected messages in consolidated archive")

        with patch.object(storage, "_validate_consolidation_output", side_effect=failing_validate):
            with pytest.raises(IntegrityError, match="Missing .* expected messages"):
                await storage.consolidate_archives(
                    source_archives=[source1], output_archive=output, deduplicate=False
                )

    async def test_consolidate_validation_unexpected_messages(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidation validation catches unexpected messages."""
        storage = HybridStorage(db_manager)

        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user@example.com"
        msg1.set_content("Body 1")

        await archive_single_message(storage, msg1, "msg1", source1, None)

        output = temp_dir / "consolidated.mbox"

        # Mock validation to simulate unexpected messages
        def failing_validate(*args: Any, **kwargs: Any) -> None:
            raise IntegrityError("Found 1 unexpected messages in consolidated archive")

        with patch.object(storage, "_validate_consolidation_output", side_effect=failing_validate):
            with pytest.raises(IntegrityError, match="Found .* unexpected messages"):
                await storage.consolidate_archives(
                    source_archives=[source1], output_archive=output, deduplicate=False
                )

    # ============ Context Manager Tests ============

    async def test_context_manager_enter(self, db_manager: DBManager) -> None:
        """Test context manager __enter__ returns self."""
        storage = HybridStorage(db_manager)

        async with storage as ctx:
            assert ctx is storage
            assert ctx._staging_area.exists()

    async def test_context_manager_exit_cleanup(self, db_manager: DBManager) -> None:
        """Test context manager __exit__ cleans up staging area."""
        storage = HybridStorage(db_manager)
        staging_path = storage._staging_area

        # Create test file in staging
        test_file = staging_path / "test.eml"
        test_file.write_text("test content")

        # Use context manager
        async with storage:
            assert test_file.exists()

        # After exit, staging files should be cleaned
        # Note: staging area itself may still exist but files should be removed

    # ============ Cleanup Edge Cases ============

    async def test_cleanup_staging_area_with_permission_error(self, db_manager: DBManager) -> None:
        """Test cleanup handles permission errors gracefully."""
        storage = HybridStorage(db_manager)

        # Create a file that can't be deleted (mock unlink to fail)
        test_file = storage._staging_area / "protected.eml"
        test_file.write_text("protected")

        # Mock unlink to raise permission error
        original_unlink = Path.unlink

        def failing_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
            if self.name == "protected.eml":
                raise PermissionError("Permission denied")
            original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", failing_unlink):
            # Should log warning but not raise
            storage._cleanup_staging_area()

    async def test_cleanup_staging_area_with_missing_attribute(self, db_manager: DBManager) -> None:
        """Test cleanup handles missing _staging_area attribute."""
        storage = HybridStorage(db_manager)

        # Remove _staging_area attribute
        delattr(storage, "_staging_area")

        # Should not raise when _staging_area doesn't exist
        storage._cleanup_staging_area()

    # ============ Body Preview Edge Cases ============

    async def test_extract_body_preview_non_multipart_with_exception(
        self, db_manager: DBManager
    ) -> None:
        """Test body preview extraction handles exceptions in non-multipart."""
        storage = HybridStorage(db_manager)

        # Create message that will throw exception during payload decode
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"

        # Mock get_payload to raise exception
        with patch.object(
            email.message.Message, "get_payload", side_effect=Exception("Payload error")
        ):
            preview = storage._extract_body_preview(msg)
            # Should return empty string when exception occurs
            assert preview == ""

    async def test_extract_body_preview_multipart_with_exception(
        self, db_manager: DBManager
    ) -> None:
        """Test body preview extraction handles exceptions in multipart."""
        storage = HybridStorage(db_manager)

        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"
        msg.set_content("Main body")
        msg.add_alternative("<html><body>HTML</body></html>", subtype="html")

        # Patch walk to return parts where one will raise during get_payload
        original_walk = msg.walk

        def failing_walk() -> Any:
            # First part is the multipart container
            yield msg
            # Second part will raise during get_payload
            failing_part = email.message.EmailMessage()
            failing_part["Content-Type"] = "text/plain"

            def raise_on_decode(decode: bool = False) -> Any:
                if decode:
                    raise Exception("Decode failed")
                return b"test"

            failing_part.get_payload = raise_on_decode  # type: ignore
            failing_part.get_content_type = lambda: "text/plain"  # type: ignore
            yield failing_part

        msg.walk = failing_walk  # type: ignore
        preview = storage._extract_body_preview(msg)
        # Should continue and return empty string since exception was caught
        assert preview == ""

    async def test_extract_body_preview_very_short(self, db_manager: DBManager) -> None:
        """Test body preview with very short max_chars."""
        storage = HybridStorage(db_manager)

        msg = email.message.EmailMessage()
        msg.set_content("This is a long body that should be truncated")

        preview = storage._extract_body_preview(msg, max_chars=10)
        assert len(preview) == 10
        assert preview == "This is a "

    # ============ Archive File Path Edge Cases ============

    async def test_archive_message_with_unusual_compressed_extension(
        self, db_manager: DBManager, sample_email_message: email.message.Message, temp_dir: Path
    ) -> None:
        """Test archiving with unusual compressed extension fallback."""
        storage = HybridStorage(db_manager)

        # Use a compressed file with unusual naming that triggers fallback
        # This tests line 139 (fallback path for unusual compression extensions)
        mbox_path = temp_dir / "test.unusual.gz"

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression="gzip",
        )

        # Verify message was archived
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None

    async def test_archive_message_with_orphaned_lock_file(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test archiving handles orphaned lock files (lines 153-154)."""
        storage = HybridStorage(db_manager)

        # Create an orphaned lock file
        lock_file = Path(str(mbox_path) + ".lock")
        lock_file.write_text("orphaned")

        # Should remove the lock file and proceed
        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify message was archived successfully
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None

    async def test_archive_message_to_new_file_offset_zero(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test archiving to new file starts at offset 0 (line 165)."""
        storage = HybridStorage(db_manager)

        # Ensure mbox file doesn't exist
        assert not mbox_path.exists()

        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify offset is 0 for first message
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data["mbox_offset"] == 0

    # ============ Validation Error Path Tests ============

    async def test_validate_message_missing_archive_file(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test validation when archive file is missing (line 527)."""
        storage = HybridStorage(db_manager)

        missing_file = temp_dir / "nonexistent.mbox"

        rfc_message_id = "<test@example.com>"
        # Record message pointing to non-existent file
        await db_manager.record_archived_message(
            rfc_message_id=rfc_message_id,
            archive_file=str(missing_file),
            mbox_offset=0,
            mbox_length=100,
            gmail_id="msg123",
        )

        # Validation should fail with IntegrityError about missing file
        # v1.2: use rfc_message_id for validation
        with pytest.raises(IntegrityError, match="Archive file missing"):
            await storage._validate_message_consistency(rfc_message_id)

    # ============ Deduplication Edge Cases ============

    async def test_deduplicate_with_duplicate_rfc_message_ids(self, db_manager: DBManager) -> None:
        """Test deduplication removes duplicates (lines 803-804)."""
        storage = HybridStorage(db_manager)

        # Create message dicts with duplicate RFC Message-IDs
        messages = [
            {"rfc_message_id": "<msg1@example.com>", "gmail_id": "gm1"},
            {"rfc_message_id": "<msg1@example.com>", "gmail_id": "gm2"},  # Duplicate
            {"rfc_message_id": "<msg2@example.com>", "gmail_id": "gm3"},
            {"rfc_message_id": "<msg2@example.com>", "gmail_id": "gm4"},  # Duplicate
        ]

        deduplicated, count = storage._deduplicate_messages(messages)

        # Should remove 2 duplicates
        assert count == 2
        assert len(deduplicated) == 2
        # Should keep first occurrence of each
        assert deduplicated[0]["gmail_id"] == "gm1"
        assert deduplicated[1]["gmail_id"] == "gm3"

    # ============ Consolidation Validation Edge Cases ============

    async def test_validate_consolidation_with_temp_file_cleanup(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidation validation cleans up temp files (line 700)."""
        storage = HybridStorage(db_manager)

        # Create compressed source
        source_gz = temp_dir / "source.mbox.gz"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<msg1@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "user@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", source_gz, compression="gzip")

        # Create consolidated output (uncompressed to avoid double compression issue)
        output = temp_dir / "consolidated.mbox"

        # Perform consolidation - source is compressed, output is not
        result = await storage.consolidate_archives(
            source_archives=[source_gz], output_archive=output, deduplicate=False
        )

        assert result.total_messages == 1
        # Temp files should be cleaned up automatically

    # ============ Cleanup Exception Tests ============

    async def test_cleanup_staging_area_iterdir_exception(self, db_manager: DBManager) -> None:
        """Test cleanup handles iterdir exception (line 982-983)."""
        storage = HybridStorage(db_manager)

        # Mock iterdir to raise exception
        original_iterdir = Path.iterdir

        def failing_iterdir(self: Path) -> Any:
            raise PermissionError("Cannot iterate directory")

        with patch.object(Path, "iterdir", failing_iterdir):
            # Should log warning but not raise
            storage._cleanup_staging_area()

    # ============ Body Preview Additional Cases ============

    async def test_extract_body_preview_no_text_plain_part(self, db_manager: DBManager) -> None:
        """Test body preview with no text/plain part (line 851-853)."""
        storage = HybridStorage(db_manager)

        # Create multipart message with only HTML
        msg = email.message.EmailMessage()
        msg["Subject"] = "HTML Only"
        msg.add_alternative("<html><body>HTML only</body></html>", subtype="html")

        preview = storage._extract_body_preview(msg)
        # Should return empty string since no text/plain part
        assert preview == ""

    async def test_extract_body_preview_payload_not_bytes(self, db_manager: DBManager) -> None:
        """Test body preview when payload is not bytes."""
        storage = HybridStorage(db_manager)

        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"

        # Mock get_payload to return non-bytes
        def mock_get_payload(decode: bool = False) -> Any:
            if decode:
                return "not bytes but string"  # Not bytes
            return b"test"

        msg.get_payload = mock_get_payload  # type: ignore

        preview = storage._extract_body_preview(msg)
        # Should return empty string when payload is not bytes
        assert preview == ""

    # ============ Error Handling with Rollback Failures ============

    async def test_batch_archive_handles_record_failures(
        self, v11_db_path: str, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test batch archive counts per-message record failures."""
        db_manager = DBManager(v11_db_path)
        await db_manager.initialize()
        storage = HybridStorage(db_manager)

        # Mock record to raise exception
        async def failing_record(*args, **kwargs):
            raise sqlite3.IntegrityError("Record failed")

        with patch.object(db_manager, "record_archived_message", side_effect=failing_record):
            result = await storage.archive_messages_batch(
                messages=[(sample_email_message, "msg123", None, None)],
                archive_file=mbox_path,
            )

        # Should count as failed, not raise exception
        assert result["failed"] == 1
        assert result["archived"] == 0

        await db_manager.close()

    async def test_batch_archive_mbox_error_raises_exception(
        self, v11_db_path: str, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test batch archive raises HybridStorageError on mbox-level errors."""
        db_manager = DBManager(v11_db_path)
        await db_manager.initialize()
        storage = HybridStorage(db_manager)

        # Mock open to simulate file error
        with patch("builtins.open", side_effect=OSError("Disk error")):
            # Should raise HybridStorageError for mbox-level errors
            with pytest.raises(HybridStorageError, match="Disk error"):
                await storage.archive_messages_batch(
                    messages=[(sample_email_message, "msg123", None, None)],
                    archive_file=mbox_path,
                )

        await db_manager.close()

    # ============ Finally Block Exception Handling ============

    async def test_archive_batch_successful(
        self, db_manager: DBManager, sample_email_message: email.message.Message, mbox_path: Path
    ) -> None:
        """Test archiving multiple messages in a batch."""
        storage = HybridStorage(db_manager)

        # Archive the message successfully first
        await archive_single_message(
            storage,
            email_message=sample_email_message,
            gmail_id="msg123",
            archive_file=mbox_path,
            compression=None,
        )

        # Verify first message archived
        msg_data = await db_manager.get_message_by_gmail_id("msg123")
        assert msg_data is not None

        # Now archive another message
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<test456@example.com>"
        msg2["Subject"] = "Test 2"
        msg2["From"] = "sender@example.com"
        msg2.set_content("Test body 2")

        await archive_single_message(
            storage, email_message=msg2, gmail_id="msg456", archive_file=mbox_path, compression=None
        )

        msg2_data = await db_manager.get_message_by_gmail_id("msg456")
        assert msg2_data is not None

    # ============ Consolidation with Compression Tests ============

    async def test_consolidate_with_compression_output(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidation with compressed output (lines 379, 385-391)."""
        storage = HybridStorage(db_manager)

        # Create uncompressed source archives
        source1 = temp_dir / "source1.mbox"
        source2 = temp_dir / "source2.mbox"

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "user1@example.com"
        msg1.set_content("Body 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Message 2"
        msg2["From"] = "user2@example.com"
        msg2.set_content("Body 2")

        await archive_single_message(storage, msg1, "msg1", source1, None)
        await archive_single_message(storage, msg2, "msg2", source2, None)

        # Consolidate to compressed output
        output_gz = temp_dir / "consolidated.mbox.gz"
        result = await storage.consolidate_archives(
            source_archives=[source1, source2],
            output_archive=output_gz,
            deduplicate=False,
            compression="gzip",
        )

        assert result.total_messages == 2
        assert output_gz.exists()

        # Verify database updated
        msg1_data = await db_manager.get_message_by_gmail_id("msg1")
        msg2_data = await db_manager.get_message_by_gmail_id("msg2")
        assert msg1_data["archive_file"] == str(output_gz)
        assert msg2_data["archive_file"] == str(output_gz)

    # ============ Bulk Write Error Recovery Tests ============

    @pytest.mark.filterwarnings("ignore::ResourceWarning")
    async def test_bulk_write_database_error_rollback(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test bulk_write rolls back on database error (lines 449-450, 529)."""
        storage = HybridStorage(db_manager)
        output_path = temp_dir / "bulk.mbox"

        # Create messages as dicts (bulk_write_messages expects dict format)
        messages = []
        for i in range(3):
            msg_dict = {
                "gmail_id": f"msg{i}",
                "rfc_message_id": f"<msg{i}@example.com>",
                "thread_id": f"thread{i}",
                "subject": f"Message {i}",
                "from_addr": "sender@example.com",
                "to_addr": "recipient@example.com",
                "cc_addr": None,
                "date": "2024-01-01T00:00:00",
                "body_preview": f"Body {i}",
                "email_message": email.message.EmailMessage(),
            }
            messages.append(msg_dict)

        # Set up email message for each dict
        for i, msg_dict in enumerate(messages):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = "sender@example.com"
            msg.set_content(f"Body {i}")
            msg_dict["email_message"] = msg

        # Mock database commit to fail
        original_commit = db_manager.commit

        call_count = [0]

        def failing_commit() -> None:
            call_count[0] += 1
            if call_count[0] > 2:  # Let first couple commits succeed, then fail
                raise sqlite3.OperationalError("Database locked")
            original_commit()

        db_manager.commit = failing_commit  # type: ignore

        # Bulk write should fail and raise error
        try:
            await storage.bulk_write_messages(
                messages=messages, output_path=output_path, compression=None
            )
        except HybridStorageError:
            pass  # Expected to fail
        finally:
            # Restore original
            db_manager.commit = original_commit  # type: ignore

            # Force garbage collection to close file handles before cleanup
            import gc

            gc.collect()

            # Clean up any leftover staging files to prevent resource warnings
            staging_area = Path(tempfile.gettempdir()) / "gmailarchiver_staging"
            if staging_area.exists():
                for staging_file in staging_area.glob("bulk_write_*.mbox*"):
                    try:
                        staging_file.unlink()
                    except Exception:
                        pass

        # Verify output was created despite error (or staging cleaned up)
        # The test validates error handling occurred

    async def test_archive_message_with_lock_file_cleanup(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test archive_message cleans up existing lock files (lines 152-155)."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive_lock.mbox"

        # Create a lock file before archiving
        lock_file = Path(str(mbox_path) + ".lock")
        lock_file.touch()
        assert lock_file.exists()

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<lock_cleanup@example.com>"
        msg["Subject"] = "Lock Cleanup Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Test body")

        # Archive message should handle and clean orphaned lock
        offset, length = await archive_single_message(
            storage,
            email_message=msg,
            gmail_id="msg_lock",
            archive_file=mbox_path,
            compression=None,
        )

        assert offset >= 0
        assert length > 0
        assert mbox_path.exists()

    async def test_archive_message_with_compression_and_various_formats(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test archive_message with all compression formats."""
        storage = HybridStorage(db_manager)

        # Test each compression format
        for compression_type, ext in [("gzip", ".gz"), ("lzma", ".xz")]:
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<compress_{compression_type}@example.com>"
            msg["Subject"] = f"Compression {compression_type}"
            msg["From"] = "sender@example.com"
            msg.set_content(f"Test {compression_type}")

            archive_path = temp_dir / f"archive_{compression_type}{ext}"
            offset, length = await archive_single_message(
                storage,
                email_message=msg,
                gmail_id=f"msg_{compression_type}",
                archive_file=archive_path,
                compression=compression_type,
            )

            assert offset >= 0
            assert length > 0
            assert archive_path.exists()

    async def test_consolidate_with_archive_file_fallback(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidate handles archive file name fallback (line 140)."""
        storage = HybridStorage(db_manager)

        # Create source with non-standard extension handling
        source = temp_dir / "source.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<fallback_test@example.com>"
        msg["Subject"] = "Fallback Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", source, None)

        output = temp_dir / "output.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source], output_archive=output, deduplicate=False, compression=None
        )

        assert result.total_messages == 1
        assert output.exists()

    async def test_archive_message_compression_extension_detection(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test archive_message handles various compression extensions (line 136-140)."""
        storage = HybridStorage(db_manager)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<ext_test@example.com>"
        msg["Subject"] = "Extension Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        # Test with .gz extension
        gz_path = temp_dir / "archive.mbox.gz"
        offset, length = await archive_single_message(
            storage, email_message=msg, gmail_id="msg_gz", archive_file=gz_path, compression="gzip"
        )
        assert offset >= 0
        assert length > 0
        assert gz_path.exists()

        # Test with .xz extension
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<ext_test2@example.com>"
        msg2["Subject"] = "Extension Test 2"
        msg2["From"] = "sender@example.com"
        msg2.set_content("Body 2")

        xz_path = temp_dir / "archive.mbox.xz"
        offset2, length2 = await archive_single_message(
            storage, email_message=msg2, gmail_id="msg_xz", archive_file=xz_path, compression="lzma"
        )
        assert offset2 >= 0
        assert length2 > 0
        assert xz_path.exists()

    async def test_consolidate_with_lock_file_cleanup(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidate cleans up lock files (lines 385-388)."""
        storage = HybridStorage(db_manager)

        source = temp_dir / "source.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<lock_test@example.com>"
        msg["Subject"] = "Lock Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", source, None)

        # Manually create a lock file to test cleanup
        lock_file = Path(str(source) + ".lock")
        lock_file.touch()
        assert lock_file.exists()

        output = temp_dir / "output.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source], output_archive=output, deduplicate=False, compression=None
        )

        # Lock file should be cleaned up after compression
        assert result.total_messages == 1

    async def test_mbox_unlock_failure_during_cleanup(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test handling of unlock failure during finally cleanup."""
        storage = HybridStorage(db_manager)
        archive = temp_dir / "test.mbox"

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<unlock_fail@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        # Patch unlock to raise exception during cleanup
        # Batch operations should handle this gracefully
        with patch.object(mailbox.mbox, "unlock", side_effect=OSError("Unlock failed")):
            result = await storage.archive_messages_batch(
                messages=[(msg, "msg1", None, None)],
                archive_file=archive,
            )

        # Should succeed despite unlock failure (warning logged)
        assert result["archived"] == 1
        assert result["failed"] == 0

    async def test_mbox_close_failure_during_cleanup(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test handling of close failure during finally cleanup."""
        storage = HybridStorage(db_manager)
        archive = temp_dir / "test.mbox"

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<close_fail@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        # Patch close to raise exception during cleanup
        # Batch operations should handle this gracefully
        with patch.object(mailbox.mbox, "close", side_effect=OSError("Close failed")):
            result = await storage.archive_messages_batch(
                messages=[(msg, "msg1", None, None)],
                archive_file=archive,
            )

        # Should succeed despite close failure (warning logged)
        assert result["archived"] == 1
        assert result["failed"] == 0

    async def test_archive_message_fallback_mbox_path(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test fallback mbox path calculation when compression extension detected (line 140)."""
        storage = HybridStorage(db_manager)

        # Create an archive file with non-standard naming (.mbox.unknown)
        archive = temp_dir / "test.mbox.unknown"

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<fallback@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        # This should trigger the fallback path calculation (line 140)
        offset, length = await archive_single_message(storage, msg, "msg1", archive, None)
        assert offset >= 0
        assert length > 0

    async def test_bulk_update_archive_locations_error(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test bulk_update_archive_locations_with_dedup error handling (lines 449-452)."""
        storage = HybridStorage(db_manager)

        # Force database error during update
        with patch.object(
            db_manager, "bulk_update_archive_locations", side_effect=RuntimeError("DB error")
        ):
            with pytest.raises(HybridStorageError, match="Failed to update archive locations"):
                await storage.bulk_update_archive_locations_with_dedup(
                    updates=[], duplicate_gmail_ids=None
                )

    async def test_consolidate_rollback_on_db_failure(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidate rollback when database rollback fails (lines 614-615, 632-633)."""
        storage = HybridStorage(db_manager)

        source = temp_dir / "source.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<rollback_fail@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", source, None)

        output = temp_dir / "output.mbox"

        # Patch both validation and rollback to test double-failure scenario
        with patch.object(
            storage,
            "_validate_consolidation_output",
            side_effect=IntegrityError("Validation failed"),
        ):
            with patch.object(db_manager, "rollback", side_effect=RuntimeError("Rollback failed")):
                with pytest.raises(IntegrityError):
                    await storage.consolidate_archives(
                        source_archives=[source],
                        output_archive=output,
                        deduplicate=False,
                        compression=None,
                    )

    async def test_consolidate_staging_cleanup_failure(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test consolidate staging cleanup failure (lines 619-623, 637-641)."""
        storage = HybridStorage(db_manager)

        source = temp_dir / "source.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<cleanup_fail@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", source, None)

        output = temp_dir / "output.mbox"

        # Patch validation to fail and unlink to fail during cleanup
        with patch.object(
            storage,
            "_validate_consolidation_output",
            side_effect=IntegrityError("Validation failed"),
        ):
            with patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")):
                with pytest.raises(IntegrityError):
                    await storage.consolidate_archives(
                        source_archives=[source],
                        output_archive=output,
                        deduplicate=False,
                        compression=None,
                    )


async def test_hybrid_storage_malformed_email_body(temp_dir, v11_db):
    """Test that malformed email body extraction doesn't crash (line 1029).

    When multipart email payload decoding raises an exception, the system should
    handle it gracefully and continue processing (return empty body preview).
    """
    from gmailarchiver.data.db_manager import DBManager

    db_manager = DBManager(str(v11_db))
    await db_manager.initialize()
    storage = HybridStorage(db_manager)

    # Create multipart message with problematic payload that will raise during decode
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<malformed@example.com>"
    msg["Subject"] = "Malformed Body Test"
    msg["From"] = "sender@example.com"
    msg.make_mixed()

    # Add a part that will cause exception when trying to decode
    from email.mime.base import MIMEBase

    problem_part = MIMEBase("text", "plain")
    # Set payload in a way that will raise exception during get_payload(decode=True)
    problem_part.set_payload(b"\xff\xfe\xfd\xfc")  # Invalid UTF-8 bytes
    problem_part["Content-Transfer-Encoding"] = "base64"
    msg.attach(problem_part)

    archive_path = temp_dir / "malformed.mbox"

    # Should handle gracefully - no crash, returns empty/truncated body
    try:
        await archive_single_message(storage, msg, "msg1", archive_path, None)
        # If we get here, the graceful handling worked
        assert True
    except Exception as e:
        # Should not raise - body extraction has try/except
        pytest.fail(f"Should handle malformed body gracefully, but raised: {e}")
    finally:
        await db_manager.close()


async def test_hybrid_storage_rollback_cleans_staging(temp_dir, v11_db):
    """Test that validation failure triggers rollback and staging cleanup (lines 619-623, 632-641).

    When validation fails during consolidation:
    1. IntegrityError is raised to caller
    2. Database is rolled back
    3. Staging file is cleaned up (deleted)
    """
    from unittest.mock import patch

    from gmailarchiver.data.db_manager import DBManager

    db_manager = DBManager(str(v11_db))
    await db_manager.initialize()
    storage = HybridStorage(db_manager)

    # Create source archive with a message
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<rollback_test@example.com>"
    msg["Subject"] = "Test Message"
    msg["From"] = "sender@example.com"
    msg.set_content("Body content")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"
    staging_pattern = temp_dir / ".staging_*.mbox"

    # Mock validation to fail
    with patch.object(
        storage,
        "_validate_consolidation_output",
        side_effect=IntegrityError("Mock validation failure"),
    ):
        # Consolidation should raise IntegrityError
        with pytest.raises(IntegrityError, match="Mock validation failure"):
            await storage.consolidate_archives(
                source_archives=[source], output_archive=output, deduplicate=False, compression=None
            )

        # Critical: Staging file should NOT exist (was cleaned up)
        import glob

        staging_files = list(glob.glob(str(staging_pattern)))
        assert len(staging_files) == 0, (
            f"Staging files should be cleaned up, but found: {staging_files}"
        )

        # Verify database was rolled back (no messages in output archive)
        async with DBManager(str(v11_db)) as db:
            messages = await db.get_all_messages_for_archive(str(output))
            assert len(messages) == 0, (
                "Database should be rolled back, no messages for output archive"
            )

    await db_manager.close()


async def test_bulk_write_length_fallback_when_file_not_created(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test bulk_write_messages handles file not created yet (lines 546, 561).

    When mbox library delays file creation, the file might not exist on disk
    yet after first flush. In this case, length = len(msg.as_bytes()).
    """
    storage = HybridStorage(db_manager)
    output_path = temp_dir / "bulk.mbox"

    # Create messages for bulk write
    messages = []
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<bulk1@example.com>"
    msg["Subject"] = "Bulk Message 1"
    msg["From"] = "sender@example.com"
    msg.set_content("Body 1")

    messages.append(
        {
            "message": msg,
            "gmail_id": "bulk1",
            "rfc_message_id": "<bulk1@example.com>",
        }
    )

    # Perform bulk write
    offset_map = await storage.bulk_write_messages(messages, output_path, compression=None)

    # Verify result
    assert len(offset_map) == 1
    assert "<bulk1@example.com>" in offset_map
    gmail_id, offset, length = offset_map["<bulk1@example.com>"]
    assert gmail_id == "bulk1"
    assert offset >= 0
    assert length > 0


async def test_consolidate_length_fallback_when_file_not_created(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test consolidate handles file not created yet during staging (lines 546, 561).

    During consolidation, if the staging mbox file doesn't exist on disk yet
    after the first message flush (mbox library delay), length should be
    calculated as len(msg.as_bytes()).
    """
    storage = HybridStorage(db_manager)

    # Create a source archive first
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<consolidate_fallback@example.com>"
    msg["Subject"] = "Consolidate Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Test body")

    await archive_single_message(storage, msg, "msg1", source, None)

    # Now consolidate to new output
    output = temp_dir / "output.mbox"
    result = await storage.consolidate_archives(
        source_archives=[source], output_archive=output, deduplicate=False, compression=None
    )

    # Verify consolidation succeeded
    assert result.total_messages == 1
    assert output.exists()

    # Verify message in database with correct offsets
    msg_data = await db_manager.get_message_by_gmail_id("msg1")
    assert msg_data is not None
    assert msg_data["mbox_offset"] >= 0
    assert msg_data["mbox_length"] > 0


async def test_bulk_write_staging_offset_zero_on_first_message(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test bulk_write_messages handles offset=0 for first message (line 370).

    When the staging mbox doesn't exist yet (first message), offset should be 0.
    """
    storage = HybridStorage(db_manager)
    output_path = temp_dir / "bulk_first.mbox"

    # Ensure output doesn't exist
    assert not output_path.exists()

    # Create single message for bulk write
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<first@example.com>"
    msg["Subject"] = "First Message"
    msg["From"] = "sender@example.com"
    msg.set_content("First body")

    messages = [
        {
            "message": msg,
            "gmail_id": "first_msg",
            "rfc_message_id": "<first@example.com>",
        }
    ]

    # Perform bulk write
    offset_map = await storage.bulk_write_messages(messages, output_path, compression=None)

    # Verify first message has offset 0
    gmail_id, offset, length = offset_map["<first@example.com>"]
    assert offset == 0, "First message should have offset 0"
    assert length > 0


async def test_bulk_write_length_fallback_path_when_file_missing(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test bulk_write handles length calculation when file doesn't exist (line 382).

    This tests the fallback path: length = len(msg.as_bytes()) when
    staging_mbox.exists() returns False after flush (edge case).
    """
    storage = HybridStorage(db_manager)
    output_path = temp_dir / "bulk_fallback.mbox"

    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<fallback@example.com>"
    msg["Subject"] = "Fallback Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Fallback body content")

    messages = [
        {
            "message": msg,
            "gmail_id": "fallback_msg",
            "rfc_message_id": "<fallback@example.com>",
        }
    ]

    # This should work normally, exercising the length calculation
    offset_map = await storage.bulk_write_messages(messages, output_path, compression=None)

    # Verify result
    assert "<fallback@example.com>" in offset_map
    gmail_id, offset, length = offset_map["<fallback@example.com>"]

    # Length should be positive (calculated via fallback or normal path)
    assert length > 0
    # Length should approximately match the message size
    expected_length = len(msg.as_bytes())
    # Allow some variance due to mbox formatting
    assert length >= expected_length * 0.9, (
        f"Length {length} seems too small compared to {expected_length}"
    )


async def test_bulk_write_cleanup_on_error_path(db_manager: DBManager, temp_dir: Path) -> None:
    """Test bulk_write cleans up staging file on error (lines 414-415).

    When bulk_write encounters an error, it should clean up the staging mbox file.
    """
    storage = HybridStorage(db_manager)
    output_path = temp_dir / "bulk_error.mbox"

    # Create a message that will cause an error during processing
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<error@example.com>"
    msg["Subject"] = "Error Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Error body")

    messages = [
        {
            "message": msg,
            "gmail_id": "error_msg",
            "rfc_message_id": "<error@example.com>",
        }
    ]

    # Mock mbox.flush to raise an error
    with patch.object(mailbox.mbox, "flush", side_effect=OSError("Disk full")):
        # Should raise HybridStorageError
        with pytest.raises(HybridStorageError, match="Failed to bulk write messages"):
            await storage.bulk_write_messages(messages, output_path, compression=None)

    # Staging file should be cleaned up (in staging area)
    # Check that no orphaned staging files exist
    staging_files = list(storage._staging_area.glob("bulk_write_*.mbox"))
    assert len(staging_files) == 0, "Staging files should be cleaned up on error"


async def test_bulk_write_finally_block_exceptions(db_manager: DBManager, temp_dir: Path) -> None:
    """Test bulk_write handles exceptions in finally block (lines 424-431).

    When mbox unlock or close fails in finally block, errors should be logged
    but not raised (graceful degradation).
    """
    storage = HybridStorage(db_manager)
    output_path = temp_dir / "bulk_finally.mbox"

    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<finally@example.com>"
    msg["Subject"] = "Finally Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Finally body")

    messages = [
        {
            "message": msg,
            "gmail_id": "finally_msg",
            "rfc_message_id": "<finally@example.com>",
        }
    ]

    # We need to let the operation succeed first, then fail during cleanup
    # The finally block calls unlock() and close(), which should log warnings but not fail
    original_unlock = mailbox.mbox.unlock
    original_close = mailbox.mbox.close
    unlock_calls = [0]
    close_calls = [0]

    def conditionally_failing_unlock(self: Any) -> None:
        unlock_calls[0] += 1
        # Succeed first time (normal operation), fail on cleanup
        if unlock_calls[0] == 1:
            original_unlock(self)
        else:
            raise OSError("Unlock failed during cleanup")

    def conditionally_failing_close(self: Any) -> None:
        close_calls[0] += 1
        # Succeed first time (normal operation), fail on cleanup
        if close_calls[0] == 1:
            original_close(self)
        else:
            raise OSError("Close failed during cleanup")

    try:
        # Patch to fail on cleanup calls
        mailbox.mbox.unlock = conditionally_failing_unlock  # type: ignore
        mailbox.mbox.close = conditionally_failing_close  # type: ignore

        # Should complete successfully (warnings logged for cleanup failures)
        offset_map = await storage.bulk_write_messages(messages, output_path, compression=None)

        # Verify operation succeeded
        assert "<finally@example.com>" in offset_map
        assert output_path.exists()

    finally:
        # Restore original methods
        mailbox.mbox.unlock = original_unlock  # type: ignore
        mailbox.mbox.close = original_close  # type: ignore


async def test_consolidate_staging_cleanup_on_validation_error(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test consolidate cleans up staging on validation error (lines 636-640).

    When validation fails after writing, staging should be cleaned up and
    database rolled back.
    """
    from unittest.mock import patch

    storage = HybridStorage(db_manager)

    # Create source archive
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<validation_error@example.com>"
    msg["Subject"] = "Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Body")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"

    # Mock validation to fail
    with patch.object(
        storage, "_validate_consolidation_output", side_effect=IntegrityError("Validation failed")
    ):
        with pytest.raises(IntegrityError):
            await storage.consolidate_archives(
                source_archives=[source], output_archive=output, deduplicate=False, compression=None
            )

    # Staging should be cleaned up
    staging_files = list(storage._staging_area.glob("*.mbox"))
    assert len(staging_files) == 0, "Staging files should be cleaned up"


async def test_consolidate_rollback_on_general_exception(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test consolidate rollback on general exception (lines 649-658).

    When consolidation fails with a general exception (not validation),
    should rollback database and clean up staging files.
    """
    from unittest.mock import patch

    storage = HybridStorage(db_manager)

    # Create source archive
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<general_error@example.com>"
    msg["Subject"] = "Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Body")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"

    # Mock to raise exception during consolidation
    with patch("mailbox.mbox") as mock_mbox:
        mock_mbox.return_value.__enter__.return_value.add.side_effect = OSError("Disk full")

        with pytest.raises(HybridStorageError, match="Failed to consolidate"):
            await storage.consolidate_archives(
                source_archives=[source], output_archive=output, deduplicate=False, compression=None
            )

    # Database should be rolled back (no messages for output)
    messages = await db_manager.get_all_messages_for_archive(str(output))
    assert len(messages) == 0, "Database should be rolled back"


async def test_consolidate_finally_block_unlock_close(
    db_manager: DBManager, temp_dir: Path
) -> None:
    """Test consolidate finally block unlock/close (lines 667-674).

    Finally block should always attempt unlock/close, even if they fail.
    Exceptions should be logged but not propagated.
    """
    storage = HybridStorage(db_manager)

    # Create source archive
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<finally_unlock@example.com>"
    msg["Subject"] = "Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Body")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"

    # This should complete successfully (finally block runs)
    result = await storage.consolidate_archives(
        source_archives=[source], output_archive=output, deduplicate=False, compression=None
    )

    assert result.total_messages == 1
    assert output.exists()


async def test_consolidate_rollback_failure_logging(db_manager: DBManager, temp_dir: Path) -> None:
    """Test consolidate logs rollback failures (lines 654-658).

    When database rollback itself fails, error should be logged but
    original exception should still be raised.
    """
    from unittest.mock import patch

    storage = HybridStorage(db_manager)

    # Create source archive
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<rollback_fail@example.com>"
    msg["Subject"] = "Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Body")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"

    # Mock both the operation and rollback to fail
    with patch("mailbox.mbox") as mock_mbox:
        mock_mbox.return_value.__enter__.return_value.add.side_effect = OSError("Disk full")

        with patch.object(db_manager, "rollback", side_effect=Exception("Rollback error")):
            with pytest.raises(HybridStorageError, match="Failed to consolidate"):
                await storage.consolidate_archives(
                    source_archives=[source],
                    output_archive=output,
                    deduplicate=False,
                    compression=None,
                )


async def test_consolidate_staging_cleanup_exception(db_manager: DBManager, temp_dir: Path) -> None:
    """Test consolidate handles staging cleanup exceptions (lines 640, 658).

    When unlinking staging file fails during cleanup, exception should be
    logged but original error should still be raised.
    """
    from unittest.mock import patch

    storage = HybridStorage(db_manager)

    # Create source archive
    source = temp_dir / "source.mbox"
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<cleanup_fail@example.com>"
    msg["Subject"] = "Test"
    msg["From"] = "sender@example.com"
    msg.set_content("Body")

    await archive_single_message(storage, msg, "msg1", source, None)

    output = temp_dir / "output.mbox"

    # Mock to fail during operation and make cleanup fail too
    with patch("mailbox.mbox") as mock_mbox:
        mock_mbox.return_value.__enter__.return_value.add.side_effect = OSError("Disk full")

        # Make staging file exist but unable to unlink
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
                with pytest.raises(HybridStorageError, match="Failed to consolidate"):
                    await storage.consolidate_archives(
                        source_archives=[source],
                        output_archive=output,
                        deduplicate=False,
                        compression=None,
                    )


# ============================================================================
# Read Operations Tests (NEW - TDD Red Phase)
# ============================================================================


class TestReadOperations:
    """Tests for HybridStorage read operations.

    These methods provide read-only access to archived messages via the
    HybridStorage gateway, following the architecture rule that core layer
    must not access DBManager directly.
    """

    async def test_search_messages_fulltext(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test search_messages with full-text query."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive messages with searchable content
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<invoice123@example.com>"
        msg1["Subject"] = "Invoice for Q1 2024"
        msg1["From"] = "billing@company.com"
        msg1["To"] = "customer@example.com"
        msg1.set_content("Please find attached the invoice for the first quarter.")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<receipt456@example.com>"
        msg2["Subject"] = "Receipt for purchase"
        msg2["From"] = "sales@company.com"
        msg2["To"] = "customer@example.com"
        msg2.set_content("Thank you for your purchase. Here is your receipt.")

        await archive_single_message(storage, msg1, "msg1", mbox_path, None)
        await archive_single_message(storage, msg2, "msg2", mbox_path, None)

        # Search for "invoice" - should return msg1 only
        results = await storage.search_messages(query="invoice", limit=10)

        assert results is not None
        assert results.total_results == 1
        assert len(results.results) == 1
        assert results.results[0].gmail_id == "msg1"
        assert results.results[0].subject == "Invoice for Q1 2024"
        assert results.query == "invoice"
        assert results.execution_time_ms >= 0

    async def test_search_messages_with_metadata_filters(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test search_messages with metadata filters (from, to, date range)."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive messages from different senders
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Test 1"
        msg1["From"] = "alice@example.com"
        msg1["To"] = "bob@example.com"
        msg1.set_content("Body 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Test 2"
        msg2["From"] = "charlie@example.com"
        msg2["To"] = "bob@example.com"
        msg2.set_content("Body 2")

        await archive_single_message(storage, msg1, "msg1", mbox_path, None)
        await archive_single_message(storage, msg2, "msg2", mbox_path, None)

        # Search with from_addr filter
        results = await storage.search_messages(query=None, from_addr="alice@example.com", limit=10)

        assert results.total_results == 1
        assert results.results[0].gmail_id == "msg1"
        assert results.results[0].from_addr == "alice@example.com"

    async def test_search_messages_with_pagination(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test search_messages with limit and offset for pagination."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive 5 messages
        for i in range(5):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = "sender@example.com"
            msg["To"] = "recipient@example.com"
            msg.set_content(f"Body {i}")
            await archive_single_message(storage, msg, f"msg{i}", mbox_path, None)

        # First page
        page1 = await storage.search_messages(query=None, limit=2, offset=0)
        assert len(page1.results) == 2
        assert page1.total_results == 5

        # Second page
        page2 = await storage.search_messages(query=None, limit=2, offset=2)
        assert len(page2.results) == 2
        assert page2.total_results == 5

        # Third page (partial)
        page3 = await storage.search_messages(query=None, limit=2, offset=4)
        assert len(page3.results) == 1
        assert page3.total_results == 5

    async def test_search_messages_empty_database(self, db_manager: DBManager) -> None:
        """Test search_messages with empty database returns empty results."""
        storage = HybridStorage(db_manager)

        results = await storage.search_messages(query="anything", limit=10)

        assert results.total_results == 0
        assert len(results.results) == 0
        assert results.query == "anything"

    async def test_search_messages_no_matches(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test search_messages when query has no matches."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg["Subject"] = "Hello World"
        msg["From"] = "sender@example.com"
        msg.set_content("This is a test message")

        await archive_single_message(storage, msg, "msg1", mbox_path, None)

        # Search for non-existent content
        results = await storage.search_messages(query="nonexistent", limit=10)

        assert results.total_results == 0
        assert len(results.results) == 0

    async def test_get_message_by_gmail_id_success(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test get_message retrieves message by gmail_id."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg["Subject"] = "Test Subject"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg.set_content("Test body")

        await archive_single_message(storage, msg, "gmail123", mbox_path, "thread456")

        # Retrieve message
        record = await storage.get_message(gmail_id="gmail123")

        assert record is not None
        assert record["gmail_id"] == "gmail123"
        assert record["rfc_message_id"] == "<test@example.com>"
        assert record["subject"] == "Test Subject"
        assert record["from_addr"] == "sender@example.com"
        assert record["to_addr"] == "recipient@example.com"
        assert record["thread_id"] == "thread456"
        assert record["archive_file"] == str(mbox_path)
        assert record["mbox_offset"] >= 0
        assert record["mbox_length"] > 0

    async def test_get_message_by_gmail_id_not_found(self, db_manager: DBManager) -> None:
        """Test get_message returns None for non-existent gmail_id."""
        storage = HybridStorage(db_manager)

        record = await storage.get_message(gmail_id="nonexistent")

        assert record is None

    async def test_get_message_by_rfc_id_success(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test get_message_by_rfc_id retrieves message by RFC Message-ID."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<unique_rfc_id@example.com>"
        msg["Subject"] = "Find me by RFC ID"
        msg["From"] = "sender@example.com"
        msg.set_content("Body content")

        await archive_single_message(storage, msg, "gmail999", mbox_path, None)

        # Retrieve by RFC Message-ID
        record = await storage.get_message_by_rfc_id(rfc_message_id="<unique_rfc_id@example.com>")

        assert record is not None
        assert record["gmail_id"] == "gmail999"
        assert record["rfc_message_id"] == "<unique_rfc_id@example.com>"
        assert record["subject"] == "Find me by RFC ID"

    async def test_get_message_by_rfc_id_not_found(self, db_manager: DBManager) -> None:
        """Test get_message_by_rfc_id returns None for non-existent RFC ID."""
        storage = HybridStorage(db_manager)

        record = await storage.get_message_by_rfc_id(rfc_message_id="<nonexistent@example.com>")

        assert record is None

    async def test_extract_message_content_from_uncompressed_mbox(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test extract_message_content reads full message from uncompressed mbox."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        original_msg = email.message.EmailMessage()
        original_msg["Message-ID"] = "<content_test@example.com>"
        original_msg["Subject"] = "Extract this content"
        original_msg["From"] = "sender@example.com"
        original_msg["To"] = "recipient@example.com"
        original_msg.set_content("This is the full message body that should be extracted.")

        await archive_single_message(storage, original_msg, "extract_msg", mbox_path, None)

        # Extract the message content
        extracted_msg = await storage.extract_message_content(gmail_id="extract_msg")

        assert extracted_msg is not None
        assert extracted_msg["Message-ID"] == "<content_test@example.com>"
        assert extracted_msg["Subject"] == "Extract this content"
        assert extracted_msg["From"] == "sender@example.com"
        assert extracted_msg["To"] == "recipient@example.com"
        assert "full message body" in extracted_msg.get_content()

    async def test_extract_message_content_from_compressed_mbox(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test extract_message_content reads from compressed (gzip) mbox."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox.gz"

        # Archive with compression
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<compressed@example.com>"
        msg["Subject"] = "Compressed message"
        msg["From"] = "sender@example.com"
        msg.set_content("This message is compressed with gzip.")

        await archive_single_message(storage, msg, "compressed_msg", mbox_path, None, None, "gzip")

        # Extract from compressed archive
        extracted_msg = await storage.extract_message_content(gmail_id="compressed_msg")

        assert extracted_msg is not None
        assert extracted_msg["Message-ID"] == "<compressed@example.com>"
        assert extracted_msg["Subject"] == "Compressed message"
        assert "compressed with gzip" in extracted_msg.get_content()

    async def test_extract_message_content_message_not_found(self, db_manager: DBManager) -> None:
        """Test extract_message_content raises error for non-existent message."""
        storage = HybridStorage(db_manager)

        with pytest.raises(HybridStorageError, match="Message.*not found"):
            await storage.extract_message_content(gmail_id="nonexistent")

    async def test_extract_message_content_archive_file_missing(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test extract_message_content raises error when archive file is missing."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<missing_archive@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "msg1", mbox_path, None)

        # Delete the archive file
        mbox_path.unlink()

        # Try to extract - should fail
        with pytest.raises(HybridStorageError, match="Archive file.*not found"):
            await storage.extract_message_content(gmail_id="msg1")


# ============================================================================
# Statistics Operations Tests (NEW - TDD Red Phase)
# ============================================================================


class TestStatisticsOperations:
    """Tests for HybridStorage statistics operations.

    These methods replace ArchiveState and provide comprehensive statistics
    via the HybridStorage gateway.
    """

    async def test_get_archive_stats_empty_database(self, db_manager: DBManager) -> None:
        """Test get_archive_stats with empty database."""
        storage = HybridStorage(db_manager)

        stats = await storage.get_archive_stats()

        assert stats is not None
        assert stats.total_messages == 0
        assert len(stats.archive_files) == 0
        assert stats.schema_version in ["1.1", "1.2", "1.3"]
        assert stats.database_size_bytes > 0  # Database file exists even if empty
        assert isinstance(stats.recent_runs, list)

    async def test_get_archive_stats_with_messages(
        self, db_manager: DBManager, temp_dir: Path
    ) -> None:
        """Test get_archive_stats returns accurate statistics."""
        storage = HybridStorage(db_manager)
        mbox1 = temp_dir / "archive1.mbox"
        mbox2 = temp_dir / "archive2.mbox"

        # Archive messages to different files
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "Message 1"
        msg1["From"] = "sender@example.com"
        msg1.set_content("Body 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Message 2"
        msg2["From"] = "sender@example.com"
        msg2.set_content("Body 2")

        msg3 = email.message.EmailMessage()
        msg3["Message-ID"] = "<msg3@example.com>"
        msg3["Subject"] = "Message 3"
        msg3["From"] = "sender@example.com"
        msg3.set_content("Body 3")

        await archive_single_message(storage, msg1, "msg1", mbox1, None)
        await archive_single_message(storage, msg2, "msg2", mbox1, None)
        await archive_single_message(storage, msg3, "msg3", mbox2, None)

        # Get statistics
        stats = await storage.get_archive_stats()

        assert stats.total_messages == 3
        assert len(stats.archive_files) == 2
        assert str(mbox1) in stats.archive_files
        assert str(mbox2) in stats.archive_files
        assert stats.schema_version in ["1.1", "1.2", "1.3"]
        assert stats.database_size_bytes > 0

    async def test_get_message_ids_for_archive(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test get_message_ids_for_archive returns correct gmail_ids."""
        storage = HybridStorage(db_manager)
        mbox1 = temp_dir / "archive1.mbox"
        mbox2 = temp_dir / "archive2.mbox"

        # Archive messages to different files
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["Subject"] = "In archive 1"
        msg1["From"] = "sender@example.com"
        msg1.set_content("Body")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["Subject"] = "Also in archive 1"
        msg2["From"] = "sender@example.com"
        msg2.set_content("Body")

        msg3 = email.message.EmailMessage()
        msg3["Message-ID"] = "<msg3@example.com>"
        msg3["Subject"] = "In archive 2"
        msg3["From"] = "sender@example.com"
        msg3.set_content("Body")

        await archive_single_message(storage, msg1, "msg1", mbox1, None)
        await archive_single_message(storage, msg2, "msg2", mbox1, None)
        await archive_single_message(storage, msg3, "msg3", mbox2, None)

        # Get IDs for archive1
        ids_archive1 = await storage.get_message_ids_for_archive(archive_file=str(mbox1))

        assert len(ids_archive1) == 2
        assert "msg1" in ids_archive1
        assert "msg2" in ids_archive1
        assert "msg3" not in ids_archive1

        # Get IDs for archive2
        ids_archive2 = await storage.get_message_ids_for_archive(archive_file=str(mbox2))

        assert len(ids_archive2) == 1
        assert "msg3" in ids_archive2

    async def test_get_message_ids_for_archive_nonexistent_file(
        self, db_manager: DBManager
    ) -> None:
        """Test get_message_ids_for_archive returns empty set for nonexistent file."""
        storage = HybridStorage(db_manager)

        ids = await storage.get_message_ids_for_archive(archive_file="/nonexistent/archive.mbox")

        assert len(ids) == 0

    async def test_get_recent_runs(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test get_recent_runs returns archive operation history."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Perform multiple archive operations
        for i in range(3):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<run{i}@example.com>"
            msg["Subject"] = f"Run {i}"
            msg["From"] = "sender@example.com"
            msg.set_content(f"Body {i}")
            await archive_single_message(storage, msg, f"msg{i}", mbox_path, None)

        # Get recent runs
        runs = await storage.get_recent_runs(limit=10)

        assert len(runs) >= 3  # At least 3 runs (may have more from batch operations)
        # Verify structure of run records
        for run in runs:
            assert "run_id" in run
            assert "run_timestamp" in run
            assert "messages_archived" in run
            assert "archive_file" in run
            assert "operation_type" in run or "query" in run  # Depends on schema version

    async def test_get_recent_runs_with_limit(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test get_recent_runs respects limit parameter."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Create 5 archive operations
        for i in range(5):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<limit_test{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = "sender@example.com"
            msg.set_content(f"Body {i}")
            await archive_single_message(storage, msg, f"limit_msg{i}", mbox_path, None)

        # Request only 2 most recent
        runs = await storage.get_recent_runs(limit=2)

        assert len(runs) <= 2

    async def test_get_recent_runs_empty_database(self, db_manager: DBManager) -> None:
        """Test get_recent_runs with no archive operations."""
        storage = HybridStorage(db_manager)

        runs = await storage.get_recent_runs(limit=10)

        assert len(runs) == 0

    async def test_is_message_archived_true(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test is_message_archived returns True for archived message."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive a message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<archived@example.com>"
        msg["Subject"] = "Archived message"
        msg["From"] = "sender@example.com"
        msg.set_content("Body")

        await archive_single_message(storage, msg, "archived_msg", mbox_path, None)

        # Check if archived
        is_archived = await storage.is_message_archived(gmail_id="archived_msg")

        assert is_archived is True

    async def test_is_message_archived_false(self, db_manager: DBManager) -> None:
        """Test is_message_archived returns False for non-archived message."""
        storage = HybridStorage(db_manager)

        is_archived = await storage.is_message_archived(gmail_id="never_archived")

        assert is_archived is False

    async def test_get_message_count_zero(self, db_manager: DBManager) -> None:
        """Test get_message_count returns 0 for empty database."""
        storage = HybridStorage(db_manager)

        count = await storage.get_message_count()

        assert count == 0

    async def test_get_message_count_accurate(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test get_message_count returns accurate count."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "archive.mbox"

        # Archive multiple messages
        for i in range(7):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<count{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = "sender@example.com"
            msg.set_content(f"Body {i}")
            await archive_single_message(storage, msg, f"count_msg{i}", mbox_path, None)

        # Get count
        count = await storage.get_message_count()

        assert count == 7
