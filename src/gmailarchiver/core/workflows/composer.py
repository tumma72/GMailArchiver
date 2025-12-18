"""Workflow composer for building and executing step-based workflows.

This module provides the WorkflowComposer class for composing Steps
into executable workflows using a fluent API.

Example:
    workflow = (
        WorkflowComposer("import")
        .add_step(ScanMboxStep())
        .add_step(CheckDuplicatesStep())
        .add_step(RecordMetadataStep())
    )

    context = await workflow.run(config, progress)
    result = ImportResult.from_context(context)
"""

from typing import Any

from gmailarchiver.core.workflows.step import (
    Step,
    StepContext,
    StepResult,
    WorkflowError,
)
from gmailarchiver.shared.protocols import ProgressReporter


class WorkflowComposer:
    """Composes steps into executable workflows.

    Provides a fluent API for building workflows from reusable steps.
    Steps are executed sequentially, with each step's output becoming
    the next step's input.

    The shared StepContext allows steps to pass additional data that
    doesn't fit the linear input/output pattern.

    Attributes:
        name: Name of this workflow (for logging/debugging)

    Example:
        # Define a workflow
        workflow = (
            WorkflowComposer("archive")
            .add_step(ScanMessagesStep())
            .add_step(FilterDuplicatesStep())
            .add_step(WriteArchiveStep())
            .add_step(ValidateArchiveStep())
        )

        # Execute it
        context = await workflow.run(initial_input, progress=reporter)
    """

    def __init__(self, name: str) -> None:
        """Initialize workflow composer.

        Args:
            name: Name of this workflow (for logging/debugging)
        """
        self.name = name
        self._steps: list[Step] = []

    def add_step(self, step: Step) -> WorkflowComposer:
        """Add a step to the workflow.

        Args:
            step: The step to add

        Returns:
            Self for fluent chaining
        """
        self._steps.append(step)
        return self

    @property
    def steps(self) -> list[Step]:
        """Return the list of steps (read-only)."""
        return list(self._steps)

    async def run(
        self,
        initial_input: Any,
        progress: ProgressReporter | None = None,
        context: StepContext | None = None,
    ) -> StepContext:
        """Execute all steps in sequence.

        Args:
            initial_input: Input data for the first step
            progress: Optional progress reporter for UI feedback
            context: Optional pre-initialized context (creates new if None)

        Returns:
            The StepContext containing all data set by steps

        Raises:
            WorkflowError: If any step fails
        """
        if context is None:
            context = StepContext()

        current_input = initial_input

        for step in self._steps:
            if progress:
                progress.info(f"Running: {step.description}")

            result: StepResult[Any] = await step.execute(context, current_input, progress)

            if not result.success:
                raise WorkflowError(step.name, result.error)

            # Pass output to next step
            current_input = result.data

            # Store step metadata in context
            if result.metadata:
                for key, value in result.metadata.items():
                    context.set(f"{step.name}.{key}", value)

        return context

    async def run_with_result(
        self,
        initial_input: Any,
        progress: ProgressReporter | None = None,
    ) -> tuple[StepContext, list[StepResult[Any]]]:
        """Execute all steps and return individual results.

        Useful for debugging or when you need access to each step's result.

        Args:
            initial_input: Input data for the first step
            progress: Optional progress reporter for UI feedback

        Returns:
            Tuple of (final context, list of all step results)

        Raises:
            WorkflowError: If any step fails
        """
        context = StepContext()
        results: list[StepResult[Any]] = []
        current_input = initial_input

        for step in self._steps:
            if progress:
                progress.info(f"Running: {step.description}")

            result: StepResult[Any] = await step.execute(context, current_input, progress)
            results.append(result)

            if not result.success:
                raise WorkflowError(step.name, result.error)

            current_input = result.data

        return context, results

    def __len__(self) -> int:
        """Return number of steps in this workflow."""
        return len(self._steps)

    def __repr__(self) -> str:
        """String representation of workflow."""
        step_names = [s.name for s in self._steps]
        return f"WorkflowComposer(name={self.name!r}, steps={step_names})"
