"""Tests for WorkflowProgressWidget - multi-step workflow display component."""

from rich.console import Group

from gmailarchiver.cli.ui.widgets.log_window import LogLevel, LogWindowWidget
from gmailarchiver.cli.ui.widgets.task import TaskStatus, TaskWidget
from gmailarchiver.cli.ui.widgets.workflow_progress import WorkflowProgressWidget


class TestWorkflowProgressWidgetInitialization:
    """Tests for WorkflowProgressWidget initialization."""

    def test_default_initialization(self) -> None:
        """WorkflowProgressWidget initializes with default values."""
        widget = WorkflowProgressWidget()
        assert widget.show_logs is True
        assert widget.max_logs == 5
        assert widget.task_count == 0
        assert widget.log_count == 0

    def test_custom_initialization(self) -> None:
        """WorkflowProgressWidget accepts custom initialization."""
        widget = WorkflowProgressWidget(show_logs=False, max_logs=10)
        assert widget.show_logs is False
        assert widget.max_logs == 10

    def test_log_window_initialized(self) -> None:
        """WorkflowProgressWidget initializes log window after init."""
        widget = WorkflowProgressWidget(max_logs=7, show_logs=True)
        assert isinstance(widget._log_window, LogWindowWidget)
        assert widget._log_window.max_size == 7
        assert widget._log_window.show_separator is True

    def test_tasks_list_empty_initially(self) -> None:
        """WorkflowProgressWidget starts with empty tasks list."""
        widget = WorkflowProgressWidget()
        assert len(widget._tasks) == 0
        assert widget.task_count == 0


class TestWorkflowProgressWidgetTaskManagement:
    """Tests for task management functionality."""

    def test_add_task_returns_widget(self) -> None:
        """add_task() returns TaskWidget."""
        widget = WorkflowProgressWidget()
        task = widget.add_task("Test task")
        assert isinstance(task, TaskWidget)
        assert task.description == "Test task"

    def test_add_task_increments_count(self) -> None:
        """add_task() increments task_count."""
        widget = WorkflowProgressWidget()
        assert widget.task_count == 0
        widget.add_task("Task 1")
        assert widget.task_count == 1
        widget.add_task("Task 2")
        assert widget.task_count == 2

    def test_add_multiple_tasks(self) -> None:
        """Multiple tasks can be added."""
        widget = WorkflowProgressWidget()
        task1 = widget.add_task("First")
        task2 = widget.add_task("Second")
        task3 = widget.add_task("Third")
        assert widget.task_count == 3
        assert task1.description == "First"
        assert task2.description == "Second"
        assert task3.description == "Third"

    def test_current_task_returns_running_task(self) -> None:
        """current_task() returns the running task if one exists."""
        widget = WorkflowProgressWidget()
        task1 = widget.add_task("First").complete("Done")
        task2 = widget.add_task("Second").start()
        assert widget.current_task() == task2

    def test_current_task_returns_none_when_no_running_task(self) -> None:
        """current_task() returns None when no task is running."""
        widget = WorkflowProgressWidget()
        widget.add_task("First").complete("Done")
        widget.add_task("Second").complete("Also done")
        assert widget.current_task() is None

    def test_current_task_returns_most_recent_running(self) -> None:
        """current_task() returns most recent running task if multiple."""
        widget = WorkflowProgressWidget()
        task1 = widget.add_task("First").start()
        task2 = widget.add_task("Second").start()
        # Most recent should be task2
        assert widget.current_task() == task2

    def test_current_task_none_when_empty(self) -> None:
        """current_task() returns None when no tasks added."""
        widget = WorkflowProgressWidget()
        assert widget.current_task() is None


