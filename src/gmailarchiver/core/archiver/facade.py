"""ArchiverFacade - Public API for Gmail archiving operations.

This module provides the public facade for the archiver package. It orchestrates
internal modules (MessageLister, MessageFilter, MessageWriter) to provide a clean,
simple API for archiving Gmail messages.

This is the main entry point for archiving operations in the clean architecture.
Internal modules are implementation details and should not be used directly.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gmailarchiver.cli.output import OperationHandle, OutputManager
from gmailarchiver.connectors.gmail_client import GmailClient

from ._filter import MessageFilter
from ._lister import MessageLister
from ._writer import MessageWriter


class ArchiverFacade:
    """Public facade for Gmail archiving operations.

    This is the main entry point for the archiver package. It orchestrates
    internal modules (MessageLister, MessageFilter, MessageWriter) to provide
    a clean, simple API for archiving Gmail messages.

    The facade implements a three-phase workflow:
    1. List messages from Gmail (via MessageLister)
    2. Filter already-archived messages (via MessageFilter)
    3. Archive messages to mbox (via MessageWriter)

    Example:
        >>> facade = ArchiverFacade(gmail_client=client)
        >>> result = facade.archive(
        ...     age_threshold="3y",
        ...     output_file="archive.mbox",
        ...     incremental=True,
        ...     dry_run=False
        ... )
        >>> print(f"Archived {result['archived_count']} messages")
    """

    def __init__(
        self,
        gmail_client: GmailClient,
        state_db_path: str = "~/.local/share/gmailarchiver/archive.db",
        output_manager: OutputManager | None = None,
    ) -> None:
        """Initialize facade with dependencies.

        Args:
            gmail_client: Authenticated Gmail client for API calls
            state_db_path: Path to state database for tracking archived messages
            output_manager: Optional output manager for progress reporting
        """
        self.gmail_client = gmail_client
        self.state_db_path = str(Path(state_db_path).expanduser())
        self.output_manager = output_manager

        # Initialize internal modules
        self._lister = MessageLister(gmail_client=gmail_client)
        self._filter = MessageFilter(state_db_path=self.state_db_path)
        self._writer = MessageWriter(gmail_client=gmail_client, state_db_path=self.state_db_path)

    def list_messages_for_archive(
        self,
        age_threshold: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """List messages from Gmail matching age threshold.

        Delegates to MessageLister for implementation.

        Args:
            age_threshold: Age expression (e.g., '3y', '6m') or ISO date
            progress_callback: Optional callback(count, page) for progress updates

        Returns:
            Tuple of (gmail_query, message_list) where message_list contains
            dicts with 'id' and 'threadId' keys

        Raises:
            InvalidInputError: If age_threshold format is invalid
        """
        return self._lister.list_messages(age_threshold, progress_callback=progress_callback)

    def filter_already_archived(
        self,
        message_ids: list[str],
        incremental: bool = True,
    ) -> tuple[list[str], int]:
        """Filter out already-archived messages.

        Delegates to MessageFilter for implementation.

        Args:
            message_ids: List of Gmail message IDs to filter
            incremental: If True, filter out already archived (default: True)

        Returns:
            Tuple of (filtered_message_ids, skipped_count)
        """
        return self._filter.filter_archived(message_ids, incremental=incremental)

    def archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
    ) -> dict[str, Any]:
        """Archive messages to mbox file.

        Delegates to MessageWriter for implementation.

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
        return self._writer.archive_messages(
            message_ids, output_file, compress=compress, operation=operation
        )

    def archive(
        self,
        age_threshold: str,
        output_file: str,
        compress: str | None = None,
        incremental: bool = True,
        dry_run: bool = False,
        operation: OperationHandle | None = None,
    ) -> dict[str, Any]:
        """Archive Gmail messages to mbox file (full workflow).

        Orchestrates the complete archiving workflow:
        1. List messages from Gmail matching age threshold
        2. Filter out already-archived messages (if incremental)
        3. Archive messages to mbox file (if not dry-run)

        Args:
            age_threshold: Age expression (e.g., '3y', '6m') or ISO date
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            incremental: If True, skip already-archived messages (default: True)
            dry_run: If True, preview without archiving (default: False)
            operation: Optional operation handle for progress tracking

        Returns:
            Dict with keys:
                - query: Gmail search query that was used
                - found_count: Total messages found matching query
                - skipped_count: Messages skipped (already archived)
                - archived_count: Messages successfully archived
                - failed_count: Messages that failed to archive
                - interrupted: Whether operation was interrupted
                - actual_file: Actual file path (only if not dry-run)

        Raises:
            InvalidInputError: If parameters are invalid
        """
        # Phase 1: List messages from Gmail
        progress_callback = getattr(operation, "progress_callback", None) if operation else None
        query, message_list = self.list_messages_for_archive(
            age_threshold, progress_callback=progress_callback
        )

        # Extract message IDs from message list
        message_ids = [msg["id"] for msg in message_list]

        # Handle empty result early
        if not message_ids:
            return {
                "query": query,
                "found_count": 0,
                "skipped_count": 0,
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
            }

        # Phase 2: Filter already-archived messages
        filtered_ids, skipped_count = self.filter_already_archived(
            message_ids, incremental=incremental
        )

        # Handle dry-run mode (no archiving)
        if dry_run:
            return {
                "query": query,
                "found_count": len(message_ids),
                "skipped_count": skipped_count,
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
            }

        # Handle all messages filtered
        if not filtered_ids:
            return {
                "query": query,
                "found_count": len(message_ids),
                "skipped_count": skipped_count,
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
            }

        # Phase 3: Archive messages
        result = self.archive_messages(
            filtered_ids, output_file, compress=compress, operation=operation
        )

        # Combine results from all phases
        return {
            "query": query,
            "found_count": len(message_ids),
            "skipped_count": skipped_count,
            **result,
        }

    def delete_archived_messages(self, message_ids: list[str], permanent: bool = False) -> int:
        """Delete or trash archived messages from Gmail.

        Args:
            message_ids: List of Gmail message IDs to delete
            permanent: If True, permanently delete; if False, move to trash

        Returns:
            Number of messages deleted/trashed
        """
        if permanent:
            return self.gmail_client.delete_messages_permanent(message_ids)
        else:
            return self.gmail_client.trash_messages(message_ids)
