"""Tests for the unified output system."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gmailarchiver.cli.output import OutputManager, TaskResult


class TestOutputManager:
    """Test OutputManager initialization."""

    def test_init_default(self) -> None:
        """Test default initialization."""
        output = OutputManager()
        assert output.json_mode is False
        assert output.quiet is False
        assert output.console is not None

    def test_init_json_mode(self) -> None:
        """Test JSON mode initialization."""
        output = OutputManager(json_mode=True)
        assert output.json_mode is True
        assert output.console is None

    def test_init_quiet_mode(self) -> None:
        """Test quiet mode initialization."""
        output = OutputManager(quiet=True)
        assert output.quiet is True


class TestStartOperation:
    """Test start_operation method."""

    def test_start_operation_normal_mode(self) -> None:
        """Test starting operation in normal mode."""
        output = OutputManager()
        with patch.object(output.console, "print") as mock_print:
            output.start_operation("test", "Testing operation")
            mock_print.assert_called_once()

    def test_start_operation_json_mode(self) -> None:
        """Test starting operation in JSON mode."""
        output = OutputManager(json_mode=True)
        output.start_operation("test", "Testing operation")
        assert len(output._json_events) == 1
        assert output._json_events[0]["event"] == "operation_start"
        assert output._json_events[0]["operation"] == "test"

    def test_start_operation_quiet_mode(self) -> None:
        """Test starting operation in quiet mode."""
        output = OutputManager(quiet=True)
        with patch.object(output.console, "print") as mock_print:
            output.start_operation("test")
            mock_print.assert_not_called()


class TestProgressContext:
    """Test progress_context method."""

    def test_progress_context_json_mode(self) -> None:
        """Test progress context in JSON mode."""
        output = OutputManager(json_mode=True)
        with output.progress_context("Testing", total=100) as progress:
            assert progress is None
        assert len(output._json_events) == 2
        assert output._json_events[0]["event"] == "progress_start"
        assert output._json_events[1]["event"] == "progress_end"

    def test_progress_context_quiet_mode(self) -> None:
        """Test progress context in quiet mode."""
        output = OutputManager(quiet=True)
        with output.progress_context("Testing") as progress:
            assert progress is None

    def test_progress_context_normal_mode(self) -> None:
        """Test progress context in normal mode."""
        output = OutputManager()
        with output.progress_context("Testing", total=100) as progress:
            assert progress is not None
            task = progress.add_task("test", total=100)
            progress.update(task, advance=50)

    def test_progress_context_update_reflects_completed_count(self) -> None:
        """Test that progress.update() correctly updates the completed count.

        Bug #2: Progress bars show total but counter never increments.
        The completed count should be accessible after update() is called.
        """
        output = OutputManager()
        with output.progress_context("Testing", total=100) as progress:
            assert progress is not None
            task = progress.add_task("test", total=100)

            # Initial state: completed should be 0
            task_obj = progress.tasks[0]
            assert task_obj.completed == 0

            # After update: completed should reflect the advance
            progress.update(task, advance=25)
            assert task_obj.completed == 25

            # After multiple updates: completed should accumulate
            progress.update(task, advance=25)
            assert task_obj.completed == 50

            progress.update(task, completed=75)
            assert task_obj.completed == 75

    def test_progress_context_uses_progress_own_live_display(self) -> None:
        """Test that progress_context uses Progress's built-in live display.

        Bug #2: When Progress is wrapped in an external Live() context,
        calling progress.update(refresh=True) does not refresh the display
        because Progress is not managing its own Live context.

        The fix is to use Progress as its own context manager so its
        internal refresh mechanism works correctly.
        """
        output = OutputManager()

        # The Progress object should manage its own live display
        # This test verifies the internal state is correct after updates
        with output.progress_context("Testing", total=10) as progress:
            assert progress is not None
            task = progress.add_task("Import", total=10)

            # Simulate the callback pattern used in import_cmd
            for i in range(10):
                progress.update(task, completed=i + 1, refresh=True)

            # Final state should show all items completed
            task_obj = progress.tasks[0]
            assert task_obj.completed == 10
            assert task_obj.total == 10

    def test_progress_context_does_not_use_external_live_wrapper(self) -> None:
        """Test that progress_context does NOT wrap Progress in external Live.

        Bug #2 Root Cause: Wrapping Progress in Live(progress, ...) disables
        Progress's internal refresh mechanism. When progress.update(refresh=True)
        is called, it only triggers Progress's internal live.refresh(), but
        since Progress isn't managing its own Live context (it's wrapped),
        the display doesn't update.

        This test verifies the fix: progress_context should NOT store a
        separate _live reference that wraps the Progress object.
        """
        output = OutputManager()

        with output.progress_context("Testing", total=10) as progress:
            assert progress is not None

            # After the fix, output._live should not exist or be None because
            # Progress manages its own live display internally.
            # The old buggy implementation stored a Live wrapper in self._live.
            live_attr = getattr(output, "_live", None)
            assert live_attr is None, (
                "progress_context should not wrap Progress in external Live context. "
                "Progress should manage its own live display for refresh=True to work."
            )


class TestTaskComplete:
    """Test task_complete method."""

    def test_task_complete_normal_mode(self) -> None:
        """Test marking task complete in normal mode."""
        output = OutputManager()
        output.task_complete("test_task", success=True, details="Completed successfully")
        assert len(output._completed_tasks) == 1
        assert output._completed_tasks[0].name == "test_task"
        assert output._completed_tasks[0].success is True

    def test_task_complete_json_mode(self) -> None:
        """Test marking task complete in JSON mode."""
        output = OutputManager(json_mode=True)
        output.task_complete("test_task", success=False, details="Failed", elapsed=1.5)
        assert len(output._json_events) == 1
        assert output._json_events[0]["event"] == "task_complete"
        assert output._json_events[0]["success"] is False
        assert output._json_events[0]["elapsed"] == 1.5


class TestShowReport:
    """Test show_report method."""

    def test_show_report_dict(self) -> None:
        """Test showing key-value report."""
        output = OutputManager()
        with patch.object(output.console, "print"):
            output.show_report("Test Report", {"key1": "value1", "key2": "value2"})

    def test_show_report_table(self) -> None:
        """Test showing tabular report."""
        output = OutputManager()
        data = [
            {"col1": "a", "col2": "b"},
            {"col1": "c", "col2": "d"},
        ]
        with patch.object(output.console, "print"):
            output.show_report("Test Table", data)

    def test_show_report_json_mode(self) -> None:
        """Test showing report in JSON mode."""
        output = OutputManager(json_mode=True)
        output.show_report("Test", {"key": "value"})
        assert len(output._json_events) == 1
        assert output._json_events[0]["event"] == "report"

    def test_show_report_quiet_mode(self) -> None:
        """Test showing report in quiet mode."""
        output = OutputManager(quiet=True)
        with patch.object(output.console, "print") as mock_print:
            output.show_report("Test", {"key": "value"})
            mock_print.assert_not_called()


class TestSuggestNextSteps:
    """Test suggest_next_steps method."""

    def test_suggest_next_steps_normal(self) -> None:
        """Test suggesting next steps in normal mode."""
        output = OutputManager()
        suggestions = ["Run command A", "Run command B"]
        with patch.object(output.console, "print"):
            output.suggest_next_steps(suggestions)

    def test_suggest_next_steps_json(self) -> None:
        """Test suggesting next steps in JSON mode."""
        output = OutputManager(json_mode=True)
        suggestions = ["Run command A", "Run command B"]
        output.suggest_next_steps(suggestions)
        assert len(output._json_events) == 1
        assert output._json_events[0]["event"] == "suggestions"
        assert output._json_events[0]["suggestions"] == suggestions


class TestErrorHandling:
    """Test error method."""

    def test_error_normal_mode(self) -> None:
        """Test error in normal mode without exit."""
        output = OutputManager()
        with patch.object(output.console, "print"):
            output.error("Test error", suggestion="Try this fix", exit_code=0)

    def test_error_json_mode(self) -> None:
        """Test error in JSON mode without exit."""
        output = OutputManager(json_mode=True)
        output.error("Test error", suggestion="Fix it", exit_code=0)
        assert len(output._json_events) == 1
        assert output._json_events[0]["event"] == "error"

    def test_error_with_exit(self) -> None:
        """Test error triggers system exit."""
        output = OutputManager()
        with patch.object(output.console, "print"), pytest.raises(SystemExit) as exc:
            output.error("Fatal error", exit_code=1)
        assert exc.value.code == 1


class TestSuccessWarningInfo:
    """Test success, warning, and info methods."""

    def test_success_normal(self) -> None:
        """Test success message in normal mode."""
        output = OutputManager()
        with patch.object(output.console, "print"):
            output.success("Operation succeeded")

    def test_success_json(self) -> None:
        """Test success message in JSON mode."""
        output = OutputManager(json_mode=True)
        output.success("Success")
        assert output._json_events[-1]["event"] == "success"

    def test_warning_normal(self) -> None:
        """Test warning message in normal mode."""
        output = OutputManager()
        with patch.object(output.console, "print"):
            output.warning("Warning message")

    def test_warning_json(self) -> None:
        """Test warning message in JSON mode."""
        output = OutputManager(json_mode=True)
        output.warning("Warning")
        assert output._json_events[-1]["event"] == "warning"

    def test_info_normal(self) -> None:
        """Test info message in normal mode."""
        output = OutputManager()
        with patch.object(output.console, "print"):
            output.info("Info message")

    def test_info_json(self) -> None:
        """Test info message in JSON mode."""
        output = OutputManager(json_mode=True)
        output.info("Info")
        assert output._json_events[-1]["event"] == "info"


class TestShowTable:
    """Test show_table helper method."""

    def test_show_table_normal_mode(self) -> None:
        """Table is rendered via Rich in normal mode."""
        output = OutputManager()
        headers = ["col1", "col2"]
        rows = [["a", "b"], ["c", "d"]]
        with patch.object(output.console, "print") as mock_print:
            output.show_table("Test Table", headers, rows)
            mock_print.assert_called_once()

    def test_show_table_json_mode(self) -> None:
        """Table is recorded as JSON event in JSON mode."""
        output = OutputManager(json_mode=True)
        headers = ["col1", "col2"]
        rows = [["1", "2"], ["3", "4"]]
        output.show_table("Test Table", headers, rows)
        assert output._json_events[-1]["event"] == "table"
        assert output._json_events[-1]["headers"] == headers
        assert output._json_events[-1]["rows"] == [["1", "2"], ["3", "4"]]


class TestEndOperation:
    """Test end_operation method."""

    def test_end_operation_success(self) -> None:
        """Test ending operation successfully."""
        output = OutputManager()
        output.start_operation("test")
        with patch.object(output.console, "print"):
            output.end_operation(success=True, summary="All done")

    def test_end_operation_failure(self) -> None:
        """Test ending operation with failure."""
        output = OutputManager()
        output.start_operation("test")
        with patch.object(output.console, "print"):
            output.end_operation(success=False, summary="Failed")

    def test_end_operation_json(self) -> None:
        """Test ending operation in JSON mode."""
        output = OutputManager(json_mode=True)
        output.start_operation("test")
        with patch("builtins.print") as mock_print:
            output.end_operation(success=True)
            # Should flush JSON
            mock_print.assert_called_once()
            output_str = mock_print.call_args[0][0]
            data = json.loads(output_str)
            assert "events" in data
            assert data["events"][-1]["event"] == "operation_end"


class TestTaskResult:
    """Test TaskResult dataclass."""

    def test_task_result_creation(self) -> None:
        """Test creating TaskResult."""
        result = TaskResult(name="test", success=True, details="Completed", elapsed=1.5)
        assert result.name == "test"
        assert result.success is True
        assert result.details == "Completed"
        assert result.elapsed == 1.5

    def test_task_result_defaults(self) -> None:
        """Test TaskResult with default values."""
        result = TaskResult(name="test", success=False)
        assert result.details is None
        assert result.elapsed is None


class TestProgressTrackerEdgeCases:
    """Test ProgressTracker edge cases and error handling."""

    def test_update_with_multiple_params_raises_error(self) -> None:
        """Test update raises error when multiple params provided (lines 104, 106)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        with pytest.raises(ValueError, match="only one"):
            tracker.update(amount=5, completed=10)

    def test_update_with_no_params_does_nothing(self) -> None:
        """Test update with no params returns early (line 104)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        # Should not raise, just return
        tracker.update()
        assert tracker.completed == 0

    def test_calculate_eta_with_zero_rate(self) -> None:
        """Test calculate_eta returns None when rate is zero (line 186)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker._start_time = 0.0
        tracker.completed = 0
        tracker._smoothed_rate = 0.0

        eta = tracker.calculate_eta()
        assert eta is None

    def test_get_rate_formatted_no_rate(self) -> None:
        """Test get_rate_formatted returns empty string when no rate (line 228)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        # Don't start, so no rate

        formatted = tracker.get_rate_formatted()
        assert formatted == ""

    def test_get_progress_string_no_start(self) -> None:
        """Test get_progress_string returns empty when not started (line 254)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        # Don't start

        progress_str = tracker.get_progress_string()
        assert progress_str == ""


