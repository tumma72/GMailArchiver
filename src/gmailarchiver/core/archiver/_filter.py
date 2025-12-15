"""Internal module for filtering already-archived messages.

This module is part of the archiver package's internal implementation.
Use the ArchiverFacade for public API access.
"""

from dataclasses import dataclass
from typing import Any

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.db_manager import DBManager


@dataclass
class FilterResult:
    """Result of filtering already-archived messages.

    Attributes:
        to_archive: List of Gmail message IDs to archive
        already_archived_count: Messages already archived (by Gmail ID)
        duplicate_count: Messages with RFC Message-ID already in database
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
    and filters them out for incremental archiving.
    This is an internal implementation detail - use ArchiverFacade for public API.
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
        gmail_client: GmailClient | None = None,
    ) -> FilterResult:
        """Filter out already-archived messages and duplicates.

        Two-phase filtering:
        1. Check Gmail IDs against database (fast, local)
        2. For remaining messages, check RFC Message-IDs (requires Gmail API)

        Args:
            message_ids: List of Gmail message IDs to filter
            incremental: If True, filter out already archived (default: True)
            gmail_client: Optional Gmail client for RFC Message-ID lookup

        Returns:
            FilterResult with to_archive list and skip counts
        """
        if not incremental:
            return FilterResult(
                to_archive=message_ids,
                already_archived_count=0,
                duplicate_count=0,
            )

        # Phase 1: Check Gmail IDs (fast, database-only)
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

        # Phase 2: Check RFC Message-IDs for remaining messages
        duplicate_count = 0
        to_archive = after_gmail_filter

        if gmail_client and after_gmail_filter:
            # Get known RFC Message-IDs from database
            try:
                known_rfc_ids = await self.db_manager.get_all_rfc_message_ids()
            except Exception:
                known_rfc_ids = set()

            if known_rfc_ids:
                # Fetch message metadata from Gmail to get Message-ID headers
                duplicates, to_archive = await self._filter_by_rfc_id(
                    after_gmail_filter, gmail_client, known_rfc_ids
                )
                duplicate_count = len(duplicates)

        return FilterResult(
            to_archive=to_archive,
            already_archived_count=already_archived_count,
            duplicate_count=duplicate_count,
        )

    async def _filter_by_rfc_id(
        self,
        message_ids: list[str],
        gmail_client: GmailClient,
        known_rfc_ids: set[str],
    ) -> tuple[list[str], list[str]]:
        """Filter messages by RFC Message-ID lookup.

        Args:
            message_ids: Gmail message IDs to check
            gmail_client: Gmail client for API calls
            known_rfc_ids: Set of RFC Message-IDs already in database

        Returns:
            Tuple of (duplicate_ids, non_duplicate_ids)
        """
        duplicates: list[str] = []
        non_duplicates: list[str] = []

        # Fetch message metadata (headers only, not full content)
        async for msg_data in gmail_client.get_messages_batch(
            message_ids, format="metadata"
        ):
            gmail_id = msg_data.get("id", "")
            rfc_message_id = self._extract_message_id_header(msg_data)

            if rfc_message_id and rfc_message_id in known_rfc_ids:
                duplicates.append(gmail_id)
            else:
                non_duplicates.append(gmail_id)

        return duplicates, non_duplicates

    def _extract_message_id_header(self, msg_data: dict[str, Any]) -> str | None:
        """Extract Message-ID header from Gmail API metadata response.

        Args:
            msg_data: Gmail API message response with format=metadata

        Returns:
            Message-ID header value or None if not found
        """
        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])

        for header in headers:
            if header.get("name", "").lower() == "message-id":
                value: str = header.get("value", "")
                return value.strip() if value else None

        return None
