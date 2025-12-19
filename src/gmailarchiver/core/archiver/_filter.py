"""Internal module for filtering already-archived messages.

This module is part of the archiver package's internal implementation.
Use the ArchiverFacade for public API access.

NOTE: RFC Message-ID deduplication now happens in HybridStorage during
the write phase, not here. This filter only checks Gmail IDs (fast, local).
"""

from dataclasses import dataclass

from gmailarchiver.data.db_manager import DBManager


@dataclass
class FilterResult:
    """Result of filtering already-archived messages.

    Attributes:
        to_archive: List of Gmail message IDs to archive
        already_archived_count: Messages already archived (by Gmail ID)
        duplicate_count: Always 0 - duplicates detected during write phase
    """

    to_archive: list[str]
    already_archived_count: int
    duplicate_count: int

    @property
    def total_skipped(self) -> int:
        """Total messages skipped (archived + duplicates)."""
        return self.already_archived_count + self.duplicate_count


class MessageFilter:
    """Internal helper for filtering already-archived messages.

    Checks database to identify which messages have been previously archived
    (by Gmail ID) and filters them out for incremental archiving.

    NOTE: RFC Message-ID deduplication is handled by HybridStorage during
    the write phase for efficiency (single API call per message instead of 2).
    """

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize MessageFilter with database manager.

        Args:
            db_manager: Database manager for tracking archived messages
        """
        self.db_manager = db_manager

    async def filter_archived(
        self,
        message_ids: list[str],
        incremental: bool = True,
    ) -> FilterResult:
        """Filter out already-archived messages by Gmail ID.

        This is a fast, database-only check. RFC Message-ID deduplication
        happens later in HybridStorage during the write phase.

        Args:
            message_ids: List of Gmail message IDs to filter
            incremental: If True, filter out already archived (default: True)

        Returns:
            FilterResult with to_archive list and skip counts.
            Note: duplicate_count is always 0 here - duplicates are
            detected during the write phase in HybridStorage.
        """
        if not incremental:
            return FilterResult(
                to_archive=message_ids,
                already_archived_count=0,
                duplicate_count=0,
            )

        # Check Gmail IDs against database (fast, O(1) per lookup)
        try:
            if self.db_manager.conn is None:
                archived_gmail_ids: set[str] = set()
            else:
                cursor = await self.db_manager.conn.execute(
                    "SELECT gmail_id FROM messages WHERE gmail_id IS NOT NULL"
                )
                rows = await cursor.fetchall()
                archived_gmail_ids = {row[0] for row in rows}
        except Exception:
            archived_gmail_ids = set()

        # Filter out already-archived by Gmail ID
        after_gmail_filter = [mid for mid in message_ids if mid not in archived_gmail_ids]
        already_archived_count = len(message_ids) - len(after_gmail_filter)

        # NOTE: duplicate_count is 0 here - RFC Message-ID deduplication
        # happens in HybridStorage.archive_messages_batch() during write
        return FilterResult(
            to_archive=after_gmail_filter,
            already_archived_count=already_archived_count,
            duplicate_count=0,
        )
