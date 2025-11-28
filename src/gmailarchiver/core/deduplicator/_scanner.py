"""Duplicate message scanner.

Internal module - use DeduplicatorFacade instead.
"""

import sqlite3
from dataclasses import dataclass


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

    def __init__(self, db_path: str) -> None:
        """
        Initialize scanner with database connection.

        Args:
            db_path: Path to SQLite database
        """
        self.conn = sqlite3.connect(db_path)

    def find_duplicates(self) -> dict[str, list[MessageInfo]]:
        """
        Find all duplicate messages grouped by rfc_message_id.

        Uses SQL GROUP BY for efficient duplicate detection.
        Only includes Message-IDs that appear 2+ times.

        Returns:
            Dict mapping rfc_message_id to list of MessageInfo (locations)
            Messages in each group are sorted by archived_timestamp DESC
        """
        # Find all rfc_message_ids that appear more than once
        cursor = self.conn.execute("""
            SELECT rfc_message_id, COUNT(*) as count
            FROM messages
            WHERE rfc_message_id IS NOT NULL
            GROUP BY rfc_message_id
            HAVING COUNT(*) > 1
        """)

        duplicate_ids = [row[0] for row in cursor.fetchall()]

        if not duplicate_ids:
            return {}

        # For each duplicate ID, get all message locations
        duplicates: dict[str, list[MessageInfo]] = {}

        for rfc_id in duplicate_ids:
            cursor = self.conn.execute(
                """
                SELECT gmail_id, archive_file, mbox_offset, mbox_length,
                       size_bytes, archived_timestamp
                FROM messages
                WHERE rfc_message_id = ?
                ORDER BY archived_timestamp DESC
            """,
                (rfc_id,),
            )

            messages = []
            for row in cursor.fetchall():
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

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