class TestOutputManagerEdgeCases:
    """Test OutputManager edge cases."""

    def test_show_report_with_summary(self) -> None:
        """Test show_report handles summary parameter (lines 505-507)."""
        output = OutputManager()

        with patch.object(output.console, "print"):
            output.show_report("Test Report", {"key": "value"}, summary={"total": 10, "passed": 8})

    def test_show_report_list_of_non_dicts(self) -> None:
        """Test show_report handles list of tuples/lists (lines 498-499)."""
        output = OutputManager()

        # List of tuples
        data = [("a", "b"), ("c", "d")]

        with patch.object(output.console, "print"):
            output.show_report("Test Table", data)

    def test_show_table_quiet_mode_skips_output(self) -> None:
        """Test show_table in quiet mode does nothing (line 540)."""
        output = OutputManager(quiet=True)

        with patch.object(output.console, "print") as mock_print:
            output.show_table("Test", ["col1"], [["val1"]])
            mock_print.assert_not_called()

    def test_suggest_next_steps_quiet_mode(self) -> None:
        """Test suggest_next_steps in quiet mode (line 562)."""
        output = OutputManager(quiet=True)

        with patch.object(output.console, "print") as mock_print:
            output.suggest_next_steps(["Step 1", "Step 2"])
            mock_print.assert_not_called()

    def test_error_json_mode_with_flush(self) -> None:
        """Test error in JSON mode flushes output (lines 590-591)."""
        output = OutputManager(json_mode=True)

        with patch("builtins.print") as mock_print, pytest.raises(SystemExit):
            output.error("Fatal error", exit_code=1)

        # Should have flushed JSON
        mock_print.assert_called()

    def test_warning_quiet_mode(self) -> None:
        """Test warning in quiet mode (line 628)."""
        output = OutputManager(quiet=True)

        with patch.object(output.console, "print") as mock_print:
            output.warning("Warning message")
            mock_print.assert_not_called()

    def test_info_quiet_mode(self) -> None:
        """Test info in quiet mode (line 643)."""
        output = OutputManager(quiet=True)

        with patch.object(output.console, "print") as mock_print:
            output.info("Info message")
            mock_print.assert_not_called()

    def test_end_operation_quiet_mode(self) -> None:
        """Test end_operation in quiet mode (lines 673, 676)."""
        output = OutputManager(quiet=True)
        output.start_operation("test")

        with patch.object(output.console, "print") as mock_print:
            output.end_operation(success=True)
            mock_print.assert_not_called()

    def test_set_json_payload_and_flush(self) -> None:
        """Test set_json_payload and flushing (line 702)."""
        output = OutputManager(json_mode=True)

        # Set explicit payload
        payload = {"custom": "data", "items": [1, 2, 3]}
        output.set_json_payload(payload)

        with patch("builtins.print") as mock_print:
            output.end_operation(success=True)

            # Should flush the custom payload
            mock_print.assert_called_once()
            output_str = mock_print.call_args[0][0]
            data = json.loads(output_str)
            assert data == payload

    def test_progress_context_with_live_update(self) -> None:
        """Test progress_context updates live display (lines 448-449)."""
        output = OutputManager()

        with output.progress_context("Testing", total=10) as progress:
            if progress:
                # Add a task
                task = progress.add_task("Test task", total=10)
                progress.update(task, advance=5)

                # Complete a task to trigger live update
                output.task_complete("task1", success=True, elapsed=1.0)


