"""Tests for TaskHandleImpl and new protocol methods."""

from unittest.mock import MagicMock

from gmailarchiver.cli.ui.builder import TaskHandleImpl, TaskSequenceImpl
from gmailarchiver.cli.ui.widgets.task import TaskStatus, TaskWidget
from gmailarchiver.shared.protocols import NoOpTaskHandle


class TestTaskHandleImplSetStatus:
    """Tests for set_status() method."""

    def test_set_status_updates_description(self) -> None:
        """set_status() updates the task description."""
        widget = TaskWidget("Initial description")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("Updated status message")

        assert widget.description == "Updated status message"

    def test_set_status_preserves_status(self) -> None:
        """set_status() does not change task status."""
        widget = TaskWidget("Task").start()
        assert widget.status == TaskStatus.RUNNING

        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("New status")

        # Status should still be RUNNING
        assert widget.status == TaskStatus.RUNNING

    def test_set_status_triggers_refresh(self) -> None:
        """set_status() calls sequence refresh."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("Status update")

        sequence._refresh.assert_called_once()

    def test_set_status_with_empty_string(self) -> None:
        """set_status() works with empty string."""
        widget = TaskWidget("Original")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("")

        assert widget.description == ""
        sequence._refresh.assert_called_once()

    def test_set_status_with_special_characters(self) -> None:
        """set_status() handles special characters."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        special_text = "Processing [123] & {456} -> 789"
        handle.set_status(special_text)

        assert widget.description == special_text

    def test_set_status_multiple_times(self) -> None:
        """set_status() can be called multiple times."""
        widget = TaskWidget("Initial")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("First update")
        handle.set_status("Second update")
        handle.set_status("Third update")

        assert widget.description == "Third update"
        # refresh should be called 3 times
        assert sequence._refresh.call_count == 3

    def test_set_status_while_task_running(self) -> None:
        """set_status() works during running task."""
        widget = TaskWidget("Processing").start()
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("Scanning: Found 1,234 messages")

        assert widget.description == "Scanning: Found 1,234 messages"
        assert widget.status == TaskStatus.RUNNING

    def test_set_status_with_progress(self) -> None:
        """set_status() works with tasks that have progress."""
        widget = TaskWidget("Processing").start().set_progress(50, 100)
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.set_status("Half done: 50/100 items")

        assert widget.description == "Half done: 50/100 items"
        assert widget.completed == 50
        assert widget.total == 100


class TestTaskHandleImplWarn:
    """Tests for warn() method."""

    def test_warn_sets_warning_status(self) -> None:
        """warn() sets task status to WARNING."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Warning message")

        assert widget.status == TaskStatus.WARNING

    def test_warn_sets_result_message(self) -> None:
        """warn() sets the result_message."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Some warnings occurred")

        assert widget.result_message == "Some warnings occurred"

    def test_warn_triggers_refresh(self) -> None:
        """warn() calls sequence refresh."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Warning")

        sequence._refresh.assert_called_once()

    def test_warn_preserves_description(self) -> None:
        """warn() does not change task description."""
        widget = TaskWidget("Original description")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Warning message")

        assert widget.description == "Original description"

    def test_warn_with_empty_message(self) -> None:
        """warn() works with empty message."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("")

        assert widget.status == TaskStatus.WARNING
        assert widget.result_message == ""

    def test_warn_with_long_message(self) -> None:
        """warn() handles long warning messages."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        long_message = "Warning: " + "A" * 200
        handle.warn(long_message)

        assert widget.result_message == long_message
        assert widget.status == TaskStatus.WARNING

    def test_warn_with_special_characters(self) -> None:
        """warn() handles special characters in message."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        message = "Warning: Found [123] items & {456} duplicates"
        handle.warn(message)

        assert widget.result_message == message

    def test_warn_multiple_times(self) -> None:
        """warn() can be called multiple times (overwrites)."""
        widget = TaskWidget("Task")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("First warning")
        handle.warn("Second warning")
        handle.warn("Third warning")

        # Final message should be the last one
        assert widget.result_message == "Third warning"
        assert widget.status == TaskStatus.WARNING
        # refresh should be called 3 times
        assert sequence._refresh.call_count == 3

    def test_warn_after_running(self) -> None:
        """warn() works for task that was running."""
        widget = TaskWidget("Processing").start().set_progress(75, 100)
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Completed with warnings")

        assert widget.status == TaskStatus.WARNING
        assert widget.result_message == "Completed with warnings"
        # Progress should be preserved
        assert widget.completed == 75
        assert widget.total == 100

    def test_warn_complete_workflow(self) -> None:
        """warn() completes a typical warning workflow."""
        widget = TaskWidget("Validation")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        # Start task
        widget.start()
        assert widget.status == TaskStatus.RUNNING

        # Update status message
        handle.set_status("Running validation...")
        assert widget.status == TaskStatus.RUNNING
        assert widget.description == "Running validation..."

        # Complete with warning
        handle.warn("Validation passed with 5 warnings")

        assert widget.status == TaskStatus.WARNING
        assert widget.result_message == "Validation passed with 5 warnings"
        assert widget.description == "Running validation..."  # Description preserved


