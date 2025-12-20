"""Workflow for archiving Gmail messages.

This workflow coordinates the archiving of Gmail messages using composable Steps:
1. ScanGmailMessagesStep - Scan Gmail for messages matching age criteria
2. FilterGmailMessagesStep - Filter out already-archived messages
3. WriteMessagesStep - Archive messages to mbox file
4. ValidateArchiveStep - Validate archive integrity
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import ContextKeys, StepContext, WorkflowError
from gmailarchiver.core.workflows.steps.gmail import (
    DeleteGmailInput,
    DeleteGmailMessagesStep,
    FilterGmailMessagesStep,
    ScanGmailInput,
    ScanGmailMessagesStep,
)
from gmailarchiver.core.workflows.steps.validate import ValidateArchiveStep
from gmailarchiver.core.workflows.steps.write import WriteMessagesStep
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter
from gmailarchiver.shared.utils import datetime_to_gmail_query, parse_age


@dataclass
class ArchiveConfig:
    """Configuration for archive operation."""

    age_threshold: str
    output_file: str | None = None
    compress: str | None = None
    incremental: bool = True
    dry_run: bool = False
    trash: bool = False
    delete: bool = False


@dataclass
class ArchiveResult:
    """Result of archive operation."""

    archived_count: int
    skipped_count: int
    duplicate_count: int
    found_count: int
    actual_file: str
    gmail_query: str
    interrupted: bool = False
    # Validation results
    validation_passed: bool = False
    validation_details: dict[str, Any] | None = None


class ArchiveWorkflow:
    """Workflow for archiving Gmail messages.

    Uses Step composition for reusable archive operations:
    - ScanGmailMessagesStep for listing messages
    - FilterGmailMessagesStep for duplicate detection
    - WriteMessagesStep for archiving
    - ValidateArchiveStep for integrity verification
    - DeleteGmailMessagesStep for cleanup
    """

    def __init__(
        self,
        client: GmailClient,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.client = client
        self.storage = storage
        self.progress = progress
        # Initialize facade with existing storage/client
        self.archiver = ArchiverFacade(
            gmail_client=client,
            db_manager=storage.db,
            storage=storage,
        )
        # Initialize steps
        self._scan_step = ScanGmailMessagesStep(self.archiver)
        self._filter_step = FilterGmailMessagesStep(self.archiver)
        self._write_step = WriteMessagesStep(self.archiver)
        self._validate_step = ValidateArchiveStep(storage)
        self._delete_step = DeleteGmailMessagesStep(client, storage)

    async def run(self, config: ArchiveConfig) -> ArchiveResult:
        """Run the full archive workflow."""
        # 1. Prepare Query and Output File
        try:
            cutoff_date = parse_age(config.age_threshold)
            gmail_query = f"before:{datetime_to_gmail_query(cutoff_date)}"
        except ValueError as e:
            raise ValueError(f"Invalid age threshold: {e}") from e

        output_file = await self._determine_output_file(
            config.output_file, config.compress, gmail_query
        )

        # 2. Set up context with config
        context = StepContext()
        context.set("compress", config.compress)
        context.set("dry_run", config.dry_run)
        context.set("incremental", config.incremental)
        context.set(ContextKeys.ARCHIVE_FILE, output_file)
        context.set(ContextKeys.GMAIL_QUERY, gmail_query)

        # 3. Build and run workflow using WorkflowComposer
        def should_write(ctx: StepContext) -> bool:
            return bool(ctx.get(ContextKeys.TO_ARCHIVE)) and not ctx.get("dry_run")

        def should_validate(ctx: StepContext) -> bool:
            archived_count = ctx.get(ContextKeys.ARCHIVED_COUNT, 0) or 0
            return archived_count > 0 and not ctx.get("dry_run")

        workflow = (
            WorkflowComposer("archive")
            .add_step(self._scan_step)
            .add_step(self._filter_step)
            .add_conditional_step(self._write_step, should_write)
            .add_conditional_step(self._validate_step, should_validate)
        )

        try:
            await workflow.run(
                ScanGmailInput(age_threshold=config.age_threshold),
                progress=self.progress,
                context=context,
            )
        except WorkflowError:
            # Step failed - return partial result from context
            pass

        # 4. Build result from context
        messages: list[Any] = context.get(ContextKeys.MESSAGES, []) or []
        already_archived_count: int = context.get("already_archived_count", 0) or 0

        return ArchiveResult(
            archived_count=context.get(ContextKeys.ARCHIVED_COUNT, 0) or 0,
            skipped_count=already_archived_count,
            duplicate_count=context.get(ContextKeys.DUPLICATE_COUNT, 0) or 0,
            found_count=len(messages),
            actual_file=context.get(ContextKeys.ACTUAL_FILE, output_file) or output_file,
            gmail_query=gmail_query,
            interrupted=context.get("interrupted", False) or False,
            validation_passed=context.get(ContextKeys.VALIDATION_PASSED, True) or True,
            validation_details=context.get(ContextKeys.VALIDATION_DETAILS),
        )

    async def delete_messages(self, archive_file: str, permanent: bool) -> int:
        """Delete messages that are in the archive file.

        Uses DeleteGmailMessagesStep for the operation.
        """
        context = StepContext()
        result = await self._delete_step.execute(
            context,
            DeleteGmailInput(archive_file=archive_file, permanent=permanent),
            self.progress,
        )

        if result.success and result.data:
            return result.data.deleted_count
        return 0

    async def _determine_output_file(
        self, output_file: str | None, compress: str | None, gmail_query: str
    ) -> str:
        """Determine output filename, checking for resumable sessions."""
        if output_file:
            return output_file

        # Check for existing partial session
        existing_partial = await self.storage.db.get_session_by_query(gmail_query, compress)
        if existing_partial:
            target = existing_partial["target_file"]
            # Note: Resume info is not logged here to avoid printing outside Live context.
            # The existing archive file will be used, and incremental mode will skip
            # already-archived messages automatically.
            return str(target)

        # Generate new filename
        timestamp = datetime.now().strftime("%Y%m%d")
        extension = ".mbox"
        if compress == "gzip":
            extension = ".mbox.gz"
        elif compress == "lzma":
            extension = ".mbox.xz"
        elif compress == "zstd":
            extension = ".mbox.zst"
        return f"archive_{timestamp}{extension}"
