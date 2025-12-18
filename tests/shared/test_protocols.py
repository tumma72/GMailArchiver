"""Tests for shared protocol interfaces and implementations.

This module tests:
- Protocol interfaces: ProgressReporter, TaskSequence, TaskHandle
- NoOp implementations: NoOpProgressReporter, NoOpTaskSequence, NoOpTaskHandle
- Context manager behavior for task sequences
"""

import pytest

from gmailarchiver.shared.protocols import (
    NoOpProgressReporter,
    NoOpTaskHandle,
    NoOpTaskSequence,
    ProgressReporter,
    TaskHandle,
    TaskSequence,
)

# ============================================================================
# Protocol Interface Tests
# ============================================================================


class TestProgressReporterProtocol:
    """Tests for ProgressReporter protocol interface."""

    def test_protocol_defines_info_method(self) -> None:
        """Verify ProgressReporter protocol includes info method."""
        assert hasattr(ProgressReporter, "info")

    def test_protocol_defines_warning_method(self) -> None:
        """Verify ProgressReporter protocol includes warning method."""
        assert hasattr(ProgressReporter, "warning")

    def test_protocol_defines_error_method(self) -> None:
        """Verify ProgressReporter protocol includes error method."""
        assert hasattr(ProgressReporter, "error")

    def test_protocol_defines_task_sequence_method(self) -> None:
        """Verify ProgressReporter protocol includes task_sequence method."""
        assert hasattr(ProgressReporter, "task_sequence")

    def test_protocol_is_runtime_checkable(self) -> None:
        """Verify ProgressReporter is a Protocol (runtime checkable)."""
        assert isinstance(ProgressReporter, type)


class TestTaskSequenceProtocol:
    """Tests for TaskSequence protocol interface."""

    def test_protocol_defines_task_method(self) -> None:
        """Verify TaskSequence protocol includes task method."""
        assert hasattr(TaskSequence, "task")

    def test_protocol_is_runtime_checkable(self) -> None:
        """Verify TaskSequence is a Protocol (runtime checkable)."""
        assert isinstance(TaskSequence, type)


class TestTaskHandleProtocol:
    """Tests for TaskHandle protocol interface."""

    def test_protocol_defines_complete_method(self) -> None:
        """Verify TaskHandle protocol includes complete method."""
        assert hasattr(TaskHandle, "complete")

    def test_protocol_defines_fail_method(self) -> None:
        """Verify TaskHandle protocol includes fail method."""
        assert hasattr(TaskHandle, "fail")

    def test_protocol_defines_advance_method(self) -> None:
        """Verify TaskHandle protocol includes advance method."""
        assert hasattr(TaskHandle, "advance")

    def test_protocol_is_runtime_checkable(self) -> None:
        """Verify TaskHandle is a Protocol (runtime checkable)."""
        assert isinstance(TaskHandle, type)


# ============================================================================
# NoOpProgressReporter Tests
# ============================================================================


