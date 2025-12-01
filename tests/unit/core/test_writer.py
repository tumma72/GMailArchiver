"""Unit tests for MessageWriter (archiver package internal module).

This module contains fast, isolated unit tests with no I/O or external
dependencies. All external components (DBManager, HybridStorage, GmailClient)
are mocked.
"""

import uuid
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.archiver._writer import MessageWriter
from gmailarchiver.shared.input_validator import InvalidInputError


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
        db.create_session = Mock()
        db.close = Mock()
        return db

    @pytest.fixture
    def mock_hybrid_storage(self):
        """Create mock hybrid storage."""
        storage = Mock()
        return storage

    @pytest.fixture
    def writer(self, mock_gmail_client):
        """Create MessageWriter with mocked client."""
        return MessageWriter(gmail_client=mock_gmail_client, state_db_path="/tmp/test.db")

    @pytest.fixture
    def mock_archive_helper(self):
        """Mock _archive_messages helper method result."""
        return {
            "archived": 3,
            "failed": 0,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox",
        }

    @pytest.mark.unit
    def test_archive_messages_with_valid_message_ids(
        self, writer, mock_db_manager, mock_hybrid_storage, mock_archive_helper
    ):
        """Test archiving with valid message IDs (success path)."""
        message_ids = ["msg001", "msg002", "msg003"]
        output_file = "/tmp/archive.mbox"

        with patch("gmailarchiver.core.archiver._writer.DBManager", return_value=mock_db_manager):
            with patch(
                "gmailarchiver.core.archiver._writer.HybridStorage",
                return_value=mock_hybrid_storage,
            ):
                test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
                with patch(
                    "gmailarchiver.core.archiver._writer.uuid.uuid4", return_value=test_uuid
                ):
                    with patch.object(
                        writer, "_archive_messages", return_value=mock_archive_helper
                    ):
                        result = writer.archive_messages(message_ids, output_file)

        # Should return correct structure
        assert result["archived_count"] == 3
        assert result["failed_count"] == 0
        assert result["interrupted"] is False
        assert result["actual_file"] == "/tmp/archive.mbox"

        # Should create DBManager with correct parameters
        mock_db_manager_class = patch("gmailarchiver.core.archiver._writer.DBManager").start()
        # Cleanup
        patch.stopall()

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_creates_db_manager_correctly(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that DBManager is created with correct parameters."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            writer.archive_messages(["msg001"], "/tmp/test.mbox")

        # Should create DBManager with validate_schema=False and auto_create=True
        mock_db_class.assert_called_once_with(
            "/tmp/test.db", validate_schema=False, auto_create=True
        )

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_creates_hybrid_storage(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that HybridStorage is created with DBManager."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            writer.archive_messages(["msg001"], "/tmp/test.mbox")

        # Should create HybridStorage with DBManager instance
        mock_hybrid_class.assert_called_once_with(mock_db)

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_creates_session_with_uuid(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that session is created with UUID and correct parameters."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_uuid.return_value = test_uuid

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 2,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            writer.archive_messages(["msg001", "msg002"], "/tmp/test.mbox", compress="gzip")

        # Should create session with UUID
        mock_db.create_session.assert_called_once()
        call_kwargs = mock_db.create_session.call_args[1]
        assert call_kwargs["session_id"] == str(test_uuid)
        assert call_kwargs["target_file"] == "/tmp/test.mbox"
        assert "archive_messages(2 messages)" in call_kwargs["query"]
        assert call_kwargs["message_ids"] == ["msg001", "msg002"]
        assert call_kwargs["compression"] == "gzip"

    @pytest.mark.unit
    def test_archive_messages_with_empty_message_list(self, writer):
        """Test that empty message list returns zeros without processing."""
        result = writer.archive_messages([], "/tmp/archive.mbox")

        assert result["archived_count"] == 0
        assert result["failed_count"] == 0
        assert result["interrupted"] is False
        assert result["actual_file"] == "/tmp/archive.mbox"

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_with_gzip_compression(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test archiving with gzip compression."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.gz",
            },
        ):
            result = writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="gzip")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.gz"

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_with_lzma_compression(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test archiving with lzma compression."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.xz",
            },
        ):
            result = writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="lzma")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.xz"

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_with_zstd_compression(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test archiving with zstd compression."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox.zst",
            },
        ):
            result = writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="zstd")

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox.zst"

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_without_compression(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test archiving without compression."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = writer.archive_messages(["msg001"], "/tmp/test.mbox", compress=None)

        assert result["archived_count"] == 1
        assert result["actual_file"] == "/tmp/test.mbox"

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.validate_compression_format")
    def test_archive_messages_validates_compression_format(self, mock_validate, writer):
        """Test that compression format is validated."""
        mock_validate.return_value = "gzip"

        # Empty message list to avoid full processing
        writer.archive_messages([], "/tmp/test.mbox", compress="gzip")

        # Should call validation
        mock_validate.assert_called_once_with("gzip")

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.validate_compression_format")
    def test_archive_messages_with_invalid_compression_format(self, mock_validate, writer):
        """Test error handling for invalid compression format."""
        mock_validate.side_effect = InvalidInputError("Invalid compression format: invalid")

        with pytest.raises(InvalidInputError):
            writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="invalid")

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_cleanup_on_success(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that database is closed on successful archiving."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            writer.archive_messages(["msg001"], "/tmp/test.mbox")

        # Should close database
        mock_db.close.assert_called_once()

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_cleanup_on_error(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that database is closed even when error occurs."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        # Simulate error in _archive_messages
        with patch.object(writer, "_archive_messages", side_effect=Exception("Archive failed")):
            with pytest.raises(Exception, match="Archive failed"):
                writer.archive_messages(["msg001"], "/tmp/test.mbox")

        # Should still close database in exception handler
        mock_db.close.assert_called_once()

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_result_dict_structure(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that result dict has correct structure with all keys."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 5,
                "failed": 2,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox.gz",
            },
        ):
            result = writer.archive_messages(["msg001"], "/tmp/test.mbox", compress="gzip")

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

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_with_operation_handle(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that operation handle is passed to helper method."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        mock_operation = Mock()

        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ) as mock_helper:
            writer.archive_messages(["msg001"], "/tmp/test.mbox", operation=mock_operation)

        # Should pass operation handle to _archive_messages
        mock_helper.assert_called_once()
        call_args = mock_helper.call_args
        assert call_args[0][3] == mock_operation  # 4th positional arg

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_with_partial_failure(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test archiving with some messages failing."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        # Simulate partial failure
        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 2,
                "failed": 1,
                "interrupted": False,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = writer.archive_messages(["msg001", "msg002", "msg003"], "/tmp/test.mbox")

        assert result["archived_count"] == 2
        assert result["failed_count"] == 1
        assert result["interrupted"] is False

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver._writer.DBManager")
    @patch("gmailarchiver.core.archiver._writer.HybridStorage")
    @patch("gmailarchiver.core.archiver._writer.uuid.uuid4")
    def test_archive_messages_handles_interruption(
        self, mock_uuid, mock_hybrid_class, mock_db_class, writer
    ):
        """Test that interrupted flag is properly returned."""
        mock_db = Mock()
        mock_db.create_session = Mock()
        mock_db.close = Mock()
        mock_db_class.return_value = mock_db

        mock_storage = Mock()
        mock_hybrid_class.return_value = mock_storage

        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        # Simulate interruption
        with patch.object(
            writer,
            "_archive_messages",
            return_value={
                "archived": 1,
                "failed": 0,
                "interrupted": True,
                "actual_file": "/tmp/test.mbox",
            },
        ):
            result = writer.archive_messages(["msg001", "msg002"], "/tmp/test.mbox")

        assert result["interrupted"] is True
        assert result["archived_count"] == 1
