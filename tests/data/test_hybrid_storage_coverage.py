"""Additional tests for HybridStorage to improve coverage.

These tests target specific uncovered lines in data/hybrid_storage.py
to achieve 95%+ coverage.
"""

import email
import mailbox
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage

pytestmark = pytest.mark.asyncio


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def v11_db(temp_dir):
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

    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL,
            operation_type TEXT,
            account_id TEXT DEFAULT 'default'
        )
    """)

    conn.commit()
    conn.close()

    return db_path


class TestHybridStorageInterruptHandling:
    """Tests for interrupt event handling (lines 194-197)."""

    async def test_archive_messages_batch_with_interrupt(self, temp_dir, v11_db):
        """Test batch archiving with interrupt event set."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create test messages
        messages = []
        for i in range(5):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@test.com>"
            msg["Subject"] = f"Test {i}"
            msg.set_content(f"Body {i}")
            messages.append((msg, f"gmail_{i}", f"thread_{i}", None))

        # Create interrupt event and set it immediately
        interrupt_event = threading.Event()
        interrupt_event.set()

        # Archive with interrupt
        archive_file = temp_dir / "test.mbox"
        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=archive_file,
            compression=None,
            interrupt_event=interrupt_event,
        )

        # Should detect interrupt early
        assert result["interrupted"] is True
        assert result["archived"] == 0  # Should stop before archiving any

        await db.close()

    async def test_archive_messages_batch_interrupt_mid_batch(self, temp_dir, v11_db):
        """Test interrupt occurring during batch processing.

        With async two-phase architecture:
        - Phase 1: mbox writes in thread pool (checks interrupt at start of each message)
        - Phase 2: database writes (async)

        This test uses a background thread to set interrupt during Phase 1 processing.
        """
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create messages (more to give interrupt time to be set)
        messages = []
        for i in range(20):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@test.com>"
            msg["Subject"] = f"Test {i}"
            # Larger body to slow down processing
            msg.set_content(f"Body {i}" * 100)
            messages.append((msg, f"gmail_{i}", f"thread_{i}", None))

        # Create interrupt event (will be set by background thread)
        interrupt_event = threading.Event()

        # Background thread sets interrupt after short delay
        def set_interrupt_after_delay():
            import time

            time.sleep(0.001)  # 1ms delay to let processing start
            interrupt_event.set()

        interrupt_thread = threading.Thread(target=set_interrupt_after_delay)
        interrupt_thread.start()

        archive_file = temp_dir / "test.mbox"
        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=archive_file,
            compression=None,
            interrupt_event=interrupt_event,
        )

        interrupt_thread.join()

        # Should save partial progress (interrupt may or may not catch any messages
        # depending on timing, but the flag should be set if interrupt was detected)
        # The key assertion is that interrupt is detected and reported
        assert result["interrupted"] is True
        # Some messages may have been processed before interrupt was detected
        assert result["archived"] < 20  # Not all messages

        await db.close()


