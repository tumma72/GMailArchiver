"""Workflow for validating archive files.

This module provides the async workflow for archive validation.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from gmailarchiver.core.validator.facade import ValidatorFacade
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ValidateConfig:
    """Configuration for validate operation."""

    archive_file: str
    state_db: str
    verbose: bool = False


@dataclass
class ValidateResult:
    """Result of validate operation."""

    passed: bool
    count_check: bool
    database_check: bool
    integrity_check: bool
    spot_check: bool
    errors: list[str]
    details: dict[str, object] | None = None


class ValidateWorkflow:
    """Workflow for validating archive files."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize validate workflow.

        Args:
            storage: HybridStorage for database access
            progress: Optional ProgressReporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: ValidateConfig) -> ValidateResult:
        """Run the full validate workflow.

        Args:
            config: ValidateConfig with archive file and database paths

        Returns:
            ValidateResult with validation status and details

        Raises:
            FileNotFoundError: If archive file doesn't exist
        """
        archive_path = Path(config.archive_file)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive file not found: {config.archive_file}")

        # Create validator facade
        validator = ValidatorFacade(
            archive_path=archive_path,
            state_db_path=config.state_db,
            progress=self.progress,
            db_manager=self.storage.db,
        )

        try:
            # Get expected message IDs from database
            archived_ids = await self.storage.get_message_ids_for_archive(config.archive_file)

            # Perform comprehensive validation
            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task("Validating archive") as task:
                        validation_result = await asyncio.to_thread(
                            validator.validate_comprehensive, archived_ids
                        )

                        if validation_result.passed:
                            task.complete("Validation passed")
                        else:
                            task.fail(f"Validation failed ({len(validation_result.errors)} errors)")
            else:
                validation_result = await asyncio.to_thread(
                    validator.validate_comprehensive, archived_ids
                )

            # Build detailed report if verbose
            details = None
            if config.verbose:
                details = {
                    "archive_file": config.archive_file,
                    "expected_count": len(archived_ids),
                    "checks": {
                        "count_check": validation_result.count_check,
                        "database_check": validation_result.database_check,
                        "integrity_check": validation_result.integrity_check,
                        "spot_check": validation_result.spot_check,
                    },
                }

            return ValidateResult(
                passed=validation_result.passed,
                count_check=validation_result.count_check,
                database_check=validation_result.database_check,
                integrity_check=validation_result.integrity_check,
                spot_check=validation_result.spot_check,
                errors=validation_result.errors,
                details=details,
            )

        finally:
            await validator.close()
