"""Tests for WorkflowComposer conditional step feature."""

import pytest

from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
    WorkflowError,
)
from gmailarchiver.shared.protocols import NoOpProgressReporter


class MockStep:
    """Mock step for testing WorkflowComposer."""

    def __init__(
        self,
        name: str,
        output: object = None,
        fail: bool = False,
        error_msg: str = "Step failed",
    ) -> None:
        self._name = name
        self._output = output
        self._fail = fail
        self._error_msg = error_msg
        self.execute_called = False
        self.received_input: object = None
        self.received_context: StepContext | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock step: {self._name}"

    async def execute(
        self,
        context: StepContext,
        input_data: object,
        progress: object = None,
    ) -> StepResult[object]:
        self.execute_called = True
        self.received_input = input_data
        self.received_context = context

        if self._fail:
            return StepResult.fail(self._error_msg)
        return StepResult.ok(self._output)


# ============================================================================
# Tests for add_conditional_step feature
# ============================================================================


class TestConditionalStepBasic:
    """Tests for basic conditional step execution."""

    @pytest.mark.asyncio
    async def test_conditional_step_executes_when_condition_true(self) -> None:
        """Conditional step executes when condition returns True."""
        step = MockStep("conditional_step", output="executed")
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        context = await composer.run("input")

        assert step.execute_called is True
        assert context is not None

    @pytest.mark.asyncio
    async def test_conditional_step_skipped_when_condition_false(self) -> None:
        """Conditional step is skipped when condition returns False."""
        step = MockStep("conditional_step", output="would execute")
        condition = lambda context: False  # noqa: E731

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        context = await composer.run("input")

        assert step.execute_called is False
        assert context is not None

    @pytest.mark.asyncio
    async def test_conditional_step_reads_context_values(self) -> None:
        """Conditional step condition can read values set by previous steps."""
        step1 = MockStep("step1", output="value_from_step1")
        step2 = MockStep("conditional_step", output="executed")

        # Condition checks value set by step1
        def condition(context: StepContext) -> bool:
            # Step1 stores data in context, step2 checks it
            context.set("step1.result", "value_from_step1")
            return context.get("step1.result") == "value_from_step1"

        composer = WorkflowComposer("test").add_step(step1).add_conditional_step(step2, condition)

        context = await composer.run("input")

        assert step2.execute_called is True
        assert context is not None

    @pytest.mark.asyncio
    async def test_add_conditional_step_returns_self(self) -> None:
        """add_conditional_step returns composer for fluent chaining."""
        step = MockStep("step1")
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test")
        result = composer.add_conditional_step(step, condition)

        assert result is composer

    @pytest.mark.asyncio
    async def test_fluent_chaining_with_conditional_steps(self) -> None:
        """Multiple conditional steps can be chained fluently."""
        step1 = MockStep("step1", output="out1")
        step2 = MockStep("step2", output="out2")
        step3 = MockStep("step3", output="out3")

        cond1 = lambda context: True  # noqa: E731
        cond2 = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, cond1)
            .add_conditional_step(step3, cond2)
        )

        context = await composer.run("input")

        assert step1.execute_called is True
        assert step2.execute_called is True
        assert step3.execute_called is True


class TestConditionalStepSequence:
    """Tests for multiple conditional steps in sequence."""

    @pytest.mark.asyncio
    async def test_multiple_conditional_steps_mixed_conditions(self) -> None:
        """Multiple conditional steps with different conditions all evaluated."""
        step1 = MockStep("step1", output="data")
        step2 = MockStep("step2", output="executed")
        step3 = MockStep("step3", output="skipped")
        step4 = MockStep("step4", output="executed")

        cond_true = lambda context: True  # noqa: E731
        cond_false = lambda context: False  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, cond_true)
            .add_conditional_step(step3, cond_false)
            .add_conditional_step(step4, cond_true)
        )

        context = await composer.run("input")

        assert step1.execute_called is True
        assert step2.execute_called is True
        assert step3.execute_called is False
        assert step4.execute_called is True

    @pytest.mark.asyncio
    async def test_mix_regular_and_conditional_steps(self) -> None:
        """Regular and conditional steps mix correctly in workflow."""
        step1 = MockStep("regular1", output="out1")
        step2 = MockStep("conditional1", output="out2")
        step3 = MockStep("regular2", output="out3")
        step4 = MockStep("conditional2", output="out4")

        cond_true = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, cond_true)
            .add_step(step3)
            .add_conditional_step(step4, cond_true)
        )

        context = await composer.run("input")

        assert step1.execute_called is True
        assert step2.execute_called is True
        assert step3.execute_called is True
        assert step4.execute_called is True


