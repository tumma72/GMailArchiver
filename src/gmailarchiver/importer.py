"""Archive importer for Gmail Archiver v1.1.0.

Imports existing mbox files into v1.1 database with accurate byte offset tracking
for O(1) message access. Supports all compression formats (gzip, lzma, zstd).
"""

import email
import gzip
import hashlib
import lzma
import mailbox
import time
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from gmailarchiver.state import ArchiveState


@dataclass
class ImportResult:
    """Result of importing a single archive."""

    archive_file: str
    messages_imported: int
    messages_skipped: int
    messages_failed: int
    execution_time_ms: float
    errors: list[str] = field(default_factory=list)


@dataclass
class MultiImportResult:
    """Result of importing multiple archives."""

    total_files: int
    total_messages_imported: int
    total_messages_skipped: int
    total_messages_failed: int
    file_results: list[ImportResult] = field(default_factory=list)


class ArchiveImporter:
    """Import mbox archives into v1.1 database with offset tracking."""

    def __init__(self, state_db_path: str) -> None:
        """
        Initialize importer with database path.

        Args:
            state_db_path: Path to SQLite database file
        """
        self.state_db_path = state_db_path

    def _get_compression_format(self, archive_path: Path) -> str | None:
        """
        Detect compression format from file extension.

        Args:
            archive_path: Path to archive file

        Returns:
            Compression format: 'gzip', 'lzma', 'zstd', or None
        """
        suffix = archive_path.suffix.lower()
        if suffix == '.gz':
            return 'gzip'
        elif suffix in ('.xz', '.lzma'):
            return 'lzma'
        elif suffix == '.zst':
            return 'zstd'
        return None

    def _decompress_to_temp(self, archive_path: Path) -> tuple[Path, bool]:
        """
        Decompress archive to temporary file if needed.

        Args:
            archive_path: Path to archive file

        Returns:
            Tuple of (uncompressed_path, is_temporary)
        """
        compression = self._get_compression_format(archive_path)

        if compression is None:
            # Not compressed, use as-is
            return archive_path, False

        # Create temporary file for decompressed data
        temp = NamedTemporaryFile(mode='wb', delete=False, suffix='.mbox')
        temp_path = Path(temp.name)

        try:
            if compression == 'gzip':
                with gzip.open(archive_path, 'rb') as f_in:
                    temp.write(f_in.read())
            elif compression == 'lzma':
                with lzma.open(archive_path, 'rb') as f_in:
                    temp.write(f_in.read())
            elif compression == 'zstd':
                # Python 3.14+ has native zstd support
                import zstandard as zstd
                dctx = zstd.ZstdDecompressor()
                with open(archive_path, 'rb') as f_in:
                    with dctx.stream_reader(f_in) as reader:
                        temp.write(reader.read())

            temp.close()
            return temp_path, True

        except Exception as e:
            temp.close()
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"Failed to decompress {archive_path}: {e}") from e

    def _extract_rfc_message_id(self, msg: email.message.Message) -> str:
        """
        Extract RFC 2822 Message-ID from email message.

        Args:
            msg: Email message

        Returns:
            Message-ID header value (or generated fallback)
        """
        message_id = msg.get('Message-ID', '').strip()
        if not message_id:
            # Generate fallback Message-ID from Subject + Date
            subject = msg.get('Subject', 'no-subject')
            date = msg.get('Date', 'no-date')
            fallback_id = f"<{hashlib.sha256(f'{subject}{date}'.encode()).hexdigest()}@generated>"
            return fallback_id
        return message_id

    def _extract_body_preview(self, msg: email.message.Message, max_chars: int = 1000) -> str:
        """
        Extract body preview from email message.

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
                            body = payload.decode('utf-8', errors='ignore')
                            break
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body = payload.decode('utf-8', errors='ignore')
            except Exception:
                pass

        return body[:max_chars]

    def _extract_thread_id(self, msg: email.message.Message) -> str | None:
        """
        Extract thread ID from email headers.

        Args:
            msg: Email message

        Returns:
            Thread ID or None
        """
        # Try X-GM-THRID header first (Gmail-specific)
        thread_id = msg.get('X-GM-THRID', '').strip()
        if thread_id:
            return thread_id

        # Fallback to References header
        references = msg.get('References', '').strip()
        if references:
            # Use first reference as thread ID
            refs = references.split()
            return refs[0] if refs else None

        return None

    def _extract_metadata(
        self,
        msg: email.message.Message,
        archive_path: str,
        offset: int,
        length: int,
        account_id: str
    ) -> dict[str, Any]:
        """
        Extract all v1.1 metadata from email message.

        Args:
            msg: Email message
            archive_path: Path to archive file
            offset: Byte offset in mbox
            length: Message length in bytes
            account_id: Account identifier

        Returns:
            Dictionary of metadata fields
        """
        message_bytes = msg.as_bytes()
        rfc_message_id = self._extract_rfc_message_id(msg)

        # Generate gmail_id as hash of Message-ID + Date
        gmail_id = hashlib.sha256(
            f"{rfc_message_id}{msg.get('Date', '')}".encode()
        ).hexdigest()[:16]

        return {
            'gmail_id': gmail_id,
            'rfc_message_id': rfc_message_id,
            'thread_id': self._extract_thread_id(msg),
            'subject': msg.get('Subject'),
            'from_addr': msg.get('From'),
            'to_addr': msg.get('To'),
            'cc_addr': msg.get('Cc'),
            'message_date': msg.get('Date'),
            'archive_file': archive_path,
            'mbox_offset': offset,
            'mbox_length': length,
            'body_preview': self._extract_body_preview(msg),
            'checksum': hashlib.sha256(message_bytes).hexdigest(),
            'size_bytes': len(message_bytes),
            'labels': None,
            'account_id': account_id
        }

    def import_archive(
        self,
        archive_path: str | Path,
        account_id: str = 'default',
        skip_duplicates: bool = True
    ) -> ImportResult:
        """
        Import single mbox archive into database.

        Parses mbox file, extracts metadata, calculates byte offsets,
        and populates v1.1 database with all required fields.

        Args:
            archive_path: Path to mbox archive file
            account_id: Account identifier (default: 'default')
            skip_duplicates: Skip messages that already exist (default: True)

        Returns:
            ImportResult with statistics and errors

        Raises:
            FileNotFoundError: If archive file doesn't exist
            RuntimeError: If decompression fails
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        result = ImportResult(
            archive_file=str(archive_path),
            messages_imported=0,
            messages_skipped=0,
            messages_failed=0,
            execution_time_ms=0.0,
            errors=[]
        )

        start_time = time.time()

        # Decompress if needed
        mbox_path, is_temp = self._decompress_to_temp(archive_path)

        try:
            # Open mbox file
            mbox = mailbox.mbox(str(mbox_path))

            with ArchiveState(self.state_db_path, validate_path=False) as state:
                # Get existing RFC Message-IDs if skip_duplicates
                existing_ids = set()
                if skip_duplicates:
                    try:
                        cursor = state.conn.execute(
                            "SELECT rfc_message_id FROM messages"
                        )
                        existing_ids = {row[0] for row in cursor.fetchall()}
                    except Exception:
                        # Table might not exist yet, continue
                        pass

                # Also track IDs seen in this import session (for intra-file duplicates)
                session_ids = set()

                # Process each message with offset tracking
                for key in mbox.keys():
                    try:
                        # Get file position from mbox library
                        # The _toc dict maps key to (offset, length) tuple
                        # _toc is private but needed for offset calculation
                        offset: int = mbox._toc[key][0]  # type: ignore[attr-defined]

                        # Read message
                        msg = mbox[key]

                        # Extract RFC Message-ID
                        rfc_message_id = self._extract_rfc_message_id(msg)

                        # Skip duplicates (check both DB and this session)
                        if skip_duplicates and (
                            rfc_message_id in existing_ids or rfc_message_id in session_ids
                        ):
                            result.messages_skipped += 1
                            continue

                        # Calculate next message position to determine length
                        keys_list = list(mbox.keys())
                        key_index = keys_list.index(key)

                        if key_index < len(keys_list) - 1:
                            # Not the last message - length is distance to next message
                            next_key = keys_list[key_index + 1]
                            next_offset = mbox._toc[next_key][0]  # type: ignore[attr-defined]
                            length = next_offset - offset
                        else:
                            # Last message - length is to end of file
                            file_size = mbox_path.stat().st_size
                            length = file_size - offset

                        # Extract all metadata
                        metadata = self._extract_metadata(
                            msg,
                            str(archive_path),  # Store original path (compressed if applicable)
                            offset,
                            length,
                            account_id
                        )

                        # Insert into database (may fail on unique constraint)
                        try:
                            state.mark_archived(**metadata)
                            session_ids.add(rfc_message_id)  # Add to session set
                            result.messages_imported += 1
                        except Exception as db_err:
                            # Database constraint violation (e.g., unique constraint)
                            result.messages_failed += 1
                            error_msg = f"Message {key}: Database error: {str(db_err)}"
                            result.errors.append(error_msg)
                            continue

                    except Exception as e:
                        result.messages_failed += 1
                        error_msg = f"Message {key}: {str(e)}"
                        result.errors.append(error_msg)
                        continue

        finally:
            # Clean up temporary file if created
            if is_temp and mbox_path.exists():
                mbox_path.unlink()

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def import_multiple(
        self,
        pattern: str,
        account_id: str = 'default',
        skip_duplicates: bool = True
    ) -> MultiImportResult:
        """
        Import multiple archives using glob pattern.

        Args:
            pattern: Glob pattern for archive files (e.g., "archives/*.mbox")
            account_id: Account identifier (default: 'default')
            skip_duplicates: Skip messages that already exist (default: True)

        Returns:
            MultiImportResult with aggregate statistics
        """
        files = glob(pattern)

        result = MultiImportResult(
            total_files=len(files),
            total_messages_imported=0,
            total_messages_skipped=0,
            total_messages_failed=0,
            file_results=[]
        )

        for file_path in files:
            try:
                file_result = self.import_archive(
                    file_path,
                    account_id=account_id,
                    skip_duplicates=skip_duplicates
                )

                result.file_results.append(file_result)
                result.total_messages_imported += file_result.messages_imported
                result.total_messages_skipped += file_result.messages_skipped
                result.total_messages_failed += file_result.messages_failed

            except Exception as e:
                # Record failure for this file
                file_result = ImportResult(
                    archive_file=file_path,
                    messages_imported=0,
                    messages_skipped=0,
                    messages_failed=0,
                    execution_time_ms=0.0,
                    errors=[f"Failed to import: {str(e)}"]
                )
                result.file_results.append(file_result)

        return result
