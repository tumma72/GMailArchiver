"""Duplicate message remover.

Internal module - use DeduplicatorFacade instead.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gmailarchiver.data.db_manager import DBManager

from ._scanner import MessageInfo


class DuplicateRemover:
    """Remove duplicate messages from database."""

    def __init__(self, db: DBManager) -> None:
        """
        Initialize remover with database manager.

        Args:
            db: DBManager instance for database operations
        """
        self.db = db

    async def remove_messages(self, messages: list[MessageInfo], dry_run: bool = True) -> int:
        """
        Remove messages from database.

        Args:
            messages: List of messages to remove
            dry_run: If True, only return count without deleting

        Returns:
            Number of messages that would be/were removed
        """
        if not messages:
            return 0

        message_count = len(messages)

        # If dry run, just return count
        if dry_run:
            return message_count

        # Execute removal using parameterized query
        gmail_ids = [msg.gmail_id for msg in messages]
        placeholders = ",".join("?" * len(gmail_ids))
        sql = f"DELETE FROM messages WHERE gmail_id IN ({placeholders})"

        if self.db.conn is None:
            raise RuntimeError("Database connection not initialized")
        await self.db.conn.execute(sql, gmail_ids)
        await self.db.commit()

        return message_count