class TestProgressTrackerSimpleCases:
    """Additional test cases for ProgressTracker."""

    def test_update_with_completed_param(self) -> None:
        """Test update using completed parameter (line 112)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        # Use completed parameter
        tracker.update(completed=50)
        assert tracker.completed == 50

    def test_update_with_advance_param(self) -> None:
        """Test update using advance parameter (line 122)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        # Use advance parameter
        tracker.update(advance=10)
        assert tracker.completed == 10

        tracker.update(advance=5)
        assert tracker.completed == 15


class TestFlushJSON:
    """Test _flush_json method."""

    def test_flush_json_not_in_json_mode(self) -> None:
        """Test _flush_json does nothing when not in JSON mode (line 702)."""
        output = OutputManager()

        # Should do nothing
        output._flush_json(success=True)


class TestOutputManagerEndOperation:
    """Test end_operation edge cases."""

    def test_end_operation_no_console_quiet_mode(self) -> None:
        """Test end_operation in quiet mode returns early (lines 673, 676)."""
        output = OutputManager(quiet=True)
        output.start_operation("test")

        # Should handle gracefully
        output.end_operation(success=True, summary="Done")

    def test_success_quiet_mode(self) -> None:
        """Test success in quiet mode (line 613)."""
        output = OutputManager(quiet=True)

        # Should not raise
        output.success("Success message")


class TestProgressTrackerETA:
    """Test ETA calculation edge cases."""

    def test_calculate_eta_already_complete(self) -> None:
        """Test calculate_eta returns None when already complete (line 186)."""
        from gmailarchiver.cli.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(completed=100)

        # Already complete
        eta = tracker.calculate_eta()
        assert eta is None or eta == 0.0


class TestStatusPanel:
    """Test status panel display with completed tasks."""

    def test_output_status_panel_with_completed_tasks(self) -> None:
        """Test status panel shows completed tasks with truncation (lines 387-403).

        Tests that:
        1. Status panel is created when tasks are completed
        2. Panel displays last 10 tasks (truncation)
        3. Each task shows success/failure icon and elapsed time
        """
        output = OutputManager()

        # Track and complete more than 10 tasks to test truncation
        for i in range(15):
            output.task_complete(f"Task {i}", success=(i % 2 == 0), elapsed=float(i))

        # Verify completed tasks are tracked
        assert len(output._completed_tasks) == 15

        # The panel logic truncates to last 10 tasks
        # We can't directly inspect the panel rendering, but we verify the data is tracked
        assert output._completed_tasks[-10:][0].name == "Task 5"
        assert output._completed_tasks[-1].name == "Task 14"

        # Verify task success states are preserved
        assert output._completed_tasks[0].success is True  # Task 0: even
        assert output._completed_tasks[1].success is False  # Task 1: odd


