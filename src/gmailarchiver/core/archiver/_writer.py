"""MessageWriter - Internal module for writing messages to mbox archives.

This is an internal implementation detail of the archiver package.
DO NOT import or use this module outside of the archiver package.
Public API is exposed through GmailArchiver class.

Phase 1.6 - Extracted from archiver_legacy.py for clean architecture.
"""

import uuid
from typing import Any

from gmailarchiver.cli.output import OperationHandle
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.input_validator import validate_compression_format


class MessageWriter:
    """Write Gmail messages to mbox archive with hybrid storage.

    Internal module - not part of public API.
    Handles the write phase of archiving workflow.
    """

    def __init__(self, gmail_client: GmailClient, state_db_path: str) -> None:
        """Initialize MessageWriter with Gmail client and database path.

        Args:
            gmail_client: Gmail API client for fetching messages
            state_db_path: Path to state database for metadata tracking
        """
        self.client = gmail_client
        self.state_db_path = state_db_path
        self.db_manager: DBManager | None = None
        self.hybrid_storage: HybridStorage | None = None

    def archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
    ) -> dict[str, Any]:
        """Archive messages to mbox file with hybrid storage.

        Args:
            message_ids: List of Gmail message IDs to archive
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            operation: Optional operation handle for progress tracking

        Returns:
            Dict with keys:
                - archived_count: Number of successfully archived messages
                - failed_count: Number of failed messages
                - interrupted: Whether operation was interrupted
                - actual_file: Actual file path where messages were written
        """
        # Validate compression format first (raises InvalidInputError if invalid)
        compress = validate_compression_format(compress)

        # Return early if no messages to archive
        if not message_ids:
            return {
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
                "actual_file": output_file,
            }

        # Initialize storage managers
        self.db_manager = DBManager(self.state_db_path, validate_schema=False, auto_create=True)
        self.hybrid_storage = HybridStorage(self.db_manager)

        # Create session for tracking progress
        session_id = str(uuid.uuid4())
        query = f"archive_messages({len(message_ids)} messages)"
        self.db_manager.create_session(
            session_id=session_id,
            target_file=output_file,
            query=query,
            message_ids=message_ids,
            compression=compress,
        )

        try:
            # Archive messages using helper method
            result = self._archive_messages(
                message_ids,
                output_file,
                compress,
                operation,
                session_id=session_id,
            )

            # Clean up database connection
            self.db_manager.close()

            # Map helper result to expected output format
            return {
                "archived_count": result.get("archived", 0),
                "failed_count": result.get("failed", 0),
                "interrupted": result.get("interrupted", False),
                "actual_file": result.get("actual_file", output_file),
            }

        except Exception:
            # Clean up on error
            if self.db_manager:
                self.db_manager.close()
            raise

    def _archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Internal helper method for archiving messages.

        This method delegates to the legacy archiver implementation during Phase 1
        refactoring. In Phase 2, the full archiving logic will be extracted here.

        This separation enables unit testing by providing a mockable boundary while
        maintaining backward compatibility with the legacy implementation.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path
            compress: Compression format
            operation: Optional operation handle for progress tracking
            session_id: Optional session ID for resumable operations

        Returns:
            Dict with keys: archived, failed, interrupted, actual_file
        """
        # Delegate to legacy archiver during Phase 1 refactoring
        # This will be extracted to standalone logic in Phase 2
        from gmailarchiver.core.archiver_legacy import GmailArchiver

        # Create legacy archiver with same client and state_db_path
        legacy_archiver = GmailArchiver(
            gmail_client=self.client,
            state_db_path=self.state_db_path,
        )

        # Delegate to legacy implementation
        # Set the db_manager and hybrid_storage that we already created
        legacy_archiver.db_manager = self.db_manager
        legacy_archiver.hybrid_storage = self.hybrid_storage

        # Call the legacy method
        return legacy_archiver._archive_messages_hybrid_storage(
            message_ids=message_ids,
            output_file=output_file,
            compress=compress,
            operation=operation,
            session_id=session_id,
        )
