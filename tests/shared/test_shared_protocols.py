"""Tests for shared protocols.

This module tests the protocol definitions and no-op implementations in
gmailarchiver.shared.protocols.
"""

from gmailarchiver.shared.protocols import (
    NoOpProgressReporter,
    NoOpTaskHandle,
    NoOpTaskSequence,
    ProgressReporter,
    TaskHandle,
    TaskSequence,
)

# ============================================================================
# Protocol Definition Tests
# ============================================================================


class TestProgressReporterProtocol:
    """Tests for ProgressReporter protocol definition."""

    def test_protocol_has_info_method(self) -> None:
        """ProgressReporter protocol defines info method."""
        assert hasattr(ProgressReporter, "info")

    def test_protocol_has_warning_method(self) -> None:
        """ProgressReporter protocol defines warning method."""
        assert hasattr(ProgressReporter, "warning")

    def test_protocol_has_error_method(self) -> None:
        """ProgressReporter protocol defines error method."""
        assert hasattr(ProgressReporter, "error")

    def test_protocol_has_task_sequence_method(self) -> None:
        """ProgressReporter protocol defines task_sequence method."""
        assert hasattr(ProgressReporter, "task_sequence")


class TestTaskSequenceProtocol:
    """Tests for TaskSequence protocol definition."""

    def test_protocol_has_task_method(self) -> None:
        """TaskSequence protocol defines task method."""
        assert hasattr(TaskSequence, "task")


class TestTaskHandleProtocol:
    """Tests for TaskHandle protocol definition."""

    def test_protocol_has_complete_method(self) -> None:
        """TaskHandle protocol defines complete method."""
        assert hasattr(TaskHandle, "complete")

    def test_protocol_has_fail_method(self) -> None:
        """TaskHandle protocol defines fail method."""
        assert hasattr(TaskHandle, "fail")

    def test_protocol_has_advance_method(self) -> None:
        """TaskHandle protocol defines advance method."""
        assert hasattr(TaskHandle, "advance")

    def test_protocol_has_log_method(self) -> None:
        """TaskHandle protocol defines log method."""
        assert hasattr(TaskHandle, "log")

    def test_protocol_has_set_total_method(self) -> None:
        """TaskHandle protocol defines set_total method."""
        assert hasattr(TaskHandle, "set_total")

    def test_protocol_has_set_status_method(self) -> None:
        """TaskHandle protocol defines set_status method."""
        assert hasattr(TaskHandle, "set_status")

    def test_protocol_has_warn_method(self) -> None:
        """TaskHandle protocol defines warn method."""
        assert hasattr(TaskHandle, "warn")


# ============================================================================
# NoOpTaskHandle Tests
# ============================================================================


class TestNoOpTaskHandle:
    """Tests for NoOpTaskHandle no-op implementation."""

    def test_complete_does_nothing(self) -> None:
        """NoOpTaskHandle.complete() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.complete("Test message")

    def test_fail_does_nothing(self) -> None:
        """NoOpTaskHandle.fail() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.fail("Error message")

    def test_fail_with_reason_does_nothing(self) -> None:
        """NoOpTaskHandle.fail() with reason does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.fail("Error message", reason="Test reason")

    def test_advance_does_nothing(self) -> None:
        """NoOpTaskHandle.advance() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.advance()

    def test_advance_with_n_does_nothing(self) -> None:
        """NoOpTaskHandle.advance(n) does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.advance(5)

    def test_log_does_nothing(self) -> None:
        """NoOpTaskHandle.log() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.log("Test log message")

    def test_log_with_level_does_nothing(self) -> None:
        """NoOpTaskHandle.log() with level does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.log("Test log message", level="WARNING")

    def test_set_total_does_nothing(self) -> None:
        """NoOpTaskHandle.set_total() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.set_total(100)

    def test_set_total_with_description_does_nothing(self) -> None:
        """NoOpTaskHandle.set_total() with description does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.set_total(100, description="Test description")

    def test_set_status_does_nothing(self) -> None:
        """NoOpTaskHandle.set_status() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.set_status("Processing...")

    def test_warn_does_nothing(self) -> None:
        """NoOpTaskHandle.warn() does nothing and doesn't raise."""
        handle = NoOpTaskHandle()
        # Should not raise
        handle.warn("Warning message")

    def test_multiple_calls_safe(self) -> None:
        """NoOpTaskHandle can be called multiple times safely."""
        handle = NoOpTaskHandle()
        # Should not raise on repeated calls
        handle.advance(1)
        handle.advance(2)
        handle.log("Message 1")
        handle.log("Message 2", "ERROR")
        handle.set_total(50)
        handle.set_total(100, "Updated")
        handle.complete("Done")


# ============================================================================
# NoOpTaskSequence Tests
# ============================================================================


class TestNoOpTaskSequence:
    """Tests for NoOpTaskSequence no-op implementation."""

    def test_task_returns_context_manager(self) -> None:
        """NoOpTaskSequence.task() returns a context manager."""
        seq = NoOpTaskSequence()
        ctx = seq.task("Test task")
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")

    def test_task_yields_noop_handle(self) -> None:
        """NoOpTaskSequence.task() yields NoOpTaskHandle."""
        seq = NoOpTaskSequence()
        with seq.task("Test task") as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_with_total(self) -> None:
        """NoOpTaskSequence.task() accepts total parameter."""
        seq = NoOpTaskSequence()
        # Should not raise
        with seq.task("Test task", total=100) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_without_total(self) -> None:
        """NoOpTaskSequence.task() works without total parameter."""
        seq = NoOpTaskSequence()
        # Should not raise
        with seq.task("Test task") as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_multiple_tasks(self) -> None:
        """NoOpTaskSequence can create multiple tasks."""
        seq = NoOpTaskSequence()
        # Should not raise
        with seq.task("Task 1"):
            pass
        with seq.task("Task 2"):
            pass
        with seq.task("Task 3"):
            pass

    def test_task_handle_usable_in_context(self) -> None:
        """NoOpTaskHandle from task() is usable within context."""
        seq = NoOpTaskSequence()
        with seq.task("Test task") as handle:
            # All these should work without raising
            handle.advance(10)
            handle.log("Progress update")
            handle.set_total(100)
            handle.complete("Done")


