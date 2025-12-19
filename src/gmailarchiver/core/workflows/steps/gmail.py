"""Gmail API steps for archive workflow.

This module provides steps for interacting with Gmail API:
- ScanGmailMessagesStep: List messages from Gmail matching criteria
- FilterGmailMessagesStep: Filter out already-archived messages
- DeleteGmailMessagesStep: Delete or trash messages from Gmail
"""

from dataclasses import dataclass
from typing import Any

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ScanGmailInput:
    """Input for ScanGmailMessagesStep."""

    age_threshold: str  # e.g., "3y", "6m", "2024-01-01"


@dataclass
class ScanGmailOutput:
    """Output from ScanGmailMessagesStep."""

    gmail_query: str
    messages: list[dict[str, Any]]  # List of {id, threadId}
    total_count: int


class ScanGmailMessagesStep:
    """Step that lists messages from Gmail matching age criteria.

    Queries the Gmail API for messages older than the specified threshold.
    Does NOT filter duplicates - that's done by FilterGmailMessagesStep.

    Input: ScanGmailInput with age threshold
    Output: ScanGmailOutput with message list
    Context: Sets GMAIL_QUERY, MESSAGES, MESSAGE_IDS
    """

    name = "scan_gmail"
    description = "Scanning messages from Gmail"

    def __init__(self, archiver: ArchiverFacade) -> None:
        """Initialize with archiver facade.

        Args:
            archiver: ArchiverFacade for Gmail API access
        """
        self.archiver = archiver

    async def execute(
        self,
        context: StepContext,
        input_data: ScanGmailInput | str,
        progress: ProgressReporter | None = None,
    ) -> StepResult[ScanGmailOutput]:
        """List messages from Gmail matching age threshold.

        Args:
            context: Shared step context
            input_data: Age threshold (ScanGmailInput or string)
            progress: Optional progress reporter

        Returns:
            StepResult with ScanGmailOutput containing message list
        """
        # Normalize input
        if isinstance(input_data, ScanGmailInput):
            age_threshold = input_data.age_threshold
        else:
            age_threshold = input_data

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Scanning messages from Gmail") as task:
                        # Note: We log count updates to the log window instead of using
                        # set_status() because set_status replaces the task description,
                        # which then gets combined with the completion message awkwardly.
                        last_logged_count = 0

                        def on_progress(count: int, page: int) -> None:
                            nonlocal last_logged_count
                            # Log every 1000 messages to show progress without spam
                            if count - last_logged_count >= 1000:
                                task.log(f"Scanned {count:,} messages...")
                                last_logged_count = count

                        query, messages = await self.archiver.list_messages_for_archive(
                            age_threshold, progress_callback=on_progress
                        )
                        if messages:
                            task.complete(f"Found {len(messages):,} messages")
                        else:
                            task.complete("No messages found matching criteria")
            else:
                query, messages = await self.archiver.list_messages_for_archive(age_threshold)

            # Store in context
            context.set(ContextKeys.GMAIL_QUERY, query)
            context.set(ContextKeys.MESSAGES, messages)
            context.set(ContextKeys.MESSAGE_IDS, [msg["id"] for msg in messages])

            output = ScanGmailOutput(
                gmail_query=query,
                messages=messages,
                total_count=len(messages),
            )
            return StepResult.ok(output, count=len(messages))

        except Exception as e:
            return StepResult.fail(f"Failed to scan Gmail: {e}")


@dataclass
class FilterGmailInput:
    """Input for FilterGmailMessagesStep."""

    message_ids: list[str]
    incremental: bool = True


@dataclass
class FilterGmailOutput:
    """Output from FilterGmailMessagesStep."""

    to_archive: list[str]  # Message IDs to archive
    already_archived_count: int
    duplicate_count: int
    total_skipped: int


