"""Message extraction facade for Gmail Archiver."""

from pathlib import Path
from typing import Any, TypedDict

from gmailarchiver.core.extractor._extractor import ExtractorError, MessageExtractorCore
from gmailarchiver.core.extractor._locator import MessageLocator
from gmailarchiver.data.db_manager import DBManager


class ExtractStats(TypedDict):
    """Statistics from batch extraction."""

    extracted: int
    failed: int
    errors: list[str]


class MessageExtractor:
    """Extract messages from mbox archives using database offsets."""

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize extractor with database manager.

        Args:
            db_manager: Database manager for message lookups
        """
        self.db_manager = db_manager
        self.locator = MessageLocator(self.db_manager)

    async def extract_by_gmail_id(
        self, gmail_id: str, output_path: str | Path | None = None
    ) -> bytes:
        """Extract message by Gmail ID.

        Args:
            gmail_id: Gmail message ID
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If message not found or extraction fails
        """
        # Get message location from database
        location = await self.locator.locate_by_gmail_id(gmail_id)
        if not location:
            raise ExtractorError(f"Message not found in database: {gmail_id}")

        return MessageExtractorCore.extract_from_archive(
            location["archive_file"],
            location["mbox_offset"],
            location["mbox_length"],
            output_path,
        )

    async def extract_by_rfc_message_id(
        self, rfc_message_id: str, output_path: str | Path | None = None
    ) -> bytes:
        """Extract message by RFC 2822 Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header value
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If message not found or extraction fails
        """
        # Get message location from database
        location = await self.locator.locate_by_rfc_message_id(rfc_message_id)
        if not location:
            raise ExtractorError(f"Message not found in database: {rfc_message_id}")

        return MessageExtractorCore.extract_from_archive(
            location["archive_file"],
            location["mbox_offset"],
            location["mbox_length"],
            output_path,
        )

    async def batch_extract(self, gmail_ids: list[str], output_dir: Path) -> ExtractStats:
        """Extract multiple messages to directory.

        Args:
            gmail_ids: List of Gmail message IDs
            output_dir: Output directory

        Returns:
            Dictionary with extraction stats
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stats: ExtractStats = {"extracted": 0, "failed": 0, "errors": []}

        for gmail_id in gmail_ids:
            try:
                # Generate output filename
                output_file = output_dir / f"{gmail_id}.eml"

                # Extract message
                await self.extract_by_gmail_id(gmail_id, output_file)
                stats["extracted"] += 1

            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{gmail_id}: {e}")

        return stats

    async def close(self) -> None:
        """Close database connection."""
        await self.db_manager.close()

    async def __aenter__(self) -> MessageExtractor:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    # Delegation methods for private methods used by tests
    def _get_compression_format(self, archive_path: Path) -> str | None:
        """Detect compression format from file extension (test compatibility)."""
        return MessageExtractorCore._get_compression_format(archive_path)

    def _extract_from_compressed(
        self, archive_path: Path, compression: str, offset: int, length: int
    ) -> bytes:
        """Extract from compressed archive (test compatibility)."""
        return MessageExtractorCore._extract_from_compressed(
            archive_path, compression, offset, length
        )
