"""Tests for step infrastructure (Step, StepContext, StepResult, WorkflowComposer)."""

import pytest

from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
    WorkflowError,
)
from gmailarchiver.shared.protocols import NoOpProgressReporter


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_ok_creates_success_result(self) -> None:
        """StepResult.ok creates successful result with data."""
        result = StepResult.ok(data=42)
        assert result.success is True
        assert result.data == 42
        assert result.error is None
        assert result.metadata == {}

    def test_ok_with_metadata(self) -> None:
        """StepResult.ok can include metadata."""
        result = StepResult.ok(data="hello", count=5, duration=1.5)
        assert result.success is True
        assert result.data == "hello"
        assert result.metadata == {"count": 5, "duration": 1.5}

    def test_fail_creates_failed_result(self) -> None:
        """StepResult.fail creates failed result with error."""
        result: StepResult[str] = StepResult.fail(error="Something went wrong")
        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_fail_with_metadata(self) -> None:
        """StepResult.fail can include metadata."""
        result: StepResult[str] = StepResult.fail(error="Failed", code=500, retry=True)
        assert result.success is False
        assert result.error == "Failed"
        assert result.metadata == {"code": 500, "retry": True}


class TestStepContext:
    """Tests for StepContext shared state container."""

    def test_set_and_get(self) -> None:
        """Context can store and retrieve values."""
        context = StepContext()
        context.set("key", "value")
        assert context.get("key") == "value"

    def test_get_with_default(self) -> None:
        """Context.get returns default for missing keys."""
        context = StepContext()
        assert context.get("missing") is None
        assert context.get("missing", "default") == "default"

    def test_contains(self) -> None:
        """Context supports 'in' operator."""
        context = StepContext()
        assert "key" not in context
        context.set("key", "value")
        assert "key" in context

    def test_dict_style_access(self) -> None:
        """Context supports dict-style bracket access."""
        context = StepContext()
        context["key"] = "value"
        assert context["key"] == "value"

    def test_getitem_raises_keyerror(self) -> None:
        """Context[key] raises KeyError for missing keys."""
        context = StepContext()
        with pytest.raises(KeyError):
            _ = context["missing"]

    def test_keys(self) -> None:
        """Context.keys returns all stored keys."""
        context = StepContext()
        context.set("a", 1)
        context.set("b", 2)
        assert set(context.keys()) == {"a", "b"}

    def test_to_dict(self) -> None:
        """Context.to_dict returns copy of internal data."""
        context = StepContext()
        context.set("x", 10)
        context.set("y", 20)
        data = context.to_dict()
        assert data == {"x": 10, "y": 20}
        # Modifying the copy doesn't affect context
        data["z"] = 30
        assert "z" not in context


class TestContextKeys:
    """Tests for ContextKeys constants."""

    def test_standard_keys_are_strings(self) -> None:
        """All context keys are non-empty strings."""
        for attr in dir(ContextKeys):
            if not attr.startswith("_"):
                value = getattr(ContextKeys, attr)
                assert isinstance(value, str)
                assert len(value) > 0


class TestWorkflowError:
    """Tests for WorkflowError exception."""

    def test_error_with_message(self) -> None:
        """WorkflowError includes step name and error message."""
        error = WorkflowError("scan_mbox", "File not found")
        assert error.step_name == "scan_mbox"
        assert error.error == "File not found"
        assert "scan_mbox" in str(error)
        assert "File not found" in str(error)

    def test_error_without_message(self) -> None:
        """WorkflowError works without error message."""
        error = WorkflowError("validate", None)
        assert error.step_name == "validate"
        assert error.error is None
        assert "validate" in str(error)


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