class FilterGmailMessagesStep:
    """Step that filters out already-archived messages.

    Checks Gmail message IDs against the database and filters out:
    1. Messages already archived (by Gmail ID)
    2. Duplicate messages (by RFC Message-ID)

    Input: FilterGmailInput with message IDs
    Output: FilterGmailOutput with filtered IDs and counts
    Context: Sets TO_ARCHIVE, SKIPPED_COUNT, DUPLICATE_COUNT
    """

    name = "filter_gmail"
    description = "Checking for already archived"

    def __init__(self, archiver: ArchiverFacade) -> None:
        """Initialize with archiver facade.

        Args:
            archiver: ArchiverFacade for duplicate checking
        """
        self.archiver = archiver

    async def execute(
        self,
        context: StepContext,
        input_data: FilterGmailInput | list[str] | None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[FilterGmailOutput]:
        """Filter messages to find those needing archival.

        Args:
            context: Shared step context
            input_data: Message IDs to filter
            progress: Optional progress reporter

        Returns:
            StepResult with FilterGmailOutput containing filtered IDs
        """
        # Normalize input
        if isinstance(input_data, FilterGmailInput):
            message_ids = input_data.message_ids
            incremental = input_data.incremental
        elif isinstance(input_data, list):
            message_ids = input_data
            incremental = True
        else:
            # Try to get from context
            message_ids = context.get(ContextKeys.MESSAGE_IDS) or []
            incremental = bool(context.get("incremental", True))

        if not message_ids:
            output = FilterGmailOutput(
                to_archive=[],
                already_archived_count=0,
                duplicate_count=0,
                total_skipped=0,
            )
            return StepResult.ok(output)

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Checking for already archived") as task:
                        filter_result = await self.archiver.filter_already_archived(
                            message_ids, incremental
                        )

                        parts = []
                        if filter_result.already_archived_count > 0:
                            count = filter_result.already_archived_count
                            parts.append(f"{count:,} already archived")
                        if filter_result.duplicate_count > 0:
                            parts.append(f"{filter_result.duplicate_count:,} duplicates")

                        msg = f"{len(filter_result.to_archive):,} to archive"
                        if parts:
                            msg = f"{', '.join(parts)}, {msg}"
                        task.complete(msg)
            else:
                filter_result = await self.archiver.filter_already_archived(
                    message_ids, incremental
                )

            # Store in context
            context.set(ContextKeys.TO_ARCHIVE, filter_result.to_archive)
            context.set(ContextKeys.SKIPPED_COUNT, filter_result.total_skipped)
            context.set(ContextKeys.DUPLICATE_COUNT, filter_result.duplicate_count)
            context.set("already_archived_count", filter_result.already_archived_count)

            output = FilterGmailOutput(
                to_archive=filter_result.to_archive,
                already_archived_count=filter_result.already_archived_count,
                duplicate_count=filter_result.duplicate_count,
                total_skipped=filter_result.total_skipped,
            )
            return StepResult.ok(
                output,
                to_archive_count=len(filter_result.to_archive),
                skipped_count=filter_result.total_skipped,
            )

        except Exception as e:
            return StepResult.fail(f"Failed to filter messages: {e}")


@dataclass
class DeleteGmailInput:
    """Input for DeleteGmailMessagesStep."""

    archive_file: str
    permanent: bool = False  # True for permanent delete, False for trash


@dataclass
class DeleteGmailOutput:
    """Output from DeleteGmailMessagesStep."""

    deleted_count: int
    permanent: bool


class DeleteGmailMessagesStep:
    """Step that deletes or trashes messages from Gmail.

    Retrieves message IDs from the archive file's database records
    and deletes or moves them to trash.

    Input: DeleteGmailInput with archive file and permanent flag
    Output: DeleteGmailOutput with deleted count
    """

    name = "delete_gmail"
    description = "Deleting messages from Gmail"

    def __init__(self, client: GmailClient, storage: HybridStorage) -> None:
        """Initialize with Gmail client and storage.

        Args:
            client: Authenticated Gmail client
            storage: HybridStorage for message ID lookup
        """
        self.client = client
        self.storage = storage

    async def execute(
        self,
        context: StepContext,
        input_data: DeleteGmailInput | str,
        progress: ProgressReporter | None = None,
    ) -> StepResult[DeleteGmailOutput]:
        """Delete messages from Gmail.

        Args:
            context: Shared step context
            input_data: Archive file path (or DeleteGmailInput)
            progress: Optional progress reporter

        Returns:
            StepResult with DeleteGmailOutput containing deleted count
        """
        # Normalize input
        if isinstance(input_data, DeleteGmailInput):
            archive_file = input_data.archive_file
            permanent = input_data.permanent
        else:
            archive_file = input_data
            permanent = False

        try:
            # Get message IDs from database
            archived_ids = await self.storage.get_message_ids_for_archive(archive_file)
            if not archived_ids:
                output = DeleteGmailOutput(deleted_count=0, permanent=permanent)
                return StepResult.ok(output, count=0)

            action = "Permanently deleting" if permanent else "Moving to trash"
            total_count = len(archived_ids)
            last_count = 0  # Track last reported count for progress updates

            if progress:
                with progress.task_sequence() as seq:
                    with seq.task(f"{action} messages", total=total_count) as task:
                        # Progress callback for per-message/batch updates
                        def on_progress(count: int) -> None:
                            nonlocal last_count
                            delta = count - last_count
                            if delta > 0:
                                task.advance(delta)
                            last_count = count

                        if permanent:
                            await self.client.delete_messages_permanent(
                                list(archived_ids), progress_callback=on_progress
                            )
                        else:
                            await self.client.trash_messages(
                                list(archived_ids), progress_callback=on_progress
                            )
                        task.complete(f"{total_count:,} messages processed")
            else:
                if permanent:
                    await self.client.delete_messages_permanent(list(archived_ids))
                else:
                    await self.client.trash_messages(list(archived_ids))

            output = DeleteGmailOutput(
                deleted_count=len(archived_ids),
                permanent=permanent,
            )
            return StepResult.ok(output, count=len(archived_ids))

        except Exception as e:
            return StepResult.fail(f"Failed to delete messages: {e}")
