"""Tests for ui_builder module - fluent builder for CLI output components."""

from unittest.mock import MagicMock

import pytest
from rich.console import Console

from gmailarchiver.cli.ui_builder import (
    SPINNER_FRAMES,
    SYMBOLS,
    TaskHandleImpl,
    TaskSequenceImpl,
    TaskState,
    TaskStatus,
    UIBuilderImpl,
)


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_status_values_exist(self) -> None:
        """TaskStatus has all expected values."""
        assert TaskStatus.PENDING is not None
        assert TaskStatus.RUNNING is not None
        assert TaskStatus.SUCCESS is not None
        assert TaskStatus.FAILED is not None

    def test_symbols_mapping(self) -> None:
        """SYMBOLS dict has entries for all statuses."""
        assert TaskStatus.PENDING in SYMBOLS
        assert TaskStatus.RUNNING in SYMBOLS
        assert TaskStatus.SUCCESS in SYMBOLS
        assert TaskStatus.FAILED in SYMBOLS

    def test_success_symbol_is_checkmark(self) -> None:
        """SUCCESS status uses checkmark symbol."""
        symbol, color = SYMBOLS[TaskStatus.SUCCESS]
        assert symbol == "✓"
        assert color == "green"

    def test_failed_symbol_is_x(self) -> None:
        """FAILED status uses X symbol."""
        symbol, color = SYMBOLS[TaskStatus.FAILED]
        assert symbol == "✗"
        assert color == "red"


class TestTaskState:
    """Tests for TaskState dataclass."""

    def test_default_values(self) -> None:
        """TaskState has correct default values."""
        state = TaskState(description="Test task")

        assert state.description == "Test task"
        assert state.status == TaskStatus.PENDING
        assert state.total is None
        assert state.completed == 0
        assert state.result_message is None
        assert state.failure_reason is None
        assert state.end_time is None
        assert state.start_time is not None  # auto-populated

    def test_with_total(self) -> None:
        """TaskState can be created with a total."""
        state = TaskState(description="Test", total=100)

        assert state.total == 100


