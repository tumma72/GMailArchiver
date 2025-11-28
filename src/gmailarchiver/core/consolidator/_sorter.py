"""Message sorting and deduplication for consolidation."""

from email.utils import parsedate_to_datetime
from typing import Any


class MessageSorter:
    """Sort and deduplicate messages."""

    def sort_by_date(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort messages chronologically by date.

        Args:
            messages: List of message dictionaries

        Returns:
            Sorted list of messages
        """
        # Parse dates and attach timestamps
        for msg_dict in messages:
            date_str = msg_dict.get("date", "")
            msg_dict["timestamp"] = self._parse_date(date_str)

        # Sort by timestamp
        return sorted(messages, key=lambda m: m["timestamp"])

    def deduplicate(
        self, messages: list[dict[str, Any]], strategy: str
    ) -> tuple[list[dict[str, Any]], int, list[str]]:
        """Remove duplicates using specified strategy.

        Args:
            messages: List of message dictionaries
            strategy: Strategy for choosing which duplicate to keep
                ('newest', 'largest', 'first')

        Returns:
            Tuple of (deduplicated_messages, duplicates_removed, duplicate_gmail_ids)

        Raises:
            ValueError: If strategy is invalid
        """
        valid_strategies = ("newest", "largest", "first")
        if strategy not in valid_strategies:
            raise ValueError(
                f"Invalid dedupe_strategy: {strategy}. Must be one of {valid_strategies}"
            )

        # Group by Message-ID
        by_message_id: dict[str, list[dict[str, Any]]] = {}
        for msg_dict in messages:
            msg_id = msg_dict["rfc_message_id"]
            if msg_id not in by_message_id:
                by_message_id[msg_id] = []
            by_message_id[msg_id].append(msg_dict)

        # Apply strategy to duplicates
        kept_messages = []
        duplicates_removed = 0
        duplicate_gmail_ids: list[str] = []

        for msg_id, msg_list in by_message_id.items():
            if len(msg_list) == 1:
                # No duplicates
                kept_messages.append(msg_list[0])
            else:
                # Apply strategy
                kept = self._select_message(msg_list, strategy)
                kept_messages.append(kept)
                duplicates_removed += len(msg_list) - 1

                # Track duplicate gmail_ids for database deletion
                for msg_dict in msg_list:
                    if msg_dict is not kept:
                        duplicate_gmail_ids.append(msg_dict["gmail_id"])

        return kept_messages, duplicates_removed, duplicate_gmail_ids

    def _select_message(self, msg_list: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
        """Select which message to keep from duplicates.

        Args:
            msg_list: List of duplicate messages
            strategy: Selection strategy

        Returns:
            Selected message dictionary
        """
        if strategy == "newest":
            # Parse dates for comparison
            for msg_dict in msg_list:
                if "timestamp" not in msg_dict:
                    msg_dict["timestamp"] = self._parse_date(msg_dict.get("date", ""))
            return max(msg_list, key=lambda m: m["timestamp"])
        elif strategy == "largest":
            return max(msg_list, key=lambda m: m["size"])
        else:  # 'first'
            return msg_list[0]

    def _parse_date(self, date_str: str) -> float:
        """Parse email Date header to timestamp.

        Args:
            date_str: RFC 2822 date string

        Returns:
            Unix timestamp (or 0.0 for invalid dates)
        """
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except (ValueError, TypeError):
            # Return epoch for invalid dates (sorts to beginning)
            return 0.0
