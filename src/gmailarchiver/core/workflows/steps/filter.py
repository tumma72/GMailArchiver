"""Filter steps for deduplication.

This module provides steps for filtering duplicate messages:
- CheckDuplicatesStep: Check messages against database and filter duplicates
"""

from dataclasses import dataclass

from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class FilterInput:
    """Input for CheckDuplicatesStep."""

    # List of (rfc_message_id, offset, length) tuples from scan step
    scanned_messages: list[tuple[str, int, int]]
    skip_duplicates: bool = True


@dataclass
class FilterOutput:
    """Output from CheckDuplicatesStep."""

    # Messages to process (not in database)
    to_process: list[tuple[str, int, int]]
    # Counts
    total_count: int
    new_count: int
    duplicate_count: int


class CheckDuplicatesStep:
    """Step that filters out duplicate messages.

    Checks scanned messages against existing RFC Message-IDs in the database
    and returns only new messages that need to be processed.

    Input: FilterInput with scanned messages and skip_duplicates flag
    Output: FilterOutput with filtered messages and counts
    Context: Reads MESSAGES if input not provided, sets TO_ARCHIVE, DUPLICATE_COUNT
    """

    name = "check_duplicates"
    description = "Checking for duplicates"

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize with database manager.

        Args:
            db_manager: Database manager for checking existing IDs
        """
        self.db_manager = db_manager

    async def execute(
        self,
        context: StepContext,
        input_data: FilterInput | list[tuple[str, int, int]] | None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[FilterOutput]:
        """Check messages against database and filter duplicates.

        Args:
            context: Shared step context
            input_data: FilterInput or list of scanned messages
            progress: Optional progress reporter

        Returns:
            StepResult with FilterOutput containing filtered messages
        """
        # Normalize input
        if isinstance(input_data, FilterInput):
            scanned_messages = input_data.scanned_messages
            skip_duplicates = input_data.skip_duplicates
        elif isinstance(input_data, list):
            scanned_messages = input_data
            skip_duplicates = True
        else:
            # Try to get from context (from previous ScanMboxStep)
            scanned_messages = context.get(ContextKeys.MESSAGES) or []
            skip_duplicates = True

        if not scanned_messages:
            return StepResult.ok(
                FilterOutput(
                    to_process=[],
                    total_count=0,
                    new_count=0,
                    duplicate_count=0,
                )
            )

        total_count = len(scanned_messages)

        if not skip_duplicates:
            # When not filtering, return all messages
            output = FilterOutput(
                to_process=scanned_messages,
                total_count=total_count,
                new_count=total_count,
                duplicate_count=0,
            )
            context.set(ContextKeys.TO_ARCHIVE, scanned_messages)
            context.set(ContextKeys.DUPLICATE_COUNT, 0)
            return StepResult.ok(output, new_count=total_count, duplicate_count=0)

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Checking existing messages") as task:
                        # Get existing RFC Message-IDs from database
                        existing_ids = await self.db_manager.get_all_rfc_message_ids()

                        # Filter out duplicates
                        to_process: list[tuple[str, int, int]] = []
                        for rfc_id, offset, length in scanned_messages:
                            if rfc_id not in existing_ids:
                                to_process.append((rfc_id, offset, length))

                        new_count = len(to_process)
                        duplicate_count = total_count - new_count

                        if duplicate_count > 0:
                            task.complete(f"{new_count:,} new, {duplicate_count:,} duplicates")
                        else:
                            task.complete(f"{new_count:,} messages to process")
            else:
                existing_ids = await self.db_manager.get_all_rfc_message_ids()
                to_process = []
                for rfc_id, offset, length in scanned_messages:
                    if rfc_id not in existing_ids:
                        to_process.append((rfc_id, offset, length))

                new_count = len(to_process)
                duplicate_count = total_count - new_count

            output = FilterOutput(
                to_process=to_process,
                total_count=total_count,
                new_count=new_count,
                duplicate_count=duplicate_count,
            )

            # Store in context for subsequent steps
            context.set(ContextKeys.TO_ARCHIVE, to_process)
            context.set(ContextKeys.DUPLICATE_COUNT, duplicate_count)
            context.set("new_count", new_count)

            return StepResult.ok(output, new_count=new_count, duplicate_count=duplicate_count)

        except Exception as e:
            return StepResult.fail(f"Failed to check duplicates: {e}")
