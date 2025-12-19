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

from collections.abc import Callable
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
        self._conditions: dict[int, Callable[[StepContext], bool]] = {}

    def add_step(self, step: Step) -> WorkflowComposer:
        """Add a step to the workflow.

        Args:
            step: The step to add

        Returns:
            Self for fluent chaining
        """
        self._steps.append(step)
        return self

    def add_conditional_step(
        self,
        step: Step,
        condition: Callable[[StepContext], bool],
    ) -> WorkflowComposer:
        """Add a step that only executes when condition(context) is True.

        Args:
            step: The step to add
            condition: Function that receives StepContext and returns bool

        Returns:
            Self for fluent chaining

        Example:
            def should_filter(context: StepContext) -> bool:
                return context.get("message_count", 0) > 0

            workflow = (
                WorkflowComposer("archive")
                .add_step(ScanStep())
                .add_conditional_step(FilterStep(), should_filter)
            )
        """
        step_index = len(self._steps)
        self._steps.append(step)
        self._conditions[step_index] = condition
        return self

    @property
    def steps(self) -> list[Step]:
        """Return the list of steps (read-only)."""
        return list(self._steps)

    def _should_execute_step(self, step_index: int, context: StepContext) -> bool:
        """Check if a step should execute based on its condition.

        Args:
            step_index: Index of the step to check
            context: Current workflow context

        Returns:
            True if step should execute, False if it should be skipped
        """
        if step_index in self._conditions:
            return self._conditions[step_index](context)
        return True

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

        for step_index, step in enumerate(self._steps):
            if not self._should_execute_step(step_index, context):
                continue

            # Note: Don't call progress.info() here - each step creates its own
            # task with the appropriate description. Calling info() here would
            # print text outside the Live context, causing display artifacts.

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
            Tuple of (final context, list of results for executed steps only)
            Note: Skipped conditional steps do not appear in the results list.

        Raises:
            WorkflowError: If any step fails
        """
        context = StepContext()
        results: list[StepResult[Any]] = []
        current_input = initial_input

        for step_index, step in enumerate(self._steps):
            if not self._should_execute_step(step_index, context):
                continue

            # Note: Don't call progress.info() here - each step creates its own
            # task with the appropriate description. Calling info() here would
            # print text outside the Live context, causing display artifacts.

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
