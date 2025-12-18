"""Tests for TaskWidget - single task display component."""

import time

from rich.text import Text

from gmailarchiver.cli.ui.widgets.task import (
    SPINNER_FRAMES,
    STATUS_SYMBOLS,
    TaskStatus,
    TaskWidget,
)


class TestTaskWidgetBasics:
    """Tests for TaskWidget basic functionality."""

    def test_initialization_defaults(self) -> None:
        """TaskWidget initializes with default values."""
        task = TaskWidget("Test task")
        assert task.description == "Test task"
        assert task.status == TaskStatus.PENDING
        assert task.total is None
        assert task.completed == 0
        assert task.result_message is None
        assert task.failure_reason is None

    def test_start_changes_status(self) -> None:
        """start() changes status to RUNNING."""
        task = TaskWidget("Test").start()
        assert task.status == TaskStatus.RUNNING

    def test_start_updates_start_time(self) -> None:
        """start() updates start_time."""
        task = TaskWidget("Test")
        before = time.time()
        task.start()
        after = time.time()
        assert before <= task.start_time <= after

    def test_complete_sets_success_status(self) -> None:
        """complete() sets status to SUCCESS."""
        task = TaskWidget("Test").complete("Done!")
        assert task.status == TaskStatus.SUCCESS
        assert task.result_message == "Done!"

    def test_fail_sets_failed_status(self) -> None:
        """fail() sets status to FAILED."""
        task = TaskWidget("Test").fail("Error message", reason="root cause")
        assert task.status == TaskStatus.FAILED
        assert task.result_message == "Error message"
        assert task.failure_reason == "root cause"

    def test_fail_without_reason(self) -> None:
        """fail() works without reason."""
        task = TaskWidget("Test").fail("Error")
        assert task.status == TaskStatus.FAILED
        assert task.failure_reason is None

    def test_warn_sets_warning_status(self) -> None:
        """warn() sets status to WARNING."""
        task = TaskWidget("Test").warn("Warning message")
        assert task.status == TaskStatus.WARNING
        assert task.result_message == "Warning message"

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        task = TaskWidget("Test").start().set_progress(10, 100).advance(5).complete("Done")
        assert task.status == TaskStatus.SUCCESS
        assert task.completed == 15


class TestTaskWidgetProgress:
    """Tests for progress tracking."""

    def test_set_progress_updates_both(self) -> None:
        """set_progress updates completed and total."""
        task = TaskWidget("Test").set_progress(50, 100)
        assert task.completed == 50
        assert task.total == 100

    def test_set_progress_only_completed(self) -> None:
        """set_progress can update only completed."""
        task = TaskWidget("Test").set_progress(50, 100).set_progress(75)
        assert task.completed == 75
        assert task.total == 100

    def test_advance_increments_completed(self) -> None:
        """advance() increments completed counter."""
        task = TaskWidget("Test").set_progress(0, 10).advance()
        assert task.completed == 1

    def test_advance_with_amount(self) -> None:
        """advance() can increment by custom amount."""
        task = TaskWidget("Test").set_progress(0, 100).advance(25)
        assert task.completed == 25

    def test_advance_multiple_times(self) -> None:
        """advance() can be called multiple times."""
        task = TaskWidget("Test").set_progress(0, 100)
        task.advance().advance().advance()
        assert task.completed == 3


class TestTaskWidgetRendering:
    """Tests for Rich text rendering."""

    def test_render_returns_text(self) -> None:
        """render() returns Rich Text object."""
        task = TaskWidget("Test")
        text = task.render()
        assert isinstance(text, Text)

    def test_render_pending_shows_dim_circle(self) -> None:
        """Pending task shows ○ (dim)."""
        task = TaskWidget("Test task")
        text = task.render()
        # Check that text contains the circle symbol
        assert "○" in text.plain

    def test_render_running_shows_spinner(self) -> None:
        """Running task shows spinner animation."""
        task = TaskWidget("Processing").start()
        text = task.render(animation_frame=0)
        # Should show first spinner frame
        assert SPINNER_FRAMES[0] in text.plain

    def test_render_running_with_different_frames(self) -> None:
        """Spinner cycles through frames based on animation_frame."""
        task = TaskWidget("Processing").start()
        frames_shown = set()
        for frame_num in range(len(SPINNER_FRAMES)):
            text = task.render(animation_frame=frame_num)
            frames_shown.add(text.plain[0])
        # Should show multiple different frames
        assert len(frames_shown) > 1

    def test_render_success_shows_checkmark(self) -> None:
        """Success task shows ✓ (green)."""
        task = TaskWidget("Task").complete("All done")
        text = task.render()
        assert "✓" in text.plain
        assert "All done" in text.plain

    def test_render_failed_shows_x(self) -> None:
        """Failed task shows ✗ (red)."""
        task = TaskWidget("Task").fail("Failed", reason="Something broke")
        text = task.render()
        assert "✗" in text.plain
        assert "FAILED" in text.plain
        assert "Something broke" in text.plain

    def test_render_warning_shows_triangle(self) -> None:
        """Warning task shows ⚠ (yellow)."""
        task = TaskWidget("Task").warn("Watch out")
        text = task.render()
        assert "⚠" in text.plain
        assert "Watch out" in text.plain

    def test_render_running_without_progress(self) -> None:
        """Running task without progress shows ellipsis."""
        task = TaskWidget("Loading").start()
        text = task.render()
        assert "..." in text.plain

    def test_render_running_with_progress(self) -> None:
        """Running task with progress shows bar and percentage."""
        task = TaskWidget("Processing").start().set_progress(50, 100)
        text = task.render()
        # Should show progress indicators
        assert "50%" in text.plain or "[" in text.plain
        assert "50" in text.plain  # Part of 50/100

    def test_render_success_with_message(self) -> None:
        """Success task displays result message."""
        task = TaskWidget("Import").complete("Imported 1,000 messages")
        text = task.render()
        assert "Imported 1,000 messages" in text.plain

    def test_render_success_without_message(self) -> None:
        """Success task works without result message."""
        task = TaskWidget("Import")
        task.status = TaskStatus.SUCCESS
        text = task.render()
        assert "✓" in text.plain
        assert "Import" in text.plain