class TestNoOpProgressReporter:
    """Tests for NoOpProgressReporter implementation."""

    def test_info_method_accepts_message(self) -> None:
        """Test info method accepts and ignores message."""
        reporter = NoOpProgressReporter()
        reporter.info("test message")  # Should not raise

    def test_info_method_does_not_raise_on_empty_message(self) -> None:
        """Test info method handles empty message."""
        reporter = NoOpProgressReporter()
        reporter.info("")  # Should not raise

    def test_info_method_does_not_raise_on_long_message(self) -> None:
        """Test info method handles long message."""
        reporter = NoOpProgressReporter()
        long_msg = "x" * 10000
        reporter.info(long_msg)  # Should not raise

    def test_warning_method_accepts_message(self) -> None:
        """Test warning method accepts and ignores message."""
        reporter = NoOpProgressReporter()
        reporter.warning("test warning")  # Should not raise

    def test_warning_method_does_not_raise_on_empty_message(self) -> None:
        """Test warning method handles empty message."""
        reporter = NoOpProgressReporter()
        reporter.warning("")  # Should not raise

    def test_warning_method_does_not_raise_on_long_message(self) -> None:
        """Test warning method handles long message."""
        reporter = NoOpProgressReporter()
        long_msg = "x" * 10000
        reporter.warning(long_msg)  # Should not raise

    def test_error_method_accepts_message(self) -> None:
        """Test error method accepts and ignores message."""
        reporter = NoOpProgressReporter()
        reporter.error("test error")  # Should not raise

    def test_error_method_does_not_raise_on_empty_message(self) -> None:
        """Test error method handles empty message."""
        reporter = NoOpProgressReporter()
        reporter.error("")  # Should not raise

    def test_error_method_does_not_raise_on_long_message(self) -> None:
        """Test error method handles long message."""
        reporter = NoOpProgressReporter()
        long_msg = "x" * 10000
        reporter.error(long_msg)  # Should not raise

    def test_task_sequence_returns_context_manager(self) -> None:
        """Test task_sequence method returns AbstractContextManager."""
        reporter = NoOpProgressReporter()
        result = reporter.task_sequence()

        assert hasattr(result, "__enter__")
        assert hasattr(result, "__exit__")

    def test_task_sequence_yields_task_sequence_instance(self) -> None:
        """Test task_sequence context manager yields TaskSequence."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq:
            assert isinstance(seq, NoOpTaskSequence)

    def test_task_sequence_context_manager_handles_exception(self) -> None:
        """Test task_sequence context manager properly handles exceptions."""
        reporter = NoOpProgressReporter()

        with pytest.raises(ValueError):
            with reporter.task_sequence():
                raise ValueError("test error")

    def test_multiple_calls_to_task_sequence(self) -> None:
        """Test multiple calls to task_sequence work independently."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq1:
            with reporter.task_sequence() as seq2:
                assert isinstance(seq1, NoOpTaskSequence)
                assert isinstance(seq2, NoOpTaskSequence)
                # Each should be independent
                assert seq1 is not seq2

    def test_reporter_is_reusable(self) -> None:
        """Test reporter instance can be reused multiple times."""
        reporter = NoOpProgressReporter()

        reporter.info("msg1")
        reporter.warning("msg2")
        reporter.error("msg3")

        with reporter.task_sequence() as seq:
            pass

        # Should work again
        reporter.info("msg4")


# ============================================================================
# NoOpTaskHandle Tests
# ============================================================================