class TestNoOpTaskHandleSetStatus:
    """Tests for NoOpTaskHandle.set_status()."""

    def test_noop_set_status_does_nothing(self) -> None:
        """NoOpTaskHandle.set_status() does not raise error."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.set_status("Any message")

    def test_noop_set_status_with_empty_string(self) -> None:
        """NoOpTaskHandle.set_status() handles empty string."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.set_status("")

    def test_noop_set_status_with_long_message(self) -> None:
        """NoOpTaskHandle.set_status() handles long message."""
        handle = NoOpTaskHandle()
        long_message = "A" * 1000

        # Should not raise any exception
        handle.set_status(long_message)

    def test_noop_set_status_multiple_calls(self) -> None:
        """NoOpTaskHandle.set_status() can be called multiple times."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.set_status("First")
        handle.set_status("Second")
        handle.set_status("Third")


class TestNoOpTaskHandleWarn:
    """Tests for NoOpTaskHandle.warn()."""

    def test_noop_warn_does_nothing(self) -> None:
        """NoOpTaskHandle.warn() does not raise error."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.warn("Warning message")

    def test_noop_warn_with_empty_message(self) -> None:
        """NoOpTaskHandle.warn() handles empty string."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.warn("")

    def test_noop_warn_with_special_characters(self) -> None:
        """NoOpTaskHandle.warn() handles special characters."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.warn("Warning: [123] & {456} issues")

    def test_noop_warn_multiple_calls(self) -> None:
        """NoOpTaskHandle.warn() can be called multiple times."""
        handle = NoOpTaskHandle()

        # Should not raise any exception
        handle.warn("First warning")
        handle.warn("Second warning")
        handle.warn("Third warning")


class TestTaskHandleImplIntegration:
    """Integration tests for set_status() and warn() together."""

    def test_set_status_then_warn(self) -> None:
        """Task can transition from status update to warning."""
        widget = TaskWidget("Processing")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        widget.start()
        handle.set_status("Processing: 50% complete")
        assert widget.description == "Processing: 50% complete"
        assert widget.status == TaskStatus.RUNNING

        handle.warn("Completed with warnings")
        assert widget.status == TaskStatus.WARNING
        assert widget.result_message == "Completed with warnings"
        assert widget.description == "Processing: 50% complete"  # Description preserved

    def test_warn_with_progress_preserved(self) -> None:
        """warn() preserves progress information."""
        widget = TaskWidget("Task").start().set_progress(100, 500)
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        handle.warn("Processed 100 items with warnings")

        assert widget.completed == 100
        assert widget.total == 500
        assert widget.status == TaskStatus.WARNING
        assert widget.result_message == "Processed 100 items with warnings"

    def test_multiple_status_updates_before_warn(self) -> None:
        """Multiple status updates work before final warning."""
        widget = TaskWidget("Import")
        sequence = MagicMock(spec=TaskSequenceImpl)
        handle = TaskHandleImpl(widget, sequence)

        widget.start()
        handle.set_status("Scanning files...")
        handle.set_status("Found 1,000 files")
        handle.set_status("Processing 500/1,000 files")
        handle.set_status("Processing 750/1,000 files")
        handle.warn("Import completed with skipped files")

        assert widget.description == "Processing 750/1,000 files"
        assert widget.result_message == "Import completed with skipped files"
        assert widget.status == TaskStatus.WARNING
        # refresh called: start + 4 set_status + 1 warn = 6 times
        # Note: start() doesn't call _refresh, only set_status and warn do
        assert sequence._refresh.call_count == 5  # 4 set_status + 1 warn