class TestWorkflowComposer:
    """Tests for WorkflowComposer."""

    def test_add_step_returns_self(self) -> None:
        """add_step returns composer for fluent chaining."""
        composer = WorkflowComposer("test")
        result = composer.add_step(MockStep("step1"))
        assert result is composer

    def test_fluent_chaining(self) -> None:
        """Steps can be added using fluent chaining."""
        composer = (
            WorkflowComposer("test")
            .add_step(MockStep("step1"))
            .add_step(MockStep("step2"))
            .add_step(MockStep("step3"))
        )
        assert len(composer) == 3

    def test_steps_property_returns_copy(self) -> None:
        """steps property returns a copy of the steps list."""
        step = MockStep("step1")
        composer = WorkflowComposer("test").add_step(step)
        steps = composer.steps
        assert steps == [step]
        # Modifying returned list doesn't affect composer
        steps.append(MockStep("step2"))
        assert len(composer) == 1

    @pytest.mark.asyncio
    async def test_run_executes_steps_in_order(self) -> None:
        """run executes steps sequentially."""
        step1 = MockStep("step1", output="output1")
        step2 = MockStep("step2", output="output2")

        composer = WorkflowComposer("test").add_step(step1).add_step(step2)

        await composer.run("initial_input")

        assert step1.execute_called
        assert step2.execute_called
        assert step1.received_input == "initial_input"
        assert step2.received_input == "output1"

    @pytest.mark.asyncio
    async def test_run_passes_context_to_all_steps(self) -> None:
        """run passes same context to all steps."""
        step1 = MockStep("step1", output="out1")
        step2 = MockStep("step2", output="out2")

        composer = WorkflowComposer("test").add_step(step1).add_step(step2)

        await composer.run("input")

        assert step1.received_context is step2.received_context

    @pytest.mark.asyncio
    async def test_run_returns_context(self) -> None:
        """run returns the StepContext."""
        step = MockStep("step1", output="result")
        composer = WorkflowComposer("test").add_step(step)

        context = await composer.run("input")

        assert isinstance(context, StepContext)

    @pytest.mark.asyncio
    async def test_run_raises_workflow_error_on_step_failure(self) -> None:
        """run raises WorkflowError when a step fails."""
        step1 = MockStep("step1", output="ok")
        step2 = MockStep("step2", fail=True, error_msg="Something broke")
        step3 = MockStep("step3", output="never reached")

        composer = WorkflowComposer("test").add_step(step1).add_step(step2).add_step(step3)

        with pytest.raises(WorkflowError) as exc_info:
            await composer.run("input")

        assert exc_info.value.step_name == "step2"
        assert exc_info.value.error == "Something broke"
        assert not step3.execute_called

    @pytest.mark.asyncio
    async def test_run_with_progress_reporter(self) -> None:
        """run accepts progress reporter."""
        step = MockStep("step1", output="result")
        composer = WorkflowComposer("test").add_step(step)
        progress = NoOpProgressReporter()

        context = await composer.run("input", progress=progress)

        assert step.execute_called
        assert isinstance(context, StepContext)

    @pytest.mark.asyncio
    async def test_run_with_existing_context(self) -> None:
        """run can use pre-initialized context."""
        step = MockStep("step1", output="result")
        composer = WorkflowComposer("test").add_step(step)

        existing_context = StepContext()
        existing_context.set("preset_key", "preset_value")

        result_context = await composer.run("input", context=existing_context)

        assert result_context is existing_context
        assert result_context.get("preset_key") == "preset_value"

    @pytest.mark.asyncio
    async def test_run_with_result_returns_all_results(self) -> None:
        """run_with_result returns context and all step results."""
        step1 = MockStep("step1", output="out1")
        step2 = MockStep("step2", output="out2")

        composer = WorkflowComposer("test").add_step(step1).add_step(step2)

        context, results = await composer.run_with_result("input")

        assert isinstance(context, StepContext)
        assert len(results) == 2
        assert results[0].success is True
        assert results[0].data == "out1"
        assert results[1].data == "out2"

    def test_len(self) -> None:
        """len() returns number of steps."""
        composer = WorkflowComposer("test")
        assert len(composer) == 0
        composer.add_step(MockStep("s1"))
        assert len(composer) == 1
        composer.add_step(MockStep("s2"))
        assert len(composer) == 2

    def test_repr(self) -> None:
        """repr shows workflow name and steps."""
        composer = (
            WorkflowComposer("my_workflow").add_step(MockStep("scan")).add_step(MockStep("filter"))
        )
        repr_str = repr(composer)
        assert "my_workflow" in repr_str
        assert "scan" in repr_str
        assert "filter" in repr_str


class MetadataCapturingStep:
    """Step that sets metadata in its result."""

    def __init__(self, name: str, output: object, metadata: dict[str, object]) -> None:
        self._name = name
        self._output = output
        self._metadata = metadata

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Metadata step: {self._name}"

    async def execute(
        self,
        context: StepContext,
        input_data: object,
        progress: object = None,
    ) -> StepResult[object]:
        return StepResult(success=True, data=self._output, metadata=self._metadata)


class TestWorkflowComposerMetadata:
    """Tests for metadata handling in WorkflowComposer."""

    @pytest.mark.asyncio
    async def test_step_metadata_stored_in_context(self) -> None:
        """Step result metadata is stored in context with step prefix."""
        step = MetadataCapturingStep("my_step", output="result", metadata={"count": 42})
        composer = WorkflowComposer("test").add_step(step)

        context = await composer.run("input")

        assert context.get("my_step.count") == 42

    @pytest.mark.asyncio
    async def test_multiple_steps_metadata(self) -> None:
        """Multiple steps can each contribute metadata."""
        step1 = MetadataCapturingStep("scan", output="msgs", metadata={"found": 100})
        step2 = MetadataCapturingStep("filter", output="filtered", metadata={"kept": 80})

        composer = WorkflowComposer("test").add_step(step1).add_step(step2)

        context = await composer.run("input")

        assert context.get("scan.found") == 100
        assert context.get("filter.kept") == 80
