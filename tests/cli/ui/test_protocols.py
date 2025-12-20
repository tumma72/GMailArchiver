"""Tests for UI protocols."""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

from gmailarchiver.cli.ui.protocols import TaskHandle, TaskSequence, UIBuilder, Widget


class ConcreteWidget:
    """Concrete implementation of Widget protocol."""

    def render(self, output: Any) -> None:
        """Render the widget to output."""
        output.render_widget(self)

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation."""
        return {"type": "widget", "data": "test"}


class ConcreteTaskHandle:
    """Concrete implementation of TaskHandle protocol."""

    def __init__(self) -> None:
        """Initialize task handle."""
        self.status = "pending"
        self.message = None
        self.reason = None
        self.progress = 0
        self.total = None
        self.description = None

    def complete(self, message: str) -> None:
        """Mark task as successfully completed."""
        self.status = "success"
        self.message = message

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed."""
        self.status = "failed"
        self.message = message
        self.reason = reason

    def advance(self, n: int = 1) -> None:
        """Advance progress counter."""
        self.progress += n

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for progress tracking."""
        self.total = total
        if description is not None:
            self.description = description

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message within the task context."""
        pass

    def warn(self, message: str) -> None:
        """Mark task as completed with warning status."""
        self.status = "warning"
        self.message = message


class ConcreteTaskSequence:
    """Concrete implementation of TaskSequence protocol."""

    def __init__(self) -> None:
        """Initialize task sequence."""
        self.tasks: list[ConcreteTaskHandle] = []

    @contextmanager
    def task(self, description: str, total: int | None = None):
        """Create a task within the sequence."""
        handle = ConcreteTaskHandle()
        handle.description = description
        handle.total = total
        self.tasks.append(handle)
        try:
            yield handle
        finally:
            pass


class ConcreteUIBuilder:
    """Concrete implementation of UIBuilder protocol."""

    def __init__(self) -> None:
        """Initialize UI builder."""
        self.sequence = None

    @contextmanager
    def task_sequence(self, title: str | None = None, show_logs: bool = False, max_logs: int = 10):
        """Create a task sequence for multi-step operations."""
        self.sequence = ConcreteTaskSequence()
        try:
            yield self.sequence
        finally:
            pass

    @contextmanager
    def spinner(self, description: str):
        """Create a simple spinner for single operations."""
        seq = ConcreteTaskSequence()
        with seq.task(description) as handle:
            yield handle


class TestWidgetProtocol:
    """Tests for Widget protocol."""

    def test_widget_protocol_render_required(self) -> None:
        """Widget protocol requires render method."""
        assert hasattr(Widget, "render")

    def test_widget_protocol_to_json_required(self) -> None:
        """Widget protocol requires to_json method."""
        assert hasattr(Widget, "to_json")

    def test_concrete_widget_implements_protocol(self) -> None:
        """Concrete widget implements Widget protocol."""
        widget = ConcreteWidget()
        assert callable(widget.render)
        assert callable(widget.to_json)

    def test_widget_render_accepts_output_manager(self) -> None:
        """Widget render accepts OutputManager."""
        widget = ConcreteWidget()
        mock_output = MagicMock()
        widget.render(mock_output)
        mock_output.render_widget.assert_called_once_with(widget)

    def test_widget_to_json_returns_dict(self) -> None:
        """Widget to_json returns dict."""
        widget = ConcreteWidget()
        result = widget.to_json()
        assert isinstance(result, dict)
        assert "type" in result

    def test_widget_to_json_is_serializable(self) -> None:
        """Widget to_json returns JSON-serializable data."""
        import json

        widget = ConcreteWidget()
        data = widget.to_json()
        json_str = json.dumps(data)
        assert isinstance(json_str, str)