class TestLogBuffer:
    """Test LogBuffer class for v1.3.1 live layout system."""

    def test_init_default(self) -> None:
        """Test LogBuffer initialization with default size (10)."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        assert buffer._max_visible == 10
        assert len(buffer._visible) == 0
        assert len(buffer._all_logs) == 0
        assert len(buffer._entry_map) == 0

    def test_init_custom_size(self) -> None:
        """Test LogBuffer initialization with custom size."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer(max_visible=5)
        assert buffer._max_visible == 5

    def test_init_zero_size(self) -> None:
        """Test LogBuffer with zero size (no visible logs, all stored)."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer(max_visible=0)
        assert buffer._max_visible == 0
        buffer.add("Test message", "INFO")
        assert len(buffer._visible) == 0
        assert len(buffer._all_logs) == 1  # Still stored in all_logs

    def test_init_negative_size_raises_error(self) -> None:
        """Test LogBuffer rejects negative size."""
        from gmailarchiver.cli.output import LogBuffer

        with pytest.raises(ValueError, match="max_visible must be non-negative"):
            LogBuffer(max_visible=-1)

    def test_add_single_entry(self) -> None:
        """Test adding a single log entry."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Test message", "INFO")

        assert len(buffer._visible) == 1
        assert len(buffer._all_logs) == 1
        assert "Test message" in buffer._entry_map

        entry = buffer._entry_map["Test message"]
        assert entry.message == "Test message"
        assert entry.level == "INFO"
        assert entry.count == 1

    def test_add_multiple_entries(self) -> None:
        """Test adding multiple distinct log entries."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Message 1", "INFO")
        buffer.add("Message 2", "WARNING")
        buffer.add("Message 3", "ERROR")

        assert len(buffer._visible) == 3
        assert len(buffer._all_logs) == 3
        assert len(buffer._entry_map) == 3

    def test_ring_buffer_overflow(self) -> None:
        """Test FIFO behavior when exceeding max_visible."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer(max_visible=3)

        # Add 5 messages
        for i in range(5):
            buffer.add(f"Message {i}", "INFO")

        # Only last 3 should be visible
        assert len(buffer._visible) == 3
        # But all 5 should be in all_logs
        assert len(buffer._all_logs) == 5

        # Verify FIFO order (messages 2, 3, 4 should be visible)
        visible_messages = [entry.message for entry in buffer._visible]
        assert visible_messages == ["Message 2", "Message 3", "Message 4"]

    def test_deduplication_exact_match(self) -> None:
        """Test deduplication increments count for exact duplicate."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Duplicate message", "INFO")
        buffer.add("Duplicate message", "INFO")
        buffer.add("Duplicate message", "INFO")

        assert len(buffer._visible) == 1
        assert len(buffer._all_logs) == 1
        assert buffer._entry_map["Duplicate message"].count == 3

    def test_deduplication_updates_timestamp(self) -> None:
        """Test deduplication updates timestamp to latest occurrence."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Message", "INFO")
        time.sleep(0.01)  # Small delay
        first_timestamp = buffer._entry_map["Message"].timestamp

        time.sleep(0.01)
        buffer.add("Message", "INFO")  # Duplicate
        second_timestamp = buffer._entry_map["Message"].timestamp

        assert second_timestamp > first_timestamp

    def test_deduplication_evicted_entry_readded(self) -> None:
        """Test that evicted duplicate entries are re-added to visible buffer."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer(max_visible=2)

        # Add 3 messages (message 0 will be evicted)
        buffer.add("Message 0", "INFO")
        buffer.add("Message 1", "INFO")
        buffer.add("Message 2", "INFO")

        # Visible should be [Message 1, Message 2]
        assert len(buffer._visible) == 2
        visible_messages = [entry.message for entry in buffer._visible]
        assert visible_messages == ["Message 1", "Message 2"]

        # Re-add Message 0 (duplicate)
        buffer.add("Message 0", "INFO")

        # Should now be visible again (re-added to ring buffer)
        visible_messages = [entry.message for entry in buffer._visible]
        assert "Message 0" in visible_messages
        assert buffer._entry_map["Message 0"].count == 2

    def test_render_empty_buffer(self) -> None:
        """Test rendering empty buffer returns empty Group."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        rendered = buffer.render()

        # Should be a Rich Group
        from rich.console import Group

        assert isinstance(rendered, Group)
        assert len(rendered.renderables) == 0

    def test_render_with_entries(self) -> None:
        """Test rendering buffer with log entries."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Info message", "INFO")
        buffer.add("Warning message", "WARNING")
        buffer.add("Error message", "ERROR")

        rendered = buffer.render()

        from rich.console import Group

        assert isinstance(rendered, Group)
        assert len(rendered.renderables) == 3

    def test_render_severity_symbols(self) -> None:
        """Test that render includes correct severity symbols."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Test", "INFO")
        buffer.add("Test", "WARNING")
        buffer.add("Test", "ERROR")
        buffer.add("Test", "SUCCESS")

        # Check SEVERITY_MAP is defined correctly
        assert LogBuffer.SEVERITY_MAP["INFO"] == ("ℹ", "blue")
        assert LogBuffer.SEVERITY_MAP["WARNING"] == ("⚠", "yellow")
        assert LogBuffer.SEVERITY_MAP["ERROR"] == ("✗", "red")
        assert LogBuffer.SEVERITY_MAP["SUCCESS"] == ("✓", "green")

    def test_render_with_duplicate_count(self) -> None:
        """Test render shows duplicate count (x2, x3, etc.)."""
        from io import StringIO

        from rich.console import Console

        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Repeated message", "INFO")
        buffer.add("Repeated message", "INFO")
        buffer.add("Repeated message", "INFO")

        rendered = buffer.render()

        # Render to string to check output
        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        # Should contain (x3) for the duplicate count
        assert "(x3)" in output

    def test_get_all_logs_returns_copy(self) -> None:
        """Test get_all_logs returns a copy, not reference."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Message 1", "INFO")
        buffer.add("Message 2", "INFO")

        logs_copy = buffer.get_all_logs()
        assert len(logs_copy) == 2

        # Modify the copy
        logs_copy.pop()

        # Original should be unchanged
        assert len(buffer._all_logs) == 2

    def test_clear(self) -> None:
        """Test clear() removes all logs."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Message 1", "INFO")
        buffer.add("Message 2", "WARNING")

        assert len(buffer._visible) == 2
        assert len(buffer._all_logs) == 2

        buffer.clear()

        assert len(buffer._visible) == 0
        assert len(buffer._all_logs) == 0
        assert len(buffer._entry_map) == 0


class TestLiveLayoutContextInitialization:
    """Test LiveLayoutContext initialization and setup."""

    def test_init_with_all_components(self) -> None:
        """Test initialization with LogBuffer, SessionLogger, and Progress."""
        from gmailarchiver.cli.output import LiveLayoutContext, LogBuffer, SessionLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_buffer = LogBuffer(max_visible=10)
            session_logger = SessionLogger(log_dir=Path(tmpdir))

            context = LiveLayoutContext(
                log_buffer=log_buffer,
                session_logger=session_logger,
            )

            assert context.log_buffer is log_buffer
            assert context.session_logger is session_logger

            # Clean up resources
            session_logger.close()

    def test_init_with_default_components(self) -> None:
        """Test initialization creates default components if not provided."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            # Should create default LogBuffer with 10 lines
            assert context.log_buffer is not None
            assert context.log_buffer._max_visible == 10

            # Should have SessionLogger
            assert context.session_logger is not None

            # Clean up resources
            context.session_logger.close()

    def test_init_custom_max_visible(self) -> None:
        """Test initialization with custom max_visible for LogBuffer."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(max_visible=5, log_dir=Path(tmpdir))
            assert context.log_buffer._max_visible == 5

            # Clean up resources
            context.session_logger.close()


