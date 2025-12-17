import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.validator.facade import ValidatorFacade
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
    """Workflow for archiving Gmail messages."""

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

        # 2. Execute Archiving Steps
        scan_result = await self._scan_messages(config.age_threshold)
        message_list = scan_result["messages"]

        if not message_list:
            return ArchiveResult(
                archived_count=0,
                skipped_count=0,
                duplicate_count=0,
                found_count=0,
                actual_file=output_file,
                gmail_query=gmail_query,
                validation_passed=True,  # Nothing to validate
            )

        # Filter
        filter_result = await self._filter_messages(message_list, config.incremental)
        messages_to_archive = filter_result["to_archive"]

        # Archive
        archive_stats: dict[str, Any] = {"archived_count": 0, "interrupted": False}
        if messages_to_archive and not config.dry_run:
            archive_stats = await self._archive_messages(
                messages_to_archive, output_file, config.compress, gmail_query
            )

        actual_file = str(archive_stats.get("actual_file", output_file))
        archived_count = int(archive_stats.get("archived_count", 0))

        # 3. Validate (if anything was archived)
        validation_res: dict[str, Any] = {"passed": True}
        if archived_count > 0 and not config.dry_run:
            validation_res = await self._validate_archive(actual_file)

        return ArchiveResult(
            archived_count=archived_count,
            skipped_count=filter_result["skipped_count"],
            duplicate_count=filter_result["duplicate_count"],
            found_count=len(message_list),
            actual_file=actual_file,
            gmail_query=gmail_query,
            interrupted=bool(archive_stats.get("interrupted", False)),
            validation_passed=bool(validation_res.get("passed", False)),
            validation_details=validation_res,
        )

    async def delete_messages(self, archive_file: str, permanent: bool) -> int:
        """Delete messages that are in the archive file."""
        archived_ids = await self.storage.get_message_ids_for_archive(archive_file)
        if not archived_ids:
            return 0

        if permanent:
            await self.client.delete_messages_permanent(list(archived_ids))
        else:
            await self.client.trash_messages(list(archived_ids))

        return len(archived_ids)

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

    async def _scan_messages(self, age_threshold: str) -> dict[str, Any]:
        """Scan messages from Gmail with UI feedback."""
        messages: list[dict[str, Any]] = []
        query = ""

        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Scanning messages from Gmail") as task:
                    query, messages = await self.archiver.list_messages_for_archive(
                        age_threshold, progress_callback=None
                    )
                    if messages:
                        task.complete(f"Found {len(messages):,} messages")
                    else:
                        task.complete("No messages found matching criteria")
        else:
            query, messages = await self.archiver.list_messages_for_archive(age_threshold)

        return {"query": query, "messages": messages}

    async def _filter_messages(
        self, message_list: list[dict[str, Any]], incremental: bool
    ) -> dict[str, Any]:
        """Filter messages with UI feedback."""
        all_ids = [msg["id"] for msg in message_list]

        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Checking for already archived") as task:
                    filter_result = await self.archiver.filter_already_archived(
                        all_ids, incremental
                    )

                    parts = []
                    if filter_result.already_archived_count > 0:
                        parts.append(f"{filter_result.already_archived_count:,} already archived")
                    if filter_result.duplicate_count > 0:
                        parts.append(f"{filter_result.duplicate_count:,} duplicates")

                    msg = f"{len(filter_result.to_archive):,} to archive"
                    if parts:
                        msg = f"{', '.join(parts)}, {msg}"
                    task.complete(msg)
        else:
            filter_result = await self.archiver.filter_already_archived(all_ids, incremental)

        return {
            "to_archive": filter_result.to_archive,
            "skipped_count": filter_result.total_skipped,
            "already_archived_count": filter_result.already_archived_count,
            "duplicate_count": filter_result.duplicate_count,
        }

    async def _archive_messages(
        self, messages: list[str], output_file: str, compress: str | None, gmail_query: str
    ) -> dict[str, Any]:
        """Archive messages with UI feedback."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Archiving messages", total=len(messages)) as task:
                    try:
                        result = await self.archiver.archive_messages(
                            messages, output_file, compress, task, gmail_query
                        )
                        if result.get("interrupted"):
                            task.complete("Interrupted")
                        elif result["archived_count"] > 0:
                            task.complete(f"Archived {result['archived_count']:,} messages")
                        else:
                            task.complete("No messages archived")
                        return result
                    except Exception as e:
                        task.fail(f"Archive failed: {e}")
                        raise
        else:
            return await self.archiver.archive_messages(
                messages, output_file, compress, None, gmail_query
            )

    async def _validate_archive(self, actual_file: str) -> dict[str, Any]:
        """Validate archive with UI feedback."""
        validator = ValidatorFacade(
            actual_file, str(self.storage.db.db_path), progress=self.progress
        )
        try:
            archived_ids = await self.storage.get_message_ids_for_archive(actual_file)
            result = await asyncio.to_thread(validator.validate_comprehensive, archived_ids)

            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task("Validating archive") as task:
                        check_keys = [
                            result.count_check,
                            result.database_check,
                            result.integrity_check,
                            result.spot_check,
                        ]
                        passed_count = sum(1 for check in check_keys if check)
                        total = len(check_keys)

                        if result.passed:
                            task.complete(f"Passed {passed_count}/{total} checks")
                        else:
                            task.fail(f"Failed {total - passed_count}/{total} checks")

            # Convert ValidationResult to dict for backward compatibility
            return {
                "count_check": result.count_check,
                "database_check": result.database_check,
                "integrity_check": result.integrity_check,
                "spot_check": result.spot_check,
                "passed": result.passed,
                "errors": result.errors,
            }
        finally:
            await validator.close()