class TestTaskHandleImpl:
    """Tests for TaskHandleImpl class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.state = TaskState(description="Test task")
        self.sequence = MagicMock(spec=TaskSequenceImpl)
        self.handle = TaskHandleImpl(self.state, self.sequence)

    def test_complete_sets_success_status(self) -> None:
        """complete() sets status to SUCCESS."""
        self.handle.complete("Done!")

        assert self.state.status == TaskStatus.SUCCESS
        assert self.state.result_message == "Done!"
        assert self.state.end_time is not None
        self.sequence._refresh.assert_called()

    def test_fail_sets_failed_status(self) -> None:
        """fail() sets status to FAILED."""
        self.handle.fail("Error occurred", reason="Network timeout")

        assert self.state.status == TaskStatus.FAILED
        assert self.state.result_message == "Error occurred"
        assert self.state.failure_reason == "Network timeout"
        assert self.state.end_time is not None
        self.sequence._refresh.assert_called()

    def test_fail_without_reason(self) -> None:
        """fail() works without a reason."""
        self.handle.fail("Error occurred")

        assert self.state.status == TaskStatus.FAILED
        assert self.state.failure_reason is None

    def test_advance_increments_completed(self) -> None:
        """advance() increments the completed count."""
        self.state.total = 100
        initial = self.state.completed

        self.handle.advance(10)

        assert self.state.completed == initial + 10
        self.sequence._refresh.assert_called()

    def test_advance_default_is_one(self) -> None:
        """advance() defaults to incrementing by 1."""
        initial = self.state.completed

        self.handle.advance()

        assert self.state.completed == initial + 1

    def test_set_total(self) -> None:
        """set_total() sets the total."""
        self.handle.set_total(50)

        assert self.state.total == 50
        self.sequence._refresh.assert_called()

    def test_log_delegates_to_sequence(self) -> None:
        """log() delegates to sequence._log()."""
        self.handle.log("Test message", "WARNING")

        self.sequence._log.assert_called_once_with("Test message", "WARNING")


class TestTaskSequenceImpl:
    """Tests for TaskSequenceImpl class."""

    def test_init_sets_attributes(self) -> None:
        """__init__ sets all attributes correctly."""
        console = MagicMock(spec=Console)
        seq = TaskSequenceImpl(console=console, json_mode=False, title="Test")

        assert seq._console is console
        assert seq._json_mode is False
        assert seq._title == "Test"
        assert seq._tasks == []
        assert seq._logs == []
        assert seq._json_events == []
        assert seq._live is None

    def test_json_mode_no_live_context(self) -> None:
        """In JSON mode, no Live context is created."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            assert seq._live is None

    def test_task_creates_running_state(self) -> None:
        """task() context manager creates task with RUNNING status."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                # Task should be running
                assert len(seq._tasks) == 1
                assert seq._tasks[0].status == TaskStatus.RUNNING
                assert seq._tasks[0].description == "Test task"

    def test_task_with_total(self) -> None:
        """task() can be created with a total."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task", total=100) as handle:
                assert seq._tasks[0].total == 100

    def test_task_handle_complete(self) -> None:
        """Task handle complete() marks task as SUCCESS."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.complete("Finished!")

                assert seq._tasks[0].status == TaskStatus.SUCCESS
                assert seq._tasks[0].result_message == "Finished!"

    def test_task_handle_fail(self) -> None:
        """Task handle fail() marks task as FAILED."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.fail("Error!", reason="Timeout")

                assert seq._tasks[0].status == TaskStatus.FAILED
                assert seq._tasks[0].result_message == "Error!"
                assert seq._tasks[0].failure_reason == "Timeout"

    def test_exception_auto_fails_task(self) -> None:
        """Uncaught exception auto-fails the running task."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with pytest.raises(ValueError):
            with seq:
                with seq.task("Test task") as handle:
                    raise ValueError("Test error")

        # Task should be auto-failed
        assert seq._tasks[0].status == TaskStatus.FAILED
        assert seq._tasks[0].result_message == "Exception"

    def test_json_events_task_start(self) -> None:
        """JSON mode emits task_start event."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task", total=50) as handle:
                handle.complete("Done")

        events = seq.get_json_events()
        start_event = events[0]

        assert start_event["event"] == "task_start"
        assert start_event["description"] == "Test task"
        assert start_event["total"] == 50
        assert "timestamp" in start_event

    def test_json_events_task_complete(self) -> None:
        """JSON mode emits task_complete event."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.complete("Done")

        events = seq.get_json_events()
        complete_event = events[1]

        assert complete_event["event"] == "task_complete"
        assert complete_event["success"] is True
        assert complete_event["result"] == "Done"

    def test_json_events_task_failed(self) -> None:
        """JSON mode emits task_complete with success=False on failure."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.fail("Error", reason="Timeout")

        events = seq.get_json_events()
        complete_event = events[1]

        assert complete_event["event"] == "task_complete"
        assert complete_event["success"] is False
        assert complete_event["reason"] == "Timeout"

    def test_multiple_tasks(self) -> None:
        """Multiple tasks can be added to a sequence."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Task 1") as t1:
                t1.complete("Done 1")

            with seq.task("Task 2") as t2:
                t2.complete("Done 2")

            with seq.task("Task 3") as t3:
                t3.complete("Done 3")

        assert len(seq._tasks) == 3
        assert all(t.status == TaskStatus.SUCCESS for t in seq._tasks)

    def test_log_stores_message(self) -> None:
        """_log() stores messages in logs list."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        seq._log("Test message", "INFO")

        assert ("INFO", "Test message") in seq._logs

    def test_log_emits_json_event(self) -> None:
        """_log() emits JSON event in JSON mode."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        seq._log("Test message", "WARNING")

        events = seq.get_json_events()
        assert len(events) == 1
        assert events[0]["event"] == "log"
        assert events[0]["level"] == "WARNING"
        assert events[0]["message"] == "Test message"


class TestTaskSequenceImplRendering:
    """Tests for TaskSequenceImpl rendering."""

    def test_render_pending_task(self) -> None:
        """Pending task renders with dim circle."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        state = TaskState(description="Pending task", status=TaskStatus.PENDING)
        seq._tasks.append(state)

        text = seq._render_task(state)
        text_str = str(text)

        assert "○" in text_str
        assert "Pending task" in text_str

    def test_render_running_task(self) -> None:
        """Running task renders with spinner and description."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        state = TaskState(description="Running task", status=TaskStatus.RUNNING)
        seq._tasks.append(state)

        text = seq._render_task(state)
        text_str = str(text)

        # Should have spinner character
        assert any(frame in text_str for frame in SPINNER_FRAMES)
        assert "Running task" in text_str

    def test_render_running_task_with_progress(self) -> None:
        """Running task with progress shows count and percentage."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        state = TaskState(
            description="Running task",
            status=TaskStatus.RUNNING,
            total=100,
            completed=50,
        )
        seq._tasks.append(state)

        text = seq._render_task(state)
        text_str = str(text)

        assert "50" in text_str
        assert "100" in text_str
        assert "50%" in text_str

    def test_render_success_task(self) -> None:
        """Success task renders with checkmark and result."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        state = TaskState(
            description="Success task",
            status=TaskStatus.SUCCESS,
            result_message="Completed!",
        )
        seq._tasks.append(state)

        text = seq._render_task(state)
        text_str = str(text)

        assert "✓" in text_str
        assert "Success task" in text_str
        assert "Completed!" in text_str

    def test_render_failed_task(self) -> None:
        """Failed task renders with X and reason."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        state = TaskState(
            description="Failed task",
            status=TaskStatus.FAILED,
            result_message="Error",
            failure_reason="Network error",
        )
        seq._tasks.append(state)

        text = seq._render_task(state)
        text_str = str(text)

        assert "✗" in text_str
        assert "Failed task" in text_str
        assert "FAILED" in text_str
        assert "Network error" in text_str