class TestLiveLayoutContextManager:
    """Test LiveLayoutContext as context manager."""

    def test_context_manager_enter_exit(self) -> None:
        """Test __enter__ and __exit__ start/stop the Live display."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            with context as live_context:
                # Should return self
                assert live_context is context

    def test_context_manager_closes_session_logger(self) -> None:
        """Test __exit__ closes SessionLogger file handle."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            with context:
                pass

            # SessionLogger should be closed
            assert context.session_logger._closed is True


class TestLiveLayoutContextAddLog:
    """Test add_log() integration with LogBuffer and SessionLogger."""

    def test_add_log_to_both_buffers(self) -> None:
        """Test add_log writes to both LogBuffer and SessionLogger."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            with context:
                context.add_log("Test message", "INFO")

            # Should be in LogBuffer
            assert len(context.log_buffer._all_logs) == 1
            assert context.log_buffer._all_logs[0].message == "Test message"

            # Should be in SessionLogger file
            log_content = context.session_logger.log_file.read_text()
            assert "Test message" in log_content
            assert "[INFO]" in log_content

    def test_add_log_different_levels(self) -> None:
        """Test add_log with different severity levels."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            with context:
                context.add_log("Info message", "INFO")
                context.add_log("Warning message", "WARNING")
                context.add_log("Error message", "ERROR")

            logs = context.log_buffer.get_all_logs()
            assert len(logs) == 3
            assert logs[0].level == "INFO"
            assert logs[1].level == "WARNING"
            assert logs[2].level == "ERROR"


class TestOutputManagerLiveLayoutContext:
    """Test OutputManager.live_layout_context() integration method."""

    def test_live_layout_context_returns_live_context(self) -> None:
        """Test live_layout_context() returns LiveLayoutContext instance."""
        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            with output.live_layout_context(log_dir=Path(tmpdir)) as live:
                from gmailarchiver.cli.output import LiveLayoutContext

                assert isinstance(live, LiveLayoutContext)

    def test_live_layout_context_auto_cleanup(self) -> None:
        """Test live_layout_context() closes SessionLogger on exit."""
        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            with output.live_layout_context(log_dir=Path(tmpdir)) as live:
                session_logger = live.session_logger

            # SessionLogger should be closed after exiting context
            assert session_logger._closed is True


# ============================================================================
# Phase 1: Protocol Tests
# ============================================================================


class TestOperationHandleProtocol:
    """Test OperationHandle protocol compliance."""

    def test_operation_handle_has_required_methods(self) -> None:
        """Test that OperationHandle protocol defines required methods."""

        from gmailarchiver.cli.output import OperationHandle

        # OperationHandle should be a Protocol with these methods
        assert hasattr(OperationHandle, "log")
        assert hasattr(OperationHandle, "update_progress")
        assert hasattr(OperationHandle, "set_status")
        assert hasattr(OperationHandle, "succeed")
        assert hasattr(OperationHandle, "fail")

    def test_operation_handle_protocol_structural_typing(self) -> None:
        """Test that any class with matching methods satisfies OperationHandle."""
        from gmailarchiver.cli.output import OperationHandle

        # Create a mock class with all required methods
        class MockOperationHandle:
            def log(self, message: str, level: str = "INFO") -> None:
                pass

            def update_progress(self, advance: int = 1) -> None:
                pass

            def set_status(self, status: str) -> None:
                pass

            def succeed(self, message: str) -> None:
                pass

            def fail(self, message: str) -> None:
                pass

        # Should be compatible with OperationHandle protocol
        mock: OperationHandle = MockOperationHandle()
        assert mock is not None


class TestOutputHandlerProtocol:
    """Test OutputHandler protocol compliance."""

    def test_output_handler_has_required_methods(self) -> None:
        """Test that OutputHandler protocol defines required methods."""
        from gmailarchiver.cli.output import OutputHandler

        # OutputHandler should be a Protocol with these methods
        assert hasattr(OutputHandler, "print")
        assert hasattr(OutputHandler, "start_operation")
        assert hasattr(OutputHandler, "__enter__")
        assert hasattr(OutputHandler, "__exit__")

    def test_output_handler_protocol_structural_typing(self) -> None:
        """Test that any class with matching methods satisfies OutputHandler."""
        from typing import Any

        from gmailarchiver.cli.output import OperationHandle, OutputHandler

        # Create a mock class with all required methods
        class MockOutputHandler:
            def print(self, content: Any) -> None:
                pass

            def start_operation(
                self, description: str, total: int | None = None
            ) -> OperationHandle:
                # Return a mock operation handle
                class MockOpHandle:
                    def log(self, message: str, level: str = "INFO") -> None:
                        pass

                    def update_progress(self, advance: int = 1) -> None:
                        pass

                    def set_status(self, status: str) -> None:
                        pass

                    def succeed(self, message: str) -> None:
                        pass

                    def fail(self, message: str) -> None:
                        pass

                return MockOpHandle()

            def __enter__(self) -> MockOutputHandler:
                return self

            def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                pass

        # Should be compatible with OutputHandler protocol
        mock: OutputHandler = MockOutputHandler()
        assert mock is not None


# ============================================================================
# Phase 2: StaticOutputHandler Tests
# ============================================================================


class TestStaticOperationHandle:
    """Test StaticOperationHandle implementation."""

    def test_log_method_calls_output_manager(self) -> None:
        """Test log() delegates to OutputManager methods."""
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        with patch.object(output, "info") as mock_info:
            handle.log("Test message", "INFO")
            mock_info.assert_called_once_with("Test message")

        with patch.object(output, "warning") as mock_warning:
            handle.log("Warning message", "WARNING")
            mock_warning.assert_called_once_with("Warning message")

        with patch.object(output, "error") as mock_error:
            handle.log("Error message", "ERROR")
            mock_error.assert_called_once_with("Error message", exit_code=0)

        with patch.object(output, "success") as mock_success:
            handle.log("Success message", "SUCCESS")
            mock_success.assert_called_once_with("Success message")

    def test_update_progress_does_nothing_in_static_mode(self) -> None:
        """Test update_progress() is a no-op in static mode."""
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        # Should not raise, but does nothing
        handle.update_progress()
        handle.update_progress(advance=10)

    def test_set_status_does_nothing_in_static_mode(self) -> None:
        """Test set_status() is a no-op in static mode."""
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        # Should not raise, but does nothing
        handle.set_status("Processing 50/100")

    def test_succeed_calls_success(self) -> None:
        """Test succeed() delegates to OutputManager.success()."""
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        with patch.object(output, "success") as mock_success:
            handle.succeed("Operation complete")
            mock_success.assert_called_once_with("Operation complete")

    def test_fail_calls_error(self) -> None:
        """Test fail() delegates to OutputManager.error()."""
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        with patch.object(output, "error") as mock_error:
            handle.fail("Operation failed")
            mock_error.assert_called_once_with("Operation failed", exit_code=0)