class TestWorkflowProgressWidgetLogging:
    """Tests for log window delegation methods."""

    def test_log_adds_entry(self) -> None:
        """log() adds entry to log window."""
        widget = WorkflowProgressWidget()
        widget.log("Test message", LogLevel.INFO)
        assert widget.log_count == 1

    def test_log_with_custom_level(self) -> None:
        """log() uses specified log level."""
        widget = WorkflowProgressWidget()
        widget.log("Info", LogLevel.INFO)
        widget.log("Success", LogLevel.SUCCESS)
        widget.log("Warning", LogLevel.WARNING)
        widget.log("Error", LogLevel.ERROR)
        assert widget.log_count == 4

    def test_log_returns_self(self) -> None:
        """log() returns self for fluent chaining."""
        widget = WorkflowProgressWidget()
        result = widget.log("Test")
        assert result is widget

    def test_log_success_adds_success_entry(self) -> None:
        """log_success() adds success level entry."""
        widget = WorkflowProgressWidget()
        widget.log_success("Success message")
        # Verify it was added to log window
        assert widget._log_window.has_entries

    def test_log_warning_adds_warning_entry(self) -> None:
        """log_warning() adds warning level entry."""
        widget = WorkflowProgressWidget()
        widget.log_warning("Warning message")
        assert widget._log_window.has_entries

    def test_log_error_adds_error_entry(self) -> None:
        """log_error() adds error level entry."""
        widget = WorkflowProgressWidget()
        widget.log_error("Error message")
        assert widget._log_window.has_entries

    def test_log_info_adds_info_entry(self) -> None:
        """log_info() adds info level entry."""
        widget = WorkflowProgressWidget()
        widget.log_info("Info message")
        assert widget._log_window.has_entries

    def test_log_methods_return_self(self) -> None:
        """All log methods return self for chaining."""
        widget = WorkflowProgressWidget()
        assert widget.log_success("msg") is widget
        assert widget.log_warning("msg") is widget
        assert widget.log_error("msg") is widget
        assert widget.log_info("msg") is widget

    def test_fluent_chaining_logging(self) -> None:
        """Log methods can be chained."""
        widget = WorkflowProgressWidget()
        widget.log_success("First").log_info("Second").log_warning("Third")
        assert widget.log_count == 3

    def test_logging_disabled_when_show_logs_false(self) -> None:
        """Logs not added when show_logs=False."""
        widget = WorkflowProgressWidget(show_logs=False)
        widget.log("Test message", LogLevel.INFO)
        # Log window should not have entries
        assert not widget._log_window.has_entries
        # But log_count is still 0
        assert widget.log_count == 0

    def test_logging_enabled_when_show_logs_true(self) -> None:
        """Logs are added when show_logs=True."""
        widget = WorkflowProgressWidget(show_logs=True)
        widget.log("Test message", LogLevel.INFO)
        assert widget._log_window.has_entries


class TestWorkflowProgressWidgetProperties:
    """Tests for widget properties."""

    def test_task_count_property(self) -> None:
        """task_count property returns correct count."""
        widget = WorkflowProgressWidget()
        assert widget.task_count == 0
        widget.add_task("1")
        assert widget.task_count == 1
        widget.add_task("2")
        assert widget.task_count == 2

    def test_log_count_property(self) -> None:
        """log_count property returns correct count."""
        widget = WorkflowProgressWidget()
        assert widget.log_count == 0
        widget.log("Message 1")
        assert widget.log_count == 1
        widget.log("Message 2")
        assert widget.log_count == 2

    def test_log_count_exceeds_visible(self) -> None:
        """log_count counts all entries even when scrolled out."""
        widget = WorkflowProgressWidget(max_logs=3)
        # Add 5 messages to a window that shows 3
        widget.log("1").log("2").log("3").log("4").log("5")
        # Should show 3 visible
        assert widget._log_window.visible_count == 3
        # But total should be 5
        assert widget.log_count == 5