class TestNoOpTaskHandle:
    """Tests for NoOpTaskHandle implementation."""

    def test_complete_method_accepts_message(self) -> None:
        """Test complete method accepts and ignores message."""
        handle = NoOpTaskHandle()
        handle.complete("test completion")  # Should not raise

    def test_complete_method_does_not_raise_on_empty_message(self) -> None:
        """Test complete method handles empty message."""
        handle = NoOpTaskHandle()
        handle.complete("")  # Should not raise

    def test_complete_method_does_not_raise_on_long_message(self) -> None:
        """Test complete method handles long message."""
        handle = NoOpTaskHandle()
        long_msg = "x" * 10000
        handle.complete(long_msg)  # Should not raise

    def test_fail_method_accepts_message(self) -> None:
        """Test fail method accepts and ignores message."""
        handle = NoOpTaskHandle()
        handle.fail("test failure")  # Should not raise

    def test_fail_method_with_reason(self) -> None:
        """Test fail method accepts message and reason."""
        handle = NoOpTaskHandle()
        handle.fail("test failure", reason="detailed reason")  # Should not raise

    def test_fail_method_with_none_reason(self) -> None:
        """Test fail method handles None reason."""
        handle = NoOpTaskHandle()
        handle.fail("test failure", reason=None)  # Should not raise

    def test_fail_method_does_not_raise_on_empty_message(self) -> None:
        """Test fail method handles empty message."""
        handle = NoOpTaskHandle()
        handle.fail("")  # Should not raise

    def test_fail_method_does_not_raise_on_empty_reason(self) -> None:
        """Test fail method handles empty reason."""
        handle = NoOpTaskHandle()
        handle.fail("msg", reason="")  # Should not raise

    def test_fail_method_does_not_raise_on_long_reason(self) -> None:
        """Test fail method handles long reason."""
        handle = NoOpTaskHandle()
        long_reason = "x" * 10000
        handle.fail("msg", reason=long_reason)  # Should not raise

    def test_advance_method_accepts_value(self) -> None:
        """Test advance method accepts and ignores value."""
        handle = NoOpTaskHandle()
        handle.advance(10)  # Should not raise

    def test_advance_method_default_value(self) -> None:
        """Test advance method with default value (1)."""
        handle = NoOpTaskHandle()
        handle.advance()  # Should not raise

    def test_advance_method_accepts_zero(self) -> None:
        """Test advance method accepts zero."""
        handle = NoOpTaskHandle()
        handle.advance(0)  # Should not raise

    def test_advance_method_accepts_negative(self) -> None:
        """Test advance method accepts negative value."""
        handle = NoOpTaskHandle()
        handle.advance(-5)  # Should not raise (no-op doesn't validate)

    def test_advance_method_accepts_large_value(self) -> None:
        """Test advance method accepts large value."""
        handle = NoOpTaskHandle()
        handle.advance(1000000)  # Should not raise

    def test_multiple_method_calls(self) -> None:
        """Test multiple method calls on same handle."""
        handle = NoOpTaskHandle()

        handle.advance(5)
        handle.advance(10)
        handle.complete("done")

        # Should not raise - operations are no-op

    def test_fail_then_advance(self) -> None:
        """Test fail followed by advance (both no-op)."""
        handle = NoOpTaskHandle()

        handle.fail("error", reason="details")
        handle.advance(1)
        # Should not raise - both are no-op

    def test_handle_is_reusable(self) -> None:
        """Test handle can be used multiple times."""
        handle = NoOpTaskHandle()

        handle.advance(1)
        handle.complete("first")

        # Should work again
        handle.advance(5)
        handle.fail("test")

    def test_log_method_accepts_message(self) -> None:
        """Test log method accepts message and level."""
        handle = NoOpTaskHandle()
        handle.log("test message", "INFO")  # Should not raise

    def test_log_method_with_default_level(self) -> None:
        """Test log method with default level."""
        handle = NoOpTaskHandle()
        handle.log("test message")  # Should not raise, level defaults to INFO

    def test_log_method_with_various_levels(self) -> None:
        """Test log method with various log levels."""
        handle = NoOpTaskHandle()
        for level in ["INFO", "SUCCESS", "WARNING", "ERROR"]:
            handle.log(f"message at {level}", level)  # Should not raise

    def test_set_total_method_accepts_total(self) -> None:
        """Test set_total method accepts total value."""
        handle = NoOpTaskHandle()
        handle.set_total(100)  # Should not raise

    def test_set_total_method_with_description(self) -> None:
        """Test set_total method accepts total and description."""
        handle = NoOpTaskHandle()
        handle.set_total(100, description="New description")  # Should not raise

    def test_set_total_method_with_none_description(self) -> None:
        """Test set_total method with None description."""
        handle = NoOpTaskHandle()
        handle.set_total(100, description=None)  # Should not raise


# ============================================================================
# NoOpTaskSequence Tests
# ============================================================================


