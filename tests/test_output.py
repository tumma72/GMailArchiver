"""Tests for the unified output system."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

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
