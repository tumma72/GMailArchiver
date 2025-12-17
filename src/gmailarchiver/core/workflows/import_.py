"""Workflow for importing existing mbox archives.

This workflow coordinates the import of mbox files into the database,
with support for deduplication and Gmail ID lookups.
"""

from dataclasses import dataclass

from gmailarchiver.core.importer.facade import ImporterFacade
from gmailarchiver.core.importer.facade import ImportResult as FacadeImportResult
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ImportConfig:
    """Configuration for import operation."""

    archive_patterns: list[str]  # glob patterns like "*.mbox"
    state_db: str
    dedupe: bool = True
    account_id: str = "default"


@dataclass
class ImportResult:
    """Result of import operation."""

    imported_count: int
    skipped_count: int
    duplicate_count: int
    files_processed: list[str]
    errors: list[str]
    gmail_ids_found: int = 0
    gmail_ids_not_found: int = 0


class ImportWorkflow:
    """Workflow for importing existing mbox archives."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize import workflow.

        Args:
            storage: HybridStorage instance for data operations
            progress: Optional progress reporter for status updates
        """
        self.storage = storage
        self.progress = progress
        # Initialize facade with storage's db_manager
        self.importer = ImporterFacade(
            db_manager=storage.db,
            gmail_client=None,  # Optional, can be added later if needed
        )

    async def run(self, config: ImportConfig) -> ImportResult:
        """Run the full import workflow.

        Args:
            config: ImportConfig with import settings

        Returns:
            ImportResult with operation statistics
        """
        imported_count = 0
        skipped_count = 0
        duplicate_count = 0
        files_processed: list[str] = []
        errors: list[str] = []
        gmail_ids_found = 0
        gmail_ids_not_found = 0

        # Process each pattern
        for pattern in config.archive_patterns:
            if self.progress:
                self.progress.info(f"Scanning pattern: {pattern}")

            # Use scanner to find matching files
            from gmailarchiver.core.importer._scanner import FileScanner

            scanner = FileScanner()
            matching_files = scanner.scan_pattern(pattern)

            if not matching_files:
                if self.progress:
                    self.progress.warning(f"No files found matching: {pattern}")
                continue

            # Import each file
            for file_path in matching_files:
                try:
                    if self.progress:
                        with self.progress.task_sequence() as seq:
                            with seq.task(f"Importing {file_path.name}") as task:
                                result = await self._import_single_file(
                                    str(file_path), config.account_id, config.dedupe
                                )

                                if result.messages_imported > 0:
                                    task.complete(f"Imported {result.messages_imported:,} messages")
                                elif result.messages_skipped > 0:
                                    task.complete(
                                        f"Skipped {result.messages_skipped:,} (duplicates)"
                                    )
                                else:
                                    task.complete("No new messages")
                    else:
                        result = await self._import_single_file(
                            str(file_path), config.account_id, config.dedupe
                        )

                    # Aggregate statistics
                    imported_count += result.messages_imported
                    skipped_count += result.messages_skipped
                    duplicate_count += result.messages_skipped  # Skipped = duplicates
                    gmail_ids_found += result.gmail_ids_found
                    gmail_ids_not_found += result.gmail_ids_not_found
                    files_processed.append(str(file_path))

                    # Collect errors
                    if result.errors:
                        errors.extend(result.errors)

                except Exception as e:
                    error_msg = f"Failed to import {file_path}: {str(e)}"
                    errors.append(error_msg)
                    if self.progress:
                        self.progress.error(error_msg)

        return ImportResult(
            imported_count=imported_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            files_processed=files_processed,
            errors=errors,
            gmail_ids_found=gmail_ids_found,
            gmail_ids_not_found=gmail_ids_not_found,
        )

    async def _import_single_file(
        self, file_path: str, account_id: str, skip_duplicates: bool
    ) -> FacadeImportResult:
        """Import a single file using the ImporterFacade.

        Args:
            file_path: Path to archive file
            account_id: Account identifier
            skip_duplicates: Whether to skip duplicate messages

        Returns:
            ImportResult from facade
        """
        return await self.importer.import_archive(
            archive_path=file_path,
            account_id=account_id,
            skip_duplicates=skip_duplicates,
            progress=self.progress,
        )
