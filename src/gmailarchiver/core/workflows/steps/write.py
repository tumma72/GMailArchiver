"""Write steps for archiving messages.

This module provides steps for writing messages to mbox archives:
- WriteMessagesStep: Archive messages to mbox file
"""

from dataclasses import dataclass
from typing import Any

from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class WriteMessagesInput:
    """Input for WriteMessagesStep."""

    message_ids: list[str]
    output_file: str
    compress: str | None = None
    gmail_query: str | None = None


@dataclass
class WriteMessagesOutput:
    """Output from WriteMessagesStep."""

    archived_count: int
    failed_count: int
    actual_file: str
    interrupted: bool = False


class WriteMessagesStep:
    """Step that archives messages to an mbox file.

    Fetches full message content from Gmail and writes to mbox file
    with database records for tracking.

    Input: WriteMessagesInput with message IDs and output config
    Output: WriteMessagesOutput with archive statistics
    Context: Sets ARCHIVED_COUNT, ACTUAL_FILE
    """

    name = "write_messages"
    description = "Archiving messages"

    def __init__(self, archiver: ArchiverFacade) -> None:
        """Initialize with archiver facade.

        Args:
            archiver: ArchiverFacade for message writing
        """
        self.archiver = archiver

    async def execute(
        self,
        context: StepContext,
        input_data: WriteMessagesInput | None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[WriteMessagesOutput]:
        """Archive messages to mbox file.

        Args:
            context: Shared step context
            input_data: Write configuration (or None to use context)
            progress: Optional progress reporter

        Returns:
            StepResult with WriteMessagesOutput containing archive stats
        """
        # Get input from parameter or context
        if input_data:
            message_ids = input_data.message_ids
            output_file = input_data.output_file
            compress = input_data.compress
            gmail_query = input_data.gmail_query
        else:
            message_ids = context.get(ContextKeys.TO_ARCHIVE) or []
            output_file = context.get(ContextKeys.ARCHIVE_FILE) or "archive.mbox"
            compress = context.get("compress")
            gmail_query = context.get(ContextKeys.GMAIL_QUERY)

        if not message_ids:
            output = WriteMessagesOutput(
                archived_count=0,
                failed_count=0,
                actual_file=output_file,
                interrupted=False,
            )
            return StepResult.ok(output, count=0)

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Archiving messages", total=len(message_ids)) as task:
                        result = await self.archiver.archive_messages(
                            message_ids,
                            output_file,
                            compress,
                            task,  # Pass task handle for progress updates
                            gmail_query,
                        )
                        if result.get("interrupted"):
                            task.complete("Interrupted")
                        elif result["archived_count"] > 0:
                            task.complete(f"Archived {result['archived_count']:,} messages")
                        else:
                            task.complete("No messages archived")
            else:
                result = await self.archiver.archive_messages(
                    message_ids,
                    output_file,
                    compress,
                    None,
                    gmail_query,
                )

            actual_file = str(result.get("actual_file", output_file))
            archived_count = int(result.get("archived_count", 0))

            # Store in context
            context.set(ContextKeys.ARCHIVED_COUNT, archived_count)
            context.set(ContextKeys.ACTUAL_FILE, actual_file)

            output = WriteMessagesOutput(
                archived_count=archived_count,
                failed_count=int(result.get("failed_count", 0)),
                actual_file=actual_file,
                interrupted=bool(result.get("interrupted", False)),
            )
            return StepResult.ok(output, count=archived_count)

        except Exception as e:
            return StepResult.fail(f"Failed to archive messages: {e}")