class TestTaskHandleProtocol:
    """Tests for TaskHandle protocol."""

    def test_task_handle_protocol_complete_required(self) -> None:
        """TaskHandle protocol requires complete method."""
        assert hasattr(TaskHandle, "complete")

    def test_task_handle_protocol_fail_required(self) -> None:
        """TaskHandle protocol requires fail method."""
        assert hasattr(TaskHandle, "fail")

    def test_task_handle_protocol_advance_required(self) -> None:
        """TaskHandle protocol requires advance method."""
        assert hasattr(TaskHandle, "advance")

    def test_task_handle_protocol_set_total_required(self) -> None:
        """TaskHandle protocol requires set_total method."""
        assert hasattr(TaskHandle, "set_total")

    def test_task_handle_protocol_log_required(self) -> None:
        """TaskHandle protocol requires log method."""
        assert hasattr(TaskHandle, "log")

    def test_task_handle_protocol_warn_required(self) -> None:
        """TaskHandle protocol requires warn method."""
        assert hasattr(TaskHandle, "warn")

    def test_concrete_task_handle_implements_protocol(self) -> None:
        """Concrete task handle implements TaskHandle protocol."""
        handle = ConcreteTaskHandle()
        assert callable(handle.complete)
        assert callable(handle.fail)
        assert callable(handle.advance)
        assert callable(handle.set_total)
        assert callable(handle.log)
        assert callable(handle.warn)

    def test_task_handle_complete_changes_status(self) -> None:
        """complete() changes task status to success."""
        handle = ConcreteTaskHandle()
        handle.complete("Done!")
        assert handle.status == "success"
        assert handle.message == "Done!"

    def test_task_handle_fail_changes_status(self) -> None:
        """fail() changes task status to failed."""
        handle = ConcreteTaskHandle()
        handle.fail("Error", reason="Network timeout")
        assert handle.status == "failed"
        assert handle.message == "Error"
        assert handle.reason == "Network timeout"

    def test_task_handle_fail_without_reason(self) -> None:
        """fail() works without reason parameter."""
        handle = ConcreteTaskHandle()
        handle.fail("Error")
        assert handle.status == "failed"
        assert handle.reason is None

    def test_task_handle_advance_increments_progress(self) -> None:
        """advance() increments progress counter."""
        handle = ConcreteTaskHandle()
        initial = handle.progress
        handle.advance(5)
        assert handle.progress == initial + 5

    def test_task_handle_advance_default_is_one(self) -> None:
        """advance() defaults to incrementing by 1."""
        handle = ConcreteTaskHandle()
        initial = handle.progress
        handle.advance()
        assert handle.progress == initial + 1

    def test_task_handle_set_total_sets_value(self) -> None:
        """set_total() sets total for progress."""
        handle = ConcreteTaskHandle()
        handle.set_total(100)
        assert handle.total == 100

    def test_task_handle_set_total_with_description(self) -> None:
        """set_total() can update description."""
        handle = ConcreteTaskHandle()
        handle.set_total(50, description="Processing items")
        assert handle.total == 50
        assert handle.description == "Processing items"

    def test_task_handle_log_accepts_message_and_level(self) -> None:
        """log() accepts message and optional level."""
        handle = ConcreteTaskHandle()
        # Should not raise
        handle.log("Test message")
        handle.log("Another message", "WARNING")

    def test_task_handle_warn_marks_warning_status(self) -> None:
        """warn() marks task with warning status."""
        handle = ConcreteTaskHandle()
        handle.warn("Warning message")
        assert handle.status == "warning"
        assert handle.message == "Warning message"


class TestTaskSequenceProtocol:
    """Tests for TaskSequence protocol."""

    def test_task_sequence_protocol_task_required(self) -> None:
        """TaskSequence protocol requires task method."""
        assert hasattr(TaskSequence, "task")

    def test_concrete_task_sequence_implements_protocol(self) -> None:
        """Concrete task sequence implements TaskSequence protocol."""
        seq = ConcreteTaskSequence()
        assert callable(seq.task)

    def test_task_sequence_task_is_context_manager(self) -> None:
        """task() returns a context manager."""
        seq = ConcreteTaskSequence()
        with seq.task("Test task") as handle:
            assert isinstance(handle, ConcreteTaskHandle)

    def test_task_sequence_task_with_total(self) -> None:
        """task() can specify total for progress."""
        seq = ConcreteTaskSequence()
        with seq.task("Test", total=100) as handle:
            assert handle.total == 100

    def test_task_sequence_task_without_total(self) -> None:
        """task() works without total parameter."""
        seq = ConcreteTaskSequence()
        with seq.task("Test") as handle:
            assert handle.total is None

    def test_task_sequence_creates_multiple_tasks(self) -> None:
        """TaskSequence can create multiple tasks."""
        seq = ConcreteTaskSequence()
        with seq.task("Task 1"):
            pass
        with seq.task("Task 2"):
            pass
        with seq.task("Task 3"):
            pass
        assert len(seq.tasks) == 3

    def test_task_sequence_task_descriptions_preserved(self) -> None:
        """TaskSequence preserves task descriptions."""
        seq = ConcreteTaskSequence()
        with seq.task("First task"):
            pass
        with seq.task("Second task"):
            pass
        assert seq.tasks[0].description == "First task"
        assert seq.tasks[1].description == "Second task"