class TestNoOpTaskSequence:
    """Tests for NoOpTaskSequence implementation."""

    def test_task_returns_context_manager(self) -> None:
        """Test task method returns AbstractContextManager."""
        seq = NoOpTaskSequence()
        result = seq.task("test task")

        assert hasattr(result, "__enter__")
        assert hasattr(result, "__exit__")

    def test_task_yields_task_handle(self) -> None:
        """Test task context manager yields TaskHandle."""
        seq = NoOpTaskSequence()

        with seq.task("test task") as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_with_total(self) -> None:
        """Test task method with total parameter."""
        seq = NoOpTaskSequence()

        with seq.task("test task", total=100) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_with_none_total(self) -> None:
        """Test task method with None total."""
        seq = NoOpTaskSequence()

        with seq.task("test task", total=None) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_with_zero_total(self) -> None:
        """Test task method with zero total."""
        seq = NoOpTaskSequence()

        with seq.task("test task", total=0) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_with_large_total(self) -> None:
        """Test task method with large total."""
        seq = NoOpTaskSequence()

        with seq.task("test task", total=1000000) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_multiple_tasks(self) -> None:
        """Test creating multiple tasks in sequence."""
        seq = NoOpTaskSequence()

        with seq.task("task1") as h1:
            assert isinstance(h1, NoOpTaskHandle)

        with seq.task("task2", total=50) as h2:
            assert isinstance(h2, NoOpTaskHandle)

        with seq.task("task3") as h3:
            assert isinstance(h3, NoOpTaskHandle)

    def test_nested_tasks(self) -> None:
        """Test nested task context managers."""
        seq = NoOpTaskSequence()

        with seq.task("outer") as outer:
            assert isinstance(outer, NoOpTaskHandle)
            outer.advance(5)

            with seq.task("inner") as inner:
                assert isinstance(inner, NoOpTaskHandle)
                inner.advance(3)

            outer.complete("outer done")

    def test_task_context_manager_handles_exception(self) -> None:
        """Test task context manager properly handles exceptions."""
        seq = NoOpTaskSequence()

        with pytest.raises(ValueError):
            with seq.task("test") as handle:
                raise ValueError("test error")

    def test_empty_description(self) -> None:
        """Test task with empty description."""
        seq = NoOpTaskSequence()

        with seq.task("") as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_long_description(self) -> None:
        """Test task with long description."""
        seq = NoOpTaskSequence()
        long_desc = "x" * 10000

        with seq.task(long_desc) as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_task_handle_operations_in_context(self) -> None:
        """Test task handle operations within context manager."""
        seq = NoOpTaskSequence()

        with seq.task("progress task", total=100) as handle:
            handle.advance(25)
            handle.advance(25)
            handle.advance(25)
            handle.advance(25)
            handle.complete("Task complete")

    def test_sequence_is_reusable(self) -> None:
        """Test sequence instance can be reused."""
        seq = NoOpTaskSequence()

        with seq.task("task1"):
            pass

        with seq.task("task2"):
            pass

        with seq.task("task3"):
            pass


# ============================================================================
# Integration Tests
# ============================================================================


class TestProgressReporterWorkflow:
    """Integration tests for ProgressReporter in typical workflows."""

    def test_complete_reporting_workflow(self) -> None:
        """Test typical reporting workflow with reporter."""
        reporter = NoOpProgressReporter()

        reporter.info("Starting operation")
        reporter.warning("Check configuration")

        with reporter.task_sequence() as seq:
            with seq.task("Step 1", total=10) as task:
                task.advance(5)
                task.advance(5)
                task.complete("Step 1 done")

            with seq.task("Step 2", total=20) as task:
                task.advance(20)
                task.complete("Step 2 done")

        reporter.info("Operation complete")

    def test_error_reporting_workflow(self) -> None:
        """Test error reporting in workflow."""
        reporter = NoOpProgressReporter()

        reporter.info("Starting")

        with reporter.task_sequence() as seq:
            with seq.task("Risky task") as task:
                task.fail("Operation failed", reason="Disk full")

        reporter.error("Workflow failed")

    def test_reporter_with_multiple_sequences(self) -> None:
        """Test reporter with multiple task sequences."""
        reporter = NoOpProgressReporter()

        reporter.info("Sequence 1")
        with reporter.task_sequence() as seq:
            with seq.task("Task 1"):
                pass

        reporter.info("Sequence 2")
        with reporter.task_sequence() as seq:
            with seq.task("Task 2"):
                pass

        reporter.info("Done")


# ============================================================================
# Implementation Verification Tests
# ============================================================================


