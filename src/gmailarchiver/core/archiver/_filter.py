"""Internal module for filtering already-archived messages.

This module is part of the archiver package's internal implementation.
Use the ArchiverFacade for public API access.
"""

from pathlib import Path

from gmailarchiver.data.db_manager import DBManager


class MessageFilter:
    """Internal helper for filtering already-archived messages.

    Checks database to identify which messages have been previously archived
    and filters them out for incremental archiving.
    This is an internal implementation detail - use ArchiverFacade for public API.
    """

    def __init__(self, state_db_path: str) -> None:
        """Initialize MessageFilter with database path.

        Args:
            state_db_path: Path to the state database for tracking archived messages
        """
        self.state_db_path = state_db_path

    def filter_archived(
        self,
        message_ids: list[str],
        incremental: bool = True,
    ) -> tuple[list[str], int]:
        """Filter out already-archived messages.

        Args:
            message_ids: List of Gmail message IDs to filter
            incremental: If True, filter out already archived (default: True)

        Returns:
            Tuple of (filtered_message_ids, skipped_count)
        """
        if not incremental:
            return message_ids, 0

        # Check database for existing messages
        db_path = Path(self.state_db_path)
        try:
            db = DBManager(str(db_path), validate_schema=False, auto_create=True)
            # Get only non-NULL gmail_ids (NULL means message deleted from Gmail)
            cursor = db.conn.execute("SELECT gmail_id FROM messages WHERE gmail_id IS NOT NULL")
            archived_ids = {row[0] for row in cursor.fetchall()}
            db.close()
        except Exception:
            # If query fails, database might be empty or table doesn't exist yet
            archived_ids = set()

        # Filter out already-archived
        filtered_ids = [mid for mid in message_ids if mid not in archived_ids]
        skipped_count = len(message_ids) - len(filtered_ids)

        return filtered_ids, skipped_count