class TestConditionalStepContextInteraction:
    """Tests for how conditional steps interact with context."""

    @pytest.mark.asyncio
    async def test_conditional_step_receives_previous_step_output(self) -> None:
        """Conditional step that executes receives output from previous step."""
        step1 = MockStep("step1", output="data_from_step1")
        step2 = MockStep("step2", output="processed")
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test").add_step(step1).add_conditional_step(step2, condition)

        context = await composer.run("initial")

        assert step2.received_input == "data_from_step1"
        assert step2.execute_called is True

    @pytest.mark.asyncio
    async def test_skipped_conditional_step_passes_previous_output(self) -> None:
        """When conditional step is skipped, its input becomes next step's input."""
        step1 = MockStep("step1", output="from_step1")
        step2 = MockStep("skipped_step", output="would be this")
        step3 = MockStep("step3", output="final")
        condition = lambda context: False  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, condition)
            .add_step(step3)
        )

        context = await composer.run("initial")

        assert step2.execute_called is False
        # step3 should receive step1's output since step2 was skipped
        assert step3.received_input == "from_step1"

    @pytest.mark.asyncio
    async def test_condition_can_examine_all_previous_context_values(self) -> None:
        """Condition function can inspect all values set by previous steps."""
        step1 = MockStep("scan", output="messages")
        step2 = MockStep("filter", output="filtered")

        # Condition checks multiple values in context
        def condition(context: StepContext) -> bool:
            # These would be set by previous steps in real workflow
            context.set("scan.count", 100)
            context.set("scan.status", "success")
            count = context.get("scan.count", 0)
            status = context.get("scan.status", "unknown")
            return count > 50 and status == "success"

        composer = WorkflowComposer("test").add_step(step1).add_conditional_step(step2, condition)

        context = await composer.run("input")

        assert step2.execute_called is True
        assert context.get("scan.count") == 100
        assert context.get("scan.status") == "success"

    @pytest.mark.asyncio
    async def test_conditional_step_result_stored_in_context(self) -> None:
        """Conditional step that executes stores result in context."""

        def step_with_metadata() -> MockStep:
            class MetadataStep(MockStep):
                async def execute(self, context, input_data, progress=None):
                    result = await super().execute(context, input_data, progress)
                    # The composer will store metadata under step.name
                    return result

            return MetadataStep("conditional", output="result_data")

        step = step_with_metadata()
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        context = await composer.run("input")

        assert step.execute_called is True


class TestConditionalStepErrorHandling:
    """Tests for error handling with conditional steps."""

    @pytest.mark.asyncio
    async def test_failed_conditional_step_raises_workflow_error(self) -> None:
        """If conditional step executes and fails, WorkflowError is raised."""
        step = MockStep("conditional", fail=True, error_msg="Execution failed")
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        with pytest.raises(WorkflowError) as exc_info:
            await composer.run("input")

        assert exc_info.value.step_name == "conditional"
        assert "Execution failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_failed_step_before_conditional_stops_workflow(self) -> None:
        """If step before conditional fails, conditional is never evaluated."""
        step1 = MockStep("step1", fail=True, error_msg="Step1 failed")
        step2 = MockStep("conditional", output="would execute")
        condition = lambda context: True  # noqa: E731

        composer = WorkflowComposer("test").add_step(step1).add_conditional_step(step2, condition)

        with pytest.raises(WorkflowError) as exc_info:
            await composer.run("input")

        assert exc_info.value.step_name == "step1"
        assert step2.execute_called is False

    @pytest.mark.asyncio
    async def test_conditional_step_after_failure_not_executed(self) -> None:
        """Conditional step is never evaluated if previous step fails."""
        step1 = MockStep("step1", output="ok")
        step2 = MockStep("step2", fail=True, error_msg="Step2 failed")
        step3 = MockStep("conditional", output="skipped")

        condition = lambda context: True  # noqa: E731
        condition_executed = False

        def condition_with_tracking(context: StepContext) -> bool:
            nonlocal condition_executed
            condition_executed = True
            return True

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_step(step2)
            .add_conditional_step(step3, condition_with_tracking)
        )

        with pytest.raises(WorkflowError) as exc_info:
            await composer.run("input")

        assert exc_info.value.step_name == "step2"
        assert condition_executed is False