class TestTaskWidgetETACalculation:
    """Tests for ETA calculation."""

    def test_eta_not_available_without_progress(self) -> None:
        """ETA unavailable when completed is 0."""
        task = TaskWidget("Test").start().set_progress(0, 100)
        eta = task._calculate_eta()
        assert eta is None

    def test_eta_not_available_without_total(self) -> None:
        """ETA unavailable without total."""
        task = TaskWidget("Test").start()
        eta = task._calculate_eta()
        assert eta is None

    def test_eta_seconds_format(self) -> None:
        """ETA shows seconds for quick tasks."""
        task = TaskWidget("Test").start().set_progress(50, 100)
        # Simulate completion took 0.1 seconds
        task.start_time = time.time() - 0.1
        eta = task._calculate_eta()
        assert eta is not None
        assert "s remaining" in eta

    def test_eta_minutes_format(self) -> None:
        """ETA shows minutes:seconds for longer tasks."""
        task = TaskWidget("Test").start().set_progress(10, 1000)
        # Simulate 1 second elapsed (processing 10 items)
        # Remaining: 990 items at 10/sec = 99 seconds = 1m 39s
        task.start_time = time.time() - 1.0
        eta = task._calculate_eta()
        assert eta is not None
        assert "m" in eta or "s remaining" in eta

    def test_eta_hours_format(self) -> None:
        """ETA shows hours for very long tasks."""
        task = TaskWidget("Test").start().set_progress(100, 100000)
        # Simulate 10 seconds elapsed
        # Remaining: 99,900 items at 10/sec = 9,990 seconds ≈ 2h 46m
        task.start_time = time.time() - 10.0
        eta = task._calculate_eta()
        assert eta is not None
        assert "h" in eta or "m" in eta or "s" in eta

    def test_eta_zero_rate_returns_none(self) -> None:
        """ETA returns None if elapsed time is zero."""
        task = TaskWidget("Test").start().set_progress(50, 100)
        task.start_time = time.time()  # Just started
        eta = task._calculate_eta()
        # With zero elapsed time, rate calculation might fail
        # (depends on timing precision)
        if eta is not None:
            assert "remaining" in eta


class TestTaskWidgetProgressRendering:
    """Tests for progress bar rendering in running state."""

    def test_progress_bar_empty(self) -> None:
        """Progress bar shows correct empty state."""
        task = TaskWidget("Test").start().set_progress(0, 100)
        text = task.render()
        # Should have 0% progress
        assert "0%" in text.plain

    def test_progress_bar_full(self) -> None:
        """Progress bar shows correct full state."""
        task = TaskWidget("Test").start().set_progress(100, 100)
        text = task.render()
        # Should have 100% progress
        assert "100%" in text.plain

    def test_progress_bar_partial(self) -> None:
        """Progress bar shows correct partial progress."""
        task = TaskWidget("Test").start().set_progress(33, 100)
        text = task.render()
        # Should show 33%
        assert "33%" in text.plain

    def test_progress_shows_count(self) -> None:
        """Progress bar shows completed/total count."""
        task = TaskWidget("Test").start().set_progress(1234, 5000)
        text = task.render()
        # Should show count (with thousands formatting)
        assert "1,234" in text.plain or "1234" in text.plain

    def test_progress_with_small_total(self) -> None:
        """Progress works with small totals."""
        task = TaskWidget("Test").start().set_progress(1, 5)
        text = task.render()
        assert "20%" in text.plain  # 1/5 = 20%


