"""Tests for ui_builder module - fluent builder for CLI output components."""

from unittest.mock import MagicMock

import pytest
from rich.console import Console

from gmailarchiver.cli.ui import (
    DEFAULT_MAX_LOGS,
    SPINNER_FRAMES,
    SYMBOLS,
    LogEntry,
    TaskHandleImpl,
    TaskSequenceImpl,
    TaskStatus,
    UIBuilderImpl,
)
from gmailarchiver.cli.ui.widgets.task import TaskWidget


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


class TestTaskHandleImpl:
    """Tests for TaskHandleImpl class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Now use TaskWidget instead of TaskState
        self.widget = TaskWidget(description="Test task")
        self.widget.start()  # Mark as running
        self.sequence = MagicMock(spec=TaskSequenceImpl)
        self.handle = TaskHandleImpl(self.widget, self.sequence)

    def test_complete_sets_success_status(self) -> None:
        """complete() sets status to SUCCESS."""
        self.handle.complete("Done!")

        assert self.widget.status == TaskStatus.SUCCESS
        assert self.widget.result_message == "Done!"
        self.sequence._refresh.assert_called()

    def test_fail_sets_failed_status(self) -> None:
        """fail() sets status to FAILED."""
        self.handle.fail("Error occurred", reason="Network timeout")

        assert self.widget.status == TaskStatus.FAILED
        assert self.widget.result_message == "Error occurred"
        assert self.widget.failure_reason == "Network timeout"
        self.sequence._refresh.assert_called()

    def test_fail_without_reason(self) -> None:
        """fail() works without a reason."""
        self.handle.fail("Error occurred")

        assert self.widget.status == TaskStatus.FAILED
        assert self.widget.failure_reason is None

    def test_advance_increments_completed(self) -> None:
        """advance() increments the completed count."""
        self.widget.total = 100
        initial = self.widget.completed

        self.handle.advance(10)

        assert self.widget.completed == initial + 10
        self.sequence._refresh.assert_called()

    def test_advance_default_is_one(self) -> None:
        """advance() defaults to incrementing by 1."""
        initial = self.widget.completed

        self.handle.advance()

        assert self.widget.completed == initial + 1

    def test_set_total(self) -> None:
        """set_total() sets the total."""
        self.handle.set_total(50)

        assert self.widget.total == 50
        self.sequence._refresh.assert_called()

    def test_log_delegates_to_sequence(self) -> None:
        """log() delegates to sequence._log()."""
        self.handle.log("Test message", "WARNING")

        self.sequence._log.assert_called_once_with("Test message", "WARNING")

    def test_set_total_with_description(self) -> None:
        """set_total() can update description."""
        self.handle.set_total(100, description="New description")

        assert self.widget.total == 100
        assert self.widget.description == "New description"
        self.sequence._refresh.assert_called()

    def test_set_total_without_description_preserves_original(self) -> None:
        """set_total() without description preserves original."""
        original_desc = self.widget.description
        self.handle.set_total(100)

        assert self.widget.total == 100
        assert self.widget.description == original_desc

    # OperationHandle compatibility tests

    def test_update_progress_delegates_to_advance(self) -> None:
        """update_progress() delegates to advance()."""
        initial = self.widget.completed

        self.handle.update_progress(5)

        assert self.widget.completed == initial + 5
        self.sequence._refresh.assert_called()

    def test_update_progress_default_is_one(self) -> None:
        """update_progress() defaults to 1."""
        initial = self.widget.completed

        self.handle.update_progress()

        assert self.widget.completed == initial + 1

    def test_set_status_updates_description(self) -> None:
        """set_status() updates task description."""
        self.handle.set_status("Processing item 50/100")

        assert self.widget.description == "Processing item 50/100"
        self.sequence._refresh.assert_called()

    def test_succeed_delegates_to_complete(self) -> None:
        """succeed() delegates to complete()."""
        self.handle.succeed("Operation finished")

        assert self.widget.status == TaskStatus.SUCCESS
        assert self.widget.result_message == "Operation finished"
        self.sequence._refresh.assert_called()

    def test_complete_pending_logs_message(self) -> None:
        """complete_pending() delegates to log()."""
        self.handle.complete_pending("Done processing")

        self.sequence._log.assert_called_once_with("Done processing", "SUCCESS")

    def test_complete_pending_with_custom_level(self) -> None:
        """complete_pending() uses custom level."""
        self.handle.complete_pending("Warning occurred", "WARNING")

        self.sequence._log.assert_called_once_with("Warning occurred", "WARNING")


class TestTaskSequenceImpl:
    """Tests for TaskSequenceImpl class."""

    def test_init_sets_attributes(self) -> None:
        """__init__ sets all attributes correctly."""
        console = MagicMock(spec=Console)
        seq = TaskSequenceImpl(console=console, json_mode=False, title="Test")

        assert seq._console is console
        assert seq._json_mode is False
        assert seq._title == "Test"
        assert seq._task_widgets == []
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
                assert len(seq._task_widgets) == 1
                assert seq._task_widgets[0].status == TaskStatus.RUNNING
                assert seq._task_widgets[0].description == "Test task"

    def test_task_with_total(self) -> None:
        """task() can be created with a total."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task", total=100) as handle:
                assert seq._task_widgets[0].total == 100

    def test_task_handle_complete(self) -> None:
        """Task handle complete() marks task as SUCCESS."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.complete("Finished!")

                assert seq._task_widgets[0].status == TaskStatus.SUCCESS
                assert seq._task_widgets[0].result_message == "Finished!"

    def test_task_handle_fail(self) -> None:
        """Task handle fail() marks task as FAILED."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with seq:
            with seq.task("Test task") as handle:
                handle.fail("Error!", reason="Timeout")

                assert seq._task_widgets[0].status == TaskStatus.FAILED
                assert seq._task_widgets[0].result_message == "Error!"
                assert seq._task_widgets[0].failure_reason == "Timeout"

    def test_exception_auto_fails_task(self) -> None:
        """Uncaught exception auto-fails the running task."""
        seq = TaskSequenceImpl(console=None, json_mode=True)

        with pytest.raises(ValueError):
            with seq:
                with seq.task("Test task") as handle:
                    raise ValueError("Test error")

        # Task should be auto-failed
        assert seq._task_widgets[0].status == TaskStatus.FAILED
        assert seq._task_widgets[0].result_message == "Exception"

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

        assert len(seq._task_widgets) == 3
        assert all(t.status == TaskStatus.SUCCESS for t in seq._task_widgets)

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
    """Tests for TaskSequenceImpl rendering via TaskWidget."""

    def test_render_pending_task(self) -> None:
        """Pending task renders with dim circle."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        widget = TaskWidget(description="Pending task")
        # Default status is PENDING
        seq._task_widgets.append(widget)

        text = widget.render(animation_frame=0)
        text_str = str(text)

        assert "○" in text_str
        assert "Pending task" in text_str

    def test_render_running_task(self) -> None:
        """Running task renders with spinner and description."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        widget = TaskWidget(description="Running task")
        widget.start()
        seq._task_widgets.append(widget)

        text = widget.render(animation_frame=0)
        text_str = str(text)

        # Should have spinner character
        assert any(frame in text_str for frame in SPINNER_FRAMES)
        assert "Running task" in text_str

    def test_render_running_task_with_progress(self) -> None:
        """Running task with progress shows count and percentage."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        widget = TaskWidget(description="Running task")
        widget.start()
        widget.total = 100
        widget.completed = 50
        seq._task_widgets.append(widget)

        text = widget.render(animation_frame=0)
        text_str = str(text)

        assert "50" in text_str
        assert "100" in text_str
        assert "50%" in text_str

    def test_render_success_task(self) -> None:
        """Success task renders with checkmark and result."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        widget = TaskWidget(description="Success task")
        widget.complete("Completed!")
        seq._task_widgets.append(widget)

        text = widget.render(animation_frame=0)
        text_str = str(text)

        assert "✓" in text_str
        assert "Success task" in text_str
        assert "Completed!" in text_str

    def test_render_failed_task(self) -> None:
        """Failed task renders with X and reason."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        widget = TaskWidget(description="Failed task")
        widget.fail("Error", reason="Network error")
        seq._task_widgets.append(widget)

        text = widget.render(animation_frame=0)
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
        assert len(seq._task_widgets) == 3
        assert all(t.status == TaskStatus.SUCCESS for t in seq._task_widgets)

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
        assert seq._task_widgets[0].status == TaskStatus.SUCCESS
        assert seq._task_widgets[1].status == TaskStatus.FAILED

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

        assert seq._task_widgets[0].total == 50
        assert seq._task_widgets[0].completed == 50


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


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_log_entry_creation(self) -> None:
        """LogEntry can be created with level and message."""
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = LogEntry(level=LogLevel.INFO, message="Test message")

        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.timestamp > 0

    def test_log_entry_with_timestamp(self) -> None:
        """LogEntry can be created with explicit timestamp."""
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = LogEntry(level=LogLevel.ERROR, message="Error!", timestamp=12345.0)

        assert entry.timestamp == 12345.0


class TestLogWindow:
    """Tests for log window functionality."""

    def test_show_logs_disabled_by_default(self) -> None:
        """Log window is disabled by default."""
        seq = TaskSequenceImpl(console=None, json_mode=True)
        assert seq._show_logs is False

    def test_show_logs_enabled(self) -> None:
        """Log window can be enabled."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True)
        assert seq._show_logs is True

    def test_max_logs_default(self) -> None:
        """Max logs has sensible default."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True)
        assert seq._max_logs == DEFAULT_MAX_LOGS

    def test_max_logs_custom(self) -> None:
        """Max logs can be customized."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True, max_logs=5)
        assert seq._max_logs == 5

    def test_log_adds_to_visible_buffer_when_show_logs(self) -> None:
        """Logs are added to visible buffer when show_logs=True."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True)

        seq._log("Test message", "INFO")

        # Now uses LogWindowWidget internally
        assert seq._log_window.visible_count == 1

    def test_log_not_added_to_visible_buffer_when_show_logs_false(self) -> None:
        """Logs are NOT added to visible buffer when show_logs=False."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=False)

        seq._log("Test message", "INFO")

        assert seq._log_window.visible_count == 0
        # But still in all logs
        assert len(seq._logs) == 1

    def test_visible_logs_ring_buffer(self) -> None:
        """Visible logs use ring buffer with max_logs limit."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True, max_logs=3)

        # Add more logs than max
        seq._log("Log 1", "INFO")
        seq._log("Log 2", "INFO")
        seq._log("Log 3", "INFO")
        seq._log("Log 4", "INFO")
        seq._log("Log 5", "INFO")

        # Should only keep last 3
        assert seq._log_window.visible_count == 3

        # All logs still stored in _logs
        assert len(seq._logs) == 5

    def test_render_log_info(self) -> None:
        """INFO log renders with info symbol."""
        from gmailarchiver.cli.ui.widgets.log_window import LogEntry as WidgetLogEntry
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = WidgetLogEntry(level=LogLevel.INFO, message="Information message")

        text = entry.render()
        text_str = str(text)

        assert "ℹ" in text_str
        assert "Information message" in text_str

    def test_render_log_warning(self) -> None:
        """WARNING log renders with warning symbol."""
        from gmailarchiver.cli.ui.widgets.log_window import LogEntry as WidgetLogEntry
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = WidgetLogEntry(level=LogLevel.WARNING, message="Warning message")

        text = entry.render()
        text_str = str(text)

        assert "⚠" in text_str
        assert "Warning message" in text_str

    def test_render_log_error(self) -> None:
        """ERROR log renders with error symbol."""
        from gmailarchiver.cli.ui.widgets.log_window import LogEntry as WidgetLogEntry
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = WidgetLogEntry(level=LogLevel.ERROR, message="Error message")

        text = entry.render()
        text_str = str(text)

        assert "✗" in text_str
        assert "Error message" in text_str

    def test_render_log_success(self) -> None:
        """SUCCESS log renders with success symbol."""
        from gmailarchiver.cli.ui.widgets.log_window import LogEntry as WidgetLogEntry
        from gmailarchiver.cli.ui.widgets.log_window import LogLevel

        entry = WidgetLogEntry(level=LogLevel.SUCCESS, message="Success message")

        text = entry.render()
        text_str = str(text)

        assert "✓" in text_str
        assert "Success message" in text_str

    def test_render_includes_log_window(self) -> None:
        """Render includes log window when show_logs=True and has logs."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=True)
        widget = TaskWidget(description="Test task")
        widget.complete("Done")
        seq._task_widgets.append(widget)
        seq._log("Log message 1", "INFO")
        seq._log("Log message 2", "SUCCESS")

        group = seq._render()

        # Should have task + log window group (separator + 2 logs)
        # Group structure: task text + Group(separator + log1 + log2)
        assert len(group.renderables) == 2  # 1 task + 1 log window group

    def test_render_no_log_window_when_disabled(self) -> None:
        """Render excludes log window when show_logs=False."""
        seq = TaskSequenceImpl(console=None, json_mode=True, show_logs=False)
        widget = TaskWidget(description="Test task")
        widget.complete("Done")
        seq._task_widgets.append(widget)
        seq._logs.append(("INFO", "Log message"))

        group = seq._render()

        # Should only have task
        assert len(group.renderables) == 1


