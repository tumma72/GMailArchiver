"""Metadata steps for database operations.

This module provides steps for recording message metadata:
- RecordMetadataStep: Write message metadata to database
"""

from dataclasses import dataclass, field
from pathlib import Path

from gmailarchiver.core.importer._reader import MboxReader
from gmailarchiver.core.importer._scanner import FileScanner
from gmailarchiver.core.importer._writer import DatabaseWriter, WriteResult
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.core.workflows.steps.filter import FilterOutput
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class MetadataInput:
    """Input for RecordMetadataStep."""

    # Messages to import: list of (rfc_message_id, offset, length)
    messages_to_import: list[tuple[str, int, int]]
    archive_path: str
    account_id: str = "default"
    gmail_id_map: dict[str, str | None] = field(default_factory=dict)


@dataclass
class MetadataOutput:
    """Output from RecordMetadataStep."""

    imported_count: int
    skipped_count: int
    failed_count: int
    errors: list[str] = field(default_factory=list)


class RecordMetadataStep:
    """Step that records message metadata to database.

    Reads full message content from mbox and writes metadata to database.
    Handles decompression automatically if needed.

    Input: MetadataInput with messages to import
    Output: MetadataOutput with import statistics
    Context: Reads MBOX_PATH, TO_ARCHIVE if input not provided; sets IMPORTED_COUNT
    """

    name = "record_metadata"
    description = "Recording message metadata"

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize with database manager.

        Args:
            db_manager: Database manager for write operations
        """
        self.db_manager = db_manager

    async def execute(
        self,
        context: StepContext,
        input_data: MetadataInput | FilterOutput | None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[MetadataOutput]:
        """Record message metadata to database.

        Args:
            context: Shared step context
            input_data: MetadataInput, FilterOutput from previous step, or None to read from context
            progress: Optional progress reporter

        Returns:
            StepResult with MetadataOutput containing import statistics
        """
        # Build input from context or input_data
        # Handle FilterOutput from CheckDuplicatesStep
        if isinstance(input_data, FilterOutput):
            messages_to_import = input_data.to_process
            archive_path = context.get(ContextKeys.ARCHIVE_FILE) or ""
            account_id = context.get("account_id") or "default"
            gmail_id_map: dict[str, str | None] = context.get("gmail_id_map") or {}
        elif isinstance(input_data, MetadataInput):
            messages_to_import = input_data.messages_to_import
            archive_path = input_data.archive_path
            account_id = input_data.account_id
            gmail_id_map = input_data.gmail_id_map
        else:
            # Read from context
            messages_to_import = context.get(ContextKeys.TO_ARCHIVE) or []
            archive_path = context.get(ContextKeys.ARCHIVE_FILE) or ""
            account_id = context.get("account_id") or "default"
            gmail_id_map = context.get("gmail_id_map") or {}

        if not archive_path:
            return StepResult.fail("No archive path provided")

        if not messages_to_import:
            # Nothing to import
            output = MetadataOutput(
                imported_count=0,
                skipped_count=0,
                failed_count=0,
            )
            context.set(ContextKeys.IMPORTED_COUNT, 0)
            return StepResult.ok(output, imported_count=0)

        archive_path_obj = Path(archive_path)
        if not archive_path_obj.exists():
            return StepResult.fail(f"Archive not found: {archive_path}")

        scanner = FileScanner()
        reader = MboxReader()

        # Decompress if needed
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path_obj)

        try:
            writer = DatabaseWriter(self.db_manager)
            await writer.load_existing_ids()

            # Build offset map for quick lookup
            offset_map = {offset: (rfc_id, length) for rfc_id, offset, length in messages_to_import}

            total_to_import = len(messages_to_import)
            imported_count = 0
            skipped_count = 0
            failed_count = 0
            errors: list[str] = []

            if progress:
                with progress.task_sequence() as seq:
                    with seq.task(
                        f"Importing {total_to_import:,} messages", total=total_to_import
                    ) as task:
                        for mbox_msg in reader.read_messages(mbox_path, str(archive_path)):
                            if mbox_msg.offset not in offset_map:
                                continue

                            rfc_message_id, length = offset_map[mbox_msg.offset]

                            try:
                                # Get Gmail ID if available
                                gmail_id = gmail_id_map.get(rfc_message_id)

                                # Extract metadata
                                metadata = reader.extract_metadata(
                                    msg=mbox_msg.message,
                                    archive_path=str(archive_path),
                                    offset=mbox_msg.offset,
                                    length=mbox_msg.length,
                                    account_id=account_id,
                                    gmail_id=gmail_id,
                                )

                                # Write to database
                                result = await writer.write_message(metadata, skip_duplicates=True)

                                if result == WriteResult.IMPORTED:
                                    imported_count += 1
                                elif result == WriteResult.SKIPPED:
                                    skipped_count += 1
                                else:
                                    failed_count += 1

                            except Exception as e:
                                failed_count += 1
                                errors.append(f"Message {rfc_message_id}: {str(e)}")

                            # Update progress
                            task.advance()

                        if imported_count > 0:
                            task.complete(f"Imported {imported_count:,} messages")
                        else:
                            task.complete("No new messages imported")
            else:
                # Without progress
                for mbox_msg in reader.read_messages(mbox_path, str(archive_path)):
                    if mbox_msg.offset not in offset_map:
                        continue

                    rfc_message_id, length = offset_map[mbox_msg.offset]

                    try:
                        gmail_id = gmail_id_map.get(rfc_message_id)
                        metadata = reader.extract_metadata(
                            msg=mbox_msg.message,
                            archive_path=str(archive_path),
                            offset=mbox_msg.offset,
                            length=mbox_msg.length,
                            account_id=account_id,
                            gmail_id=gmail_id,
                        )
                        result = await writer.write_message(metadata, skip_duplicates=True)

                        if result == WriteResult.IMPORTED:
                            imported_count += 1
                        elif result == WriteResult.SKIPPED:
                            skipped_count += 1
                        else:
                            failed_count += 1

                    except Exception as e:
                        failed_count += 1
                        errors.append(f"Message {rfc_message_id}: {str(e)}")

            # Record archive run if messages were imported
            if imported_count > 0:
                await writer.record_archive_run(
                    archive_file=str(archive_path),
                    messages_count=imported_count,
                    account_id=account_id,
                )

            # Commit all changes
            await self.db_manager.commit()

            output = MetadataOutput(
                imported_count=imported_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                errors=errors,
            )

            context.set(ContextKeys.IMPORTED_COUNT, imported_count)
            context.set(ContextKeys.SKIPPED_COUNT, skipped_count)

            return StepResult.ok(
                output,
                imported_count=imported_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
            )

        except Exception as e:
            return StepResult.fail(f"Failed to record metadata: {e}")
        finally:
            scanner.cleanup_temp_file(mbox_path, is_temp)
