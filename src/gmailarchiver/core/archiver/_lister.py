"""Internal module for listing messages from Gmail API.

This module is part of the archiver package's internal implementation.
Use the ArchiverFacade for public API access.
"""

from collections.abc import Callable

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.shared.input_validator import validate_age_expression
from gmailarchiver.shared.utils import datetime_to_gmail_query, parse_age


class MessageLister:
    """Internal helper for listing messages from Gmail API.

    Handles age threshold parsing and Gmail API interaction for message listing.
    This is an internal implementation detail - use ArchiverFacade for public API.
    """

    def __init__(self, gmail_client: GmailClient) -> None:
        """Initialize MessageLister with Gmail client.

        Args:
            gmail_client: Authenticated Gmail client for API calls
        """
        self.client = gmail_client

    def list_messages(
        self,
        age_threshold: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """List messages from Gmail matching age threshold.

        Args:
            age_threshold: Age expression (e.g., '3y', '6m') or ISO date
            progress_callback: Optional callback(count, page) for progress updates

        Returns:
            Tuple of (gmail_query, message_list) where message_list contains
            dicts with 'id' and 'threadId' keys

        Raises:
            InvalidInputError: If age_threshold format is invalid
        """
        # Validate age threshold
        age_threshold = validate_age_expression(age_threshold)

        # Parse to date and build query
        cutoff_date = parse_age(age_threshold)
        query = f"before:{datetime_to_gmail_query(cutoff_date)}"

        # List messages from Gmail API with progress callback
        message_list = self.client.list_messages(query, progress_callback=progress_callback)

        return query, message_list
