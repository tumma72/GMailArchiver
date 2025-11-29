"""Unit tests for importer MboxReader module.

Tests mbox reading, message parsing, and metadata extraction.
All tests use mocks - no actual file I/O.
"""

import email
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.importer._reader import MboxReader, MessageMetadata


@pytest.mark.unit
class TestMboxReaderInit:
    """Tests for MboxReader initialization."""

    def test_init(self) -> None:
        """Test initialization."""
        reader = MboxReader()
        assert reader is not None


@pytest.mark.unit
class TestMboxReaderCountMessages:
    """Tests for message counting."""

    @patch("gmailarchiver.core.importer._reader.mailbox.mbox")
    def test_count_messages_success(self, mock_mbox_class: Mock) -> None:
        """Test counting messages in mbox file."""
        mock_mbox = Mock()
        mock_mbox.__len__ = Mock(return_value=42)
        mock_mbox_class.return_value = mock_mbox

        reader = MboxReader()
        count = reader.count_messages(Path("/tmp/test.mbox"))

        assert count == 42
        mock_mbox.close.assert_called_once()

    @patch("gmailarchiver.core.importer._reader.mailbox.mbox")
    def test_count_messages_empty(self, mock_mbox_class: Mock) -> None:
        """Test counting messages in empty mbox."""
        mock_mbox = Mock()
        mock_mbox.__len__ = Mock(return_value=0)
        mock_mbox_class.return_value = mock_mbox

        reader = MboxReader()
        count = reader.count_messages(Path("/tmp/empty.mbox"))

        assert count == 0


@pytest.mark.unit
class TestMboxReaderExtractRfcMessageId:
    """Tests for RFC Message-ID extraction."""

    def test_extract_rfc_message_id_present(self) -> None:
        """Test extracting existing Message-ID."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test123@example.com>"

        reader = MboxReader()
        message_id = reader.extract_rfc_message_id(msg)

        assert message_id == "<test123@example.com>"

    def test_extract_rfc_message_id_missing_generates_fallback(self) -> None:
        """Test generating fallback Message-ID when missing."""
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test Subject"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"

        reader = MboxReader()
        message_id = reader.extract_rfc_message_id(msg)

        # Should generate a fallback based on subject + date
        assert message_id.startswith("<")
        assert message_id.endswith("@generated>")
        assert "@generated>" in message_id

    def test_extract_rfc_message_id_whitespace_trimmed(self) -> None:
        """Test that whitespace is trimmed from Message-ID."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "  <test123@example.com>  "

        reader = MboxReader()
        message_id = reader.extract_rfc_message_id(msg)

        assert message_id == "<test123@example.com>"


@pytest.mark.unit
class TestMboxReaderExtractThreadId:
    """Tests for thread ID extraction."""

    def test_extract_thread_id_gmail_header(self) -> None:
        """Test extracting thread ID from X-GM-THRID header."""
        msg = email.message.EmailMessage()
        msg["X-GM-THRID"] = "thread123"

        reader = MboxReader()
        thread_id = reader.extract_thread_id(msg)

        assert thread_id == "thread123"

    def test_extract_thread_id_references_fallback(self) -> None:
        """Test extracting thread ID from References header when Gmail header missing."""
        msg = email.message.EmailMessage()
        msg["References"] = "<ref1@example.com> <ref2@example.com>"

        reader = MboxReader()
        thread_id = reader.extract_thread_id(msg)

        assert thread_id == "<ref1@example.com>"

    def test_extract_thread_id_missing(self) -> None:
        """Test thread ID extraction when no headers present."""
        msg = email.message.EmailMessage()

        reader = MboxReader()
        thread_id = reader.extract_thread_id(msg)

        assert thread_id is None


@pytest.mark.unit
class TestMboxReaderExtractBodyPreview:
    """Tests for body preview extraction."""

    def test_extract_body_preview_plain_text(self) -> None:
        """Test extracting preview from plain text message."""
        msg = email.message.EmailMessage()
        msg.set_content("This is the email body content.")

        reader = MboxReader()
        preview = reader.extract_body_preview(msg, max_chars=1000)

        assert "This is the email body content" in preview

    def test_extract_body_preview_truncated(self) -> None:
        """Test that preview is truncated to max_chars."""
        long_text = "A" * 2000
        msg = email.message.EmailMessage()
        msg.set_content(long_text)

        reader = MboxReader()
        preview = reader.extract_body_preview(msg, max_chars=100)

        assert len(preview) == 100
        assert preview == "A" * 100

    def test_extract_body_preview_multipart(self) -> None:
        """Test extracting preview from multipart message."""
        msg = email.message.EmailMessage()
        msg.make_mixed()
        text_part = email.message.EmailMessage()
        text_part.set_content("Plain text body")
        msg.attach(text_part)

        reader = MboxReader()
        preview = reader.extract_body_preview(msg, max_chars=1000)

        assert "Plain text body" in preview

    def test_extract_body_preview_empty(self) -> None:
        """Test extracting preview from message with no body."""
        msg = email.message.EmailMessage()

        reader = MboxReader()
        preview = reader.extract_body_preview(msg, max_chars=1000)

        assert preview == ""


