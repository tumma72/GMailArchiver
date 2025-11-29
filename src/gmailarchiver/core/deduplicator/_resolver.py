"""Duplicate message resolution strategies.

Internal module - use DeduplicatorFacade instead.
"""

from dataclasses import dataclass

from ._scanner import MessageInfo


@dataclass
class Resolution:
    """Resolution of a duplicate group."""

    keep: MessageInfo
    remove: list[MessageInfo]
    space_saved: int


class DuplicateResolver:
    """Resolve which duplicate messages to keep/remove using strategies."""

    VALID_STRATEGIES = ["newest", "largest", "first"]

    def resolve(self, messages: list[MessageInfo], strategy: str = "newest") -> Resolution:
        """
        Resolve which message to keep based on strategy.

        Args:
            messages: List of duplicate messages
            strategy: Which copy to keep ('newest', 'largest', 'first')

        Returns:
            Resolution with message to keep and messages to remove

        Raises:
            ValueError: If strategy is invalid
        """
        if strategy not in self.VALID_STRATEGIES:
            raise ValueError(
                f"Invalid strategy: {strategy}. Must be one of: {', '.join(self.VALID_STRATEGIES)}"
            )

        # Select message to keep based on strategy
        if strategy == "newest":
            # Sort by archived_timestamp descending (newest first)
            sorted_msgs = sorted(messages, key=lambda m: m.archived_timestamp, reverse=True)
            keep_msg = sorted_msgs[0]
        elif strategy == "largest":
            # Sort by size_bytes descending
            sorted_msgs = sorted(messages, key=lambda m: m.size_bytes, reverse=True)
            keep_msg = sorted_msgs[0]
        elif strategy == "first":
            # Sort by archive_file alphabetically
            sorted_msgs = sorted(messages, key=lambda m: m.archive_file)
            keep_msg = sorted_msgs[0]
        else:
            # Should never reach here due to validation above
            raise ValueError(f"Invalid strategy: {strategy}")

        # Mark all others for removal
        to_remove = [msg for msg in messages if msg.gmail_id != keep_msg.gmail_id]

        # Calculate space saved
        space_saved = sum(msg.size_bytes for msg in to_remove)

        return Resolution(keep=keep_msg, remove=to_remove, space_saved=space_saved)
