"""Message extraction for Gmail Archiver v1.2.0.

Extracts full messages from mbox archives using database offsets for O(1) access.
Supports all compression formats (gzip, lzma, zstd) with transparent decompression.
"""

import gzip
import lzma
import sys
from io import IOBase
from pathlib import Path
from typing import Any, TypedDict

from gmailarchiver.db_manager import DBManager


class ExtractStats(TypedDict):
    """Statistics from batch extraction."""

    extracted: int
    failed: int
    errors: list[str]


class ExtractorError(Exception):
    """Raised when extraction fails."""

    pass


class MessageExtractor:
    """Extract messages from mbox archives using database offsets."""

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize extractor with database path.

        Args:
            db_path: Path to SQLite database file

        Raises:
            FileNotFoundError: If database doesn't exist
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        self.db = DBManager(str(db_path))

    def extract_by_gmail_id(self, gmail_id: str, output_path: str | Path | None = None) -> bytes:
        """
        Extract message by Gmail ID.

        Args:
            gmail_id: Gmail message ID
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If message not found or extraction fails
        """
        # Get message location from database by gmail_id
        location = self.db.get_message_location_by_gmail_id(gmail_id)
        if not location:
            raise ExtractorError(f"Message not found in database: {gmail_id}")

        archive_file, mbox_offset, mbox_length = location
        return self._extract_from_archive(archive_file, mbox_offset, mbox_length, output_path)

    def extract_by_rfc_message_id(
        self, rfc_message_id: str, output_path: str | Path | None = None
    ) -> bytes:
        """
        Extract message by RFC 2822 Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header value
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If message not found or extraction fails
        """
        # Get message metadata from database
        message = self.db.get_message_by_rfc_message_id(rfc_message_id)
        if not message:
            raise ExtractorError(f"Message not found in database: {rfc_message_id}")

        archive_file = message["archive_file"]
        mbox_offset = message["mbox_offset"]
        mbox_length = message["mbox_length"]

        return self._extract_from_archive(archive_file, mbox_offset, mbox_length, output_path)

    def batch_extract(self, gmail_ids: list[str], output_dir: Path) -> ExtractStats:
        """
        Extract multiple messages to directory.

        Args:
            gmail_ids: List of Gmail message IDs
            output_dir: Output directory

        Returns:
            Dictionary with extraction stats:
            {
                'extracted': int,
                'failed': int,
                'errors': list[str]
            }
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stats: ExtractStats = {"extracted": 0, "failed": 0, "errors": []}

        for gmail_id in gmail_ids:
            try:
                # Generate output filename
                output_file = output_dir / f"{gmail_id}.eml"

                # Extract message
                self.extract_by_gmail_id(gmail_id, output_file)
                stats["extracted"] += 1

            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{gmail_id}: {e}")

        return stats

    def _extract_from_archive(
        self,
        archive_file: str,
        mbox_offset: int,
        mbox_length: int,
        output_path: str | Path | None = None,
    ) -> bytes:
        """
        Extract message from archive at specified offset.

        Args:
            archive_file: Path to archive file
            mbox_offset: Byte offset in archive
            mbox_length: Message length in bytes
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If extraction fails
        """
        archive_path = Path(archive_file)
        if not archive_path.exists():
            raise ExtractorError(f"Archive file not found: {archive_file}")

        # Detect compression format
        compression = self._get_compression_format(archive_path)

        try:
            if compression:
                # Decompress and extract
                message_bytes = self._extract_from_compressed(
                    archive_path, compression, mbox_offset, mbox_length
                )
            else:
                # Extract directly from uncompressed mbox
                with open(archive_path, "rb") as f:
                    f.seek(mbox_offset)
                    message_bytes = f.read(mbox_length)

            # Output to file or stdout
            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(message_bytes)
            else:
                # Write to stdout
                sys.stdout.buffer.write(message_bytes)

            return message_bytes

        except Exception as e:
            raise ExtractorError(f"Failed to extract message: {e}") from e

    def _extract_from_compressed(
        self, archive_path: Path, compression: str, offset: int, length: int
    ) -> bytes:
        """
        Extract message from compressed archive.

        For compressed archives, we need to decompress the entire file
        (or up to the offset + length) to access the message at the offset.

        Args:
            archive_path: Path to compressed archive
            compression: Compression format ('gzip', 'lzma', 'zstd')
            offset: Byte offset in decompressed data
            length: Message length in bytes

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If extraction fails
        """
        try:
            # Open compressed file
            f: IOBase
            if compression == "gzip":
                f = gzip.open(archive_path, "rb")
            elif compression == "lzma":
                f = lzma.open(archive_path, "rb")
            elif compression == "zstd":
                # Python 3.14+ has native zstd support
                try:
                    from compression import zstd

                    f = zstd.open(archive_path, "rb")
                except ImportError:
                    raise ExtractorError(
                        "zstd compression requires Python 3.14+ or 'zstandard' package"
                    )
            else:
                raise ExtractorError(f"Unsupported compression format: {compression}")

            # Seek to offset and read message
            with f:
                f.seek(offset)
                message_bytes = f.read(length)

            return message_bytes

        except Exception as e:
            raise ExtractorError(f"Failed to extract from compressed archive: {e}") from e

    def _get_compression_format(self, archive_path: Path) -> str | None:
        """
        Detect compression format from file extension.

        Args:
            archive_path: Path to archive file

        Returns:
            Compression format: 'gzip', 'lzma', 'zstd', or None
        """
        suffix = archive_path.suffix.lower()
        if suffix == ".gz":
            return "gzip"
        elif suffix in (".xz", ".lzma"):
            return "lzma"
        elif suffix == ".zst":
            return "zstd"
        return None

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    def __enter__(self) -> MessageExtractor:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