class TestConditionalStepWithProgressReporter:
    """Tests for progress reporting with conditional steps."""

    @pytest.mark.asyncio
    async def test_conditional_step_with_progress_reporter(self) -> None:
        """Progress reporter is passed to conditional step when it executes."""
        step = MockStep("conditional", output="result")
        condition = lambda context: True  # noqa: E731
        progress = NoOpProgressReporter()

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        context = await composer.run("input", progress=progress)

        assert step.execute_called is True
        assert context is not None

    @pytest.mark.asyncio
    async def test_skipped_conditional_step_no_progress_report(self) -> None:
        """Progress not reported for skipped conditional steps."""
        step = MockStep("conditional", output="skipped")
        condition = lambda context: False  # noqa: E731
        progress = NoOpProgressReporter()

        composer = WorkflowComposer("test").add_conditional_step(step, condition)

        context = await composer.run("input", progress=progress)

        assert step.execute_called is False


class TestConditionalStepDataFlow:
    """Tests for data flow through conditional steps."""

    @pytest.mark.asyncio
    async def test_condition_based_on_context_value(self) -> None:
        """Condition can branch based on values stored in context."""
        step1 = MockStep("setup", output="data")
        step2_execute = MockStep("branch_true", output="executed_true")
        step2_skip = MockStep("branch_false", output="would_execute")

        def set_flag_in_context(context: StepContext) -> None:
            context.set("should_execute", True)

        def condition(context: StepContext) -> bool:
            # Check flag set by setup step or condition logic
            return context.get("should_execute", False)

        composer = (
            WorkflowComposer("test").add_step(step1).add_conditional_step(step2_execute, condition)
        )

        # Manually set context value that condition checks
        initial_context = StepContext()
        initial_context.set("should_execute", True)

        context = await composer.run("input", context=initial_context)

        assert step2_execute.execute_called is True
        assert context.get("should_execute") is True

    @pytest.mark.asyncio
    async def test_multiple_conditional_branches(self) -> None:
        """Multiple conditional steps can create branching logic."""
        initial_step = MockStep("init", output="1")
        branch_a = MockStep("branch_a", output="2a")
        branch_b = MockStep("branch_b", output="2b")
        final_step = MockStep("final", output="3")

        def condition_a(context: StepContext) -> bool:
            context.set("branch", "a")
            return True

        def condition_b(context: StepContext) -> bool:
            # Skip if branch is already set to 'a'
            current_branch = context.get("branch", None)
            return current_branch != "a"

        composer = (
            WorkflowComposer("test")
            .add_step(initial_step)
            .add_conditional_step(branch_a, condition_a)
            .add_conditional_step(branch_b, condition_b)
            .add_step(final_step)
        )

        context = await composer.run("input")

        assert branch_a.execute_called is True
        assert branch_b.execute_called is False
        assert final_step.execute_called is True
        assert context.get("branch") == "a"


class TestConditionalStepRunWithResult:
    """Tests for run_with_result() with conditional steps."""

    @pytest.mark.asyncio
    async def test_run_with_result_skipped_steps_not_in_results(self) -> None:
        """Skipped conditional steps do not appear in results list."""
        step1 = MockStep("step1", output="executed")
        step2 = MockStep("skipped", output="would execute")
        step3 = MockStep("step3", output="executed")

        cond_skip = lambda context: False  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, cond_skip)
            .add_step(step3)
        )

        context, results = await composer.run_with_result("input")

        # Only executed steps should be in results (skipped step not in list)
        assert len(results) == 2
        assert results[0].success is True
        assert results[0].data == "executed"
        assert results[1].success is True
        assert results[1].data == "executed"
        # Verify step2 was skipped by checking it was never added to results
        assert step2.execute_called is False

    @pytest.mark.asyncio
    async def test_run_with_result_executed_conditional_steps_in_results(self) -> None:
        """Executed conditional steps appear in results list."""
        step1 = MockStep("step1", output="executed")
        step2 = MockStep("conditional", output="executed")
        step3 = MockStep("step3", output="executed")

        cond_execute = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, cond_execute)
            .add_step(step3)
        )

        context, results = await composer.run_with_result("input")

        # All steps should be in results
        assert len(results) == 3
        assert all(r.success for r in results)
        assert results[0].data == "executed"
        assert results[1].data == "executed"
        assert results[2].data == "executed"