class TestUIBuilderProtocol:
    """Tests for UIBuilder protocol."""

    def test_ui_builder_protocol_task_sequence_required(self) -> None:
        """UIBuilder protocol requires task_sequence method."""
        assert hasattr(UIBuilder, "task_sequence")

    def test_ui_builder_protocol_spinner_required(self) -> None:
        """UIBuilder protocol requires spinner method."""
        assert hasattr(UIBuilder, "spinner")

    def test_concrete_ui_builder_implements_protocol(self) -> None:
        """Concrete UI builder implements UIBuilder protocol."""
        builder = ConcreteUIBuilder()
        assert callable(builder.task_sequence)
        assert callable(builder.spinner)

    def test_ui_builder_task_sequence_is_context_manager(self) -> None:
        """task_sequence() returns a context manager."""
        builder = ConcreteUIBuilder()
        with builder.task_sequence() as seq:
            assert isinstance(seq, ConcreteTaskSequence)

    def test_ui_builder_task_sequence_with_title(self) -> None:
        """task_sequence() accepts title parameter."""
        builder = ConcreteUIBuilder()
        # Should not raise
        with builder.task_sequence(title="Test"):
            pass

    def test_ui_builder_task_sequence_with_show_logs(self) -> None:
        """task_sequence() accepts show_logs parameter."""
        builder = ConcreteUIBuilder()
        # Should not raise
        with builder.task_sequence(show_logs=True):
            pass

    def test_ui_builder_task_sequence_with_max_logs(self) -> None:
        """task_sequence() accepts max_logs parameter."""
        builder = ConcreteUIBuilder()
        # Should not raise
        with builder.task_sequence(max_logs=20):
            pass

    def test_ui_builder_spinner_is_context_manager(self) -> None:
        """spinner() returns a context manager."""
        builder = ConcreteUIBuilder()
        with builder.spinner("Loading...") as handle:
            assert isinstance(handle, ConcreteTaskHandle)

    def test_ui_builder_spinner_creates_single_task(self) -> None:
        """spinner() creates a single task context."""
        builder = ConcreteUIBuilder()
        with builder.spinner("Loading...") as handle:
            assert callable(handle.complete)

    def test_ui_builder_task_sequence_in_task_sequence(self) -> None:
        """TaskSequence can be used within task_sequence context."""
        builder = ConcreteUIBuilder()
        with builder.task_sequence() as seq:
            with seq.task("Task 1") as t1:
                t1.complete("Done")
            with seq.task("Task 2") as t2:
                t2.fail("Error")
        assert len(seq.tasks) == 2
        assert seq.tasks[0].status == "success"
        assert seq.tasks[1].status == "failed"

    def test_ui_builder_spinner_context_manager_protocol(self) -> None:
        """spinner() context manager follows protocol."""
        builder = ConcreteUIBuilder()
        handle = None
        with builder.spinner("Test") as h:
            handle = h
            assert hasattr(handle, "complete")
            assert hasattr(handle, "fail")
            assert hasattr(handle, "advance")


class TestProtocolComposition:
    """Tests for protocol composition and integration."""

    def test_ui_builder_creates_task_sequences(self) -> None:
        """UIBuilder can create multiple task sequences."""
        builder = ConcreteUIBuilder()

        with builder.task_sequence() as seq1:
            with seq1.task("Task 1") as t:
                t.complete("Done")

        with builder.task_sequence() as seq2:
            with seq2.task("Task 2") as t:
                t.complete("Done")

    def test_task_sequence_manages_task_lifecycle(self) -> None:
        """TaskSequence manages task creation and lifecycle."""
        seq = ConcreteTaskSequence()

        with seq.task("Processing") as handle:
            assert handle.status == "pending"
            handle.complete("Processed 100 items")
            assert handle.status == "success"

    def test_task_handle_progress_tracking(self) -> None:
        """TaskHandle tracks progress correctly."""
        handle = ConcreteTaskHandle()
        handle.set_total(100)

        for i in range(10):
            handle.advance(10)

        assert handle.progress == 100

    def test_widget_protocol_implementations(self) -> None:
        """Multiple widgets can implement protocol."""
        widget1 = ConcreteWidget()
        widget2 = ConcreteWidget()

        output = MagicMock()
        widget1.render(output)
        widget2.render(output)

        assert output.render_widget.call_count == 2

    def test_task_handle_multiple_operations(self) -> None:
        """TaskHandle supports various operations."""
        handle = ConcreteTaskHandle()

        # Setup
        handle.set_total(100, description="Processing files")
        assert handle.total == 100
        assert handle.description == "Processing files"

        # Process with progress
        for _ in range(50):
            handle.advance(1)
        assert handle.progress == 50

        # Log some activity
        handle.log("Halfway done", "INFO")

        # Complete
        handle.complete(f"Processed {handle.progress} items")
        assert handle.status == "success"

    def test_protocol_duck_typing(self) -> None:
        """Protocols work with any compatible implementation."""

        class MinimalWidget:
            def render(self, output: Any) -> None:
                pass

            def to_json(self) -> dict[str, Any]:
                return {}

        widget = MinimalWidget()
        # Should work with minimal implementation
        assert callable(widget.render)
        assert callable(widget.to_json)


