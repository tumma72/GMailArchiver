"""Internal module for mbox reading and message parsing.

This module handles mbox file reading, message offset calculation, and
metadata extraction. Part of importer package's internal implementation.
"""

import email
import hashlib
import mailbox
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MessageMetadata:
    """Metadata extracted from an email message."""

    gmail_id: str | None
    rfc_message_id: str
    thread_id: str | None
    subject: str | None
    from_addr: str | None
    to_addr: str | None
    cc_addr: str | None
    date: str | None
    archive_file: str
    mbox_offset: int
    mbox_length: int
    body_preview: str
    checksum: str
    size_bytes: int
    account_id: str

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary for database insertion.

        Returns:
            Dictionary matching DBManager.record_archived_message signature
        """
        return {
            "gmail_id": self.gmail_id,
            "rfc_message_id": self.rfc_message_id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "cc_addr": self.cc_addr,
            "date": self.date,
            "archive_file": self.archive_file,
            "mbox_offset": self.mbox_offset,
            "mbox_length": self.mbox_length,
            "body_preview": self.body_preview,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "labels": None,
            "account_id": self.account_id,
        }


@dataclass
class MboxMessage:
    """Message read from mbox with offset information."""

    message: email.message.Message
    offset: int
    length: int


class MboxReader:
    """Internal helper for mbox reading and message parsing.

    Handles mbox file reading with offset tracking and metadata extraction.
    This is an internal implementation detail - use ImporterFacade for public API.
    """

    def count_messages(self, mbox_path: Path) -> int:
        """Count messages in mbox file without reading them.

        Args:
            mbox_path: Path to mbox file

        Returns:
            Number of messages in the mbox
        """
        mbox = mailbox.mbox(str(mbox_path))
        try:
            return len(mbox)
        finally:
            mbox.close()

    def scan_rfc_message_ids(
        self, mbox_path: Path, progress_callback: Callable[[int, int], None] | None = None
    ) -> list[tuple[str, int, int]]:
        """Scan mbox and extract RFC Message-IDs with offsets (fast scan).

        This is a lightweight scan that only extracts Message-IDs without
        full metadata extraction. Used for duplicate detection before import.

        Args:
            mbox_path: Path to mbox file
            progress_callback: Optional callback(current, total) for progress

        Returns:
            List of (rfc_message_id, offset, length) tuples
        """
        mbox = mailbox.mbox(str(mbox_path))
        result: list[tuple[str, int, int]] = []

        try:
            all_keys = list(mbox.keys())
            total_messages = len(all_keys)
            file_size = mbox_path.stat().st_size

            for msg_index, key in enumerate(all_keys):
                # Get offset from mbox's internal table of contents
                offset: int = mbox._toc[key][0]  # type: ignore[attr-defined]

                # Calculate message length
                if msg_index < total_messages - 1:
                    next_key = all_keys[msg_index + 1]
                    next_offset = mbox._toc[next_key][0]  # type: ignore[attr-defined]
                    length = next_offset - offset
                else:
                    length = file_size - offset

                # Read message and extract Message-ID
                msg = mbox[key]
                rfc_message_id = self.extract_rfc_message_id(msg)
                result.append((rfc_message_id, offset, length))

                if progress_callback:
                    progress_callback(msg_index + 1, total_messages)

        finally:
            mbox.close()

        return result

    def extract_rfc_message_id(self, msg: email.message.Message) -> str:
        """Extract RFC 2822 Message-ID from email message.

        Args:
            msg: Email message

        Returns:
            Message-ID header value (or generated fallback)
        """
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            # Generate fallback Message-ID from Subject + Date
            subject = msg.get("Subject", "no-subject")
            date = msg.get("Date", "no-date")
            fallback_id = f"<{hashlib.sha256(f'{subject}{date}'.encode()).hexdigest()}@generated>"
            return fallback_id
        return message_id

    def extract_thread_id(self, msg: email.message.Message) -> str | None:
        """Extract thread ID from email headers.

        Args:
            msg: Email message

        Returns:
            Thread ID or None
        """
        # Try X-GM-THRID header first (Gmail-specific)
        thread_id = msg.get("X-GM-THRID", "").strip()
        if thread_id:
            return thread_id

        # Fallback to References header
        references = msg.get("References", "").strip()
        if references:
            # Use first reference as thread ID
            refs = references.split()
            return refs[0] if refs else None

        return None

    def extract_body_preview(self, msg: email.message.Message, max_chars: int = 1000) -> str:
        """Extract body preview from email message.

        Args:
            msg: Email message
            max_chars: Maximum characters to extract

        Returns:
            Plain text preview
        """
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload and isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")
                            break
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body = payload.decode("utf-8", errors="ignore")
            except Exception:
                pass

        return body[:max_chars]

    def extract_metadata(
        self,
        msg: email.message.Message,
        archive_path: str,
        offset: int,
        length: int,
        account_id: str,
        gmail_id: str | None = None,
    ) -> MessageMetadata:
        """Extract all metadata from email message.

        Args:
            msg: Email message
            archive_path: Path to archive file
            offset: Byte offset in mbox
            length: Message length in bytes
            account_id: Account identifier
            gmail_id: Real Gmail ID if known (from API lookup), or None

        Returns:
            MessageMetadata instance with all extracted fields
        """
        message_bytes = msg.as_bytes()
        rfc_message_id = self.extract_rfc_message_id(msg)

        return MessageMetadata(
            gmail_id=gmail_id,
            rfc_message_id=rfc_message_id,
            thread_id=self.extract_thread_id(msg),
            subject=msg.get("Subject"),
            from_addr=msg.get("From"),
            to_addr=msg.get("To"),
            cc_addr=msg.get("Cc"),
            date=msg.get("Date"),
            archive_file=archive_path,
            mbox_offset=offset,
            mbox_length=length,
            body_preview=self.extract_body_preview(msg),
            checksum=hashlib.sha256(message_bytes).hexdigest(),
            size_bytes=len(message_bytes),
            account_id=account_id,
        )

    def read_messages(self, mbox_path: Path, archive_path: str) -> Iterator[MboxMessage]:
        """Read messages from mbox file with offset tracking.

        Args:
            mbox_path: Path to mbox file (may be decompressed temp file)
            archive_path: Original archive path for metadata

        Yields:
            MboxMessage instances with message and offset information
        """
        mbox = mailbox.mbox(str(mbox_path))

        try:
            all_keys = list(mbox.keys())
            total_messages = len(all_keys)

            for msg_index, key in enumerate(all_keys):
                # Get file position from mbox library
                # The _toc dict maps key to (offset, length) tuple
                offset: int = mbox._toc[key][0]  # type: ignore[attr-defined]

                # Read message
                msg = mbox[key]

                # Calculate message length
                if msg_index < total_messages - 1:
                    # Not the last message - length is distance to next message
                    next_key = all_keys[msg_index + 1]
                    next_offset = mbox._toc[next_key][0]  # type: ignore[attr-defined]
                    length = next_offset - offset
                else:
                    # Last message - length is to end of file
                    file_size = mbox_path.stat().st_size
                    length = file_size - offset

                yield MboxMessage(message=msg, offset=offset, length=length)

        finally:
            mbox.close()