@pytest.mark.unit
class TestMboxReaderExtractMetadata:
    """Tests for complete metadata extraction."""

    def test_extract_metadata_complete(self) -> None:
        """Test extracting complete metadata from message."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test123@example.com>"
        msg["Subject"] = "Test Subject"
        msg["From"] = "sender@example.com"
        msg["To"] = "receiver@example.com"
        msg["Cc"] = "cc@example.com"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg["X-GM-THRID"] = "thread123"
        msg.set_content("Email body")

        reader = MboxReader()
        metadata = reader.extract_metadata(
            msg=msg,
            archive_path="/tmp/archive.mbox",
            offset=1024,
            length=2048,
            account_id="test_account",
            gmail_id="gmail123",
        )

        assert isinstance(metadata, MessageMetadata)
        assert metadata.gmail_id == "gmail123"
        assert metadata.rfc_message_id == "<test123@example.com>"
        assert metadata.thread_id == "thread123"
        assert metadata.subject == "Test Subject"
        assert metadata.from_addr == "sender@example.com"
        assert metadata.to_addr == "receiver@example.com"
        assert metadata.cc_addr == "cc@example.com"
        assert metadata.date == "Mon, 01 Jan 2024 12:00:00 +0000"
        assert metadata.archive_file == "/tmp/archive.mbox"
        assert metadata.mbox_offset == 1024
        assert metadata.mbox_length == 2048
        assert metadata.account_id == "test_account"
        assert len(metadata.checksum) == 64  # SHA256 hex
        assert metadata.size_bytes > 0

    def test_extract_metadata_without_gmail_id(self) -> None:
        """Test extracting metadata without Gmail ID (deleted messages)."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test123@example.com>"
        msg["Subject"] = "Test Subject"
        msg.set_content("Body")

        reader = MboxReader()
        metadata = reader.extract_metadata(
            msg=msg,
            archive_path="/tmp/archive.mbox",
            offset=0,
            length=100,
            account_id="default",
            gmail_id=None,
        )

        assert metadata.gmail_id is None
        assert metadata.rfc_message_id == "<test123@example.com>"

    def test_extract_metadata_checksum_consistent(self) -> None:
        """Test that checksum is consistent for same message."""
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"
        msg.set_content("Body")

        reader = MboxReader()
        metadata1 = reader.extract_metadata(msg, "/tmp/test.mbox", 0, 100, "default", None)
        metadata2 = reader.extract_metadata(msg, "/tmp/test.mbox", 0, 100, "default", None)

        assert metadata1.checksum == metadata2.checksum


@pytest.mark.unit
class TestMboxReaderReadMessages:
    """Tests for reading messages from mbox with offsets."""

    @patch("gmailarchiver.core.importer._reader.mailbox.mbox")
    def test_read_messages_with_offsets(self, mock_mbox_class: Mock) -> None:
        """Test reading messages and calculating offsets."""
        # Create mock messages
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1.set_content("Message 1")

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2.set_content("Message 2")

        # Setup mock mbox
        mock_mbox = Mock()
        mock_mbox.keys.return_value = ["key1", "key2"]
        mock_mbox._toc = {"key1": (0, 100), "key2": (100, 150)}
        mock_mbox.__getitem__ = Mock(side_effect=lambda k: msg1 if k == "key1" else msg2)
        mock_mbox_class.return_value = mock_mbox

        # Mock Path.stat() for file size
        with patch("gmailarchiver.core.importer._reader.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 250

            reader = MboxReader()
            messages = list(reader.read_messages(Path("/tmp/test.mbox"), "/tmp/test.mbox"))

        assert len(messages) == 2

        # First message
        assert messages[0].offset == 0
        assert messages[0].length == 100  # Distance to next message
        assert messages[0].message["Message-ID"] == "<msg1@example.com>"

        # Second message (last in file)
        assert messages[1].offset == 100
        assert messages[1].length == 150  # To end of file
        assert messages[1].message["Message-ID"] == "<msg2@example.com>"

        mock_mbox.close.assert_called_once()

    @patch("gmailarchiver.core.importer._reader.mailbox.mbox")
    def test_read_messages_empty_mbox(self, mock_mbox_class: Mock) -> None:
        """Test reading from empty mbox."""
        mock_mbox = Mock()
        mock_mbox.keys.return_value = []
        mock_mbox_class.return_value = mock_mbox

        reader = MboxReader()
        messages = list(reader.read_messages(Path("/tmp/empty.mbox"), "/tmp/empty.mbox"))

        assert len(messages) == 0
        mock_mbox.close.assert_called_once()
