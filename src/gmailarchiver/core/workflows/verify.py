"""Verification workflow for Gmail Archiver.

This workflow handles multiple verification operations: integrity, consistency, and offsets.
Uses WorkflowComposer + Steps pattern for composable, reusable verification logic.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from gmailarchiver.core.doctor._diagnostics import CheckResult
from gmailarchiver.core.doctor.facade import Doctor
from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.core.workflows.steps.verify import (
    VerifyConsistencyStep,
    VerifyIntegrityStep,
    VerifyOffsetsStep,
)
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
    """Workflow for database and archive verification.

    Uses Step composition for reusable verification operations:
    - VerifyIntegrityStep for database integrity checks
    - VerifyConsistencyStep for database-archive consistency checks
    - VerifyOffsetsStep for mbox offset accuracy checks
    """

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize verify workflow.

        Args:
            storage: HybridStorage instance for data access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

        # Initialize steps for composable verification
        self._integrity_step = VerifyIntegrityStep()
        self._consistency_step = VerifyConsistencyStep()
        self._offsets_step = VerifyOffsetsStep()

    async def run(self, config: VerifyConfig) -> VerifyResult:
        """Execute the verification workflow.

        Args:
            config: Verification configuration

        Returns:
            VerifyResult with diagnostic outcomes

        Raises:
            ValueError: If unknown verify type
            FileNotFoundError: If database or archive file doesn't exist
        """
        # Create doctor instance
        doctor = await Doctor.create(
            db_path=config.state_db, validate_schema=False, auto_create=False
        )

        try:
            # Create context and inject doctor
            context = StepContext()
            context.set("doctor", doctor)

            # Validate verify_type is a valid VerifyType enum
            if not isinstance(config.verify_type, VerifyType):
                raise ValueError(f"Unknown verify type: {config.verify_type}")

            context.set("verify_type", config.verify_type.value)

            # Execute appropriate step based on verify type
            if config.verify_type == VerifyType.INTEGRITY:
                integrity_result = await self._integrity_step.execute(
                    context, None, progress=self.progress
                )
                return self._convert_integrity_result(integrity_result.data, config)

            elif config.verify_type == VerifyType.CONSISTENCY:
                consistency_result = await self._consistency_step.execute(
                    context, None, progress=self.progress
                )
                return self._convert_consistency_result(consistency_result.data, config)

            elif config.verify_type == VerifyType.OFFSETS:
                # For offsets, use archive_file as input if provided
                offsets_result = await self._offsets_step.execute(
                    context, config.archive_file, progress=self.progress
                )
                return self._convert_offsets_result(offsets_result.data, config)

            else:
                raise ValueError(f"Unknown verify type: {config.verify_type}")
        finally:
            await doctor.close()

    def _convert_integrity_result(
        self, check: CheckResult | None, config: VerifyConfig
    ) -> VerifyResult:
        """Convert integrity check result to VerifyResult."""
        if check is None:
            return VerifyResult(
                passed=False,
                issues_found=1,
                issues=[
                    {
                        "name": "Integrity check",
                        "severity": "ERROR",
                        "message": "Check failed",
                        "fixable": False,
                        "details": None,
                    }
                ],
                verify_type=config.verify_type.value,
            )

        issues: list[dict[str, Any]] = []
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

    def _convert_consistency_result(
        self, checks: list[CheckResult] | None, config: VerifyConfig
    ) -> VerifyResult:
        """Convert consistency check results to VerifyResult."""
        if checks is None:
            return VerifyResult(
                passed=False,
                issues_found=1,
                issues=[
                    {
                        "name": "Consistency check",
                        "severity": "ERROR",
                        "message": "Check failed",
                        "fixable": False,
                        "details": None,
                    }
                ],
                verify_type=config.verify_type.value,
            )

        passed = all(c.severity.value == "OK" for c in checks)
        issues: list[dict[str, Any]] = [
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

    def _convert_offsets_result(
        self, check: CheckResult | None, config: VerifyConfig
    ) -> VerifyResult:
        """Convert offsets check result to VerifyResult."""
        if check is None:
            return VerifyResult(
                passed=False,
                issues_found=1,
                issues=[
                    {
                        "name": "Offset check",
                        "severity": "ERROR",
                        "message": "Check failed",
                        "fixable": False,
                        "details": None,
                    }
                ],
                verify_type=config.verify_type.value,
            )

        issues: list[dict[str, Any]] = []
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