class TestNoOpImplementationsAreCompatible:
    """Tests verifying NoOp implementations match protocol signatures."""

    def test_noop_reporter_implements_protocol(self) -> None:
        """Verify NoOpProgressReporter implements ProgressReporter protocol."""
        reporter = NoOpProgressReporter()

        # Verify all required methods exist and are callable
        assert callable(reporter.info)
        assert callable(reporter.warning)
        assert callable(reporter.error)
        assert callable(reporter.task_sequence)

    def test_noop_task_sequence_implements_protocol(self) -> None:
        """Verify NoOpTaskSequence implements TaskSequence protocol."""
        seq = NoOpTaskSequence()

        assert callable(seq.task)

    def test_noop_task_handle_implements_protocol(self) -> None:
        """Verify NoOpTaskHandle implements TaskHandle protocol."""
        handle = NoOpTaskHandle()

        assert callable(handle.complete)
        assert callable(handle.fail)
        assert callable(handle.advance)

    def test_protocol_method_signatures(self) -> None:
        """Test that NoOp implementations accept correct parameters."""
        reporter = NoOpProgressReporter()

        # These should all work without raising
        reporter.info("test")
        reporter.warning("test")
        reporter.error("test")

        with reporter.task_sequence() as seq:
            with seq.task("desc") as handle:
                handle.complete("done")
                handle.fail("failed")
                handle.advance(5)


# ============================================================================
# Edge Cases and Boundary Tests
# ============================================================================


class TestEdgeCasesAndBoundaries:
    """Tests for edge cases and boundary conditions."""

    def test_rapid_sequential_calls(self) -> None:
        """Test rapid sequential method calls."""
        reporter = NoOpProgressReporter()

        for i in range(100):
            reporter.info(f"message {i}")

    def test_very_deep_nesting(self) -> None:
        """Test deeply nested task sequences."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq:
            with seq.task("level1") as t1:
                with seq.task("level2") as t2:
                    with seq.task("level3") as t3:
                        with seq.task("level4") as t4:
                            with seq.task("level5") as t5:
                                t5.advance(1)

    def test_special_characters_in_messages(self) -> None:
        """Test handling of special characters in messages."""
        reporter = NoOpProgressReporter()
        special_msgs = [
            "test\n\n\n",
            "test\t\t\t",
            "test\r\n",
            "test😀emoji",
            "test\x00null",
            "test" + chr(127),
        ]

        for msg in special_msgs:
            reporter.info(msg)
            reporter.warning(msg)
            reporter.error(msg)

    def test_unicode_in_task_descriptions(self) -> None:
        """Test unicode handling in task descriptions."""
        seq = NoOpTaskSequence()

        descriptions = [
            "Hello 世界",
            "Привет мир",
            "مرحبا بالعالم",
            "🚀 Rocket Task",
            "Çüm över Ûñíçödé",
        ]

        for desc in descriptions:
            with seq.task(desc) as handle:
                handle.advance(1)
                handle.complete("done")

    def test_none_in_optional_parameters(self) -> None:
        """Test None values in optional parameters."""
        seq = NoOpTaskSequence()

        # Test with explicit None
        with seq.task("task", total=None) as handle:
            pass

        # Test fail with None reason
        handle = NoOpTaskHandle()
        handle.fail("msg", reason=None)
        handle.fail("msg")  # reason defaults to None


class TestContextManagerSemantics:
    """Tests for proper context manager semantics."""

    def test_context_manager_cleanup_on_normal_exit(self) -> None:
        """Test context manager properly cleans up on normal exit."""
        reporter = NoOpProgressReporter()

        with reporter.task_sequence() as seq:
            pass

        # Should be able to use again without issues
        reporter.info("after first context")

        with reporter.task_sequence() as seq:
            pass

    def test_context_manager_cleanup_on_exception(self) -> None:
        """Test context manager properly cleans up even on exception."""
        reporter = NoOpProgressReporter()

        try:
            with reporter.task_sequence() as seq:
                raise RuntimeError("test error")
        except RuntimeError:
            pass

        # Should still be usable
        reporter.info("after exception")
        with reporter.task_sequence() as seq:
            pass

    def test_nested_exception_handling(self) -> None:
        """Test nested context managers handle exceptions correctly."""
        seq = NoOpTaskSequence()

        try:
            with seq.task("outer") as outer:
                try:
                    with seq.task("inner") as inner:
                        raise ValueError("inner error")
                except ValueError:
                    pass

                outer.complete("outer done")
        except Exception:
            pytest.fail("Should not raise after catching inner exception")
