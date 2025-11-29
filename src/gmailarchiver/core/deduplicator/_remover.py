"""Duplicate message remover.

Internal module - use DeduplicatorFacade instead.
"""

import sqlite3

from ._scanner import MessageInfo


class DuplicateRemover:
    """Remove duplicate messages from database."""

    def __init__(self, db_path: str) -> None:
        """
        Initialize remover with database connection.

        Args:
            db_path: Path to SQLite database
        """
        self.conn = sqlite3.connect(db_path)

    def remove_messages(self, messages: list[MessageInfo], dry_run: bool = True) -> int:
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

        self.conn.execute(sql, gmail_ids)
        self.conn.commit()

        return message_count

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
