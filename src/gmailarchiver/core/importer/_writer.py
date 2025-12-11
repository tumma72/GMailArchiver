"""Internal module for database writing and deduplication.

This module handles database operations, duplicate detection, and
batch writing during import. Part of importer package's internal implementation.
"""

import logging
from datetime import datetime
from enum import Enum

from gmailarchiver.core.importer._reader import MessageMetadata
from gmailarchiver.data.db_manager import DBManager

logger = logging.getLogger(__name__)


# Note: This module uses async methods because DBManager is now async.
# All methods that interact with the database must be async.


class WriteResult(Enum):
    """Result of writing a message to database."""

    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


class DatabaseWriter:
    """Internal helper for database operations during import.

    Handles deduplication, message writing, and archive run recording.
    This is an internal implementation detail - use ImporterFacade for public API.
    """

    def __init__(self, db: DBManager) -> None:
        """Initialize DatabaseWriter with database manager.

        Args:
            db: Database manager for all database operations
        """
        self.db = db
        self.existing_ids: set[str] = set()
        self.session_ids: set[str] = set()

    async def load_existing_ids(self) -> set[str]:
        """Load existing RFC Message-IDs from database for deduplication.

        Returns:
            Set of existing RFC Message-IDs
        """
        try:
            self.existing_ids = await self.db.get_all_rfc_message_ids()
            return self.existing_ids
        except Exception:
            # Table might not exist yet, return empty set
            return set()

    def is_duplicate(self, rfc_message_id: str) -> bool:
        """Check if message is a duplicate.

        Args:
            rfc_message_id: RFC Message-ID to check

        Returns:
            True if message already exists, False otherwise
        """
        return rfc_message_id in self.existing_ids or rfc_message_id in self.session_ids

    async def write_message(self, metadata: MessageMetadata, skip_duplicates: bool) -> WriteResult:
        """Write message metadata to database.

        Args:
            metadata: Message metadata to write
            skip_duplicates: Whether to skip duplicates or replace them

        Returns:
            WriteResult indicating success/skip/failure
        """
        # Check for duplicates
        if skip_duplicates and self.is_duplicate(metadata.rfc_message_id):
            return WriteResult.SKIPPED

        try:
            if skip_duplicates:
                # Use DBManager's INSERT (will fail on duplicates, caught above)
                await self.db.record_archived_message(**metadata.to_dict(), record_run=False)
            else:
                # Use INSERT OR REPLACE for non-skip mode
                archived_timestamp = datetime.now().isoformat()
                if self.db.conn is None:
                    raise RuntimeError("Database connection not initialized")
                await self.db.conn.execute(
                    """
                    INSERT OR REPLACE INTO messages (
                        gmail_id, rfc_message_id, thread_id,
                        subject, from_addr, to_addr, cc_addr,
                        date, archived_timestamp, archive_file,
                        mbox_offset, mbox_length,
                        body_preview, checksum, size_bytes,
                        labels, account_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metadata.gmail_id,
                        metadata.rfc_message_id,
                        metadata.thread_id,
                        metadata.subject,
                        metadata.from_addr,
                        metadata.to_addr,
                        metadata.cc_addr,
                        metadata.date,
                        archived_timestamp,
                        metadata.archive_file,
                        metadata.mbox_offset,
                        metadata.mbox_length,
                        metadata.body_preview,
                        metadata.checksum,
                        metadata.size_bytes,
                        None,  # labels
                        metadata.account_id,
                    ),
                )

            # Track in session IDs
            self.session_ids.add(metadata.rfc_message_id)
            return WriteResult.IMPORTED

        except Exception as e:
            logger.debug(f"Database write failed for {metadata.rfc_message_id}: {e}")
            await self.db.rollback()
            return WriteResult.FAILED

    async def record_archive_run(
        self, archive_file: str, messages_count: int, account_id: str
    ) -> None:
        """Record import operation in archive_runs table.

        Args:
            archive_file: Path to archive file
            messages_count: Number of messages imported
            account_id: Account identifier
        """
        await self.db.record_archive_run(
            operation="import",
            messages_count=messages_count,
            archive_file=archive_file,
            account_id=account_id,
        )