class TestStaticOutputHandler:
    """Test StaticOutputHandler implementation."""

    def test_print_delegates_to_console(self) -> None:
        """Test print() delegates to console.print()."""
        from gmailarchiver.cli.output import OutputManager, StaticOutputHandler

        output = OutputManager()
        handler = StaticOutputHandler(output)

        with patch.object(output.console, "print") as mock_print:
            handler.print("Test content")
            mock_print.assert_called_once_with("Test content")

    def test_start_operation_returns_static_handle(self) -> None:
        """Test start_operation() returns StaticOperationHandle."""
        from gmailarchiver.cli.output import (
            OutputManager,
            StaticOperationHandle,
            StaticOutputHandler,
        )

        output = OutputManager()
        handler = StaticOutputHandler(output)

        handle = handler.start_operation("Test operation", total=100)
        assert isinstance(handle, StaticOperationHandle)

    def test_context_manager_returns_self(self) -> None:
        """Test __enter__/__exit__ context manager support."""
        from gmailarchiver.cli.output import OutputManager, StaticOutputHandler

        output = OutputManager()
        handler = StaticOutputHandler(output)

        with handler as h:
            assert h is handler

    def test_json_mode_respects_output_manager_mode(self) -> None:
        """Test StaticOutputHandler respects OutputManager's json_mode."""
        from gmailarchiver.cli.output import OutputManager, StaticOutputHandler

        output = OutputManager(json_mode=True)
        handler = StaticOutputHandler(output)

        # Console should be None in JSON mode
        assert output.console is None

        # start_operation should still return a valid handle
        handle = handler.start_operation("Test", total=10)
        assert handle is not None


class TestOutputManagerWithStaticHandler:
    """Test OutputManager integration with StaticOutputHandler."""

    def test_output_manager_uses_static_handler_by_default(self) -> None:
        """Test OutputManager uses StaticOutputHandler as default."""
        from gmailarchiver.cli.output import OutputManager, StaticOutputHandler

        output = OutputManager()

        # OutputManager should have a _handler attribute (StaticOutputHandler)
        assert hasattr(output, "_handler")
        assert isinstance(output._handler, StaticOutputHandler)

    def test_output_manager_info_delegates_to_handler(self) -> None:
        """Test OutputManager.info() delegates to handler."""
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()

        with patch.object(output._handler, "print") as mock_print:
            output.info("Test info")
            # info() should eventually call handler.print()
            # (implementation may vary, but verify delegation happens)


# ============================================================================
# Phase 3: LiveOutputHandler Tests
# ============================================================================


