"""Internal module for Gmail ID lookups during import.

This module handles optional Gmail API lookups to find real Gmail IDs
for messages being imported. Part of importer package's internal implementation.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gmailarchiver.connectors.gmail_client import GmailClient

logger = logging.getLogger(__name__)


@dataclass
class LookupResult:
    """Result of a Gmail ID lookup operation."""

    gmail_id: str | None
    found: bool
    error: str | None


class GmailLookup:
    """Internal helper for Gmail ID lookups via API.

    Handles optional Gmail API calls to find real Gmail IDs for messages
    during import. This is an internal implementation detail - use
    ImporterFacade for public API.
    """

    def __init__(self, gmail_client: GmailClient | None) -> None:
        """Initialize GmailLookup with optional Gmail client.

        Args:
            gmail_client: Optional authenticated async Gmail client for API calls.
                         If None, lookups are skipped.
        """
        self.client = gmail_client

    def is_enabled(self) -> bool:
        """Check if Gmail lookups are enabled.

        Returns:
            True if Gmail client is configured, False otherwise
        """
        return self.client is not None

    async def lookup_gmail_id(self, rfc_message_id: str) -> LookupResult:
        """Look up Gmail ID for message by RFC Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header

        Returns:
            LookupResult with gmail_id if found, or None if not found/disabled
        """
        if not self.is_enabled():
            return LookupResult(gmail_id=None, found=False, error=None)

        try:
            gmail_id = await self.client.search_by_rfc_message_id(rfc_message_id)  # type: ignore[union-attr]
            if gmail_id:
                return LookupResult(gmail_id=gmail_id, found=True, error=None)
            else:
                return LookupResult(gmail_id=None, found=False, error=None)

        except Exception as e:
            logger.debug(f"Gmail ID lookup failed for {rfc_message_id}: {e}")
            return LookupResult(gmail_id=None, found=False, error=str(e))
