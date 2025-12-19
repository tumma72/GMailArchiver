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
from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.gmail import (
    DeleteGmailInput,
    DeleteGmailMessagesStep,
    FilterGmailInput,
    FilterGmailMessagesStep,
    ScanGmailInput,
    ScanGmailMessagesStep,
)
from gmailarchiver.core.workflows.steps.validate import ValidateArchiveStep, ValidateInput
from gmailarchiver.core.workflows.steps.write import WriteMessagesInput, WriteMessagesStep
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
        self._validate_step = ValidateArchiveStep(storage.db)
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

        # 2. Execute Archiving Steps using step composition
        context = StepContext()
        context.set("compress", config.compress)
        context.set(ContextKeys.ARCHIVE_FILE, output_file)

        # Step 1: Scan Gmail for messages
        scan_result = await self._scan_step.execute(
            context, ScanGmailInput(age_threshold=config.age_threshold), self.progress
        )

        if not scan_result.success or not scan_result.data:
            return ArchiveResult(
                archived_count=0,
                skipped_count=0,
                duplicate_count=0,
                found_count=0,
                actual_file=output_file,
                gmail_query=gmail_query,
                validation_passed=True,
            )

        message_list = scan_result.data.messages
        if not message_list:
            return ArchiveResult(
                archived_count=0,
                skipped_count=0,
                duplicate_count=0,
                found_count=0,
                actual_file=output_file,
                gmail_query=gmail_query,
                validation_passed=True,
            )

        # Step 2: Filter already-archived messages
        message_ids = [msg["id"] for msg in message_list]
        filter_result = await self._filter_step.execute(
            context,
            FilterGmailInput(message_ids=message_ids, incremental=config.incremental),
            self.progress,
        )

        if not filter_result.success or not filter_result.data:
            return ArchiveResult(
                archived_count=0,
                skipped_count=0,
                duplicate_count=0,
                found_count=len(message_list),
                actual_file=output_file,
                gmail_query=gmail_query,
                validation_passed=True,
            )

        messages_to_archive = filter_result.data.to_archive
        skipped_count = filter_result.data.already_archived_count  # Already archived by Gmail ID

        # Step 3: Archive messages (if not dry run)
        # duplicate_count comes from write step (RFC Message-ID deduplication)
        archived_count = 0
        duplicate_count = 0
        interrupted = False
        actual_file = output_file

        if messages_to_archive and not config.dry_run:
            write_result = await self._write_step.execute(
                context,
                WriteMessagesInput(
                    message_ids=messages_to_archive,
                    output_file=output_file,
                    compress=config.compress,
                    gmail_query=gmail_query,
                ),
                self.progress,
            )

            if write_result.success and write_result.data:
                archived_count = write_result.data.archived_count
                duplicate_count = write_result.data.duplicate_count
                interrupted = write_result.data.interrupted
                actual_file = write_result.data.actual_file

        # Step 4: Validate (if anything was archived)
        validation_passed = True
        validation_details: dict[str, Any] | None = None

        if archived_count > 0 and not config.dry_run:
            validate_result = await self._validate_step.execute(
                context, ValidateInput(archive_path=actual_file), self.progress
            )

            if validate_result.success and validate_result.data:
                validation_passed = validate_result.data.passed
                validation_details = {
                    "count_check": validate_result.data.count_check,
                    "database_check": validate_result.data.database_check,
                    "integrity_check": validate_result.data.integrity_check,
                    "spot_check": validate_result.data.spot_check,
                    "passed": validate_result.data.passed,
                    "errors": validate_result.data.errors,
                }

        return ArchiveResult(
            archived_count=archived_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            found_count=len(message_list),
            actual_file=actual_file,
            gmail_query=gmail_query,
            interrupted=interrupted,
            validation_passed=validation_passed,
            validation_details=validation_details,
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
            processed = existing_partial.get("processed_count", 0)
            total = existing_partial.get("total_count", 0)
            if self.progress:
                self.progress.info(f"Resuming partial archive: {target}")
                self.progress.info(f"Progress: {processed:,}/{total:,} messages already archived")
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

    # Backward compatibility: Keep private methods that delegate to steps
    # These can be removed once all callers are updated

    async def _scan_messages(self, age_threshold: str) -> dict[str, Any]:
        """Scan messages from Gmail with UI feedback.

        DEPRECATED: Use ScanGmailMessagesStep directly.
        """
        context = StepContext()
        result = await self._scan_step.execute(
            context, ScanGmailInput(age_threshold=age_threshold), self.progress
        )

        if result.success and result.data:
            return {"query": result.data.gmail_query, "messages": result.data.messages}
        return {"query": "", "messages": []}

    async def _filter_messages(
        self, message_list: list[dict[str, Any]], incremental: bool
    ) -> dict[str, Any]:
        """Filter messages with UI feedback.

        DEPRECATED: Use FilterGmailMessagesStep directly.
        """
        context = StepContext()
        message_ids = [msg["id"] for msg in message_list]
        result = await self._filter_step.execute(
            context,
            FilterGmailInput(message_ids=message_ids, incremental=incremental),
            self.progress,
        )

        if result.success and result.data:
            return {
                "to_archive": result.data.to_archive,
                "skipped_count": result.data.total_skipped,
                "already_archived_count": result.data.already_archived_count,
                "duplicate_count": result.data.duplicate_count,
            }
        return {
            "to_archive": [],
            "skipped_count": 0,
            "already_archived_count": 0,
            "duplicate_count": 0,
        }

    async def _archive_messages(
        self, messages: list[str], output_file: str, compress: str | None, gmail_query: str
    ) -> dict[str, Any]:
        """Archive messages with UI feedback.

        DEPRECATED: Use WriteMessagesStep directly.
        """
        context = StepContext()
        result = await self._write_step.execute(
            context,
            WriteMessagesInput(
                message_ids=messages,
                output_file=output_file,
                compress=compress,
                gmail_query=gmail_query,
            ),
            self.progress,
        )

        if result.success and result.data:
            return {
                "archived_count": result.data.archived_count,
                "failed_count": result.data.failed_count,
                "actual_file": result.data.actual_file,
                "interrupted": result.data.interrupted,
            }
        return {"archived_count": 0, "failed_count": 0, "actual_file": output_file, "interrupted": False}

    async def _validate_archive(self, actual_file: str) -> dict[str, Any]:
        """Validate archive with UI feedback.

        DEPRECATED: Use ValidateArchiveStep directly.
        """
        context = StepContext()
        result = await self._validate_step.execute(
            context, ValidateInput(archive_path=actual_file), self.progress
        )

        if result.success and result.data:
            return {
                "count_check": result.data.count_check,
                "database_check": result.data.database_check,
                "integrity_check": result.data.integrity_check,
                "spot_check": result.data.spot_check,
                "passed": result.data.passed,
                "errors": result.data.errors,
            }
        return {"passed": False, "errors": ["Validation step failed"]}
