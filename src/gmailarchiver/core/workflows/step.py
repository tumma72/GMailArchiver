"""Step protocol and base classes for workflow composition.

This module provides the foundation for composable workflow steps:
- Step: Protocol defining the interface for all workflow steps
- StepContext: Shared state dictionary for inter-step communication
- StepResult: Generic result dataclass from step execution
- WorkflowError: Exception raised when a step fails
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from gmailarchiver.shared.protocols import ProgressReporter

# Type variable for StepResult
T = TypeVar("T")


@dataclass
class StepResult[T]:
    """Result from a step execution.

    Attributes:
        success: Whether the step completed successfully
        data: The output data from the step (type T)
        error: Error message if success is False
        metadata: Additional metadata about the step execution
    """

    success: bool
    data: T | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> StepResult[T]:
        """Create a successful result."""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> StepResult[T]:
        """Create a failed result."""
        return cls(success=False, error=error, metadata=metadata)


class StepContext:
    """Shared context passed between steps in a workflow.

    Provides a type-safe dictionary-like interface for passing data
    between steps. Each step can read from and write to the context.

    Example:
        context = StepContext()
        context.set("messages", [msg1, msg2])
        messages = context.get("messages", [])
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: T | None = None) -> T | None:
        """Get a value from context, with optional default."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in context."""
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        """Check if key exists in context."""
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        """Get a value, raising KeyError if not found."""
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a value in context."""
        self._data[key] = value

    def keys(self) -> list[str]:
        """Return all keys in context."""
        return list(self._data.keys())

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the context data."""
        return dict(self._data)


class Step(Protocol):
    """Protocol for workflow steps.

    Each step is a reusable unit of work that:
    - Takes typed input and produces typed output
    - Can read from and write to shared context
    - Reports progress via ProgressReporter protocol
    - Returns a StepResult indicating success/failure

    Example implementation:
        class ScanMboxStep:
            name = "scan_mbox"
            description = "Scan mbox file for messages"

            async def execute(
                self,
                context: StepContext,
                input_data: str,  # mbox path
                progress: ProgressReporter | None = None,
            ) -> StepResult[list[MboxMessage]]:
                # ... scan mbox and return messages
    """

    @property
    def name(self) -> str:
        """Unique identifier for this step."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this step does."""
        ...

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[Any]:
        """Execute this step.

        Args:
            context: Shared context for inter-step communication
            input_data: Input data for this step
            progress: Optional progress reporter for UI feedback

        Returns:
            StepResult containing output data or error
        """
        ...


class WorkflowError(Exception):
    """Exception raised when a workflow step fails."""

    def __init__(self, step_name: str, error: str | None) -> None:
        self.step_name = step_name
        self.error = error
        message = f"Step '{step_name}' failed"
        if error:
            message += f": {error}"
        super().__init__(message)


# Common context keys used across steps
class ContextKeys:
    """Standard keys for StepContext to ensure consistency."""

    # Input data
    MBOX_PATH = "mbox_path"
    ARCHIVE_FILE = "archive_file"
    GMAIL_QUERY = "gmail_query"

    # Message data
    MESSAGES = "messages"
    MESSAGE_IDS = "message_ids"
    RFC_MESSAGE_IDS = "rfc_message_ids"

    # Filtered results
    TO_ARCHIVE = "to_archive"
    SKIPPED_COUNT = "skipped_count"
    DUPLICATE_COUNT = "duplicate_count"

    # Output data
    ARCHIVED_COUNT = "archived_count"
    IMPORTED_COUNT = "imported_count"
    ACTUAL_FILE = "actual_file"

    # Validation
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_DETAILS = "validation_details"
