"""Tests for CLI adapters.

This module tests the CLIProgressAdapter and WorkflowProgressContext classes.
"""

from unittest.mock import MagicMock, Mock

from gmailarchiver.cli.ui.adapters import CLIProgressAdapter, WorkflowProgressContext
from gmailarchiver.shared.protocols import NoOpTaskHandle, NoOpTaskSequence


class TestCLIProgressAdapter:
    """Tests for CLIProgressAdapter."""

    def test_info_delegates_to_output(self):
        """info() should delegate to output manager."""
        output = MagicMock()
        adapter = CLIProgressAdapter(output)

        adapter.info("test message")

        output.info.assert_called_once_with("test message")

    def test_warning_delegates_to_output(self):
        """warning() should delegate to output manager."""
        output = MagicMock()
        adapter = CLIProgressAdapter(output)

        adapter.warning("test warning")

        output.warning.assert_called_once_with("test warning")

    def test_error_delegates_to_output(self):
        """error() should delegate to output manager."""
        output = MagicMock()
        adapter = CLIProgressAdapter(output)

        adapter.error("test error")

        output.error.assert_called_once_with("test error")

    def test_task_sequence_without_ui_returns_noop(self):
        """task_sequence() returns NoOpTaskSequence when no UI."""
        output = MagicMock()
        adapter = CLIProgressAdapter(output, ui=None)

        with adapter.task_sequence() as seq:
            assert isinstance(seq, NoOpTaskSequence)

    def test_task_sequence_with_ui_delegates(self):
        """task_sequence() delegates to UIBuilder when available."""
        output = MagicMock()
        ui = MagicMock()

        mock_seq = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = Mock(return_value=mock_seq)
        mock_context.__exit__ = Mock(return_value=None)
        ui.task_sequence = Mock(return_value=mock_context)

        adapter = CLIProgressAdapter(output, ui=ui)

        with adapter.task_sequence() as seq:
            assert seq is mock_seq

        ui.task_sequence.assert_called_once()

    def test_task_sequence_uses_shared_when_workflow_active(self):
        """task_sequence() returns shared sequence when workflow_sequence is active."""
        output = MagicMock()
        ui = MagicMock()

        mock_seq = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = Mock(return_value=mock_seq)
        mock_context.__exit__ = Mock(return_value=None)
        ui.task_sequence = Mock(return_value=mock_context)

        adapter = CLIProgressAdapter(output, ui=ui)

        with adapter.workflow_sequence():
            # Now task_sequence should return the shared sequence
            with adapter.task_sequence() as seq:
                assert seq is mock_seq

    def test_workflow_sequence_without_ui_returns_noop_context(self):
        """workflow_sequence() returns WorkflowProgressContext with NoOp when no UI."""
        output = MagicMock()
        adapter = CLIProgressAdapter(output, ui=None)

        with adapter.workflow_sequence() as ctx:
            assert isinstance(ctx, WorkflowProgressContext)
            # The internal sequence should be NoOpTaskSequence
            with ctx.task("test") as handle:
                assert isinstance(handle, NoOpTaskHandle)

    def test_workflow_sequence_with_ui_creates_shared_context(self):
        """workflow_sequence() creates shared Live context for all tasks."""
        output = MagicMock()
        ui = MagicMock()

        mock_task_handle = MagicMock()
        mock_task_context = MagicMock()
        mock_task_context.__enter__ = Mock(return_value=mock_task_handle)
        mock_task_context.__exit__ = Mock(return_value=None)

        mock_seq = MagicMock()
        mock_seq.task = Mock(return_value=mock_task_context)

        mock_context = MagicMock()
        mock_context.__enter__ = Mock(return_value=mock_seq)
        mock_context.__exit__ = Mock(return_value=None)
        ui.task_sequence = Mock(return_value=mock_context)

        adapter = CLIProgressAdapter(output, ui=ui)

        with adapter.workflow_sequence() as wf_ctx:
            with wf_ctx.task("Step 1") as handle:
                assert handle is mock_task_handle

        # Verify task_sequence was called with show_logs=False by default
        ui.task_sequence.assert_called_once_with(show_logs=False, max_logs=5)

    def test_workflow_sequence_with_show_logs(self):
        """workflow_sequence() passes show_logs parameter."""
        output = MagicMock()
        ui = MagicMock()

        mock_seq = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = Mock(return_value=mock_seq)
        mock_context.__exit__ = Mock(return_value=None)
        ui.task_sequence = Mock(return_value=mock_context)

        adapter = CLIProgressAdapter(output, ui=ui)

        with adapter.workflow_sequence(show_logs=True, max_logs=10):
            pass

        ui.task_sequence.assert_called_once_with(show_logs=True, max_logs=10)

    def test_workflow_sequence_clears_shared_on_exit(self):
        """workflow_sequence() clears shared sequence on context exit."""
        output = MagicMock()
        ui = MagicMock()

        mock_seq = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = Mock(return_value=mock_seq)
        mock_context.__exit__ = Mock(return_value=None)
        ui.task_sequence = Mock(return_value=mock_context)

        adapter = CLIProgressAdapter(output, ui=ui)

        with adapter.workflow_sequence():
            assert adapter._shared_sequence is mock_seq

        # After exit, shared sequence should be cleared
        assert adapter._shared_sequence is None


class TestWorkflowProgressContext:
    """Tests for WorkflowProgressContext."""

    def test_task_delegates_to_sequence(self):
        """task() should delegate to underlying sequence."""
        mock_handle = MagicMock()
        mock_task_ctx = MagicMock()
        mock_task_ctx.__enter__ = Mock(return_value=mock_handle)
        mock_task_ctx.__exit__ = Mock(return_value=None)

        mock_seq = MagicMock()
        mock_seq.task = Mock(return_value=mock_task_ctx)

        output = MagicMock()
        ctx = WorkflowProgressContext(mock_seq, output)

        with ctx.task("Test task", total=100) as handle:
            assert handle is mock_handle

        mock_seq.task.assert_called_once_with("Test task", 100)

    def test_task_returns_noop_for_noop_sequence(self):
        """task() should return NoOpTaskHandle for NoOpTaskSequence."""
        mock_seq = NoOpTaskSequence()
        output = MagicMock()
        ctx = WorkflowProgressContext(mock_seq, output)

        with ctx.task("Test task") as handle:
            assert isinstance(handle, NoOpTaskHandle)

    def test_info_delegates_to_output(self):
        """info() should delegate to output manager."""
        mock_seq = MagicMock()
        output = MagicMock()
        ctx = WorkflowProgressContext(mock_seq, output)

        ctx.info("test info")

        output.info.assert_called_once_with("test info")

    def test_warning_delegates_to_output(self):
        """warning() should delegate to output manager."""
        mock_seq = MagicMock()
        output = MagicMock()
        ctx = WorkflowProgressContext(mock_seq, output)

        ctx.warning("test warning")

        output.warning.assert_called_once_with("test warning")

    def test_error_delegates_to_output(self):
        """error() should delegate to output manager."""
        mock_seq = MagicMock()
        output = MagicMock()
        ctx = WorkflowProgressContext(mock_seq, output)

        ctx.error("test error")

        output.error.assert_called_once_with("test error")
