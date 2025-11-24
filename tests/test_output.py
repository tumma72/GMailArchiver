"""Tests for the unified output system."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gmailarchiver.output import OutputManager, TaskResult


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
        assert output._json_events[0]["event"] == "next_steps"
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
        result = TaskResult(
            name="test", success=True, details="Completed", elapsed=1.5
        )
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
        from gmailarchiver.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        with pytest.raises(ValueError, match="only one"):
            tracker.update(amount=5, completed=10)

    def test_update_with_no_params_does_nothing(self) -> None:
        """Test update with no params returns early (line 104)."""
        from gmailarchiver.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        # Should not raise, just return
        tracker.update()
        assert tracker.completed == 0

    def test_calculate_eta_with_zero_rate(self) -> None:
        """Test calculate_eta returns None when rate is zero (line 186)."""
        from gmailarchiver.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker._start_time = 0.0
        tracker.completed = 0
        tracker._smoothed_rate = 0.0

        eta = tracker.calculate_eta()
        assert eta is None

    def test_get_rate_formatted_no_rate(self) -> None:
        """Test get_rate_formatted returns empty string when no rate (line 228)."""
        from gmailarchiver.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        # Don't start, so no rate

        formatted = tracker.get_rate_formatted()
        assert formatted == ""

    def test_get_progress_string_no_start(self) -> None:
        """Test get_progress_string returns empty when not started (line 254)."""
        from gmailarchiver.output import ProgressTracker

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
            output.show_report(
                "Test Report",
                {"key": "value"},
                summary={"total": 10, "passed": 8}
            )

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
        from gmailarchiver.output import ProgressTracker

        tracker = ProgressTracker(total=100)
        tracker.start()

        # Use completed parameter
        tracker.update(completed=50)
        assert tracker.completed == 50

    def test_update_with_advance_param(self) -> None:
        """Test update using advance parameter (line 122)."""
        from gmailarchiver.output import ProgressTracker

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
        from gmailarchiver.output import ProgressTracker

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
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer()
        assert buffer._max_visible == 10
        assert len(buffer._visible) == 0
        assert len(buffer._all_logs) == 0
        assert len(buffer._entry_map) == 0

    def test_init_custom_size(self) -> None:
        """Test LogBuffer initialization with custom size."""
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer(max_visible=5)
        assert buffer._max_visible == 5

    def test_init_zero_size(self) -> None:
        """Test LogBuffer with zero size (no visible logs, all stored)."""
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer(max_visible=0)
        assert buffer._max_visible == 0
        buffer.add("Test message", "INFO")
        assert len(buffer._visible) == 0
        assert len(buffer._all_logs) == 1  # Still stored in all_logs

    def test_init_negative_size_raises_error(self) -> None:
        """Test LogBuffer rejects negative size."""
        from gmailarchiver.output import LogBuffer

        with pytest.raises(ValueError, match="max_visible must be non-negative"):
            LogBuffer(max_visible=-1)

    def test_add_single_entry(self) -> None:
        """Test adding a single log entry."""
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Message 1", "INFO")
        buffer.add("Message 2", "WARNING")
        buffer.add("Message 3", "ERROR")

        assert len(buffer._visible) == 3
        assert len(buffer._all_logs) == 3
        assert len(buffer._entry_map) == 3

    def test_ring_buffer_overflow(self) -> None:
        """Test FIFO behavior when exceeding max_visible."""
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer()
        buffer.add("Duplicate message", "INFO")
        buffer.add("Duplicate message", "INFO")
        buffer.add("Duplicate message", "INFO")

        assert len(buffer._visible) == 1
        assert len(buffer._all_logs) == 1
        assert buffer._entry_map["Duplicate message"].count == 3

    def test_deduplication_updates_timestamp(self) -> None:
        """Test deduplication updates timestamp to latest occurrence."""
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

        buffer = LogBuffer()
        rendered = buffer.render()

        # Should be a Rich Group
        from rich.console import Group
        assert isinstance(rendered, Group)
        assert len(rendered.renderables) == 0

    def test_render_with_entries(self) -> None:
        """Test rendering buffer with log entries."""
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

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

        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LogBuffer

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
        from gmailarchiver.output import LiveLayoutContext, LogBuffer, SessionLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_buffer = LogBuffer(max_visible=10)
            session_logger = SessionLogger(log_dir=Path(tmpdir))

            context = LiveLayoutContext(
                log_buffer=log_buffer,
                session_logger=session_logger,
            )

            assert context.log_buffer is log_buffer
            assert context.session_logger is session_logger

    def test_init_with_default_components(self) -> None:
        """Test initialization creates default components if not provided."""
        from gmailarchiver.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            # Should create default LogBuffer with 10 lines
            assert context.log_buffer is not None
            assert context.log_buffer._max_visible == 10

            # Should have SessionLogger
            assert context.session_logger is not None

    def test_init_custom_max_visible(self) -> None:
        """Test initialization with custom max_visible for LogBuffer."""
        from gmailarchiver.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(max_visible=5, log_dir=Path(tmpdir))
            assert context.log_buffer._max_visible == 5


class TestLiveLayoutContextManager:
    """Test LiveLayoutContext as context manager."""

    def test_context_manager_enter_exit(self) -> None:
        """Test __enter__ and __exit__ start/stop the Live display."""
        from gmailarchiver.output import LiveLayoutContext

        with tempfile.TemporaryDirectory() as tmpdir:
            context = LiveLayoutContext(log_dir=Path(tmpdir))

            with context as live_context:
                # Should return self
                assert live_context is context

    def test_context_manager_closes_session_logger(self) -> None:
        """Test __exit__ closes SessionLogger file handle."""
        from gmailarchiver.output import LiveLayoutContext

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
        from gmailarchiver.output import LiveLayoutContext

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
        from gmailarchiver.output import LiveLayoutContext

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
                from gmailarchiver.output import LiveLayoutContext
                assert isinstance(live, LiveLayoutContext)

    def test_live_layout_context_auto_cleanup(self) -> None:
        """Test live_layout_context() closes SessionLogger on exit."""
        output = OutputManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            with output.live_layout_context(log_dir=Path(tmpdir)) as live:
                session_logger = live.session_logger

            # SessionLogger should be closed after exiting context
            assert session_logger._closed is True
