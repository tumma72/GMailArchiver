"""Duplicate message scanner.

Internal module - use DeduplicatorFacade instead.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gmailarchiver.data.db_manager import DBManager


@dataclass
class MessageInfo:
    """Information about a message location in archive."""

    gmail_id: str
    archive_file: str
    mbox_offset: int
    mbox_length: int
    size_bytes: int
    archived_timestamp: str


class DuplicateScanner:
    """Scan database for duplicate messages via RFC 2822 Message-ID."""

    def __init__(self, db: DBManager) -> None:
        """
        Initialize scanner with database manager.

        Args:
            db: DBManager instance for database operations
        """
        self.db = db

    async def find_duplicates(self) -> dict[str, list[MessageInfo]]:
        """
        Find all duplicate messages grouped by rfc_message_id.

        Uses SQL GROUP BY for efficient duplicate detection.
        Only includes Message-IDs that appear 2+ times.

        Returns:
            Dict mapping rfc_message_id to list of MessageInfo (locations)
            Messages in each group are sorted by archived_timestamp DESC
        """
        if self.db.conn is None:
            return {}
        conn = self.db.conn  # Type narrowed

        # Find all rfc_message_ids that appear more than once
        cursor = await conn.execute("""
            SELECT rfc_message_id, COUNT(*) as count
            FROM messages
            WHERE rfc_message_id IS NOT NULL
            GROUP BY rfc_message_id
            HAVING COUNT(*) > 1
        """)

        rows = await cursor.fetchall()
        duplicate_ids = [row[0] for row in rows]

        if not duplicate_ids:
            return {}

        # For each duplicate ID, get all message locations
        duplicates: dict[str, list[MessageInfo]] = {}

        for rfc_id in duplicate_ids:
            cursor = await conn.execute(
                """
                SELECT gmail_id, archive_file, mbox_offset, mbox_length,
                       size_bytes, archived_timestamp
                FROM messages
                WHERE rfc_message_id = ?
                ORDER BY archived_timestamp DESC
            """,
                (rfc_id,),
            )

            rows = await cursor.fetchall()
            messages = []
            for row in rows:
                # Handle NULL size_bytes by using mbox_length as fallback
                size = row[4] if row[4] is not None else row[3]

                messages.append(
                    MessageInfo(
                        gmail_id=row[0],
                        archive_file=row[1],
                        mbox_offset=row[2],
                        mbox_length=row[3],
                        size_bytes=size,
                        archived_timestamp=row[5],
                    )
                )

            duplicates[rfc_id] = messages

        return duplicates
