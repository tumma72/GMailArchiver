"""Tests for cli.ui_builder re-export module (deprecated)."""

from gmailarchiver.cli.ui_builder import (
    DEFAULT_MAX_LOGS,
    SPINNER_FRAMES,
    SYMBOLS,
    LogEntry,
    TaskHandleImpl,
    TaskSequenceImpl,
    TaskStatus,
    UIBuilderImpl,
)


class TestUIBuilderDeprecatedImports:
    """Tests for backward compatibility imports from cli.ui_builder."""

    def test_default_max_logs_imported(self) -> None:
        """DEFAULT_MAX_LOGS is available for import."""
        assert isinstance(DEFAULT_MAX_LOGS, int)
        assert DEFAULT_MAX_LOGS > 0

    def test_spinner_frames_imported(self) -> None:
        """SPINNER_FRAMES is available for import."""
        assert len(SPINNER_FRAMES) > 0
        assert all(isinstance(frame, str) for frame in SPINNER_FRAMES)

    def test_symbols_imported(self) -> None:
        """SYMBOLS is available for import."""
        assert isinstance(SYMBOLS, dict)
        assert TaskStatus.SUCCESS in SYMBOLS
        assert TaskStatus.FAILED in SYMBOLS

    def test_log_entry_class_imported(self) -> None:
        """LogEntry class is available for import."""
        entry = LogEntry(level="INFO", message="Test message")
        assert entry.level == "INFO"
        assert entry.message == "Test message"

    def test_task_handle_impl_imported(self) -> None:
        """TaskHandleImpl is available for import."""
        assert hasattr(TaskHandleImpl, "complete")
        assert hasattr(TaskHandleImpl, "fail")
        assert hasattr(TaskHandleImpl, "advance")

    def test_task_sequence_impl_imported(self) -> None:
        """TaskSequenceImpl is available for import."""
        assert hasattr(TaskSequenceImpl, "task")
        assert hasattr(TaskSequenceImpl, "__enter__")
        assert hasattr(TaskSequenceImpl, "__exit__")

    def test_task_status_imported(self) -> None:
        """TaskStatus enum is available for import."""
        assert hasattr(TaskStatus, "PENDING")
        assert hasattr(TaskStatus, "RUNNING")
        assert hasattr(TaskStatus, "SUCCESS")
        assert hasattr(TaskStatus, "FAILED")

    def test_ui_builder_impl_imported(self) -> None:
        """UIBuilderImpl is available for import."""
        assert hasattr(UIBuilderImpl, "task_sequence")
        assert hasattr(UIBuilderImpl, "spinner")

    def test_all_symbols_exported(self) -> None:
        """All expected symbols are in module __all__."""
        from gmailarchiver import cli

        assert hasattr(cli.ui_builder, "__all__")
        all_symbols = cli.ui_builder.__all__
        assert "TaskHandle" in all_symbols
        assert "TaskSequence" in all_symbols
        assert "UIBuilder" in all_symbols
        assert "UIBuilderImpl" in all_symbols