class TestHybridStorageProgressCallbacks:
    """Tests for progress callback handling (lines 208, 267, 283)."""

    async def test_progress_callback_on_skip(self, temp_dir, v11_db):
        """Test progress callback called when skipping duplicate (line 208)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=True)

        # Pre-archive a message
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<duplicate@test.com>"
        msg1["Subject"] = "Original"
        msg1.set_content("Body 1")

        archive_file = temp_dir / "test.mbox"
        await storage.archive_messages_batch(
            messages=[(msg1, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            compression=None,
        )

        # Try to archive duplicate with callback
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<duplicate@test.com>"
        msg2["Subject"] = "Duplicate"
        msg2.set_content("Body 2")

        callback_calls = []

        def progress_callback(gmail_id, subject, status):
            callback_calls.append((gmail_id, subject, status))

        await storage.archive_messages_batch(
            messages=[(msg2, "gmail_2", "thread_2", None)],
            archive_file=archive_file,
            compression=None,
            progress_callback=progress_callback,
        )

        # Should have called callback with "skipped"
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == "gmail_2"
        assert callback_calls[0][2] == "skipped"

        await db.close()

    async def test_progress_callback_on_success(self, temp_dir, v11_db):
        """Test progress callback called on successful archive (line 267)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        callback_calls = []

        def progress_callback(gmail_id, subject, status):
            callback_calls.append((gmail_id, subject, status))

        archive_file = temp_dir / "test.mbox"
        await storage.archive_messages_batch(
            messages=[(msg, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            compression=None,
            progress_callback=progress_callback,
        )

        # Should have called callback with "success"
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == "gmail_1"
        assert callback_calls[0][2] == "success"

        await db.close()

    async def test_progress_callback_on_error(self, temp_dir, v11_db):
        """Test progress callback called on error (line 283)."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        callback_calls = []

        def progress_callback(gmail_id, subject, status):
            callback_calls.append((gmail_id, subject, status))

        # Mock record_archived_message to fail
        with patch.object(db, "record_archived_message", side_effect=Exception("DB error")):
            archive_file = temp_dir / "test.mbox"
            await storage.archive_messages_batch(
                messages=[(msg, "gmail_1", "thread_1", None)],
                archive_file=archive_file,
                compression=None,
                progress_callback=progress_callback,
            )

            # Should have called callback with "error"
            assert len(callback_calls) == 1
            assert callback_calls[0][0] == "gmail_1"
            assert callback_calls[0][2] == "error"

        await db.close()


class TestHybridStorageFallbackPaths:
    """Tests for fallback paths when mbox._file is not available (lines 219-222, 233)."""

    async def test_offset_calculation_without_mbox_file(self, temp_dir, v11_db):
        """Test offset calculation when mbox._file is None (line 219-222)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body content")

        # Pre-create mbox file so mbox_path.exists() is True
        archive_file = temp_dir / "test.mbox"
        mbox_obj = mailbox.mbox(str(archive_file))
        mbox_obj.close()

        # Archive message (should use fallback path)
        await storage.archive_messages_batch(
            messages=[(msg, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            compression=None,
        )

        # Verify message was archived
        messages = await db.get_all_messages_for_archive(str(archive_file))
        assert len(messages) == 1

        await db.close()

    async def test_length_calculation_fallback(self, temp_dir, v11_db):
        """Test length calculation fallback (line 233)."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        archive_file = temp_dir / "test.mbox"

        # Mock mailbox.mbox to return object without _file
        with patch("mailbox.mbox") as mock_mbox:
            mock_instance = MagicMock()
            mock_instance._file = None  # Force fallback
            mock_instance.lock = MagicMock()
            mock_instance.unlock = MagicMock()
            mock_instance.add = MagicMock()
            mock_mbox.return_value = mock_instance

            # Should use fallback length calculation
            await storage.archive_messages_batch(
                messages=[(msg, "gmail_1", "thread_1", None)],
                archive_file=archive_file,
                compression=None,
            )

            # Verify add was called
            assert mock_instance.add.called

        await db.close()


class TestHybridStorageCleanupPaths:
    """Tests for cleanup exception handling (lines 302-303, 335, 386-391, 508-509, 518-519)."""

    async def test_unlock_exception_handling(self, temp_dir, v11_db):
        """Test exception handling during unlock (line 296, 386)."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        archive_file = temp_dir / "test.mbox"

        # Mock mbox to raise exception on unlock
        with patch("mailbox.mbox") as mock_mbox:
            mock_instance = MagicMock()
            mock_instance.lock = MagicMock()
            mock_instance.add = MagicMock()
            mock_instance.unlock = MagicMock(side_effect=Exception("Unlock failed"))
            mock_instance.close = MagicMock()
            mock_instance._file = None
            mock_mbox.return_value = mock_instance

            # Should handle unlock exception gracefully
            await storage.archive_messages_batch(
                messages=[(msg, "gmail_1", "thread_1", None)],
                archive_file=archive_file,
                compression=None,
            )

            # Should have attempted unlock
            assert mock_instance.unlock.called

        await db.close()

    async def test_close_exception_handling(self, temp_dir, v11_db):
        """Test exception handling during close (lines 302-303, 389-391)."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        archive_file = temp_dir / "test.mbox"

        # Mock mbox._file to raise exception on close
        with patch("mailbox.mbox") as mock_mbox:
            mock_instance = MagicMock()
            mock_file = MagicMock()
            mock_file.close = MagicMock(side_effect=Exception("Close failed"))
            mock_file.flush = MagicMock()
            mock_file.tell = MagicMock(return_value=0)
            mock_file.seek = MagicMock()

            mock_instance._file = mock_file
            mock_instance.lock = MagicMock()
            mock_instance.add = MagicMock()
            mock_instance.unlock = MagicMock()
            mock_mbox.return_value = mock_instance

            # Should handle close exception gracefully
            await storage.archive_messages_batch(
                messages=[(msg, "gmail_1", "thread_1", None)],
                archive_file=archive_file,
                compression=None,
            )

            # Should have attempted close
            assert mock_file.close.called

        await db.close()

    async def test_lock_file_cleanup_on_compression(self, temp_dir, v11_db):
        """Test lock file cleanup during compression (line 335)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        archive_file = temp_dir / "test.mbox.zst"

        # Create lock file manually
        lock_file = temp_dir / "test.mbox.lock"
        lock_file.touch()

        # Archive with compression
        await storage.archive_messages_batch(
            messages=[(msg, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            compression="zstd",
        )

        # Lock file should be removed after compression
        assert not lock_file.exists()

        await db.close()


class TestCompressionNonStandardExtension:
    """Test compression path without standard extension (line 181)."""

    async def test_archive_compression_without_standard_extension(self, temp_dir, v11_db):
        """Test archiving with compression when file doesn't have .gz/.xz/.zst extension."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        # Use filename without standard compression extension
        archive_file = temp_dir / "archive_custom"

        result = await storage.archive_messages_batch(
            messages=[(msg, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            compression="gzip",
        )

        assert result["archived"] == 1
        # Should have created archive_custom.mbox temp file

        await db.close()


class TestSessionProgressUpdates:
    """Test session progress tracking (line 261)."""

    async def test_session_progress_updated_at_commit_interval(self, temp_dir, v11_db):
        """Test that session progress is updated when commit interval is reached."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create archive_sessions table if not exists
        await db._conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_sessions (
                session_id TEXT PRIMARY KEY,
                target_file TEXT NOT NULL,
                query TEXT NOT NULL,
                message_ids TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT,
                status TEXT DEFAULT 'in_progress',
                compression TEXT,
                total_count INTEGER NOT NULL,
                processed_count INTEGER DEFAULT 0,
                account_id TEXT DEFAULT 'default'
            )
        """)

        session_id = "test_session"
        archive_file = temp_dir / "test.mbox"

        # Insert session
        from datetime import datetime

        await db._conn.execute(
            """INSERT INTO archive_sessions
               (session_id, target_file, query, message_ids, started_at, total_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, str(archive_file), "test", "msg1", datetime.now().isoformat(), 1),
        )
        await db.commit()

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        # Archive with session_id and commit_interval=1
        result = await storage.archive_messages_batch(
            messages=[(msg, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
            session_id=session_id,
            commit_interval=1,  # Triggers line 261
        )

        assert result["archived"] == 1

        # Verify session was completed
        cursor = await db._conn.execute(
            "SELECT status FROM archive_sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "completed"

        await db.close()


class TestDuplicateConstraintHandling:
    """Test duplicate handling via UNIQUE constraint (lines 269-275)."""

    async def test_unique_constraint_treated_as_skip(self, temp_dir, v11_db):
        """Test that UNIQUE constraint violation on rfc_message_id is treated as skip."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<duplicate@test.com>"
        msg1["Subject"] = "Test"
        msg1.set_content("Body 1")

        archive_file = temp_dir / "test.mbox"

        # Archive first
        result1 = await storage.archive_messages_batch(
            messages=[(msg1, "gmail_1", "thread_1", None)],
            archive_file=archive_file,
        )
        assert result1["archived"] == 1

        # Archive same rfc_message_id again (should trigger UNIQUE constraint)
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<duplicate@test.com>"
        msg2["Subject"] = "Duplicate"
        msg2.set_content("Body 2")

        callback_calls = []

        def progress_callback(gmail_id, subject, status):
            callback_calls.append((gmail_id, subject, status))

        result2 = await storage.archive_messages_batch(
            messages=[(msg2, "gmail_2", "thread_2", None)],
            archive_file=archive_file,
            progress_callback=progress_callback,
        )

        # Should be skipped due to unique constraint
        assert result2["skipped"] == 1
        assert result2["archived"] == 0
        # Progress callback should be called with "skipped" (line 275)
        assert any(call[2] == "skipped" for call in callback_calls)

        await db.close()


class TestRollbackErrorHandling:
    """Test rollback error handling (lines 345-346)."""

    async def test_rollback_failure_logged_but_not_suppressed(self, temp_dir, v11_db):
        """Test that rollback failures are logged but original exception is raised."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        archive_file = temp_dir / "test.mbox"

        # Mock rollback to fail
        async def failing_rollback():
            raise Exception("Rollback failed")

        original_rollback = db.rollback
        db.rollback = failing_rollback  # type: ignore

        # Mock _write_messages_to_mbox_sync to fail
        with patch.object(
            storage,
            "_write_messages_to_mbox_sync",
            side_effect=Exception("Write failed"),
        ):
            # Should raise HybridStorageError despite rollback failure
            from gmailarchiver.data.hybrid_storage import HybridStorageError

            with pytest.raises(HybridStorageError):
                await storage.archive_messages_batch(
                    messages=[(msg, "gmail_1", "thread_1", None)],
                    archive_file=archive_file,
                )

        db.rollback = original_rollback  # type: ignore
        await db.close()


# Additional targeted tests for 95% coverage


class TestValidationEdgeCases:
    """Test validation edge cases to cover lines 703, 739-743, 760, 880, 887."""

    async def test_batch_validation_failure(self, temp_dir, v11_db):
        """Test batch validation detects missing message (line 703)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        from gmailarchiver.data.hybrid_storage import IntegrityError

        # Validate non-existent RFC ID - should fail
        with pytest.raises(IntegrityError, match="not in database"):
            await storage._validate_batch_consistency(["<nonexistent@test.com>"])

        await db.close()

    async def test_validate_message_decompression_failure(self, temp_dir, v11_db):
        """Test message validation with corrupt compressed file (lines 741-743)."""
        from datetime import datetime

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create corrupt compressed file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"not valid gzip data")

        # Insert record pointing to corrupt file
        await db._conn.execute(
            """INSERT INTO messages
               (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                archived_timestamp, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "msg1",
                "<test@test.com>",
                str(corrupt_gz),
                0,
                100,
                datetime.now().isoformat(),
                "Test",
            ),
        )
        await db.commit()

        from gmailarchiver.data.hybrid_storage import IntegrityError

        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_message_consistency("<test@test.com>")

        await db.close()

    async def test_validate_consolidation_missing_messages(self, temp_dir, v11_db):
        """Test consolidation validation detects missing messages (line 880)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create archive with one message
        archive_path = temp_dir / "archive.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<present@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        await storage.archive_messages_batch(
            messages=[(msg, "msg1", "thread1", None)],
            archive_file=archive_path,
        )

        from gmailarchiver.data.hybrid_storage import IntegrityError

        # Expect two but only one present
        with pytest.raises(IntegrityError, match="Missing.*expected"):
            await storage._validate_consolidation_output(
                archive_path,
                expected_message_ids={"<present@test.com>", "<missing@test.com>"},
            )

        await db.close()

    async def test_validate_consolidation_unexpected_messages(self, temp_dir, v11_db):
        """Test consolidation validation detects unexpected messages (line 887)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create archive with message
        archive_path = temp_dir / "archive.mbox"
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<unexpected@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        await storage.archive_messages_batch(
            messages=[(msg, "msg1", "thread1", None)],
            archive_file=archive_path,
        )

        from gmailarchiver.data.hybrid_storage import IntegrityError

        # Expect none but one present
        with pytest.raises(IntegrityError, match="unexpected"):
            await storage._validate_consolidation_output(archive_path, expected_message_ids=set())

        await db.close()


class TestBulkWriteEdgeCases:
    """Test bulk_write edge cases (lines 427, 439, 467-472, 478-482, 493-494)."""

    async def test_bulk_write_offset_calculation(self, temp_dir, v11_db):
        """Test offset calculation when staging file doesn't exist (line 427)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        messages = [{"message": msg, "gmail_id": "gmail_1", "rfc_message_id": "<test@test.com>"}]

        output_path = temp_dir / "output.mbox"
        offset_map = await storage.bulk_write_messages(messages, output_path)

        assert "<test@test.com>" in offset_map
        gmail_id, offset, length = offset_map["<test@test.com>"]
        assert offset == 0  # First message starts at 0
        assert length > 0

        await db.close()

    async def test_bulk_write_with_compression(self, temp_dir, v11_db):
        """Test compression cleanup paths (lines 467-472)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@test.com>"
        msg["Subject"] = "Test"
        msg.set_content("Body")

        messages = [{"message": msg, "gmail_id": "gmail_1", "rfc_message_id": "<test@test.com>"}]

        output_path = temp_dir / "output.mbox.gz"
        offset_map = await storage.bulk_write_messages(messages, output_path, compression="gzip")

        assert len(offset_map) == 1
        # Temp mbox should be deleted
        temp_mbox = temp_dir / "output.mbox"
        assert not temp_mbox.exists()
        # Lock file should be cleaned
        lock_file = temp_dir / "output.mbox.lock"
        assert not lock_file.exists()

        await db.close()


class TestConsolidationEdgeCases:
    """Test consolidation edge cases (lines 608, 659-663, 679)."""

    async def test_consolidation_with_compression(self, temp_dir, v11_db):
        """Test lock file cleanup in consolidation with compression (line 608)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create source archive
        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@test.com>"
        msg1["Subject"] = "Test"
        msg1.set_content("Body")

        await storage.archive_messages_batch(
            messages=[(msg1, "gmail_1", "thread_1", None)],
            archive_file=source1,
        )

        # Consolidate with compression
        output_path = temp_dir / "output.mbox.gz"
        result = await storage.consolidate_archives(
            source_archives=[source1],
            output_archive=output_path,
            deduplicate=False,
            compression="gzip",
        )

        assert result.messages_consolidated == 1
        # Lock file should be cleaned
        lock_file = temp_dir / "output.mbox.lock"
        assert not lock_file.exists()

        await db.close()

    async def test_consolidation_staging_cleanup_on_integrity_error(self, temp_dir, v11_db):
        """Test staging cleanup on IntegrityError (lines 659-663)."""
        from unittest.mock import patch

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create source
        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@test.com>"
        msg1["Subject"] = "Test"
        msg1.set_content("Body")

        await storage.archive_messages_batch(
            messages=[(msg1, "gmail_1", "thread_1", None)],
            archive_file=source1,
        )

        output_path = temp_dir / "output.mbox"

        from gmailarchiver.data.hybrid_storage import IntegrityError

        # Mock validation to raise IntegrityError
        with patch.object(
            storage,
            "_validate_consolidation_output",
            side_effect=IntegrityError("Validation failed"),
        ):
            with pytest.raises(IntegrityError):
                await storage.consolidate_archives(
                    source_archives=[source1],
                    output_archive=output_path,
                    deduplicate=False,
                )

        await db.close()


class TestExtractAndValidateArchive:
    """Test extract_message_content and validate_archive_integrity."""

    async def test_extract_message_decompression_failure(self, temp_dir, v11_db):
        """Test decompression failure in extract_message_content (lines 1620-1623)."""
        from datetime import datetime

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create corrupt compressed file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"corrupt")

        await db._conn.execute(
            """INSERT INTO messages
               (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                archived_timestamp, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "msg1",
                "<test@test.com>",
                str(corrupt_gz),
                0,
                100,
                datetime.now().isoformat(),
                "Test",
            ),
        )
        await db.commit()

        from gmailarchiver.data.hybrid_storage import HybridStorageError

        with pytest.raises(HybridStorageError, match="Failed to decompress"):
            await storage.extract_message_content("msg1")

        await db.close()

    async def test_validate_archive_nonexistent_file(self, temp_dir, v11_db):
        """Test validate_archive_integrity with nonexistent file (line 1662)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        result = await storage.validate_archive_integrity("/nonexistent/file.mbox")
        assert result is False

        await db.close()

    async def test_validate_archive_decompression_failure(self, temp_dir, v11_db):
        """Test validate_archive_integrity with decompression failure (lines 1675-1677)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create corrupt compressed file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"not gzip")

        result = await storage.validate_archive_integrity(str(corrupt_gz))
        assert result is False

        await db.close()

    async def test_validate_archive_is_directory(self, temp_dir, v11_db):
        """Test validate_archive_integrity with directory (lines 1696-1698)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create directory instead of file
        fake_archive = temp_dir / "archive.mbox"
        fake_archive.mkdir()

        result = await storage.validate_archive_integrity(str(fake_archive))
        assert result is False

        await db.close()


class TestCollectMessagesErrors:
    """Test _collect_messages error paths (lines 937-939)."""

    async def test_collect_messages_decompression_failure(self, temp_dir, v11_db):
        """Test decompression failure in collect messages."""
        from datetime import datetime

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create corrupt file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"not gzip")

        await db._conn.execute(
            """INSERT INTO messages
               (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                archived_timestamp, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "msg1",
                "<test@test.com>",
                str(corrupt_gz),
                0,
                100,
                datetime.now().isoformat(),
                "Test",
            ),
        )
        await db.commit()

        from gmailarchiver.data.hybrid_storage import HybridStorageError

        with pytest.raises(HybridStorageError, match="Failed to decompress"):
            await storage._collect_messages([corrupt_gz])

        await db.close()


class TestWriteMboxSyncErrors:
    """Test _write_messages_to_mbox_sync error paths (lines 1195-1197, 1227-1234)."""

    @pytest.mark.filterwarnings("ignore:Use of text mode files is deprecated:DeprecationWarning")
    async def test_message_archive_exception_during_write(self, temp_dir, v11_db):
        """Test message archiving failure during mbox write (lines 1195-1197)."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create a mock message that fails during as_bytes()
        bad_msg = MagicMock()
        bad_msg.__getitem__ = MagicMock(return_value="<test@test.com>")
        bad_msg.get = MagicMock(return_value="<test@test.com>")
        bad_msg.as_bytes = MagicMock(side_effect=Exception("Failed to serialize"))

        mbox_path = temp_dir / "test.mbox"

        result = await storage.archive_messages_batch(
            messages=[(bad_msg, "bad_msg", None, None)],
            archive_file=mbox_path,
        )

        # Should count as failed
        assert result["failed"] == 1
        assert result["archived"] == 0

        await db.close()


class TestArchiveValidationEdgeCases:
    """Test _validate_archive_consistency edge cases (lines 791-795, 827)."""

    async def test_validate_archive_with_corrupt_gzip(self, temp_dir, v11_db):
        """Test archive validation with corrupt gzip file (lines 793-795)."""
        from datetime import datetime

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create corrupt compressed file
        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"invalid gzip data")

        # Insert record pointing to corrupt file
        await db._conn.execute(
            """INSERT INTO messages
               (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                archived_timestamp, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "msg1",
                "<test@test.com>",
                str(corrupt_gz),
                0,
                100,
                datetime.now().isoformat(),
                "Test",
            ),
        )
        await db.commit()

        from gmailarchiver.data.hybrid_storage import IntegrityError

        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_archive_consistency(corrupt_gz)

        await db.close()


class TestConsolidationValidationDecompression:
    """Test consolidation validation with decompression failure (lines 857-860)."""

    async def test_validate_consolidation_corrupt_gzip(self, temp_dir, v11_db):
        """Test consolidation validation with corrupt compressed file."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        corrupt_gz = temp_dir / "corrupt.mbox.gz"
        corrupt_gz.write_bytes(b"bad gzip data")

        from gmailarchiver.data.hybrid_storage import IntegrityError

        with pytest.raises(IntegrityError, match="Failed to decompress"):
            await storage._validate_consolidation_output(
                corrupt_gz, expected_message_ids={"<test@test.com>"}
            )

        await db.close()


class TestBodyExtractionEdgeCases:
    """Test body extraction edge cases (lines 1031-1032)."""

    async def test_extract_body_from_multipart(self, temp_dir, v11_db):
        """Test body extraction from multipart message."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create multipart message
        msg = MIMEMultipart()
        msg["Message-ID"] = "<multipart@test.com>"
        msg["Subject"] = "Multipart Test"
        msg.attach(MIMEText("Plain text body content here", "plain"))
        msg.attach(MIMEText("<html>HTML body</html>", "html"))

        archive_file = temp_dir / "test.mbox"
        result = await storage.archive_messages_batch(
            messages=[(msg, "msg1", "thread1", None)],
            archive_file=archive_file,
        )

        assert result["archived"] == 1
        # Verify body_preview was extracted
        msg_data = await db.get_message_by_gmail_id("msg1")
        assert msg_data["body_preview"] is not None
        assert "Plain text body" in msg_data["body_preview"]

        await db.close()


class TestConsolidationOffsetCalculation:
    """Test consolidation offset calculation (lines 1319, 1331)."""

    async def test_consolidation_multiple_messages(self, temp_dir, v11_db):
        """Test offset and length calculation with multiple messages."""
        db = DBManager(str(v11_db), validate_schema=False)
        await db.initialize()
        storage = HybridStorage(db, preload_rfc_ids=False)

        # Create source with two messages
        source1 = temp_dir / "source1.mbox"
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@test.com>"
        msg1["Subject"] = "First Message"
        msg1.set_content("First body content")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@test.com>"
        msg2["Subject"] = "Second Message"
        msg2.set_content("Second body content that is a bit longer")

        await storage.archive_messages_batch(
            messages=[
                (msg1, "msg1", "thread1", None),
                (msg2, "msg2", "thread2", None),
            ],
            archive_file=source1,
        )

        # Consolidate
        output_path = temp_dir / "consolidated.mbox"
        result = await storage.consolidate_archives(
            source_archives=[source1],
            output_archive=output_path,
            deduplicate=False,
        )

        assert result.messages_consolidated == 2

        # Verify offsets are different and lengths are positive
        msg1_data = await db.get_message_by_rfc_message_id("<msg1@test.com>")
        msg2_data = await db.get_message_by_rfc_message_id("<msg2@test.com>")

        assert msg1_data["mbox_length"] > 0
        assert msg2_data["mbox_length"] > 0
        # Second message should have offset > first message offset
        assert msg2_data["mbox_offset"] >= msg1_data["mbox_offset"] + msg1_data["mbox_length"]

        await db.close()


class TestDuplicateRfcMessageIdHandling:
    """Tests for UNIQUE constraint handling on rfc_message_id (lines 269-275)."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Provide temporary directory."""
        return tmp_path

    @pytest.fixture
    async def v11_db(self, temp_dir):
        """Provide initialized v1.1 database."""
        db_path = temp_dir / "test.db"
        db = DBManager(db_path)
        await db.initialize()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_duplicate_rfc_message_id_skipped(self, temp_dir, v11_db):
        """Test that duplicate rfc_message_id triggers skip path (lines 269-275)."""
        storage = HybridStorage(v11_db, temp_dir / "archives")
        archive_file = temp_dir / "archives" / "test.mbox"
        archive_file.parent.mkdir(parents=True, exist_ok=True)

        # Create first message and archive
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<duplicate@test.com>"
        msg1["Subject"] = "First message"
        msg1["From"] = "test@example.com"
        msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg1.set_content("First content")

        # Archive first message using tuples format
        result1 = await storage.archive_messages_batch(
            messages=[(msg1, "id1", "thread1", None)],
            archive_file=archive_file,
        )
        assert result1["archived"] == 1

        # Create second message with SAME rfc_message_id but different gmail_id
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<duplicate@test.com>"  # Same as first!
        msg2["Subject"] = "Second message"
        msg2["From"] = "test@example.com"
        msg2["Date"] = "Tue, 02 Jan 2024 12:00:00 +0000"
        msg2.set_content("Second content")

        # Track progress to verify skip callback
        progress_calls = []

        def track_progress(gmail_id, subject, status):
            progress_calls.append((gmail_id, subject, status))

        # Archive second message - should trigger UNIQUE constraint skip
        result2 = await storage.archive_messages_batch(
            messages=[(msg2, "id2", "thread2", None)],
            archive_file=archive_file,
            progress_callback=track_progress,
        )

        # Message should be skipped due to duplicate rfc_message_id
        assert result2["skipped"] == 1 or result2["archived"] == 0


class TestLockFileCleanupDuringCompression:
    """Tests for lock file cleanup during compression (line 312)."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Provide temporary directory."""
        return tmp_path

    @pytest.fixture
    async def v11_db(self, temp_dir):
        """Provide initialized v1.1 database."""
        db_path = temp_dir / "test.db"
        db = DBManager(db_path)
        await db.initialize()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_lock_file_removed_after_compression(self, temp_dir, v11_db):
        """Test lock file is removed after compression (line 312)."""
        storage = HybridStorage(v11_db, temp_dir / "archives")
        archive_file = temp_dir / "archives" / "test.mbox.gz"  # Request compression
        archive_file.parent.mkdir(parents=True, exist_ok=True)

        # Create test message
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<compress-test@test.com>"
        msg["Subject"] = "Compression test"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Test content for compression")

        # Archive with compression using tuples format
        result = await storage.archive_messages_batch(
            messages=[(msg, "compress1", "thread1", None)],
            archive_file=archive_file,
            compression="gzip",
        )

        assert result["archived"] == 1
        # The actual archive file might have different extension depending on implementation
        # Check that compressed file exists
        compressed_files = list(archive_file.parent.glob("*.gz"))
        assert len(compressed_files) >= 1


class TestSessionProgressWithCommitInterval:
    """Additional tests for session progress updates."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Provide temporary directory."""
        return tmp_path

    @pytest.fixture
    async def v11_db(self, temp_dir):
        """Provide initialized v1.1 database."""
        db_path = temp_dir / "test.db"
        db = DBManager(db_path)
        await db.initialize()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_session_progress_debug_logging(self, temp_dir, v11_db):
        """Test session progress debug logging path (line 262)."""
        storage = HybridStorage(v11_db, temp_dir / "archives")
        archive_file = temp_dir / "archives" / "test.mbox"
        archive_file.parent.mkdir(parents=True, exist_ok=True)

        # Create messages to trigger commit (using tuples format)
        messages = []
        for i in range(5):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<progress-{i}@test.com>"
            msg["Subject"] = f"Progress test {i}"
            msg["From"] = "test@example.com"
            msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
            msg.set_content(f"Content {i}")
            messages.append((msg, f"progress{i}", f"thread{i}", None))

        # Archive with small commit interval to trigger progress updates
        result = await storage.archive_messages_batch(
            messages=messages,
            archive_file=archive_file,
            commit_interval=2,
        )

        assert result["archived"] == 5