class TestUIBuilderImpl:
    """Tests for UIBuilderImpl class."""

    def test_init(self) -> None:
        """UIBuilderImpl initializes with console and json_mode."""
        console = MagicMock(spec=Console)
        builder = UIBuilderImpl(console=console, json_mode=True)

        assert builder._console is console
        assert builder._json_mode is True

    def test_task_sequence_creates_sequence(self) -> None:
        """task_sequence() creates and returns a TaskSequenceImpl."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence(title="Test") as seq:
            assert isinstance(seq, TaskSequenceImpl)
            assert seq._title == "Test"

    def test_task_sequence_propagates_json_mode(self) -> None:
        """task_sequence() propagates json_mode to sequence."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence() as seq:
            assert seq._json_mode is True

    def test_spinner_creates_single_task(self) -> None:
        """spinner() is shorthand for task_sequence with one task."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.spinner("Loading...") as task:
            task.complete("Done!")

    def test_spinner_task_can_complete(self) -> None:
        """spinner() task can be marked complete."""
        builder = UIBuilderImpl(console=None, json_mode=True)
        completed = False

        with builder.spinner("Loading...") as task:
            task.complete("Finished!")
            completed = True

        assert completed

    def test_spinner_task_can_fail(self) -> None:
        """spinner() task can be marked failed."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.spinner("Loading...") as task:
            task.fail("Error occurred", reason="Timeout")


class TestUIBuilderImplIntegration:
    """Integration tests for UIBuilderImpl."""

    def test_full_task_sequence_workflow(self) -> None:
        """Full workflow with multiple tasks and progress."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence() as seq:
            # Task 1: Counting
            with seq.task("Counting items") as t1:
                total = 100
                t1.complete(f"Found {total} items")

            # Task 2: Processing with progress
            with seq.task("Processing items", total=total) as t2:
                for i in range(total):
                    t2.advance(1)
                t2.complete(f"Processed {total} items")

            # Task 3: Finalizing
            with seq.task("Finalizing") as t3:
                t3.complete("Done!")

        # Verify all tasks completed
        assert len(seq._tasks) == 3
        assert all(t.status == TaskStatus.SUCCESS for t in seq._tasks)

        # Verify JSON events
        events = seq.get_json_events()
        assert len(events) == 6  # 3 start + 3 complete

    def test_task_sequence_with_failure(self) -> None:
        """Task sequence handles failure gracefully."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence() as seq:
            with seq.task("Task 1") as t1:
                t1.complete("Done")

            with seq.task("Task 2") as t2:
                t2.fail("Error", reason="Something went wrong")

        # First task succeeded, second failed
        assert seq._tasks[0].status == TaskStatus.SUCCESS
        assert seq._tasks[1].status == TaskStatus.FAILED

    def test_late_bound_total(self) -> None:
        """Task can have total set after creation."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence() as seq:
            with seq.task("Processing") as t:
                # Discover total late
                t.set_total(50)

                for _ in range(50):
                    t.advance(1)

                t.complete("Processed 50 items")

        assert seq._tasks[0].total == 50
        assert seq._tasks[0].completed == 50


class TestSpinnerFrames:
    """Tests for spinner animation frames."""

    def test_spinner_frames_exist(self) -> None:
        """SPINNER_FRAMES has animation frames."""
        assert len(SPINNER_FRAMES) > 0

    def test_spinner_frames_are_braille(self) -> None:
        """SPINNER_FRAMES uses braille characters."""
        # Braille characters are in Unicode range U+2800-U+28FF
        for frame in SPINNER_FRAMES:
            assert len(frame) == 1
            code_point = ord(frame)
            assert 0x2800 <= code_point <= 0x28FF
