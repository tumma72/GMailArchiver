"""Message deduplication system for Gmail Archiver v1.1.0."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DeduplicationError(Exception):
    """Raised when deduplication fails."""
    pass


@dataclass
class MessageInfo:
    """Information about a message location in archive."""

    gmail_id: str
    archive_file: str
    mbox_offset: int
    mbox_length: int
    size_bytes: int
    archived_timestamp: str


@dataclass
class DeduplicationReport:
    """Report on deduplication analysis."""

    total_messages: int
    duplicate_message_ids: int
    total_duplicate_messages: int
    messages_to_remove: int
    space_recoverable: int
    breakdown_by_archive: dict[str, dict[str, Any]]


@dataclass
class DeduplicationResult:
    """Result of deduplication operation."""

    messages_removed: int
    messages_kept: int
    space_saved: int
    dry_run: bool


class MessageDeduplicator:
    """
    Find and remove duplicate messages using RFC 2822 Message-ID.

    Requires v1.1 database schema with rfc_message_id field.
    Provides 100% precision deduplication via exact Message-ID matching.
    """

    def __init__(self, state_db_path: str) -> None:
        """
        Initialize with database path.

        Args:
            state_db_path: Path to SQLite state database

        Raises:
            FileNotFoundError: If database doesn't exist
            ValueError: If database is not v1.1 schema
        """
        self.state_db_path = Path(state_db_path).resolve()

        if not self.state_db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.state_db_path}")

        self.conn: sqlite3.Connection | None = sqlite3.connect(str(self.state_db_path))

        # Verify v1.1 schema
        version = self._detect_schema_version()
        if version != "1.1":
            self.conn.close()
            raise ValueError(
                f"MessageDeduplicator requires v1.1 database schema, "
                f"found: {version}. Run migration first."
            )

    def _detect_schema_version(self) -> str:
        """
        Detect database schema version.

        Returns:
            Schema version string ("1.0", "1.1", or "none")
        """
        if not self.conn:
            return "none"

        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone():
            version_cursor = self.conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = version_cursor.fetchone()
            return row[0] if row else "1.0"

        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if cursor.fetchone():
            return "1.1"

        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='archived_messages'"
        )
        if cursor.fetchone():
            return "1.0"

        return "none"

    def find_duplicates(self) -> dict[str, list[MessageInfo]]:
        """
        Find all duplicate messages grouped by rfc_message_id.

        Uses SQL GROUP BY for efficient duplicate detection.
        Only includes Message-IDs that appear 2+ times.

        Returns:
            Dict mapping rfc_message_id to list of MessageInfo (locations)
        """
        if not self.conn:
            return {}

        # Find all rfc_message_ids that appear more than once
        # Use SQL for efficiency
        cursor = self.conn.execute('''
            SELECT rfc_message_id, COUNT(*) as count
            FROM messages
            WHERE rfc_message_id IS NOT NULL
            GROUP BY rfc_message_id
            HAVING COUNT(*) > 1
        ''')

        duplicate_ids = [row[0] for row in cursor.fetchall()]

        if not duplicate_ids:
            return {}

        # For each duplicate ID, get all message locations
        duplicates: dict[str, list[MessageInfo]] = {}

        for rfc_id in duplicate_ids:
            cursor = self.conn.execute('''
                SELECT gmail_id, archive_file, mbox_offset, mbox_length,
                       size_bytes, archived_timestamp
                FROM messages
                WHERE rfc_message_id = ?
                ORDER BY archived_timestamp DESC
            ''', (rfc_id,))

            messages = []
            for row in cursor.fetchall():
                # Handle NULL size_bytes by using mbox_length as fallback
                size = row[4] if row[4] is not None else row[3]

                messages.append(MessageInfo(
                    gmail_id=row[0],
                    archive_file=row[1],
                    mbox_offset=row[2],
                    mbox_length=row[3],
                    size_bytes=size,
                    archived_timestamp=row[5]
                ))

            duplicates[rfc_id] = messages

        return duplicates

    def generate_report(self, duplicates: dict[str, list[MessageInfo]]) -> DeduplicationReport:
        """
        Generate report showing deduplication analysis.

        Args:
            duplicates: From find_duplicates()

        Returns:
            DeduplicationReport with statistics
        """
        if not self.conn:
            raise RuntimeError("Database connection is closed")

        # Get total message count
        cursor = self.conn.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]

        if not duplicates:
            return DeduplicationReport(
                total_messages=total_messages,
                duplicate_message_ids=0,
                total_duplicate_messages=0,
                messages_to_remove=0,
                space_recoverable=0,
                breakdown_by_archive={}
            )

        # Calculate statistics
        duplicate_message_ids = len(duplicates)
        total_duplicate_messages = sum(len(msgs) for msgs in duplicates.values())
        messages_to_remove = total_duplicate_messages - duplicate_message_ids  # Keep 1 per group

        # Calculate space recoverable (sum of sizes that would be removed)
        # Strategy: keep largest in each group
        space_recoverable = 0
        breakdown: dict[str, dict[str, Any]] = {}

        for rfc_id, messages in duplicates.items():
            # Sort by size descending to find largest
            sorted_msgs = sorted(messages, key=lambda m: m.size_bytes, reverse=True)

            # Keep first (largest), remove rest
            for msg in sorted_msgs[1:]:
                space_recoverable += msg.size_bytes

                # Track by archive file
                if msg.archive_file not in breakdown:
                    breakdown[msg.archive_file] = {
                        'messages_to_remove': 0,
                        'space_recoverable': 0
                    }

                breakdown[msg.archive_file]['messages_to_remove'] += 1
                breakdown[msg.archive_file]['space_recoverable'] += msg.size_bytes

        return DeduplicationReport(
            total_messages=total_messages,
            duplicate_message_ids=duplicate_message_ids,
            total_duplicate_messages=total_duplicate_messages,
            messages_to_remove=messages_to_remove,
            space_recoverable=space_recoverable,
            breakdown_by_archive=breakdown
        )

    def deduplicate(
        self,
        duplicates: dict[str, list[MessageInfo]],
        strategy: str = 'newest',
        dry_run: bool = True
    ) -> DeduplicationResult:
        """
        Remove duplicates using specified strategy.

        Args:
            duplicates: From find_duplicates()
            strategy: Which copy to keep ('newest', 'largest', 'first')
            dry_run: If True, only report what would be done

        Returns:
            DeduplicationResult with counts and space saved

        Raises:
            ValueError: If strategy is invalid
        """
        valid_strategies = ['newest', 'largest', 'first']
        if strategy not in valid_strategies:
            raise ValueError(
                f"Invalid strategy: {strategy}. "
                f"Must be one of: {', '.join(valid_strategies)}"
            )

        if not duplicates:
            return DeduplicationResult(
                messages_removed=0,
                messages_kept=0,
                space_saved=0,
                dry_run=dry_run
            )

        # Determine which messages to keep and which to remove
        to_remove: list[str] = []  # gmail_ids
        space_saved = 0

        for rfc_id, messages in duplicates.items():
            # Select message to keep based on strategy
            if strategy == 'newest':
                # Already sorted by archived_timestamp DESC in find_duplicates
                keep_msg = messages[0]
            elif strategy == 'largest':
                # Sort by size_bytes descending
                sorted_msgs = sorted(messages, key=lambda m: m.size_bytes, reverse=True)
                keep_msg = sorted_msgs[0]
            elif strategy == 'first':
                # Sort by archive_file alphabetically
                sorted_msgs = sorted(messages, key=lambda m: m.archive_file)
                keep_msg = sorted_msgs[0]
            else:
                # Should never reach here due to validation above
                raise ValueError(f"Invalid strategy: {strategy}")

            # Mark all others for removal
            for msg in messages:
                if msg.gmail_id != keep_msg.gmail_id:
                    to_remove.append(msg.gmail_id)
                    space_saved += msg.size_bytes

        messages_removed = len(to_remove)
        messages_kept = len(duplicates)  # One per group

        # Execute removal if not dry run
        if not dry_run and to_remove:
            if not self.conn:
                raise RuntimeError("Database connection is closed")

            # Use parameterized query to avoid SQL injection
            placeholders = ','.join('?' * len(to_remove))
            self.conn.execute(
                f'DELETE FROM messages WHERE gmail_id IN ({placeholders})',
                to_remove
            )
            self.conn.commit()

        return DeduplicationResult(
            messages_removed=messages_removed,
            messages_kept=messages_kept,
            space_saved=space_saved,
            dry_run=dry_run
        )

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> MessageDeduplicator:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - closes connection."""
        self.close()

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