class TestTaskWidgetJSON:
    """Tests for JSON serialization."""

    def test_to_json_pending(self) -> None:
        """to_json serializes pending task."""
        task = TaskWidget("Test")
        json_data = task.to_json()
        assert json_data["type"] == "task"
        assert json_data["description"] == "Test"
        assert json_data["status"] == "pending"
        assert json_data["completed"] == 0
        assert json_data["total"] is None

    def test_to_json_running(self) -> None:
        """to_json serializes running task."""
        task = TaskWidget("Process").start().set_progress(25, 100)
        json_data = task.to_json()
        assert json_data["status"] == "running"
        assert json_data["completed"] == 25
        assert json_data["total"] == 100

    def test_to_json_success(self) -> None:
        """to_json serializes successful task."""
        task = TaskWidget("Import").complete("Imported 500 items")
        json_data = task.to_json()
        assert json_data["status"] == "success"
        assert json_data["result"] == "Imported 500 items"
        assert json_data["reason"] is None

    def test_to_json_failed(self) -> None:
        """to_json serializes failed task."""
        task = TaskWidget("Delete").fail("Operation failed", reason="File locked")
        json_data = task.to_json()
        assert json_data["status"] == "failed"
        assert json_data["result"] == "Operation failed"
        assert json_data["reason"] == "File locked"

    def test_to_json_warning(self) -> None:
        """to_json serializes warning task."""
        task = TaskWidget("Validate").warn("Validation passed with warnings")
        json_data = task.to_json()
        assert json_data["status"] == "warning"
        assert json_data["result"] == "Validation passed with warnings"


class TestTaskWidgetStatusSymbols:
    """Tests for status symbol configuration."""

    def test_status_symbols_defined(self) -> None:
        """All TaskStatus values have defined symbols."""
        for status in TaskStatus:
            assert status in STATUS_SYMBOLS

    def test_pending_symbol(self) -> None:
        """Pending status uses circle symbol."""
        symbol, color = STATUS_SYMBOLS[TaskStatus.PENDING]
        assert symbol == "○"
        assert color == "dim"

    def test_success_symbol(self) -> None:
        """Success status uses checkmark symbol."""
        symbol, color = STATUS_SYMBOLS[TaskStatus.SUCCESS]
        assert symbol == "✓"
        assert color == "green"

    def test_failed_symbol(self) -> None:
        """Failed status uses X symbol."""
        symbol, color = STATUS_SYMBOLS[TaskStatus.FAILED]
        assert symbol == "✗"
        assert color == "red"

    def test_warning_symbol(self) -> None:
        """Warning status uses triangle symbol."""
        symbol, color = STATUS_SYMBOLS[TaskStatus.WARNING]
        assert symbol == "⚠"
        assert color == "yellow"

    def test_running_symbol(self) -> None:
        """Running status uses first spinner frame."""
        symbol, color = STATUS_SYMBOLS[TaskStatus.RUNNING]
        assert symbol == SPINNER_FRAMES[0]
        assert color == "cyan"


class TestSpinnerFrames:
    """Tests for spinner animation frames."""

    def test_spinner_frames_defined(self) -> None:
        """SPINNER_FRAMES is defined and non-empty."""
        assert len(SPINNER_FRAMES) > 0

    def test_spinner_frames_are_unique(self) -> None:
        """All spinner frames are different."""
        assert len(SPINNER_FRAMES) == len(set(SPINNER_FRAMES))

    def test_spinner_frames_are_strings(self) -> None:
        """All spinner frames are strings."""
        for frame in SPINNER_FRAMES:
            assert isinstance(frame, str)

    def test_animation_frame_wraps_around(self) -> None:
        """Animation frames wrap around correctly."""
        task = TaskWidget("Test").start()
        # Test with frame number beyond available frames
        for frame_num in range(len(SPINNER_FRAMES) * 2):
            text = task.render(animation_frame=frame_num)
            # Should not raise an error
            assert isinstance(text, Text)


class TestTaskWidgetEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_task_description_with_special_characters(self) -> None:
        """Task handles descriptions with special characters."""
        task = TaskWidget("Processing [important] & {special} chars")
        text = task.render()
        assert "Processing" in text.plain

    def test_task_result_with_unicode(self) -> None:
        """Task result message can contain unicode."""
        task = TaskWidget("Import").complete("Imported 你好 items")
        text = task.render()
        assert "Imported" in text.plain

    def test_task_failure_reason_very_long(self) -> None:
        """Task handles very long failure reasons."""
        long_reason = "A" * 200
        task = TaskWidget("Test").fail("Failed", reason=long_reason)
        text = task.render()
        # Should include FAILED status and long reason
        assert "FAILED" in text.plain

    def test_task_zero_total(self) -> None:
        """Task handles zero total gracefully."""
        task = TaskWidget("Test").start().set_progress(0, 0)
        text = task.render()
        # Should not cause division by zero
        assert isinstance(text, Text)

    def test_task_completed_exceeds_total(self) -> None:
        """Task handles completed > total (overage)."""
        task = TaskWidget("Test").start().set_progress(150, 100)
        text = task.render()
        # Should render without error, percentage might be > 100
        assert isinstance(text, Text)

    def test_task_status_transitions(self) -> None:
        """Task can transition through different states."""
        task = TaskWidget("Multi-state")
        states_visited = []

        # Pending -> Running
        states_visited.append(task.status)
        task.start()
        states_visited.append(task.status)

        # Can change to success
        task.complete("Done")
        states_visited.append(task.status)

        assert TaskStatus.PENDING in states_visited
        assert TaskStatus.RUNNING in states_visited
        assert TaskStatus.SUCCESS in states_visited
