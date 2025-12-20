"""Tests for SessionLogger class (v1.3.1 live layout system)."""

import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from gmailarchiver.cli.output import SessionLogger


class TestSessionLoggerInitialization:
    """Test SessionLogger initialization and directory management."""

    def test_init_default_path(self) -> None:
        """Test initialization with default XDG-compliant path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gmailarchiver.cli.output.SessionLogger._get_default_log_dir") as mock_dir:
                mock_dir.return_value = Path(tmpdir)

                logger = SessionLogger()

                # Should create log directory
                assert logger.log_dir.exists()
                assert logger.log_dir.is_dir()

                # Should generate timestamped filename
                assert logger.log_file is not None
                assert logger.log_file.name.startswith("session_")
                assert logger.log_file.name.endswith(".log")
                assert logger.log_file.parent == Path(tmpdir)

                # Clean up resources
                logger.close()

    def test_init_custom_path(self) -> None:
        """Test initialization with custom log directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom_logs"

            logger = SessionLogger(log_dir=custom_dir)

            # Should create custom directory
            assert logger.log_dir == custom_dir
            assert custom_dir.exists()
            assert custom_dir.is_dir()

            # Clean up resources
            logger.close()

    def test_init_creates_nested_directories(self) -> None:
        """Test that initialization creates nested directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = Path(tmpdir) / "level1" / "level2" / "logs"

            logger = SessionLogger(log_dir=nested_dir)

            # Should create all parent directories
            assert nested_dir.exists()
            assert nested_dir.is_dir()
            assert logger.log_dir == nested_dir

            # Clean up resources
            logger.close()

    def test_init_permission_error_handling(self) -> None:
        """Test graceful handling of permission errors during directory creation."""
        # Use a path that will fail on permission (root directory on Unix, C:\\ on Windows)
        if os.name == "nt":
            bad_path = Path("C:\\Windows\\System32\\gmailarchiver_logs")
        else:
            bad_path = Path("/root/gmailarchiver_logs")

        # Can raise PermissionError or OSError depending on system configuration
        with pytest.raises((PermissionError, OSError)):
            SessionLogger(log_dir=bad_path)

    def test_init_invalid_path(self) -> None:
        """Test handling of invalid path characters."""
        # Use a truly invalid path (contains null byte)
        with pytest.raises((ValueError, OSError)):
            SessionLogger(log_dir=Path("/tmp/test\x00invalid"))

    def test_timestamped_filename_format(self) -> None:
        """Test that generated filename matches expected format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            # Filename should be: session_YYYY-MM-DD_HHMMSS.log
            filename = logger.log_file.name
            assert filename.startswith("session_")
            assert filename.endswith(".log")

            # Extract timestamp portion
            timestamp_part = filename[8:-4]  # Remove "session_" and ".log"

            # Should be parseable as datetime
            try:
                datetime.strptime(timestamp_part, "%Y-%m-%d_%H%M%S")
            except ValueError:
                pytest.fail(f"Filename timestamp '{timestamp_part}' doesn't match format")

            # Clean up resources
            logger.close()

    def test_file_handle_opened(self) -> None:
        """Test that file handle is opened on initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            # Should have open file handle
            assert logger._file_handle is not None
            assert not logger._file_handle.closed

            # Cleanup
            logger.close()


class TestSessionLoggerWriting:
    """Test SessionLogger write operations."""

    def test_write_single_entry(self) -> None:
        """Test writing a single log entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Test message", level="INFO")
            logger.close()

            # Read and verify
            content = logger.log_file.read_text()
            assert "INFO" in content
            assert "Test message" in content
            assert len(content.strip().split("\n")) == 1

    def test_write_multiple_entries(self) -> None:
        """Test writing multiple log entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Message 1", level="INFO")
            logger.write("Message 2", level="WARNING")
            logger.write("Message 3", level="ERROR")
            logger.close()

            content = logger.log_file.read_text()
            lines = content.strip().split("\n")

            assert len(lines) == 3
            assert "INFO" in lines[0]
            assert "WARNING" in lines[1]
            assert "ERROR" in lines[2]

    def test_write_all_severity_levels(self) -> None:
        """Test that all severity levels are written (including DEBUG)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            levels = ["DEBUG", "INFO", "WARNING", "ERROR", "SUCCESS"]
            for level in levels:
                logger.write(f"Test {level}", level=level)

            logger.close()

            content = logger.log_file.read_text()
            for level in levels:
                assert level in content

    def test_write_includes_timestamp(self) -> None:
        """Test that each log entry includes a timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Test message", level="INFO")
            logger.close()

            content = logger.log_file.read_text()
            line = content.strip()

            # Should start with ISO timestamp
            # Format: YYYY-MM-DD HH:MM:SS.mmm
            timestamp_part = line.split()[0] + " " + line.split()[1]
            try:
                datetime.strptime(timestamp_part, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                pytest.fail(f"Timestamp '{timestamp_part}' doesn't match expected format")

    def test_write_format(self) -> None:
        """Test complete log entry format: [timestamp] LEVEL: message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Test message", level="INFO")
            logger.close()

            content = logger.log_file.read_text().strip()

            # Expected format: YYYY-MM-DD HH:MM:SS.mmm [INFO] Test message
            parts = content.split("] ", 1)
            assert len(parts) == 2

            timestamp_and_level = parts[0]
            message = parts[1]

            assert "[INFO" in timestamp_and_level
            assert message == "Test message"

    def test_write_flushes_immediately(self) -> None:
        """Test that writes are flushed immediately for real-time debugging."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Test message", level="INFO")

            # Without closing, read the file (should be flushed)
            content = logger.log_file.read_text()
            assert "Test message" in content

            logger.close()

    def test_write_multiline_message(self) -> None:
        """Test writing messages with newlines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            multiline = "Line 1\nLine 2\nLine 3"
            logger.write(multiline, level="INFO")
            logger.close()

            content = logger.log_file.read_text()
            assert "Line 1" in content
            assert "Line 2" in content
            assert "Line 3" in content

    def test_write_special_characters(self) -> None:
        """Test writing messages with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            special_msg = 'Test with unicode: 🔥 ⚠️ ✓ and symbols: <>&"'
            logger.write(special_msg, level="INFO")
            logger.close()

            content = logger.log_file.read_text()
            assert special_msg in content


class TestSessionLoggerFileManagement:
    """Test SessionLogger file handle management."""

    def test_close_method(self) -> None:
        """Test close() properly closes file handle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            assert not logger._file_handle.closed

            logger.close()

            assert logger._file_handle.closed

    def test_context_manager_basic(self) -> None:
        """Test SessionLogger works as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with SessionLogger(log_dir=Path(tmpdir)) as logger:
                logger.write("Test message", level="INFO")
                assert not logger._file_handle.closed

            # After exiting context, file should be closed
            assert logger._file_handle.closed

    def test_context_manager_writes_persist(self) -> None:
        """Test that writes made in context manager persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file_path = None

            with SessionLogger(log_dir=Path(tmpdir)) as logger:
                log_file_path = logger.log_file
                logger.write("Persistent message", level="INFO")

            # After context exits, file should exist with content
            assert log_file_path.exists()
            content = log_file_path.read_text()
            assert "Persistent message" in content

    def test_context_manager_exception_handling(self) -> None:
        """Test context manager closes file even on exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                with SessionLogger(log_dir=Path(tmpdir)) as logger:
                    logger.write("Before exception", level="INFO")
                    raise ValueError("Test exception")
            except ValueError:
                pass

            # File should still be closed despite exception
            assert logger._file_handle.closed

    def test_multiple_close_calls_safe(self) -> None:
        """Test that calling close() multiple times is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.close()
            logger.close()  # Should not raise
            logger.close()  # Should not raise