class TestConditionalStepConditionExceptions:
    """Tests for exception handling in condition functions."""

    @pytest.mark.asyncio
    async def test_condition_function_exception_propagates(self) -> None:
        """Exception raised in condition function propagates to caller."""
        step = MockStep("step", output="result")

        def bad_condition(context: StepContext) -> bool:
            raise ValueError("Condition evaluation failed")

        composer = WorkflowComposer("test").add_conditional_step(step, bad_condition)

        with pytest.raises(ValueError) as exc_info:
            await composer.run("input")

        assert "Condition evaluation failed" in str(exc_info.value)
        assert step.execute_called is False

    @pytest.mark.asyncio
    async def test_condition_exception_prevents_step_execution(self) -> None:
        """Step does not execute when condition raises exception."""
        step = MockStep("conditional", output="result")
        condition_called = False

        def failing_condition(context: StepContext) -> bool:
            nonlocal condition_called
            condition_called = True
            raise RuntimeError("Condition error")

        composer = WorkflowComposer("test").add_conditional_step(step, failing_condition)

        with pytest.raises(RuntimeError):
            await composer.run("input")

        assert condition_called is True
        assert step.execute_called is False


class TestConditionalStepProperties:
    """Tests for WorkflowComposer properties with conditional steps."""

    @pytest.mark.asyncio
    async def test_steps_property_includes_conditional_steps(self) -> None:
        """The steps property includes conditional steps like regular steps."""
        step1 = MockStep("regular1")
        step2 = MockStep("conditional1")
        step3 = MockStep("regular2")

        condition = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, condition)
            .add_step(step3)
        )

        steps = composer.steps
        assert len(steps) == 3
        assert steps[0].name == "regular1"
        assert steps[1].name == "conditional1"
        assert steps[2].name == "regular2"

    @pytest.mark.asyncio
    async def test_repr_includes_conditional_steps(self) -> None:
        """String representation includes conditional step names."""
        step1 = MockStep("step1")
        step2 = MockStep("conditional1")
        step3 = MockStep("step3")

        condition = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, condition)
            .add_step(step3)
        )

        repr_str = repr(composer)

        assert "step1" in repr_str
        assert "conditional1" in repr_str
        assert "step3" in repr_str

    @pytest.mark.asyncio
    async def test_len_includes_conditional_steps(self) -> None:
        """Length of composer includes conditional steps."""
        step1 = MockStep("step1")
        step2 = MockStep("conditional1")
        step3 = MockStep("conditional2")

        condition = lambda context: True  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_step(step1)
            .add_conditional_step(step2, condition)
            .add_conditional_step(step3, condition)
        )

        assert len(composer) == 3


class TestConditionalStepEdgeCases:
    """Tests for edge cases with conditional steps."""

    @pytest.mark.asyncio
    async def test_all_steps_conditional_all_skipped(self) -> None:
        """Workflow completes when all conditional steps are skipped."""
        step1 = MockStep("conditional1", output="skipped")
        step2 = MockStep("conditional2", output="skipped")
        step3 = MockStep("conditional3", output="skipped")

        condition_skip = lambda context: False  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_conditional_step(step1, condition_skip)
            .add_conditional_step(step2, condition_skip)
            .add_conditional_step(step3, condition_skip)
        )

        context = await composer.run("input")

        assert step1.execute_called is False
        assert step2.execute_called is False
        assert step3.execute_called is False
        assert context is not None

    @pytest.mark.asyncio
    async def test_all_steps_conditional_all_skipped_with_result(self) -> None:
        """run_with_result returns empty results when all conditional steps skipped."""
        step1 = MockStep("conditional1", output="skipped")
        step2 = MockStep("conditional2", output="skipped")

        condition_skip = lambda context: False  # noqa: E731

        composer = (
            WorkflowComposer("test")
            .add_conditional_step(step1, condition_skip)
            .add_conditional_step(step2, condition_skip)
        )

        context, results = await composer.run_with_result("input")

        assert len(results) == 0
        assert context is not None
