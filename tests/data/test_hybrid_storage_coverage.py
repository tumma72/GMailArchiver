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