class TestWorkflowProgressWidgetRendering:
    """Tests for Rich rendering."""

    def test_render_returns_group(self) -> None:
        """render() returns Rich Group."""
        widget = WorkflowProgressWidget()
        result = widget.render()
        assert isinstance(result, Group)

    def test_render_empty_widget(self) -> None:
        """render() handles empty widget."""
        widget = WorkflowProgressWidget()
        result = widget.render()
        # Should still return a Group (even if empty)
        assert isinstance(result, Group)

    def test_render_single_task(self) -> None:
        """render() displays single task."""
        widget = WorkflowProgressWidget()
        widget.add_task("Processing").start()
        result = widget.render()
        assert isinstance(result, Group)

    def test_render_multiple_tasks(self) -> None:
        """render() displays multiple tasks in order."""
        widget = WorkflowProgressWidget()
        widget.add_task("Task 1").complete("Done")
        widget.add_task("Task 2").start()
        widget.add_task("Task 3")
        result = widget.render()
        # Should render all three tasks
        assert isinstance(result, Group)

    def test_render_with_animation_frame(self) -> None:
        """render() passes animation_frame to tasks."""
        widget = WorkflowProgressWidget()
        widget.add_task("Processing").start()
        # Should not raise error with animation frame
        result = widget.render(animation_frame=5)
        assert isinstance(result, Group)

    def test_render_includes_log_window_when_enabled(self) -> None:
        """render() includes log window when show_logs=True and has entries."""
        widget = WorkflowProgressWidget(show_logs=True)
        widget.add_task("Task").start()
        widget.log_success("Log entry")
        result = widget.render()
        # Should include both task and log window
        assert isinstance(result, Group)

    def test_render_excludes_log_window_when_disabled(self) -> None:
        """render() excludes log window when show_logs=False."""
        widget = WorkflowProgressWidget(show_logs=False)
        widget.add_task("Task").start()
        widget.log("Entry")  # This should not be added
        result = widget.render()
        assert isinstance(result, Group)

    def test_render_excludes_empty_log_window(self) -> None:
        """render() excludes log window when it has no entries."""
        widget = WorkflowProgressWidget(show_logs=True)
        widget.add_task("Task").start()
        # Don't add any logs
        result = widget.render()
        # Should still render the task
        assert isinstance(result, Group)

    def test_render_different_animation_frames(self) -> None:
        """render() produces different output for different animation frames."""
        widget = WorkflowProgressWidget()
        widget.add_task("Processing").start()

        result1 = widget.render(animation_frame=0)
        result2 = widget.render(animation_frame=5)

        # Both should be valid groups
        assert isinstance(result1, Group)
        assert isinstance(result2, Group)


class TestWorkflowProgressWidgetJSON:
    """Tests for JSON serialization."""

    def test_to_json_returns_dict(self) -> None:
        """to_json() returns dictionary."""
        widget = WorkflowProgressWidget()
        result = widget.to_json()
        assert isinstance(result, dict)

    def test_to_json_empty_widget(self) -> None:
        """to_json() handles empty widget."""
        widget = WorkflowProgressWidget()
        result = widget.to_json()
        assert result["type"] == "workflow_progress"
        assert result["show_logs"] is True
        assert result["max_logs"] == 5
        assert result["tasks"] == []

    def test_to_json_with_tasks(self) -> None:
        """to_json() includes all tasks."""
        widget = WorkflowProgressWidget()
        widget.add_task("Task 1").complete("Done")
        widget.add_task("Task 2").start()
        result = widget.to_json()

        assert len(result["tasks"]) == 2
        assert result["tasks"][0]["description"] == "Task 1"
        assert result["tasks"][1]["description"] == "Task 2"

    def test_to_json_with_logs_enabled(self) -> None:
        """to_json() includes logs when show_logs=True."""
        widget = WorkflowProgressWidget(show_logs=True)
        widget.log_success("Log 1")
        widget.log_error("Log 2")
        result = widget.to_json()

        assert result["logs"] is not None
        assert isinstance(result["logs"], dict)

    def test_to_json_with_logs_disabled(self) -> None:
        """to_json() excludes logs when show_logs=False."""
        widget = WorkflowProgressWidget(show_logs=False)
        widget.log("This shouldn't appear")
        result = widget.to_json()

        assert result["logs"] is None

    def test_to_json_structure(self) -> None:
        """to_json() has correct structure."""
        widget = WorkflowProgressWidget(show_logs=True, max_logs=7)
        widget.add_task("Task 1").start().set_progress(25, 100)
        widget.log_success("Success message")

        result = widget.to_json()

        assert "type" in result
        assert "show_logs" in result
        assert "max_logs" in result
        assert "tasks" in result
        assert "logs" in result


