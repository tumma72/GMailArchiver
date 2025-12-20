"""Workflow for validating archive files.

This workflow validates archive file integrity using the Step composition
pattern via WorkflowComposer.
"""

from dataclasses import dataclass

from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.validate import ValidateArchiveStep, ValidateInput
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
    """Workflow for validating archive files.

    Uses Step composition via WorkflowComposer:
    1. ValidateArchiveStep - Performs comprehensive archive validation
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize validate workflow.

        Args:
            storage: HybridStorage for database access
            progress: Optional ProgressReporter for UI feedback
        """
        self.storage = storage
        self.progress = progress
        self._validate_step = ValidateArchiveStep(storage)

    async def run(self, config: ValidateConfig) -> ValidateResult:
        """Run the validate workflow.

        Args:
            config: ValidateConfig with archive file and options

        Returns:
            ValidateResult with validation status and details

        Raises:
            FileNotFoundError: If archive file doesn't exist
        """
        # Build workflow
        workflow = WorkflowComposer("validate").add_step(self._validate_step)

        # Create context with config
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, config.archive_file)
        context.set("verbose", config.verbose)

        # Create input
        validate_input = ValidateInput(archive_path=config.archive_file)

        # Execute workflow
        await workflow.run(validate_input, progress=self.progress, context=context)

        # Extract results from context
        validation_passed = context.get(ContextKeys.VALIDATION_PASSED, False) or False
        validation_details: dict[str, object] = context.get(ContextKeys.VALIDATION_DETAILS) or {}

        # Build detailed report if verbose
        details: dict[str, object] | None = None
        if config.verbose:
            details = {
                "archive_file": config.archive_file,
                "checks": validation_details,
            }

        # Extract check results with proper typing
        errors_list = validation_details.get("errors", [])
        errors = list(errors_list) if isinstance(errors_list, list) else []

        return ValidateResult(
            passed=validation_passed,
            count_check=bool(validation_details.get("count_check", False)),
            database_check=bool(validation_details.get("database_check", False)),
            integrity_check=bool(validation_details.get("integrity_check", False)),
            spot_check=bool(validation_details.get("spot_check", False)),
            errors=errors,
            details=details,
        )