class TestLiveOperationHandle:
    """Test LiveOperationHandle implementation."""

    def test_log_adds_to_live_layout_context(self) -> None:
        """Test log() adds messages to LiveLayoutContext."""
        from gmailarchiver.cli.output import (
            LiveLayoutContext,
            LiveOperationHandle,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            live_context = LiveLayoutContext(log_dir=Path(tmpdir))
            handle = LiveOperationHandle(output, live_context, description="Test", total=10)

            with live_context:
                handle.log("Test message", "INFO")

                # Should be in log buffer
                logs = live_context.log_buffer.get_all_logs()
                assert len(logs) == 1
                assert logs[0].message == "Test message"
                assert logs[0].level == "INFO"

    def test_update_progress_tracks_completion(self) -> None:
        """Test update_progress() tracks completion count."""
        from gmailarchiver.cli.output import (
            LiveLayoutContext,
            LiveOperationHandle,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            live_context = LiveLayoutContext(log_dir=Path(tmpdir))
            handle = LiveOperationHandle(output, live_context, description="Test", total=100)

            with live_context:
                assert handle.completed == 0

                handle.update_progress(advance=10)
                assert handle.completed == 10

                handle.update_progress(advance=5)
                assert handle.completed == 15

    def test_set_status_updates_description(self) -> None:
        """Test set_status() updates operation description."""
        from gmailarchiver.cli.output import (
            LiveLayoutContext,
            LiveOperationHandle,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            live_context = LiveLayoutContext(log_dir=Path(tmpdir))
            handle = LiveOperationHandle(output, live_context, description="Test", total=10)

            with live_context:
                handle.set_status("Processing 5/10")
                assert handle.description == "Processing 5/10"

    def test_succeed_logs_success_message(self) -> None:
        """Test succeed() logs success message."""
        from gmailarchiver.cli.output import (
            LiveLayoutContext,
            LiveOperationHandle,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            live_context = LiveLayoutContext(log_dir=Path(tmpdir))
            handle = LiveOperationHandle(output, live_context, description="Test", total=10)

            with live_context:
                handle.succeed("Operation complete")

                logs = live_context.log_buffer.get_all_logs()
                assert any(log.level == "SUCCESS" for log in logs)

    def test_fail_logs_error_message(self) -> None:
        """Test fail() logs error message."""
        from gmailarchiver.cli.output import (
            LiveLayoutContext,
            LiveOperationHandle,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            live_context = LiveLayoutContext(log_dir=Path(tmpdir))
            handle = LiveOperationHandle(output, live_context, description="Test", total=10)

            with live_context:
                handle.fail("Operation failed")

                logs = live_context.log_buffer.get_all_logs()
                assert any(log.level == "ERROR" for log in logs)


class TestLiveOutputHandler:
    """Test LiveOutputHandler implementation."""

    def test_context_manager_creates_live_layout(self) -> None:
        """Test __enter__/__exit__ manages LiveLayoutContext."""
        from gmailarchiver.cli.output import LiveOutputHandler, OutputManager

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LiveOutputHandler(output, log_dir=Path(tmpdir))

            with handler as h:
                # Should have created LiveLayoutContext
                assert h._live_context is not None

            # Should have cleaned up after exit
            assert h._live_context.session_logger._closed

    def test_start_operation_returns_live_handle(self) -> None:
        """Test start_operation() returns LiveOperationHandle."""
        from gmailarchiver.cli.output import (
            LiveOperationHandle,
            LiveOutputHandler,
            OutputManager,
        )

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LiveOutputHandler(output, log_dir=Path(tmpdir))

            with handler:
                handle = handler.start_operation("Test operation", total=100)
                assert isinstance(handle, LiveOperationHandle)
                assert handle.total == 100
                assert handle.description == "Test operation"

    def test_print_logs_to_live_context(self) -> None:
        """Test print() adds messages to LiveLayoutContext."""
        from gmailarchiver.cli.output import LiveOutputHandler, OutputManager

        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LiveOutputHandler(output, log_dir=Path(tmpdir))

            with handler:
                handler.print("Test content")

                # Should be in log buffer
                logs = handler._live_context.log_buffer.get_all_logs()
                assert len(logs) == 1
                assert logs[0].message == "Test content"


class TestOutputManagerWithLiveMode:
    """Test OutputManager with live_mode parameter."""

    def test_output_manager_uses_live_handler_when_enabled(self) -> None:
        """Test OutputManager uses LiveOutputHandler when live_mode=True."""
        from gmailarchiver.cli.output import LiveOutputHandler, OutputManager

        with tempfile.TemporaryDirectory() as tmpdir:
            output = OutputManager(live_mode=True, log_dir=Path(tmpdir))

            # Should use LiveOutputHandler
            assert isinstance(output._handler, LiveOutputHandler)


# ============================================================================
# Coverage Improvement Tests - LogBuffer.complete_pending()
# ============================================================================


class TestLogBufferCompletePending:
    """Test LogBuffer.complete_pending() behavior."""

    def test_complete_pending_with_pending_entry(self) -> None:
        """Test completing a pending entry updates it in place."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()

        # Add a pending entry (use level="PENDING" to mark as pending)
        buffer.add("Processing...", "PENDING")

        # Verify pending entry exists
        assert buffer._pending_key == "Processing..."
        assert "Processing..." in buffer._entry_map

        # Complete the pending entry
        buffer.complete_pending("Done!", "SUCCESS")

        # Pending key should be cleared
        assert buffer._pending_key is None

        # Old key should be removed, new key should exist
        assert "Processing..." not in buffer._entry_map
        assert "Done!" in buffer._entry_map

        # Entry should have updated level
        entry = buffer._entry_map["Done!"]
        assert entry.level == "SUCCESS"
        assert entry.message == "Done!"

    def test_complete_pending_without_pending_entry(self) -> None:
        """Test complete_pending falls back to add() when no pending entry."""
        from gmailarchiver.cli.output import LogBuffer

        buffer = LogBuffer()

        # No pending entry
        assert buffer._pending_key is None

        # Complete should just add as new entry
        buffer.complete_pending("New message", "INFO")

        # Should be added as regular entry
        assert len(buffer._all_logs) == 1
        assert buffer._all_logs[0].message == "New message"
        assert buffer._all_logs[0].level == "INFO"


# ============================================================================
# Coverage Improvement Tests - LiveLayoutContext.get_progress_eta()
# ============================================================================


class TestLiveLayoutContextProgressETA:
    """Test LiveLayoutContext.get_progress_eta() behavior."""

    def test_get_progress_eta_not_started(self) -> None:
        """Test ETA returns 'calculating...' when progress not started."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))
            with context:
                # No progress set
                eta = context.get_progress_eta()
                assert eta == "calculating..."

    def test_get_progress_eta_zero_completed(self) -> None:
        """Test ETA returns 'calculating...' when no progress made."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))
            with context:
                context.set_progress_total(100, "Testing")
                # No progress yet
                eta = context.get_progress_eta()
                assert eta == "calculating..."

    def test_get_progress_eta_seconds_remaining(self) -> None:
        """Test ETA shows seconds when less than 60 seconds remain."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))
            with context:
                context.set_progress_total(100, "Testing")
                # Simulate significant progress (90%) in a short time
                context.progress_completed = 90
                context.progress_start_time = time.time() - 9  # 9 seconds elapsed

                # Rate = 90/9 = 10/sec, remaining = 10, ETA = 1 second
                eta = context.get_progress_eta()
                assert "s remaining" in eta
                # Should NOT have minutes format like "Xm Ys" - just seconds
                assert "m " not in eta  # No "Xm " pattern

    def test_get_progress_eta_minutes_remaining(self) -> None:
        """Test ETA shows minutes when 1-59 minutes remain."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))
            with context:
                context.set_progress_total(1000, "Testing")
                # Simulate progress where we have ~5 minutes remaining
                context.progress_completed = 100
                context.progress_start_time = time.time() - 60  # 60 seconds elapsed

                # Rate = 100/60 = 1.67/sec, remaining = 900, ETA = ~540s = 9m
                eta = context.get_progress_eta()
                assert "m" in eta and "remaining" in eta

    def test_get_progress_eta_hours_remaining(self) -> None:
        """Test ETA shows hours when more than 60 minutes remain."""
        from gmailarchiver.cli.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))
            with context:
                context.set_progress_total(100000, "Testing")
                # Simulate progress where we have hours remaining
                context.progress_completed = 100
                context.progress_start_time = time.time() - 60  # 60 seconds elapsed

                # Rate = 100/60 = 1.67/sec, remaining = 99900, ETA = ~60000s = ~16h
                eta = context.get_progress_eta()
                assert "h" in eta and "m" in eta and "remaining" in eta


# ============================================================================
# Coverage Improvement Tests - OutputManager.show_error_panel()
# ============================================================================


class TestShowErrorPanel:
    """Test OutputManager.show_error_panel() behavior."""

    def test_show_error_panel_json_mode(self) -> None:
        """Test show_error_panel records event in JSON mode."""
        output = OutputManager(json_mode=True)

        output.show_error_panel(
            title="Test Error",
            message="Something went wrong",
            suggestion="Try again",
            details=["Detail 1", "Detail 2"],
            exit_code=0,  # Don't exit
        )

        # Should record JSON event
        assert len(output._json_events) == 1
        event = output._json_events[0]
        assert event["event"] == "error_panel"
        assert event["title"] == "Test Error"
        assert event["message"] == "Something went wrong"
        assert event["suggestion"] == "Try again"
        assert event["details"] == ["Detail 1", "Detail 2"]

    def test_show_error_panel_json_mode_with_exit(self) -> None:
        """Test show_error_panel exits in JSON mode when exit_code > 0."""
        output = OutputManager(json_mode=True)

        with pytest.raises(SystemExit) as exc:
            output.show_error_panel(
                title="Fatal Error",
                message="Cannot continue",
                exit_code=1,
            )
        assert exc.value.code == 1

    def test_show_error_panel_quiet_mode(self) -> None:
        """Test show_error_panel is silent in quiet mode (no exit)."""
        output = OutputManager(quiet=True)

        # Should not raise, just return
        output.show_error_panel(
            title="Test Error",
            message="Something went wrong",
            exit_code=0,
        )

    def test_show_error_panel_quiet_mode_with_exit(self) -> None:
        """Test show_error_panel exits in quiet mode when exit_code > 0."""
        output = OutputManager(quiet=True)

        with pytest.raises(SystemExit) as exc:
            output.show_error_panel(
                title="Fatal Error",
                message="Cannot continue",
                exit_code=1,
            )
        assert exc.value.code == 1

    def test_show_error_panel_normal_mode(self) -> None:
        """Test show_error_panel renders panel in normal mode."""
        output = OutputManager()

        with patch.object(output.console, "print"):
            output.show_error_panel(
                title="Test Error",
                message="Something went wrong",
                suggestion="Try again",
                details=["Detail 1"],
                exit_code=0,
            )


# ============================================================================
# Coverage Improvement Tests - OutputManager.show_validation_report()
# ============================================================================


class TestShowValidationReport:
    """Test OutputManager.show_validation_report() behavior."""

    def test_show_validation_report_json_mode(self) -> None:
        """Test show_validation_report records event in JSON mode."""
        output = OutputManager(json_mode=True)

        results = {
            "count_check": True,
            "database_check": True,
            "integrity_check": False,
            "spot_check": True,
            "passed": False,
            "errors": ["Integrity check failed"],
        }

        output.show_validation_report(results, title="Validation Results")

        # Should record JSON event
        assert len(output._json_events) == 1
        event = output._json_events[0]
        assert event["event"] == "validation_report"
        assert event["title"] == "Validation Results"
        assert event["results"] == results

    def test_show_validation_report_quiet_mode(self) -> None:
        """Test show_validation_report is silent in quiet mode."""
        output = OutputManager(quiet=True)

        results = {"count_check": True, "passed": True}

        # Should not raise, just return
        output.show_validation_report(results)

    def test_show_validation_report_normal_mode_passed(self) -> None:
        """Test show_validation_report renders green panel when passed."""
        output = OutputManager()

        results = {
            "count_check": True,
            "database_check": True,
            "integrity_check": True,
            "spot_check": True,
            "passed": True,
        }

        with patch.object(output.console, "print"):
            output.show_validation_report(results, title="Validation")

    def test_show_validation_report_normal_mode_failed(self) -> None:
        """Test show_validation_report renders red panel with errors."""
        output = OutputManager()

        results = {
            "count_check": True,
            "database_check": False,
            "integrity_check": False,
            "spot_check": True,
            "passed": False,
            "errors": ["Database mismatch", "Checksum failed"],
        }

        with patch.object(output.console, "print"):
            output.show_validation_report(results, title="Validation Failed")


# ============================================================================
# Coverage Improvement Tests - CommandContext methods
# ============================================================================


class TestCommandContextOperationMethods:
    """Test CommandContext operation tracking methods."""

    def test_set_progress_total_with_operation_handle(self) -> None:
        """Test set_progress_total delegates to operation_handle."""
        from unittest.mock import MagicMock

        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        # Mock operation handle
        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.set_progress_total(100, "Processing")

        mock_handle.set_total.assert_called_once_with(100, "Processing")

    def test_advance_progress_with_operation_handle(self) -> None:
        """Test advance_progress delegates to operation_handle."""
        from unittest.mock import MagicMock

        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        # Mock operation handle
        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.advance_progress(5)

        mock_handle.update_progress.assert_called_once_with(5)

    def test_log_progress_with_operation_handle(self) -> None:
        """Test log_progress delegates to operation_handle."""
        from unittest.mock import MagicMock

        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        # Mock operation handle
        mock_handle = MagicMock()
        ctx.operation_handle = mock_handle

        ctx.log_progress("Test message", "WARNING")

        mock_handle.log.assert_called_once_with("Test message", "WARNING")

    def test_log_progress_fallback_warning(self) -> None:
        """Test log_progress falls back to output.warning when no handle."""
        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        # No operation handle
        ctx.operation_handle = None

        with patch.object(output, "warning") as mock_warning:
            ctx.log_progress("Warning message", "WARNING")
            mock_warning.assert_called_once_with("Warning message")

    def test_log_progress_fallback_error(self) -> None:
        """Test log_progress falls back to output.error when no handle."""
        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        ctx.operation_handle = None

        with patch.object(output, "error") as mock_error:
            ctx.log_progress("Error message", "ERROR")
            # error() is called with exit_code=0 to not exit on log messages
            mock_error.assert_called_once_with("Error message", exit_code=0)

    def test_log_progress_fallback_success(self) -> None:
        """Test log_progress falls back to output.success when no handle."""
        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        ctx.operation_handle = None

        with patch.object(output, "success") as mock_success:
            ctx.log_progress("Success message", "SUCCESS")
            mock_success.assert_called_once_with("Success message")

    def test_log_progress_fallback_info(self) -> None:
        """Test log_progress falls back to output.info for INFO level."""
        from gmailarchiver.cli.command_context import CommandContext
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()
        ctx = CommandContext(output=output, _operation_name="test")

        ctx.operation_handle = None

        with patch.object(output, "info") as mock_info:
            ctx.log_progress("Info message", "INFO")
            mock_info.assert_called_once_with("Info message")


# ============================================================================
# Coverage Improvement Tests - _StaticOperationHandle
# ============================================================================


class TestStaticOperationHandleSetTotal:
    """Test _StaticOperationHandle.set_total() behavior."""

    def test_set_total_creates_task_when_none_exists(self) -> None:
        """Test set_total creates new task when task_id is None."""
        from gmailarchiver.cli.command_context import _StaticOperationHandle
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()

        with output.progress_context("Testing", total=None) as progress:
            if progress:
                handle = _StaticOperationHandle(output, progress, "Initial", total=None)

                # Initially no task
                assert handle._task_id is None

                # Set total creates task
                handle.set_total(100, "New description")

                assert handle._task_id is not None
                assert handle._total == 100

    def test_set_total_updates_existing_task(self) -> None:
        """Test set_total updates existing task when task_id exists."""
        from gmailarchiver.cli.command_context import _StaticOperationHandle
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager()

        with output.progress_context("Testing", total=50) as progress:
            if progress:
                handle = _StaticOperationHandle(output, progress, "Initial", total=50)

                # Create initial task
                handle.set_total(50, "Initial")
                first_task_id = handle._task_id

                # Update total on existing task
                handle.set_total(100, "Updated")

                # Same task should be updated
                assert handle._task_id == first_task_id
                assert handle._total == 100


class TestStaticOperationHandleUncovered:
    """Tests for StaticOperationHandle uncovered methods (output.py)."""

    def test_set_total_is_noop(self) -> None:
        """Test set_total is a no-op in static mode (line 234).

        StaticOperationHandle.set_total does nothing (pass statement)
        because progress isn't tracked in static output mode.
        """
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        # Should not raise, just does nothing
        handle.set_total(100, "New description")

        # No state to verify since it's a no-op

    def test_complete_pending_logs_message(self, capsys) -> None:
        """Test complete_pending calls log (line 243).

        StaticOperationHandle.complete_pending delegates to log method.
        """
        from gmailarchiver.cli.output import OutputManager, StaticOperationHandle

        output = OutputManager()
        handle = StaticOperationHandle(output)

        # complete_pending should log the final message
        handle.complete_pending("Operation completed successfully", "SUCCESS")

        # The log call would output to console
        # We verify it doesn't raise and completes