class TestSessionLoggerCleanup:
    """Test SessionLogger cleanup of old log files."""

    def test_cleanup_old_logs_basic(self) -> None:
        """Test cleanup removes old log files beyond retention limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)

            # Create 10 fake old log files
            for i in range(10):
                fake_log = log_dir / f"session_2024-01-{i + 1:02d}_120000.log"
                fake_log.write_text(f"Old log {i}")

            # Create new logger with keep_last=5
            logger = SessionLogger(log_dir=log_dir, keep_last=5)
            logger.close()

            # Should keep only 5 old logs + 1 new = 6 total
            log_files = list(log_dir.glob("session_*.log"))
            assert len(log_files) == 6

    def test_cleanup_keeps_most_recent(self) -> None:
        """Test cleanup keeps the most recent log files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)

            # Create logs with different timestamps
            old_dates = [
                "2024-01-01_120000",
                "2024-01-05_120000",
                "2024-01-10_120000",
            ]

            for date in old_dates:
                fake_log = log_dir / f"session_{date}.log"
                fake_log.write_text(f"Log from {date}")

            # Create new logger with keep_last=2
            logger = SessionLogger(log_dir=log_dir, keep_last=2)
            logger.close()

            # Should keep the 2 most recent old logs + new one = 3 total
            log_files = sorted(log_dir.glob("session_*.log"))
            assert len(log_files) == 3

            # The oldest (2024-01-01) should be deleted
            assert not (log_dir / "session_2024-01-01_120000.log").exists()

    def test_cleanup_disabled_with_zero(self) -> None:
        """Test that keep_last=0 disables cleanup (keeps all logs)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)

            # Create 5 old logs
            for i in range(5):
                fake_log = log_dir / f"session_2024-01-{i + 1:02d}_120000.log"
                fake_log.write_text(f"Old log {i}")

            # Create logger with keep_last=0 (no cleanup)
            logger = SessionLogger(log_dir=log_dir, keep_last=0)
            logger.close()

            # Should keep all old logs + new one = 6 total
            log_files = list(log_dir.glob("session_*.log"))
            assert len(log_files) == 6

    def test_cleanup_ignores_non_session_files(self) -> None:
        """Test cleanup only removes session log files, not other files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)

            # Create some session logs
            for i in range(3):
                fake_log = log_dir / f"session_2024-01-{i + 1:02d}_120000.log"
                fake_log.write_text(f"Old log {i}")

            # Create non-session files
            other_file = log_dir / "other.log"
            other_file.write_text("Keep me")

            readme = log_dir / "README.txt"
            readme.write_text("Important info")

            # Create logger with keep_last=1
            logger = SessionLogger(log_dir=log_dir, keep_last=1)
            logger.close()

            # Non-session files should still exist
            assert other_file.exists()
            assert readme.exists()

            # Should have 1 old session log + 1 new = 2 session logs
            session_logs = list(log_dir.glob("session_*.log"))
            assert len(session_logs) == 2

    def test_cleanup_handles_unlink_errors_gracefully(self) -> None:
        """Test cleanup continues even if unlink() raises OSError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)

            # Create 3 old log files
            old_logs = []
            for i in range(3):
                fake_log = log_dir / f"session_2024-01-{i + 1:02d}_120000.log"
                fake_log.write_text(f"Old log {i}")
                old_logs.append(fake_log)

            # Mock unlink() to raise OSError for first file, succeed for others
            original_unlink = Path.unlink
            call_count = [0]

            def mock_unlink(self: Path, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                call_count[0] += 1
                if call_count[0] == 1:
                    # First call: simulate file locked/permission error
                    raise OSError("Permission denied")
                # Other calls: succeed normally
                original_unlink(self, *args, **kwargs)

            with patch.object(Path, "unlink", mock_unlink):
                # Create logger with keep_last=1 (should try to delete 2 old logs)
                logger = SessionLogger(log_dir=log_dir, keep_last=1)
                logger.close()

            # Even though first unlink failed, logger should continue and not crash
            # Verify logger completed initialization successfully
            assert logger.log_file.exists()
            # First unlink() was called and raised OSError (covered lines 286-288)
            assert call_count[0] >= 1


class TestSessionLoggerEdgeCases:
    """Test SessionLogger edge cases and error handling."""

    def test_write_after_close_raises_error(self) -> None:
        """Test that writing after close() raises an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))
            logger.close()

            with pytest.raises(ValueError, match="closed"):
                logger.write("Test", level="INFO")

    def test_disk_full_simulation(self) -> None:
        """Test handling of disk space issues during write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            # Mock write to raise OSError (disk full)
            with patch.object(logger._file_handle, "write", side_effect=OSError("No space left")):
                with pytest.raises(OSError, match="No space left"):
                    logger.write("Test", level="INFO")

            logger.close()

    def test_empty_message(self) -> None:
        """Test writing empty message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("", level="INFO")
            logger.close()

            content = logger.log_file.read_text()
            assert "[INFO]" in content

    def test_very_long_message(self) -> None:
        """Test writing very long message (10KB+)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            long_message = "A" * 10000
            logger.write(long_message, level="INFO")
            logger.close()

            content = logger.log_file.read_text()
            assert long_message in content

    def test_concurrent_write_safety(self) -> None:
        """Test that multiple rapid writes don't corrupt file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            # Write 100 messages rapidly
            for i in range(100):
                logger.write(f"Message {i}", level="INFO")

            logger.close()

            content = logger.log_file.read_text()
            lines = content.strip().split("\n")

            # Should have exactly 100 lines
            assert len(lines) == 100

            # Check a few samples
            assert "Message 0" in content
            assert "Message 50" in content
            assert "Message 99" in content

    def test_default_level_is_info(self) -> None:
        """Test that default level is INFO when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger(log_dir=Path(tmpdir))

            logger.write("Test message")  # No level specified
            logger.close()

            content = logger.log_file.read_text()
            assert "[INFO]" in content


class TestSessionLoggerIntegration:
    """Test SessionLogger integration with LogBuffer."""

    def test_integration_with_log_buffer(self) -> None:
        """Test SessionLogger and LogBuffer receive same log entries."""
        from gmailarchiver.cli.output import LogBuffer

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = LogBuffer(max_visible=5)
            session_logger = SessionLogger(log_dir=Path(tmpdir))

            # Simulate OutputManager sending logs to both
            messages = [
                ("Processing started", "INFO"),
                ("Found 100 messages", "INFO"),
                ("Warning: rate limit approaching", "WARNING"),
                ("Archive complete", "SUCCESS"),
            ]

            for message, level in messages:
                buffer.add(message, level)
                session_logger.write(message, level)

            session_logger.close()

            # Verify LogBuffer has entries
            assert len(buffer._visible) == 4

            # Verify SessionLogger has all entries
            content = session_logger.log_file.read_text()
            for message, level in messages:
                assert message in content
                assert level in content

    def test_session_logger_gets_debug_logs(self) -> None:
        """Test that SessionLogger receives DEBUG logs that LogBuffer might filter."""
        from gmailarchiver.cli.output import LogBuffer

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = LogBuffer(max_visible=5)
            session_logger = SessionLogger(log_dir=Path(tmpdir))

            # Send DEBUG logs (LogBuffer might not show, but SessionLogger should store)
            debug_messages = [
                "Debug: API request started",
                "Debug: Response received (200 OK)",
                "Debug: Parsing 50 messages",
            ]

            for msg in debug_messages:
                buffer.add(msg, "DEBUG")
                session_logger.write(msg, "DEBUG")

            session_logger.close()

            # SessionLogger should have all DEBUG entries
            content = session_logger.log_file.read_text()
            for msg in debug_messages:
                assert msg in content
                assert "DEBUG" in content

    def test_xdg_config_home_respected(self) -> None:
        """Test that XDG_CONFIG_HOME environment variable is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_config = Path(tmpdir) / "custom_config"

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(custom_config)}):
                log_dir = SessionLogger._get_default_log_dir()

                # Should use XDG_CONFIG_HOME
                expected = custom_config / "gmailarchiver" / "logs"
                assert log_dir == expected