class TestWorkflowProgressWidgetIntegration:
    """Integration tests simulating real workflow scenarios."""

    def test_full_workflow_archive(self) -> None:
        """Simulate a complete archive workflow."""
        wf = WorkflowProgressWidget(max_logs=5, show_logs=True)

        # Step 1: Scan
        task1 = wf.add_task("Scanning messages from Gmail").start()
        task1.complete("Found 15,000 messages")

        # Step 2: Filter
        task2 = wf.add_task("Checking for already archived").start()
        task2.complete("Identified 13,267 to archive")

        # Step 3: Archive with progress
        task3 = wf.add_task("Archiving messages").start()
        task3.set_progress(0, 13267)

        # Simulate logging items
        wf.log_success("Archived: RE: Q4 Budget Review")
        wf.log_success("Archived: Meeting Notes - Product Sync")
        wf.log_success("Archived: Invoice #12345")
        wf.log_warning("Skipped (duplicate): FW: Contract Update")

        # Simulate progress
        task3.set_progress(3980, 13267)

        # Verify state
        assert wf.task_count == 3
        assert wf.log_count == 4
        assert wf.current_task() == task3
        assert task3.status == TaskStatus.RUNNING

    def test_workflow_with_failure(self) -> None:
        """Simulate workflow with task failure."""
        wf = WorkflowProgressWidget()

        task1 = wf.add_task("Scanning").start()
        task1.complete("Found 100")

        task2 = wf.add_task("Processing").start()
        task2.fail("Process failed", reason="Database connection lost")

        assert wf.task_count == 2
        assert task2.status == TaskStatus.FAILED
        assert wf.current_task() is None  # No running tasks

    def test_workflow_with_warnings(self) -> None:
        """Simulate workflow with task warnings."""
        wf = WorkflowProgressWidget()

        task1 = wf.add_task("Validation").start()
        task1.warn("Completed with warnings")

        assert task1.status == TaskStatus.WARNING
        assert wf.log_count == 0  # No logs added yet

    def test_fluent_workflow_building(self) -> None:
        """Build complete workflow using fluent chaining."""
        wf = WorkflowProgressWidget()

        # Add and complete multiple tasks with chaining
        wf.add_task("Scan").start().complete("Found 100")
        wf.add_task("Process").start()
        wf.log_success("Item 1").log_success("Item 2")

        assert wf.task_count == 2
        assert wf.log_count == 2

        # Current task should be Process
        current = wf.current_task()
        assert current is not None
        assert current.description == "Process"

    def test_workflow_logging_with_different_levels(self) -> None:
        """Test logging with all different severity levels."""
        wf = WorkflowProgressWidget()

        wf.log_info("Informational message")
        wf.log_success("Successful operation")
        wf.log_warning("Warning condition")
        wf.log_error("Error occurred")

        assert wf.log_count == 4

    def test_workflow_render_sequence(self) -> None:
        """Test rendering at different workflow stages."""
        wf = WorkflowProgressWidget()

        # Initial render
        render1 = wf.render()
        assert isinstance(render1, Group)

        # Add task and render
        wf.add_task("Task").start()
        render2 = wf.render(animation_frame=0)
        assert isinstance(render2, Group)

        # Add logs and render
        wf.log_success("Log")
        render3 = wf.render(animation_frame=1)
        assert isinstance(render3, Group)

        # Complete task and render
        wf.current_task().complete("Done")
        render4 = wf.render()
        assert isinstance(render4, Group)

    def test_multiple_workflows_independent(self) -> None:
        """Multiple workflow widgets remain independent."""
        wf1 = WorkflowProgressWidget(max_logs=3)
        wf2 = WorkflowProgressWidget(max_logs=5)

        wf1.add_task("Task 1")
        wf2.add_task("Task A")
        wf2.add_task("Task B")

        assert wf1.task_count == 1
        assert wf2.task_count == 2
        assert wf1.max_logs == 3
        assert wf2.max_logs == 5

    def test_workflow_json_export(self) -> None:
        """Export complete workflow as JSON."""
        wf = WorkflowProgressWidget()

        wf.add_task("Scan").complete("Found 100")
        wf.add_task("Process").start().set_progress(50, 100)
        wf.log_success("Processed item 1")
        wf.log_success("Processed item 2")

        json_data = wf.to_json()

        # Verify structure
        assert json_data["type"] == "workflow_progress"
        assert len(json_data["tasks"]) == 2
        assert json_data["tasks"][0]["status"] == "success"
        assert json_data["tasks"][1]["status"] == "running"
        assert json_data["logs"] is not None


class TestWorkflowProgressWidgetEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_task_with_long_description(self) -> None:
        """Handle task with very long description."""
        wf = WorkflowProgressWidget()
        long_desc = "A" * 200
        wf.add_task(long_desc)
        assert wf.task_count == 1

    def test_log_with_unicode_characters(self) -> None:
        """Handle log entries with unicode."""
        wf = WorkflowProgressWidget()
        wf.log_success("Processed 你好 items")
        wf.log_warning("⚠️ Warning: special chars")
        assert wf.log_count == 2

    def test_many_tasks(self) -> None:
        """Handle widget with many tasks."""
        wf = WorkflowProgressWidget()
        for i in range(100):
            wf.add_task(f"Task {i}")
        assert wf.task_count == 100

    def test_log_window_overflow(self) -> None:
        """Log window scrolls properly when exceeding max_size."""
        wf = WorkflowProgressWidget(max_logs=3)
        # Add 10 logs to a window with max 3
        for i in range(10):
            wf.log(f"Message {i}")

        # Total should be 10
        assert wf.log_count == 10
        # Visible should be 3
        assert wf._log_window.visible_count == 3

    def test_render_no_crash_with_mixed_states(self) -> None:
        """Render handles mixed task states without crashing."""
        wf = WorkflowProgressWidget()
        wf.add_task("Pending")  # PENDING
        wf.add_task("Running").start()  # RUNNING
        wf.add_task("Success").complete("Done")  # SUCCESS
        wf.add_task("Failed").fail("Error")  # FAILED
        wf.add_task("Warning").warn("Watch out")  # WARNING

        # Should render without error
        result = wf.render(animation_frame=3)
        assert isinstance(result, Group)

    def test_current_task_with_all_status_types(self) -> None:
        """current_task returns running even with all status types."""
        wf = WorkflowProgressWidget()
        wf.add_task("1").complete("Done")
        wf.add_task("2").fail("Failed")
        wf.add_task("3").warn("Warning")
        running_task = wf.add_task("4").start()
        wf.add_task("5")  # PENDING

        assert wf.current_task() == running_task

    def test_task_status_transitions(self) -> None:
        """Task transitions are reflected in workflow."""
        wf = WorkflowProgressWidget()
        task = wf.add_task("Multi-state")

        assert task.status == TaskStatus.PENDING
        task.start()
        assert wf.current_task() == task

        task.set_progress(50, 100)
        assert wf.current_task() == task

        task.complete("Done")
        assert wf.current_task() is None

    def test_empty_widget_json(self) -> None:
        """Empty workflow produces valid JSON."""
        wf = WorkflowProgressWidget()
        json_data = wf.to_json()

        # Should be valid and minimal
        assert json_data["type"] == "workflow_progress"
        assert json_data["tasks"] == []
        assert json_data["logs"] is None or json_data["logs"]["visible_entries"] == []
