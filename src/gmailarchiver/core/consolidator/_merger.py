"""Message merging operations for consolidation."""

from pathlib import Path
from typing import Any

from gmailarchiver.data.hybrid_storage import HybridStorage


class MessageMerger:
    """Read and merge messages from multiple archives."""

    def __init__(self, storage: HybridStorage) -> None:
        """Initialize merger with storage backend.

        Args:
            storage: HybridStorage instance for atomic operations
        """
        self.storage = storage

    async def merge_archives(self, source_paths: list[Path]) -> list[dict[str, Any]]:
        """Read and merge messages from multiple archives.

        Args:
            source_paths: List of source archive paths

        Returns:
            List of message dictionaries

        Raises:
            FileNotFoundError: If any source archive doesn't exist
        """
        # Verify all files exist before reading
        for source_path in source_paths:
            if not source_path.exists():
                raise FileNotFoundError(f"Source archive not found: {source_path}")

        # Use HybridStorage primitive to read messages
        return await self.storage.read_messages_from_archives(source_paths)
