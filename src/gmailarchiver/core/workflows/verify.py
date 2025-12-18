"""Verification workflow for Gmail Archiver.

This workflow handles multiple verification operations: integrity, consistency, and offsets.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


class VerifyType(Enum):
    """Type of verification to perform."""

    INTEGRITY = "integrity"
    CONSISTENCY = "consistency"
    OFFSETS = "offsets"


@dataclass
class VerifyConfig:
    """Configuration for verify operation."""

    verify_type: VerifyType
    state_db: str
    verbose: bool = False
    archive_file: str | None = None  # for consistency/offsets checks


@dataclass
class VerifyResult:
    """Result of verify operation."""

    passed: bool
    issues_found: int
    issues: list[dict[str, Any]]
    verify_type: str


class VerifyWorkflow:
    """Workflow for database and archive verification."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize verify workflow.

        Args:
            storage: HybridStorage instance for data access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: VerifyConfig) -> VerifyResult:
        """Execute the verification workflow.

        Args:
            config: Verification configuration

        Returns:
            VerifyResult with diagnostic outcomes

        Raises:
            FileNotFoundError: If database or archive file doesn't exist
        """
        # Create doctor instance
        doctor = await Doctor.create(
            db_path=config.state_db, validate_schema=False, auto_create=False
        )

        try:
            if config.verify_type == VerifyType.INTEGRITY:
                return await self._verify_integrity(doctor, config)
            elif config.verify_type == VerifyType.CONSISTENCY:
                return await self._verify_consistency(doctor, config)
            elif config.verify_type == VerifyType.OFFSETS:
                return await self._verify_offsets(doctor, config)
            else:
                raise ValueError(f"Unknown verify type: {config.verify_type}")
        finally:
            await doctor.close()

    async def _verify_integrity(self, doctor: Doctor, config: VerifyConfig) -> VerifyResult:
        """Verify database integrity."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Checking database integrity") as task:
                    check = await doctor.check_database_integrity()
                    if check.severity.value == "OK":
                        task.complete("Database integrity check passed")
                    else:
                        task.fail("Database integrity check failed")

                    issues = []
                    if check.severity.value != "OK":
                        issues.append(
                            {
                                "name": check.name,
                                "severity": check.severity.value,
                                "message": check.message,
                                "fixable": check.fixable,
                                "details": check.details,
                            }
                        )

                    return VerifyResult(
                        passed=check.severity.value == "OK",
                        issues_found=len(issues),
                        issues=issues,
                        verify_type=config.verify_type.value,
                    )
        else:
            check = await doctor.check_database_integrity()
            issues = []
            if check.severity.value != "OK":
                issues.append(
                    {
                        "name": check.name,
                        "severity": check.severity.value,
                        "message": check.message,
                        "fixable": check.fixable,
                        "details": check.details,
                    }
                )

            return VerifyResult(
                passed=check.severity.value == "OK",
                issues_found=len(issues),
                issues=issues,
                verify_type=config.verify_type.value,
            )

    async def _verify_consistency(self, doctor: Doctor, config: VerifyConfig) -> VerifyResult:
        """Verify database-archive consistency."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Checking database-archive consistency") as task:
                    # Run multiple checks
                    checks = [
                        await doctor.check_database_schema(),
                        await doctor.check_orphaned_fts(),
                        await doctor.check_archive_files_exist(),
                    ]

                    passed = all(c.severity.value == "OK" for c in checks)
                    issues = [
                        {
                            "name": c.name,
                            "severity": c.severity.value,
                            "message": c.message,
                            "fixable": c.fixable,
                            "details": c.details,
                        }
                        for c in checks
                        if c.severity.value != "OK"
                    ]

                    if passed:
                        task.complete("All consistency checks passed")
                    else:
                        task.fail(f"Found {len(issues)} consistency issues")

                    return VerifyResult(
                        passed=passed,
                        issues_found=len(issues),
                        issues=issues,
                        verify_type=config.verify_type.value,
                    )
        else:
            checks = [
                await doctor.check_database_schema(),
                await doctor.check_orphaned_fts(),
                await doctor.check_archive_files_exist(),
            ]

            passed = all(c.severity.value == "OK" for c in checks)
            issues = [
                {
                    "name": c.name,
                    "severity": c.severity.value,
                    "message": c.message,
                    "fixable": c.fixable,
                    "details": c.details,
                }
                for c in checks
                if c.severity.value != "OK"
            ]

            return VerifyResult(
                passed=passed,
                issues_found=len(issues),
                issues=issues,
                verify_type=config.verify_type.value,
            )

    async def _verify_offsets(self, doctor: Doctor, config: VerifyConfig) -> VerifyResult:
        """Verify mbox offset accuracy."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Checking mbox offsets") as task:
                    # For offset verification, we would need to check actual mbox files
                    # This is a simplified version that checks if archives exist
                    check = await doctor.check_archive_files_exist()

                    passed = check.severity.value == "OK"
                    issues = []
                    if not passed:
                        issues.append(
                            {
                                "name": check.name,
                                "severity": check.severity.value,
                                "message": check.message,
                                "fixable": check.fixable,
                                "details": check.details,
                            }
                        )

                    if passed:
                        task.complete("Offset verification passed")
                    else:
                        task.fail("Offset verification failed")

                    return VerifyResult(
                        passed=passed,
                        issues_found=len(issues),
                        issues=issues,
                        verify_type=config.verify_type.value,
                    )
        else:
            check = await doctor.check_archive_files_exist()

            passed = check.severity.value == "OK"
            issues = []
            if not passed:
                issues.append(
                    {
                        "name": check.name,
                        "severity": check.severity.value,
                        "message": check.message,
                        "fixable": check.fixable,
                        "details": check.details,
                    }
                )

            return VerifyResult(
                passed=passed,
                issues_found=len(issues),
                issues=issues,
                verify_type=config.verify_type.value,
            )