# ============================================================================
# NoOpProgressReporter Tests
# ============================================================================


class TestNoOpProgressReporter:
    """Tests for NoOpProgressReporter no-op implementation."""

    def test_info_does_nothing(self) -> None:
        """NoOpProgressReporter.info() does nothing and doesn't raise."""
        reporter = NoOpProgressReporter()
        # Should not raise
        reporter.info("Test info message")

    def test_warning_does_nothing(self) -> None:
        """NoOpProgressReporter.warning() does nothing and doesn't raise."""
        reporter = NoOpProgressReporter()
        # Should not raise
        reporter.warning("Test warning message")

    def test_error_does_nothing(self) -> None:
        """NoOpProgressReporter.error() does nothing and doesn't raise."""
        reporter = NoOpProgressReporter()
        # Should not raise
        reporter.error("Test error message")

    def test_task_sequence_returns_context_manager(self) -> None:
        """NoOpProgressReporter.task_sequence() returns a context manager."""
        reporter = NoOpProgressReporter()
        ctx = reporter.task_sequence()
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")

    def test_task_sequence_yields_noop_sequence(self) -> None:
        """NoOpProgressReporter.task_sequence() yields NoOpTaskSequence."""
        reporter = NoOpProgressReporter()
        with reporter.task_sequence() as seq:
            assert isinstance(seq, NoOpTaskSequence)

    def test_task_sequence_can_create_tasks(self) -> None:
        """NoOpProgressReporter.task_sequence() sequence can create tasks."""
        reporter = NoOpProgressReporter()
        with reporter.task_sequence() as seq:
            with seq.task("Test task") as handle:
                assert isinstance(handle, NoOpTaskHandle)
                handle.complete("Done")

    def test_multiple_messages_safe(self) -> None:
        """NoOpProgressReporter can be called multiple times safely."""
        reporter = NoOpProgressReporter()
        # Should not raise on repeated calls
        reporter.info("Info 1")
        reporter.info("Info 2")
        reporter.warning("Warning 1")
        reporter.error("Error 1")
        reporter.warning("Warning 2")


# ============================================================================
# Integration Tests
# ============================================================================


class TestNoOpProtocolIntegration:
    """Integration tests for no-op protocol implementations."""

    def test_full_workflow_with_noop_reporter(self) -> None:
        """Complete workflow with NoOpProgressReporter doesn't raise."""
        reporter = NoOpProgressReporter()

        # Log some messages
        reporter.info("Starting operation")
        reporter.warning("This is a warning")

        # Create a task sequence
        with reporter.task_sequence() as seq:
            # Create multiple tasks
            with seq.task("Step 1") as task1:
                task1.advance(10)
                task1.log("Progress update")
                task1.complete("Step 1 done")

            with seq.task("Step 2", total=100) as task2:
                for i in range(10):
                    task2.advance(10)
                    task2.set_status(f"Processing {i * 10}%")
                task2.complete("Step 2 done")

            with seq.task("Step 3") as task3:
                task3.set_total(50, "Finalizing")
                task3.warn("Completed with warnings")

        reporter.info("Operation complete")

    def test_nested_task_sequences(self) -> None:
        """Nested task sequences work with no-op implementations."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq1:
            with seq1.task("Outer task 1") as t1:
                t1.log("Starting outer task")
                t1.complete("Done")

            with seq1.task("Outer task 2") as t2:
                # Simulate nested operation
                with reporter.task_sequence() as seq2:
                    with seq2.task("Inner task") as inner:
                        inner.advance(5)
                        inner.complete("Inner done")
                t2.complete("Outer done")

    def test_error_scenarios_with_noop(self) -> None:
        """Error scenarios work correctly with no-op implementations."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq:
            with seq.task("Task that fails") as task:
                task.advance(50)
                task.fail("Operation failed", reason="Network timeout")

            with seq.task("Task that succeeds") as task:
                task.complete("Success")

        # Should reach here without raising
        reporter.info("Workflow completed despite failures")

    def test_noop_reporter_as_protocol_implementation(self) -> None:
        """NoOpProgressReporter can be used where ProgressReporter is expected."""

        def process_with_reporter(reporter: ProgressReporter) -> None:
            """Function that expects a ProgressReporter."""
            reporter.info("Processing started")
            with reporter.task_sequence() as seq:
                with seq.task("Work") as task:
                    task.advance(100)
                    task.complete("Work done")
            reporter.info("Processing complete")

        # Should work with NoOpProgressReporter
        noop_reporter = NoOpProgressReporter()
        process_with_reporter(noop_reporter)

    def test_noop_handle_supports_all_methods(self) -> None:
        """NoOpTaskHandle implements all TaskHandle protocol methods."""
        handle = NoOpTaskHandle()

        # Test all methods from TaskHandle protocol
        handle.complete("message")
        handle.fail("message", "reason")
        handle.advance(5)
        handle.log("message", "INFO")
        handle.set_total(100, "description")
        handle.set_status("status")
        handle.warn("message")

        # All should complete without error
