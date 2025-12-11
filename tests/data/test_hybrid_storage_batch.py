"""Tests for HybridStorage batch archiving - Performance optimization for Issue #6.

This module tests the batch archiving functionality that addresses the 100x
performance regression identified in GitHub Issue #6. The key optimization is
to amortize expensive I/O operations (fsync, mbox open/close, DB commits)
across a batch of messages rather than per-message.

Test Coverage:
- Batch archiving basic functionality
- Batch atomicity (all succeed or all rollback)
- Batch validation at end (not per-message)
- Batch DB commits (configurable interval)
- Duplicate handling within batch
- Error handling and rollback
- Performance characteristics (fewer I/O operations)
"""

import email
import mailbox
import sqlite3
import tempfile
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage, HybridStorageError

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
def mbox_path(temp_dir: Path) -> Path:
    """Create a path for test mbox file."""
    return temp_dir / "test.mbox"


def create_sample_email(
    message_id: str, subject: str = "Test Subject", from_addr: str = "sender@example.com"
) -> email.message.Message:
    """Helper to create sample email messages with unique Message-IDs."""
    msg = email.message.EmailMessage()
    msg["Message-ID"] = f"<{message_id}@example.com>"
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
    msg.set_content(f"This is the body for message {message_id}.")
    return msg


# ============================================================================
# Batch Archive Basic Functionality Tests
# ============================================================================