class TestWidgetProtocolRendering:
    """Additional tests for Widget protocol rendering."""

    def test_widget_render_with_different_outputs(self) -> None:
        """Widget render works with any output object."""
        widget = ConcreteWidget()

        # Test with various output types
        output1 = MagicMock()
        output2 = MagicMock()
        output3 = MagicMock()

        widget.render(output1)
        widget.render(output2)
        widget.render(output3)

        output1.render_widget.assert_called_once()
        output2.render_widget.assert_called_once()
        output3.render_widget.assert_called_once()

    def test_widget_json_serialization(self) -> None:
        """Widget JSON is properly serializable."""
        import json

        widget = ConcreteWidget()
        json_data = widget.to_json()

        # Should be JSON serializable
        json_str = json.dumps(json_data)
        assert isinstance(json_str, str)
        assert isinstance(json_data, dict)


class TestTaskHandleFullWorkflow:
    """Full workflow tests for TaskHandle."""

    def test_task_complete_with_large_numbers(self) -> None:
        """TaskHandle works with large progress numbers."""
        handle = ConcreteTaskHandle()
        handle.set_total(1_000_000)

        # Advance in large increments
        for _ in range(100):
            handle.advance(10_000)

        assert handle.progress == 1_000_000

    def test_task_failure_preserves_context(self) -> None:
        """Task failure preserves all context information."""
        handle = ConcreteTaskHandle()
        handle.set_total(100, description="Data processing")

        # Advance some progress
        for _ in range(50):
            handle.advance(1)

        # Then fail
        handle.fail("Network timeout", reason="Connection lost to server")

        assert handle.status == "failed"
        assert handle.total == 100
        assert handle.description == "Data processing"
        assert handle.progress == 50
        assert handle.reason == "Connection lost to server"


class TestTaskSequenceAdvanced:
    """Advanced tests for TaskSequence."""

    def test_task_sequence_with_multiple_sequential_operations(self) -> None:
        """TaskSequence properly sequences multiple tasks."""
        seq = ConcreteTaskSequence()

        with seq.task("Download") as t1:
            t1.complete("Downloaded 100 files")

        with seq.task("Process") as t2:
            t2.advance(50)
            t2.complete("Processed all files")

        # Verify both tasks were created
        assert len(seq.tasks) == 2
        assert seq.tasks[0].description == "Download"
        assert seq.tasks[1].description == "Process"
        assert seq.tasks[0].status == "success"
        assert seq.tasks[1].status == "success"
        assert seq.tasks[1].progress == 50

    def test_task_with_late_bound_total(self) -> None:
        """TaskHandle supports setting total later."""
        seq = ConcreteTaskSequence()

        with seq.task("Discovery") as handle:
            # Don't know total yet
            assert handle.total is None

            # Discover items
            handle.set_total(42)
            assert handle.total == 42

            # Process
            for i in range(42):
                handle.advance(1)

            assert handle.progress == 42


class TestUIBuilderWithVariousScenarios:
    """Tests for UIBuilder in various scenarios."""

    def test_builder_empty_task_sequence(self) -> None:
        """UIBuilder handles empty task sequences."""
        builder = ConcreteUIBuilder()

        with builder.task_sequence() as seq:
            # Empty sequence - no tasks
            pass

        assert len(seq.tasks) == 0

    def test_builder_many_tasks(self) -> None:
        """UIBuilder handles sequences with many tasks."""
        builder = ConcreteUIBuilder()

        with builder.task_sequence() as seq:
            for i in range(20):
                with seq.task(f"Task {i + 1}") as handle:
                    handle.complete(f"Completed task {i + 1}")

        assert len(seq.tasks) == 20
        assert all(t.status == "success" for t in seq.tasks)

    def test_spinner_with_progress(self) -> None:
        """Spinner context properly manages single task."""
        builder = ConcreteUIBuilder()

        with builder.spinner("Working") as task:
            assert task.status == "pending"
            task.set_total(100)

            for _ in range(100):
                task.advance(1)

            task.complete("Done!")
            assert task.status == "success"

    def test_mixed_task_outcomes(self) -> None:
        """UIBuilder handles mix of successes and failures."""
        builder = ConcreteUIBuilder()

        with builder.task_sequence() as seq:
            with seq.task("Task 1") as t1:
                t1.complete("Success")

            with seq.task("Task 2") as t2:
                t2.fail("Error occurred", reason="Network issue")

            with seq.task("Task 3") as t3:
                t3.warn("Completed with warnings")

        statuses = [t.status for t in seq.tasks]
        assert "success" in statuses
        assert "failed" in statuses
        assert "warning" in statuses
