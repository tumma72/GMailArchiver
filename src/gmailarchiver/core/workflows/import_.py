"""Workflow for importing existing mbox archives.

This workflow coordinates the import of mbox files into the database,
using composable Steps for scanning, filtering, and recording metadata.
"""

from dataclasses import dataclass, field
from typing import Any

from gmailarchiver.core.importer._scanner import FileScanner
from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import ContextKeys, StepContext, WorkflowError
from gmailarchiver.core.workflows.steps.filter import CheckDuplicatesStep
from gmailarchiver.core.workflows.steps.metadata import RecordMetadataStep
from gmailarchiver.core.workflows.steps.scan import MboxScanInput, ScanMboxStep
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
    errors: list[str] = field(default_factory=list)
    gmail_ids_found: int = 0
    gmail_ids_not_found: int = 0


class ImportWorkflow:
    """Workflow for importing existing mbox archives.

    Uses Step composition to build a reusable import pipeline:
    1. ScanMboxStep - Scan mbox for messages
    2. CheckDuplicatesStep - Filter out duplicates
    3. RecordMetadataStep - Write to database
    """

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize import workflow.

        Args:
            storage: HybridStorage instance for data operations
            progress: Optional progress reporter for status updates
        """
        self.storage = storage
        self.progress = progress

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

        # Process each pattern
        for pattern in config.archive_patterns:
            # Find matching files
            scanner = FileScanner()
            matching_files = scanner.scan_pattern(pattern)

            if not matching_files:
                # No files found - will be handled by CLI layer
                continue

            # Import each file using step-based workflow
            for file_path in matching_files:
                try:
                    result = await self._import_single_file(
                        str(file_path), config.account_id, config.dedupe
                    )

                    # Aggregate statistics
                    imported_count += result.get("imported_count", 0)
                    skipped_count += result.get("skipped_count", 0)
                    duplicate_count += result.get("duplicate_count", 0)
                    files_processed.append(str(file_path))

                    # Collect errors
                    if result.get("errors"):
                        errors.extend(result["errors"])

                except WorkflowError as e:
                    error_msg = f"Failed to import {file_path}: {e}"
                    errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Failed to import {file_path}: {str(e)}"
                    errors.append(error_msg)

        return ImportResult(
            imported_count=imported_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            files_processed=files_processed,
            errors=errors,
        )

    async def _import_single_file(
        self, file_path: str, account_id: str, skip_duplicates: bool
    ) -> dict[str, Any]:
        """Import a single file using step-based workflow.

        Args:
            file_path: Path to archive file
            account_id: Account identifier
            skip_duplicates: Whether to skip duplicate messages

        Returns:
            Dictionary with import statistics
        """
        # Build the import workflow from steps
        workflow = (
            WorkflowComposer("import_single")
            .add_step(ScanMboxStep())
            .add_step(CheckDuplicatesStep(self.storage.db))
            .add_step(RecordMetadataStep(self.storage.db))
        )

        # Initialize context with config
        context = StepContext()
        context.set("account_id", account_id)
        context.set("skip_duplicates", skip_duplicates)

        # Create input for first step
        scan_input = MboxScanInput(archive_path=file_path)

        # Execute workflow with progress reporting
        await workflow.run(scan_input, progress=self.progress, context=context)

        # Extract results from context
        return {
            "imported_count": context.get(ContextKeys.IMPORTED_COUNT, 0),
            "skipped_count": context.get(ContextKeys.SKIPPED_COUNT, 0),
            "duplicate_count": context.get(ContextKeys.DUPLICATE_COUNT, 0),
            "errors": context.get("errors", []),
        }
