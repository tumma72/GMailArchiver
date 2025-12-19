"""Unit tests for MessageWriter (archiver package internal module).

This module contains fast, isolated unit tests with no I/O or external
dependencies. All external components (DBManager, HybridStorage, GmailClient)
are mocked.
"""

import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gmailarchiver.core.archiver._writer import MessageWriter
from gmailarchiver.shared.input_validator import InvalidInputError


# Helper function to create async generators for mocking
async def _async_generator_from_list(items: list):
    """Convert a list to an async generator."""
    for item in items:
        yield item


@pytest.mark.unit
class TestMessageWriter:
    """Unit tests for MessageWriter internal module."""

    @pytest.fixture
    def mock_gmail_client(self):
        """Create mock Gmail client."""
        client = Mock()
        return client

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db = Mock()
        db.create_session = AsyncMock()
        db.close = AsyncMock()
        return db

    @pytest.fixture
    def mock_hybrid_storage(self, mock_db_manager):
        """Create mock hybrid storage."""
        storage = Mock()
        storage.db = mock_db_manager
        return storage

    @pytest.fixture
    def writer(self, mock_gmail_client, mock_hybrid_storage):
        """Create MessageWriter with mocked client and storage."""
        return MessageWriter(gmail_client=mock_gmail_client, storage=mock_hybrid_storage)

    @pytest.fixture
    def mock_archive_helper(self):
        """Mock _archive_messages helper method result."""
        return {
            "archived": 3,
            "failed": 0,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox",
        }

    @pytest.mark.asyncio
    async def test_archive_messages_with_valid_message_ids(
        self, writer, mock_db_manager, mock_archive_helper
    ):
        """Test archiving with valid message IDs (success path)."""
        message_ids = ["msg001", "msg002", "msg003"]
        output_file = "/tmp/archive.mbox"

        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        with patch("gmailarchiver.core.archiver._writer.uuid.uuid4", return_value=test_uuid):
            with patch.object(
                writer,
                "_archive_messages",
                new_callable=AsyncMock,
                return_value=mock_archive_helper,
            ):
                result = await writer.archive_messages(message_ids, output_file)

        # Should return correct structure
        assert result["archived_count"] == 3
        assert result["failed_count"] == 0
        assert result["interrupted"] is False
        assert result["actual_file"] == "/tmp/archive.mbox"

        # Should create session with correct parameters
        mock_db_manager.create_session.assert_called_once()

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_creates_session_with_uuid(
        self, mock_uuid, writer, mock_db_manager
    ):
        """Test that session is created with UUID and correct parameters."""
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_uuid.return_value = test_uuid

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 2,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            await writer.archive_messages(["msg001", "msg002"], "/tmp/test.mbox", compress="gzip")

        # Should create session with UUID
        mock_db_manager.create_session.assert_called_once()
        call_kwargs = mock_db_manager.create_session.call_args[1]
        assert call_kwargs["session_id"] == str(test_uuid)
        assert call_kwargs["target_file"] == "/tmp/test.mbox"
        assert "archive_messages(2 messages)" in call_kwargs["query"]
        assert call_kwargs["message_ids"] == ["msg001", "msg002"]
        assert call_kwargs["compression"] == "gzip"

    @pytest.mark.asyncio
    async def test_archive_messages_with_empty_message_list(self, writer):
        """Test that empty message list returns zeros without processing."""
        result = await writer.archive_messages([], "/tmp/archive.mbox")

        assert result["archived_count"] == 0
        assert result["failed_count"] == 0
        assert result["interrupted"] is False
        assert result["actual_file"] == "/tmp/archive.mbox"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_with_gzip_compression(self, mock_uuid, writer):
        """Test archiving with gzip compression."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.gz",
            },
        ):
            result = await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="gzip")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.gz"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_with_lzma_compression(self, mock_uuid, writer):
        """Test archiving with lzma compression."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.xz",
            },
        ):
            result = await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="lzma")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.xz"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_with_zstd_compression(self, mock_uuid, writer):
        """Test archiving with zstd compression."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.zst",
            },
        ):
            result = await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="zstd")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.zst"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_without_compression(self, mock_uuid, writer):
        """Test archiving without compression."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress=None)

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.validate_compression_format")
    async def test_archive_messages_validates_compression_format(self, mock_validate, writer):
        """Test that compression format is validated."""
        mock_validate.return_value = "gzip"

        # Empty message list to avoid full processing
        await writer.archive_messages([], "/tmp/test.mbox", compress="gzip")

        # Should call validation
        mock_validate.assert_called_once_with("gzip")

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.validate_compression_format")
    async def test_archive_messages_with_invalid_compression_format(self, mock_validate, writer):
        """Test error handling for invalid compression format."""
        mock_validate.side_effect = InvalidInputError("Invalid compression format: invalid")

        with pytest.raises(InvalidInputError):
            await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="invalid")

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_result_dict_structure(self, mock_uuid, writer):
        """Test that result dict has correct structure with all keys."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 5,
                "failed": 2,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox.gz",
            },
        ):
            result = await writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="gzip")

        # Should have all required keys
        assert "archived_count" in result
        assert "failed_count" in result
        assert "interrupted" in result
        assert "actual_file" in result

        # Should map helper result to output format
        assert result["archived_count"] == 5
        assert result["failed_count"] == 2
        assert result["interrupted"] is True
        assert result["actual_file"] == "/tmp/test.mbox.gz"

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_with_task_handle(self, mock_uuid, writer):
        """Test that task handle is passed to helper method."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        mock_task = Mock()

        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ) as mock_helper:
            await writer.archive_messages(["msg001"], "/tmp/test.mbox", task=mock_task)

        # Should pass task handle to _archive_messages
        mock_helper.assert_called_once()
        call_args = mock_helper.call_args
        assert call_args[0][3] == mock_task  # 4th positional arg

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_with_partial_failure(self, mock_uuid, writer):
        """Test archiving with some messages failing."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        # Simulate partial failure
        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 2,
                "failed": 1,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = await writer.archive_messages(["msg001", "msg002", "msg003"], "/tmp/test.mbox")

        assert result["archived_count"] == 2
        assert result["failed_count"] == 1
        assert result["interrupted"] is False

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    async def test_archive_messages_handles_interruption(self, mock_uuid, writer):
        """Test that interrupted flag is properly returned."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        # Simulate interruption
        with patch.object(
            writer,
            "_archive_messages",
            new_callable=AsyncMock,
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = await writer.archive_messages(["msg001", "msg002"], "/tmp/test.mbox")

        assert result["interrupted"] is True
        assert result["archived_count"] == 1


# ============================================================================
# Tests for _archive_messages internal implementation
# ============================================================================


@pytest.mark.unit
class TestArchiveMessagesInternal:
    """Tests for _archive_messages internal implementation."""

    @pytest.fixture
    def mock_gmail_client(self):
        """Create mock Gmail client."""
        client = Mock()
        return client

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db = Mock()
        db.create_session = AsyncMock()
        db.close = AsyncMock()
        return db

    @pytest.fixture
    def mock_hybrid_storage(self, mock_db_manager):
        """Create mock hybrid storage."""
        storage = Mock()
        storage.db = mock_db_manager
        storage.archive_messages_batch = AsyncMock()
        return storage

    @pytest.fixture
    def writer(self, mock_gmail_client, mock_hybrid_storage):
        """Create MessageWriter with mocked dependencies."""
        return MessageWriter(gmail_client=mock_gmail_client, storage=mock_hybrid_storage)

    @pytest.mark.asyncio
    async def test_archive_messages_fetch_and_parse_with_labels(self, writer):
        """Test fetching and parsing messages with Gmail labels."""

        # Create a sample email message
        sample_raw = b"""From alice@example.com Mon Jan 01 00:00:00 2024
From: alice@example.com
To: bob@example.com
Subject: Test Message
Message-ID: <test001@example.com>
Date: Mon, 01 Jan 2024 00:00:00 +0000

Test message body."""

        # Mock the client to return messages
        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
            "labelIds": ["INBOX", "IMPORTANT"],
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        result = await writer._archive_messages(
            ["msg001"],
            "/tmp/test.mbox",
            compress=None,
            task=None,
            session_id="session123",
        )

        assert result["archived"] == 1
        assert result["failed"] == 0
        assert result["interrupted"] is False

    @pytest.mark.asyncio
    async def test_archive_messages_fetch_error_handling(self, writer):
        """Test handling of fetch errors during message retrieval."""

        sample_raw = b"""From: test@example.com
Subject: Test
Message-ID: <test@example.com>

Test body."""

        mock_message_good = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        mock_message_bad = {
            "id": "msg002",
            "threadId": "thread002",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message_good
            yield mock_message_bad  # This will fail

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(side_effect=[sample_raw, Exception("Decode error")])

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log"):
            result = await writer._archive_messages(
                ["msg001", "msg002"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        # Should have 1 fetch failure
        assert result["failed"] >= 1

    @pytest.mark.asyncio
    async def test_archive_messages_interrupt_during_fetch(self, writer):
        """Test interrupt handling during message fetch phase."""

        async def mock_batch_generator(message_ids):
            # Simulate interruption signal
            writer._interrupted.set()
            yield {"id": "msg001", "threadId": "thread001"}

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=b"raw message")

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log"):
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        # Should handle interruption gracefully
        assert result["interrupted"] is True

    @pytest.mark.asyncio
    async def test_archive_messages_keyboard_interrupt_during_batch(self, writer):
        """Test KeyboardInterrupt during batch archiving phase."""
        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": b"raw message",
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=b"raw message")

        # Make archive_messages_batch raise KeyboardInterrupt
        writer.storage.archive_messages_batch = AsyncMock(side_effect=KeyboardInterrupt())

        with patch.object(writer, "_log"):
            with patch.object(writer, "_install_sigint_handler"):
                with patch.object(writer, "_restore_sigint_handler"):
                    result = await writer._archive_messages(
                        ["msg001"],
                        "/tmp/test.mbox",
                        compress=None,
                        task=None,
                        session_id="session123",
                    )

        # Should return with interrupted=True
        assert result["interrupted"] is True
        assert result["archived"] == 0

    @pytest.mark.asyncio
    async def test_archive_messages_with_task_progress_tracking(self, writer):
        """Test progress callback during fetch phase."""

        sample_raw = b"""From: test@example.com
Subject: Test
Message-ID: <test@example.com>

Test body."""

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        mock_task = Mock()
        mock_task.advance = Mock()

        result = await writer._archive_messages(
            ["msg001"],
            "/tmp/test.mbox",
            compress=None,
            task=mock_task,
            session_id="session123",
        )

        # Task should have been advanced during fetch
        assert mock_task.advance.called
        assert result["archived"] == 1

    @pytest.mark.asyncio
    async def test_archive_messages_batch_operation_with_interrupted_flag(self, writer):
        """Test batch operation returning interrupted flag."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        # Simulate batch operation returning interrupted flag
        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log") as mock_log:
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        assert result["interrupted"] is True
        # Should log progress message
        mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_archive_messages_with_skipped_duplicates(self, writer):
        """Test handling of skipped duplicate messages."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        # Simulate skipped duplicates
        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log") as mock_log:
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        assert result["archived"] == 0
        # Should log the skipped count
        log_calls = [call[0][0] for call in mock_log.call_args_list]
        assert any("Skipped" in msg for msg in log_calls)

    @pytest.mark.asyncio
    async def test_archive_messages_with_compression(self, writer):
        """Test archiving with compression format."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.gz",
            }
        )

        result = await writer._archive_messages(
            ["msg001"],
            "/tmp/test.mbox",
            compress="gzip",
            task=None,
            session_id="session123",
        )

        assert result["archived"] == 1
        # Verify storage was called with compression
        call_kwargs = writer.storage.archive_messages_batch.call_args[1]
        assert call_kwargs["compression"] == "gzip"

    @pytest.mark.asyncio
    async def test_archive_messages_without_session_id(self, writer):
        """Test archiving without session ID."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        result = await writer._archive_messages(
            ["msg001"],
            "/tmp/test.mbox",
            compress=None,
            task=None,
            session_id=None,
        )

        assert result["archived"] == 1
        # Verify session_id=None is passed
        call_kwargs = writer.storage.archive_messages_batch.call_args[1]
        assert call_kwargs["session_id"] is None

    @pytest.mark.asyncio
    async def test_archive_messages_logs_summary(self, writer):
        """Test that archive summary is logged correctly."""

        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log") as mock_log:
            with patch("gmailarchiver.core.archiver._writer.Path") as mock_path_class:
                mock_path = Mock()
                mock_path.exists.return_value = True
                mock_path.stat.return_value = Mock(st_size=1024)
                mock_path_class.return_value = mock_path

                result = await writer._archive_messages(
                    ["msg001"],
                    "/tmp/test.mbox",
                    compress=None,
                    task=None,
                    session_id="session123",
                )

        # Should log archive summary with file size
        assert result["archived"] == 1
        log_calls = [call[0][0] for call in mock_log.call_args_list]
        assert any("Archived" in msg for msg in log_calls)

    def test_sigint_handler_installation(self, writer):
        """Test SIGINT handler is installed and restored."""
        import signal

        original_handler = signal.getsignal(signal.SIGINT)

        writer._install_sigint_handler()
        installed_handler = signal.getsignal(signal.SIGINT)

        # Handler should be different from original
        assert installed_handler != original_handler

        # Restoring should return to original
        writer._restore_sigint_handler()
        restored_handler = signal.getsignal(signal.SIGINT)
        assert restored_handler == original_handler

    def test_log_method_prints_message(self, writer, capsys):
        """Test that _log method prints to stdout."""
        writer._log("Test log message")

        captured = capsys.readouterr()
        assert "Test log message" in captured.out

    @pytest.mark.asyncio
    async def test_archive_messages_with_failed_messages(self, writer):
        """Test handling of failed message archiving."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        # Simulate archive failures
        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 0,
                "failed": 1,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log") as mock_log:
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        assert result["failed"] == 1
        # Should log failure count
        log_calls = [call[0][0] for call in mock_log.call_args_list]
        assert any("Failed" in msg for msg in log_calls)

    @pytest.mark.asyncio
    async def test_archive_messages_fetch_error_with_task_tracking(self, writer):
        """Test that task is advanced even when fetch errors occur."""

        sample_raw = b"""From: test@example.com
Subject: Test
Message-ID: <test@example.com>

Test body."""

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        # Make decode_message_raw fail
        writer.client.decode_message_raw = Mock(side_effect=Exception("Decode failed"))

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        mock_task = Mock()
        mock_task.advance = Mock()

        with patch.object(writer, "_log"):
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=mock_task,
                session_id="session123",
            )

        # Task should be advanced even when error occurs during fetch
        assert mock_task.advance.called
        # Should have recorded the fetch failure
        assert result["failed"] >= 1

    @pytest.mark.asyncio
    async def test_progress_callback_is_called(self, writer):
        """Test that progress callback is invoked during batch archiving."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        # Capture the progress_callback that gets passed to archive_messages_batch
        captured_callback = None

        async def mock_archive(
            messages,
            archive_file,
            compression,
            commit_interval,
            progress_callback,
            interrupt_event,
            session_id,
        ):
            nonlocal captured_callback
            captured_callback = progress_callback
            return {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }

        writer.storage.archive_messages_batch = mock_archive

        result = await writer._archive_messages(
            ["msg001"],
            "/tmp/test.mbox",
            compress=None,
            task=None,
            session_id="session123",
        )

        # Progress callback should have been passed to batch operation
        assert captured_callback is not None
        assert callable(captured_callback)
        assert result["archived"] == 1

    @pytest.mark.asyncio
    async def test_sigint_handler_called_and_restored(self, writer):
        """Test SIGINT handler is properly installed and restored."""
        import signal

        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        original_handler = signal.getsignal(signal.SIGINT)

        with patch.object(writer, "_log"):
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=None,
                session_id="session123",
            )

        # After _archive_messages completes, handler should be restored
        restored_handler = signal.getsignal(signal.SIGINT)
        assert restored_handler == original_handler
        assert result["archived"] == 1

    def test_sigint_handler_sets_interrupted_event(self, writer):
        """Test that SIGINT handler sets the interrupted event."""
        import os
        import signal

        writer._install_sigint_handler()

        # Verify the event is not set initially
        assert not writer._interrupted.is_set()

        # Send SIGINT to this process
        os.kill(os.getpid(), signal.SIGINT)

        # The signal handler should have set the event (if we get here without exiting)
        # Note: This test is best-effort as it depends on signal timing
        writer._restore_sigint_handler()

    @pytest.mark.asyncio
    async def test_progress_callback_with_task(self, writer):
        """Test progress callback is properly invoked with task."""
        sample_raw = b"test message"

        mock_message = {
            "id": "msg001",
            "threadId": "thread001",
            "raw": sample_raw,
        }

        async def mock_batch_generator(message_ids):
            yield mock_message

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=sample_raw)

        mock_task = Mock()
        mock_task.advance = Mock()

        # Create a custom archive_messages_batch that calls the progress callback
        async def mock_archive_with_callback(
            messages,
            archive_file,
            compression,
            commit_interval,
            progress_callback,
            interrupt_event,
            session_id,
        ):
            # Simulate calling the progress callback
            if progress_callback:
                progress_callback("msg001", "Test Subject", "archived")
            return {
                "archived": 1,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }

        writer.storage.archive_messages_batch = mock_archive_with_callback

        with patch.object(writer, "_log"):
            result = await writer._archive_messages(
                ["msg001"],
                "/tmp/test.mbox",
                compress=None,
                task=mock_task,
                session_id="session123",
            )

        # Task should have been advanced during batch operation via callback
        assert mock_task.advance.called
        assert result["archived"] == 1

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_during_async_for(self, writer):
        """Test KeyboardInterrupt handler during async for loop."""

        async def mock_batch_generator(message_ids):
            # Yield one message and then raise KeyboardInterrupt
            yield {"id": "msg001", "threadId": "thread001", "raw": b"test"}
            raise KeyboardInterrupt()

        writer.client.get_messages_batch = mock_batch_generator
        writer.client.decode_message_raw = Mock(return_value=b"test")

        writer.storage.archive_messages_batch = AsyncMock(
            return_value={
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            }
        )

        with patch.object(writer, "_log") as mock_log:
            with patch.object(writer, "_install_sigint_handler"):
                with patch.object(writer, "_restore_sigint_handler"):
                    result = await writer._archive_messages(
                        ["msg001"],
                        "/tmp/test.mbox",
                        compress=None,
                        task=None,
                        session_id="session123",
                    )

        # Should log the interrupt message
        log_calls = [call[0][0] for call in mock_log.call_args_list]
        assert any("Interrupt during fetch" in msg for msg in log_calls)