class TestArchiveMessagesBatch:
    """Tests for archive_messages_batch method - the core performance fix."""

    async def test_archive_messages_batch_exists(self, db_manager: DBManager) -> None:
        """Verify archive_messages_batch method exists on HybridStorage."""
        storage = HybridStorage(db_manager)

        # The method should exist
        assert hasattr(storage, "archive_messages_batch")
        assert callable(getattr(storage, "archive_messages_batch"))

    async def test_archive_messages_batch_basic_success(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test batch archiving multiple messages successfully."""
        storage = HybridStorage(db_manager)

        # Prepare batch of messages
        messages = [
            (create_sample_email("msg1", "Subject 1"), "gmail_id_1", None, None),
            (create_sample_email("msg2", "Subject 2"), "gmail_id_2", None, None),
            (create_sample_email("msg3", "Subject 3"), "gmail_id_3", None, None),
        ]

        # Archive batch
        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
        )

        # Verify counts
        assert result["archived"] == 3
        assert result["skipped"] == 0

        # Verify all messages in mbox
        mbox = mailbox.mbox(str(mbox_path))
        assert len(mbox) == 3
        mbox.close()

        # Verify all messages in database
        for i in range(1, 4):
            msg_data = await db_manager.get_message_by_gmail_id(f"gmail_id_{i}")
            assert msg_data is not None
            assert msg_data["subject"] == f"Subject {i}"

    async def test_archive_messages_batch_empty_list(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test batch archiving with empty list returns zero counts."""
        storage = HybridStorage(db_manager)

        result = await storage.archive_messages_batch(
            messages=[],
            archive_file=mbox_path,
        )

        assert result["archived"] == 0
        assert result["skipped"] == 0
        # Mbox should not be created for empty batch
        assert not mbox_path.exists()

    async def test_archive_messages_batch_records_correct_offsets(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that batch archiving records correct mbox offsets for each message."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email("msg1"), "gmail_id_1", None, None),
            (create_sample_email("msg2"), "gmail_id_2", None, None),
        ]

        await storage.archive_messages_batch(messages=messages, archive_file=mbox_path)

        # Get recorded offsets
        msg1 = await db_manager.get_message_by_gmail_id("gmail_id_1")
        msg2 = await db_manager.get_message_by_gmail_id("gmail_id_2")

        # First message should start at offset 0
        assert msg1["mbox_offset"] == 0
        assert msg1["mbox_length"] > 0

        # Second message should start after first
        assert msg2["mbox_offset"] == msg1["mbox_offset"] + msg1["mbox_length"]
        assert msg2["mbox_length"] > 0

        # Verify we can read messages at recorded offsets
        with open(mbox_path, "rb") as f:
            f.seek(msg1["mbox_offset"])
            data1 = f.read(msg1["mbox_length"])
            parsed1 = email.message_from_bytes(data1)
            assert parsed1["Message-ID"] == "<msg1@example.com>"

            f.seek(msg2["mbox_offset"])
            data2 = f.read(msg2["mbox_length"])
            parsed2 = email.message_from_bytes(data2)
            assert parsed2["Message-ID"] == "<msg2@example.com>"


# ============================================================================
# Batch Atomicity Tests (CRITICAL)
# ============================================================================


class TestArchiveMessagesBatchAtomicity:
    """Tests for batch atomicity - all succeed or all rollback."""

    async def test_batch_handles_per_message_db_errors(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that database errors are handled per-message without stopping batch."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email("msg1"), "gmail_id_1", None, None),
            (create_sample_email("msg2"), "gmail_id_2", None, None),
        ]

        # Mock database to fail on second insert
        original_record = db_manager.record_archived_message

        call_count = [0]

        async def failing_record(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise sqlite3.Error("Simulated database error")
            return await original_record(*args, **kwargs)

        with patch.object(db_manager, "record_archived_message", side_effect=failing_record):
            result = await storage.archive_messages_batch(messages=messages, archive_file=mbox_path)

        # First message should succeed, second should fail
        assert result["archived"] == 1
        assert result["failed"] == 1

        # First message should be in database
        assert await db_manager.get_message_by_gmail_id("gmail_id_1") is not None
        # Second message should not be in database (failed)
        assert await db_manager.get_message_by_gmail_id("gmail_id_2") is None

    async def test_batch_all_or_nothing_semantics(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that partial batch failures don't leave partial state."""
        storage = HybridStorage(db_manager)

        # First batch should succeed
        messages1 = [
            (create_sample_email("msg1"), "gmail_id_1", None, None),
        ]
        await storage.archive_messages_batch(messages=messages1, archive_file=mbox_path)

        # Verify first batch succeeded
        assert await db_manager.get_message_by_gmail_id("gmail_id_1") is not None

        # Second batch that fails should not affect first batch
        messages2 = [
            (create_sample_email("msg2"), "gmail_id_2", None, None),
            (create_sample_email("msg3"), "gmail_id_3", None, None),
        ]

        with patch.object(db_manager, "commit", side_effect=sqlite3.Error("Commit failed")):
            with pytest.raises(HybridStorageError):
                await storage.archive_messages_batch(messages=messages2, archive_file=mbox_path)

        # First batch should still be intact
        assert await db_manager.get_message_by_gmail_id("gmail_id_1") is not None
        # Second batch should be rolled back
        assert await db_manager.get_message_by_gmail_id("gmail_id_2") is None
        assert await db_manager.get_message_by_gmail_id("gmail_id_3") is None


# ============================================================================
# Duplicate Handling Tests
# ============================================================================


class TestArchiveMessagesBatchDuplicates:
    """Tests for duplicate handling within batch."""

    async def test_batch_skips_duplicates_by_rfc_message_id(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that duplicates within batch are skipped."""
        storage = HybridStorage(db_manager)

        # Same RFC Message-ID, different Gmail IDs
        messages = [
            (create_sample_email("same_msg_id"), "gmail_id_1", None, None),
            (create_sample_email("same_msg_id"), "gmail_id_2", None, None),  # Duplicate
        ]

        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
        )

        # One archived, one skipped
        assert result["archived"] == 1
        assert result["skipped"] == 1

        # Only first should be in DB
        assert await db_manager.get_message_by_gmail_id("gmail_id_1") is not None
        assert await db_manager.get_message_by_gmail_id("gmail_id_2") is None

    async def test_batch_skips_already_archived_messages(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that messages already in DB are skipped."""
        storage = HybridStorage(db_manager)

        # Archive first message using batch method with single message
        msg1 = create_sample_email("existing_msg")
        await storage.archive_messages_batch(
            messages=[(msg1, "existing_gmail_id", None, None)],
            archive_file=mbox_path,
        )

        # Now try batch with same RFC Message-ID
        messages = [
            (create_sample_email("existing_msg"), "new_gmail_id", None, None),
            (create_sample_email("new_msg"), "new_gmail_id_2", None, None),
        ]

        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
        )

        # One new message archived, one skipped (duplicate)
        assert result["archived"] == 1
        assert result["skipped"] == 1


# ============================================================================
# Batch Commit Interval Tests
# ============================================================================


class TestArchiveMessagesBatchCommitInterval:
    """Tests for configurable batch commit intervals."""

    async def test_batch_commits_at_interval(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test that batch commits occur at specified interval."""
        storage = HybridStorage(db_manager)

        # Create 150 messages (should trigger 1 intermediate commit at 100)
        messages = [
            (create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(150)
        ]

        commit_count = [0]
        original_commit = db_manager.commit

        async def counting_commit():
            commit_count[0] += 1
            return await original_commit()

        with patch.object(db_manager, "commit", side_effect=counting_commit):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
                commit_interval=100,
            )

        # Should have committed at 100 and then final commit
        # (2 commits for 150 messages with interval 100)
        assert commit_count[0] == 2

    async def test_batch_single_commit_for_small_batch(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that small batches only trigger one commit."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(50)
        ]

        commit_count = [0]
        original_commit = db_manager.commit

        async def counting_commit():
            commit_count[0] += 1
            return await original_commit()

        with patch.object(db_manager, "commit", side_effect=counting_commit):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
                commit_interval=100,
            )

        # Should only have final commit
        assert commit_count[0] == 1


# ============================================================================
# I/O Efficiency Tests (Performance Characteristics)
# ============================================================================


class TestArchiveMessagesBatchIOEfficiency:
    """Tests for I/O efficiency - the core performance optimization."""

    async def test_batch_single_fsync_at_end(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test that batch uses single fsync at end, not per message."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(10)
        ]

        fsync_count = [0]

        import os

        original_fsync = os.fsync

        def counting_fsync(fd):
            fsync_count[0] += 1
            return original_fsync(fd)

        with patch("os.fsync", side_effect=counting_fsync):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
            )

        # Should only have 1 fsync for the entire batch (not 10)
        assert fsync_count[0] == 1

    async def test_batch_single_mbox_open_close_cycle(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that batch opens/closes mbox only once."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(10)
        ]

        mbox_init_count = [0]
        original_mbox_init = mailbox.mbox.__init__

        def counting_init(self, *args, **kwargs):
            mbox_init_count[0] += 1
            return original_mbox_init(self, *args, **kwargs)

        with patch.object(mailbox.mbox, "__init__", counting_init):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
            )

        # Should only open mbox once for entire batch
        assert mbox_init_count[0] == 1

    async def test_batch_no_per_message_validation(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that batch does not validate each message individually."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(10)
        ]

        validation_count = [0]

        def counting_validation(rfc_message_id):
            validation_count[0] += 1

        with patch.object(
            storage, "_validate_message_consistency", side_effect=counting_validation
        ):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
            )

        # Should not call per-message validation
        assert validation_count[0] == 0


# ============================================================================
# Batch Validation Tests
# ============================================================================


class TestArchiveMessagesBatchValidation:
    """Tests for batch-level validation."""

    async def test_batch_validates_at_end(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test that batch validation runs once at end."""
        storage = HybridStorage(db_manager)

        messages = [(create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(5)]

        # Add validate_batch method call check
        batch_validation_called = [False]

        def mock_batch_validation(rfc_message_ids):
            batch_validation_called[0] = True
            assert len(rfc_message_ids) == 5

        with patch.object(
            storage, "_validate_batch_consistency", side_effect=mock_batch_validation
        ):
            await storage.archive_messages_batch(
                messages=messages,
                archive_file=mbox_path,
            )

        assert batch_validation_called[0]

    async def test_validate_batch_consistency_method_exists(self, db_manager: DBManager) -> None:
        """Verify _validate_batch_consistency method exists."""
        storage = HybridStorage(db_manager)

        assert hasattr(storage, "_validate_batch_consistency")
        assert callable(getattr(storage, "_validate_batch_consistency"))


# ============================================================================
# Thread/Label Support Tests
# ============================================================================


class TestArchiveMessagesBatchMetadata:
    """Tests for thread_id and labels support in batch."""

    async def test_batch_records_thread_ids(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test that batch records thread IDs correctly."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email("msg1"), "gmail_id_1", "thread_1", None),
            (create_sample_email("msg2"), "gmail_id_2", "thread_2", None),
        ]

        await storage.archive_messages_batch(messages=messages, archive_file=mbox_path)

        msg1 = await db_manager.get_message_by_gmail_id("gmail_id_1")
        msg2 = await db_manager.get_message_by_gmail_id("gmail_id_2")

        assert msg1["thread_id"] == "thread_1"
        assert msg2["thread_id"] == "thread_2"

    async def test_batch_records_labels(self, db_manager: DBManager, mbox_path: Path) -> None:
        """Test that batch records Gmail labels correctly."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email("msg1"), "gmail_id_1", None, '["INBOX", "IMPORTANT"]'),
            (create_sample_email("msg2"), "gmail_id_2", None, '["SENT"]'),
        ]

        await storage.archive_messages_batch(messages=messages, archive_file=mbox_path)

        msg1 = await db_manager.get_message_by_gmail_id("gmail_id_1")
        msg2 = await db_manager.get_message_by_gmail_id("gmail_id_2")

        assert msg1["labels"] == '["INBOX", "IMPORTANT"]'
        assert msg2["labels"] == '["SENT"]'


# ============================================================================
# Compression Support Tests
# ============================================================================


class TestArchiveMessagesBatchCompression:
    """Tests for compression support in batch archiving."""

    async def test_batch_with_gzip_compression(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test batch archiving with gzip compression."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "test.mbox.gz"

        messages = [(create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(3)]

        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
            compression="gzip",
        )

        assert result["archived"] == 3
        assert mbox_path.exists()

    async def test_batch_with_zstd_compression(self, db_manager: DBManager, temp_dir: Path) -> None:
        """Test batch archiving with zstd compression."""
        storage = HybridStorage(db_manager)
        mbox_path = temp_dir / "test.mbox.zst"

        messages = [(create_sample_email(f"msg{i}"), f"gmail_id_{i}", None, None) for i in range(3)]

        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
            compression="zstd",
        )

        assert result["archived"] == 3
        assert mbox_path.exists()


# ============================================================================
# Return Value Tests
# ============================================================================


class TestArchiveMessagesBatchReturnValues:
    """Tests for batch return values."""

    async def test_batch_returns_dict_with_counts(
        self, db_manager: DBManager, mbox_path: Path
    ) -> None:
        """Test that batch returns dict with archived, skipped, failed, interrupted keys."""
        storage = HybridStorage(db_manager)

        messages = [
            (create_sample_email("msg1"), "gmail_id_1", None, None),
        ]

        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=mbox_path,
        )

        # Should return dict with required keys
        assert isinstance(result, dict)
        assert "archived" in result
        assert "skipped" in result
        assert "failed" in result
        assert "interrupted" in result
        assert "actual_file" in result
        assert isinstance(result["archived"], int)
        assert isinstance(result["skipped"], int)
        assert isinstance(result["failed"], int)
        assert isinstance(result["interrupted"], bool)