class TestLogWindowIntegration:
    """Integration tests for log window with tasks."""

    def test_task_log_appears_in_window(self) -> None:
        """Logs from task.log() appear in log window."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence(show_logs=True) as seq:
            with seq.task("Test task") as t:
                t.log("Processing started", "INFO")
                t.log("Item 1 processed", "SUCCESS")
                t.complete("Done")

        # Check logs in visible buffer (via log window widget)
        assert seq._log_window.visible_count == 2

    def test_full_workflow_with_logs(self) -> None:
        """Full workflow with task sequence and logging."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence(show_logs=True, max_logs=5) as seq:
            with seq.task("Phase 1: Listing") as t1:
                t1.log("Searching for items...", "INFO")
                t1.log("Found 100 items", "SUCCESS")
                t1.complete("Listed 100 items")

            with seq.task("Phase 2: Processing", total=100) as t2:
                t2.log("Starting processing...", "INFO")
                for i in range(100):
                    t2.advance(1)
                t2.log("Processed all items", "SUCCESS")
                t2.complete("Processed 100 items")

        # Verify tasks
        assert len(seq._task_widgets) == 2
        assert all(t.status == TaskStatus.SUCCESS for t in seq._task_widgets)

        # Verify logs (last 5 due to max_logs)
        assert seq._log_window.visible_count <= 5

    def test_json_events_include_logs(self) -> None:
        """JSON events include log entries."""
        builder = UIBuilderImpl(console=None, json_mode=True)

        with builder.task_sequence(show_logs=True) as seq:
            with seq.task("Test") as t:
                t.log("Log message", "INFO")
                t.complete("Done")

        events = seq.get_json_events()

        # Should have: task_start, log, task_complete
        assert len(events) == 3
        log_event = events[1]
        assert log_event["event"] == "log"
        assert log_event["message"] == "Log message"
        assert log_event["level"] == "INFO"
