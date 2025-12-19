"""Validation steps for archive integrity.

This module provides steps for validating archives:
- ValidateArchiveStep: Validate archive integrity against database
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gmailarchiver.core.validator.facade import ValidatorFacade
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ValidateInput:
    """Input for ValidateArchiveStep."""

    archive_path: str
    expected_count: int | None = None  # If known, validates count matches


@dataclass
class ValidateOutput:
    """Output from ValidateArchiveStep."""

    passed: bool
    count_check: bool
    database_check: bool
    integrity_check: bool
    spot_check: bool
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class ValidateArchiveStep:
    """Step that validates archive integrity.

    Runs comprehensive validation including:
    - Message count verification
    - Database cross-check
    - Content integrity
    - Random spot-check sampling

    Input: ValidateInput with archive path
    Output: ValidateOutput with validation results
    Context: Reads ARCHIVE_FILE if input not provided; sets VALIDATION_PASSED
    """

    name = "validate_archive"
    description = "Validating archive integrity"

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize with database manager.

        Args:
            db_manager: Database manager for validation
        """
        self.db_manager = db_manager

    async def execute(
        self,
        context: StepContext,
        input_data: ValidateInput | str | None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[ValidateOutput]:
        """Validate archive integrity.

        Args:
            context: Shared step context
            input_data: ValidateInput, path string, or None to read from context
            progress: Optional progress reporter

        Returns:
            StepResult with ValidateOutput containing validation results
        """
        # Normalize input
        if isinstance(input_data, ValidateInput):
            archive_path = input_data.archive_path
        elif isinstance(input_data, str):
            archive_path = input_data
        else:
            archive_path = (
                context.get(ContextKeys.ACTUAL_FILE) or context.get(ContextKeys.ARCHIVE_FILE) or ""
            )

        if not archive_path:
            return StepResult.fail("No archive path provided for validation")

        archive_path_obj = Path(archive_path)
        if not archive_path_obj.exists():
            return StepResult.fail(f"Archive not found: {archive_path}")

        try:
            # Create validator
            validator = ValidatorFacade(
                str(archive_path),
                str(self.db_manager.db_path),
                progress=progress,
            )

            try:
                # Get archived message IDs for this archive
                archived_ids = await self.db_manager.get_message_ids_for_archive(archive_path)
                archived_ids_set = set(archived_ids)

                if progress:
                    with progress.task_sequence() as seq:
                        with seq.task("Validating archive") as task:
                            # Run comprehensive validation in thread
                            result = await asyncio.to_thread(
                                validator.validate_comprehensive, archived_ids_set
                            )

                            passed_count = sum(
                                1
                                for check in [
                                    result.count_check,
                                    result.database_check,
                                    result.integrity_check,
                                    result.spot_check,
                                ]
                                if check
                            )
                            total_checks = 4

                            if result.passed:
                                task.complete(f"Passed {passed_count}/{total_checks} checks")
                            else:
                                task.fail(
                                    f"Failed {total_checks - passed_count}/{total_checks} checks"
                                )
                else:
                    result = await asyncio.to_thread(
                        validator.validate_comprehensive, archived_ids_set
                    )

                output = ValidateOutput(
                    passed=result.passed,
                    count_check=result.count_check,
                    database_check=result.database_check,
                    integrity_check=result.integrity_check,
                    spot_check=result.spot_check,
                    errors=result.errors,
                    details={
                        "count_check": result.count_check,
                        "database_check": result.database_check,
                        "integrity_check": result.integrity_check,
                        "spot_check": result.spot_check,
                        "passed": result.passed,
                        "errors": result.errors,
                    },
                )

                context.set(ContextKeys.VALIDATION_PASSED, result.passed)
                context.set(ContextKeys.VALIDATION_DETAILS, output.details)

                return StepResult.ok(output, passed=result.passed)

            finally:
                await validator.close()

        except Exception as e:
            return StepResult.fail(f"Validation failed: {e}")
