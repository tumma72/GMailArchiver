"""Tests for LogWindowWidget - scrolling log window display."""

import time

from rich.console import Group
from rich.text import Text

from gmailarchiver.cli.ui.widgets.log_window import (
    LOG_SYMBOLS,
    LogEntry,
    LogLevel,
    LogWindowWidget,
)


class TestLogLevelEnum:
    """Tests for LogLevel enumeration."""

    def test_log_levels_defined(self) -> None:
        """All expected log levels are defined."""
        assert hasattr(LogLevel, "INFO")
        assert hasattr(LogLevel, "SUCCESS")
        assert hasattr(LogLevel, "WARNING")
        assert hasattr(LogLevel, "ERROR")

    def test_log_symbols_complete(self) -> None:
        """All log levels have defined symbols."""
        for level in LogLevel:
            assert level in LOG_SYMBOLS

    def test_log_symbols_format(self) -> None:
        """Log symbols are tuple of (symbol, color)."""
        for symbol, color in LOG_SYMBOLS.values():
            assert isinstance(symbol, str)
            assert isinstance(color, str)
            assert len(symbol) > 0
            assert len(color) > 0

    def test_log_symbol_colors(self) -> None:
        """Each log level has correct color."""
        assert LOG_SYMBOLS[LogLevel.INFO][1] == "blue"
        assert LOG_SYMBOLS[LogLevel.SUCCESS][1] == "green"
        assert LOG_SYMBOLS[LogLevel.WARNING][1] == "yellow"
        assert LOG_SYMBOLS[LogLevel.ERROR][1] == "red"

    def test_log_symbol_characters(self) -> None:
        """Each log level has correct symbol."""
        assert LOG_SYMBOLS[LogLevel.INFO][0] == "ℹ"
        assert LOG_SYMBOLS[LogLevel.SUCCESS][0] == "✓"
        assert LOG_SYMBOLS[LogLevel.WARNING][0] == "⚠"
        assert LOG_SYMBOLS[LogLevel.ERROR][0] == "✗"


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_log_entry_creation(self) -> None:
        """LogEntry can be created with required fields."""
        entry = LogEntry(level=LogLevel.SUCCESS, message="Test message")
        assert entry.level == LogLevel.SUCCESS
        assert entry.message == "Test message"
        assert isinstance(entry.timestamp, float)

    def test_log_entry_timestamp_auto_set(self) -> None:
        """LogEntry timestamp is auto-set if not provided."""
        before = time.time()
        entry = LogEntry(level=LogLevel.INFO, message="Test")
        after = time.time()
        assert before <= entry.timestamp <= after

    def test_log_entry_timestamp_custom(self) -> None:
        """LogEntry timestamp can be explicitly set."""
        custom_time = 1234567890.0
        entry = LogEntry(level=LogLevel.SUCCESS, message="Test", timestamp=custom_time)
        assert entry.timestamp == custom_time

    def test_log_entry_render_returns_text(self) -> None:
        """LogEntry.render() returns Rich Text."""
        entry = LogEntry(level=LogLevel.SUCCESS, message="Test")
        text = entry.render()
        assert isinstance(text, Text)

    def test_log_entry_render_includes_symbol(self) -> None:
        """LogEntry.render() includes the symbol."""
        entry = LogEntry(level=LogLevel.SUCCESS, message="Test")
        text = entry.render()
        assert "✓" in text.plain

    def test_log_entry_render_includes_message(self) -> None:
        """LogEntry.render() includes the message."""
        entry = LogEntry(level=LogLevel.INFO, message="Important info")
        text = entry.render()
        assert "Important info" in text.plain

    def test_log_entry_render_all_levels(self) -> None:
        """LogEntry.render() works for all log levels."""
        for level in LogLevel:
            entry = LogEntry(level=level, message="Test")
            text = entry.render()
            symbol, _ = LOG_SYMBOLS[level]
            assert symbol in text.plain

    def test_log_entry_to_json(self) -> None:
        """LogEntry.to_json() returns proper dictionary."""
        entry = LogEntry(level=LogLevel.WARNING, message="Warning")
        json_data = entry.to_json()
        assert json_data["level"] == "warning"
        assert json_data["message"] == "Warning"
        assert isinstance(json_data["timestamp"], float)

    def test_log_entry_to_json_all_levels(self) -> None:
        """LogEntry.to_json() formats all levels correctly."""
        for level in LogLevel:
            entry = LogEntry(level=level, message="Test")
            json_data = entry.to_json()
            assert json_data["level"] == level.name.lower()


class TestLogWindowWidgetInitialization:
    """Tests for LogWindowWidget initialization."""

    def test_default_initialization(self) -> None:
        """LogWindowWidget initializes with defaults."""
        log = LogWindowWidget()
        assert log.max_size == 5
        assert log.show_separator is True
        assert log.visible_count == 0
        assert log.total_count == 0

    def test_custom_max_size(self) -> None:
        """LogWindowWidget accepts custom max_size."""
        log = LogWindowWidget(max_size=10)
        assert log.max_size == 10

    def test_separator_toggle(self) -> None:
        """LogWindowWidget separator can be disabled."""
        log = LogWindowWidget(show_separator=False)
        assert log.show_separator is False

    def test_initial_state(self) -> None:
        """LogWindowWidget starts empty."""
        log = LogWindowWidget()
        assert log.has_entries is False
        assert log.visible_count == 0
        assert log.total_count == 0


class TestLogWindowWidgetLogging:
    """Tests for adding log entries."""

    def test_log_with_default_level(self) -> None:
        """log() uses INFO level by default."""
        log = LogWindowWidget()
        log.log("Message")
        assert log.visible_count == 1
        assert log._entries[0].level == LogLevel.INFO

    def test_log_with_explicit_level(self) -> None:
        """log() accepts explicit log level."""
        log = LogWindowWidget()
        log.log("Message", LogLevel.ERROR)
        assert log._entries[0].level == LogLevel.ERROR

    def test_info_adds_info_level(self) -> None:
        """info() adds entry with INFO level."""
        log = LogWindowWidget()
        log.info("Info message")
        assert log._entries[0].level == LogLevel.INFO
        assert log._entries[0].message == "Info message"

    def test_success_adds_success_level(self) -> None:
        """success() adds entry with SUCCESS level."""
        log = LogWindowWidget()
        log.success("Completed successfully")
        assert log._entries[0].level == LogLevel.SUCCESS
        assert log._entries[0].message == "Completed successfully"

    def test_warning_adds_warning_level(self) -> None:
        """warning() adds entry with WARNING level."""
        log = LogWindowWidget()
        log.warning("Be careful")
        assert log._entries[0].level == LogLevel.WARNING
        assert log._entries[0].message == "Be careful"

    def test_error_adds_error_level(self) -> None:
        """error() adds entry with ERROR level."""
        log = LogWindowWidget()
        log.error("Something went wrong")
        assert log._entries[0].level == LogLevel.ERROR
        assert log._entries[0].message == "Something went wrong"

    def test_fluent_chaining(self) -> None:
        """All log methods return Self for chaining."""
        log = LogWindowWidget()
        result = log.success("Done").warning("Issue").error("Problem")
        assert result is log
        assert log.visible_count == 3


class TestLogWindowWidgetRingBuffer:
    """Tests for ring buffer behavior (max_size limit)."""

    def test_entries_stay_within_max_size(self) -> None:
        """Visible entries never exceed max_size."""
        log = LogWindowWidget(max_size=3)
        for i in range(5):
            log.info(f"Message {i}")
        assert log.visible_count == 3
        assert log.max_size == 3

    def test_oldest_entries_removed(self) -> None:
        """Oldest entries are removed when buffer is full."""
        log = LogWindowWidget(max_size=2)
        log.success("First")
        log.warning("Second")
        log.error("Third")
        # Should have Second and Third, not First
        assert log.visible_count == 2
        messages = [entry.message for entry in log._entries]
        assert "Second" in messages
        assert "Third" in messages
        assert "First" not in messages

    def test_all_entries_tracked(self) -> None:
        """Total count includes scrolled-out entries."""
        log = LogWindowWidget(max_size=2)
        for i in range(5):
            log.info(f"Message {i}")
        assert log.total_count == 5
        assert log.visible_count == 2

    def test_max_size_one(self) -> None:
        """Ring buffer works with max_size=1."""
        log = LogWindowWidget(max_size=1)
        log.info("First")
        log.info("Second")
        assert log.visible_count == 1
        assert log._entries[0].message == "Second"

    def test_max_size_large(self) -> None:
        """Ring buffer works with large max_size."""
        log = LogWindowWidget(max_size=100)
        for i in range(50):
            log.info(f"Message {i}")
        assert log.visible_count == 50
        assert log.total_count == 50


class TestLogWindowWidgetClearing:
    """Tests for clearing entries."""

    def test_clear_removes_all_entries(self) -> None:
        """clear() removes all visible entries."""
        log = LogWindowWidget()
        log.success("First").warning("Second").error("Third")
        log.clear()
        assert log.visible_count == 0
        assert log.has_entries is False

    def test_clear_empties_total_count(self) -> None:
        """clear() also clears total count."""
        log = LogWindowWidget(max_size=2)
        for i in range(5):
            log.info(f"Message {i}")
        log.clear()
        assert log.total_count == 0
        assert log.visible_count == 0

    def test_clear_returns_self(self) -> None:
        """clear() returns self for chaining."""
        log = LogWindowWidget()
        log.info("Message")
        result = log.clear()
        assert result is log

    def test_can_add_after_clear(self) -> None:
        """Can add entries after clearing."""
        log = LogWindowWidget()
        log.info("First")
        log.clear()
        log.info("Second")
        assert log.visible_count == 1
        assert log._entries[0].message == "Second"


class TestLogWindowWidgetProperties:
    """Tests for property accessors."""

    def test_visible_count_empty(self) -> None:
        """visible_count is 0 for empty widget."""
        log = LogWindowWidget()
        assert log.visible_count == 0

    def test_visible_count_partial(self) -> None:
        """visible_count reflects actual visible entries."""
        log = LogWindowWidget(max_size=5)
        log.info("First").info("Second").info("Third")
        assert log.visible_count == 3

    def test_total_count_exceeds_visible(self) -> None:
        """total_count can exceed visible_count."""
        log = LogWindowWidget(max_size=2)
        for i in range(5):
            log.info(f"Message {i}")
        assert log.total_count == 5
        assert log.visible_count == 2

    def test_has_entries_false_when_empty(self) -> None:
        """has_entries is False when widget is empty."""
        log = LogWindowWidget()
        assert log.has_entries is False

    def test_has_entries_true_when_populated(self) -> None:
        """has_entries is True when entries exist."""
        log = LogWindowWidget()
        log.info("Message")
        assert log.has_entries is True

    def test_has_entries_false_after_clear(self) -> None:
        """has_entries becomes False after clear()."""
        log = LogWindowWidget()
        log.info("Message")
        log.clear()
        assert log.has_entries is False


class TestLogWindowWidgetRendering:
    """Tests for Rich text rendering."""

    def test_render_returns_group(self) -> None:
        """render() returns Rich Group."""
        log = LogWindowWidget()
        log.info("Message")
        group = log.render()
        assert isinstance(group, Group)

    def test_render_empty_returns_group(self) -> None:
        """render() returns Group even when empty."""
        log = LogWindowWidget()
        group = log.render()
        assert isinstance(group, Group)

    def test_render_includes_separator(self) -> None:
        """render() includes separator when enabled and has entries."""
        log = LogWindowWidget(show_separator=True)
        log.info("Message")
        group = log.render()
        # Group contains renderables; check that it has multiple items
        # (separator + log entry)
        assert len(group.renderables) >= 2

    def test_render_no_separator_when_disabled(self) -> None:
        """render() doesn't include separator when disabled."""
        log = LogWindowWidget(show_separator=False)
        log.info("Message")
        group = log.render()
        # Should only have the log entry, not separator
        assert len(group.renderables) == 1

    def test_render_no_separator_when_empty(self) -> None:
        """render() omits separator for empty widget."""
        log = LogWindowWidget(show_separator=True)
        group = log.render()
        # Empty widget, so no separator regardless of setting
        assert len(group.renderables) == 1

    def test_render_shows_visible_entries(self) -> None:
        """render() displays all visible entries."""
        log = LogWindowWidget(max_size=3)
        log.success("First").warning("Second").error("Third")
        group = log.render()
        # 3 entries + separator = 4 renderables
        assert len(group.renderables) == 4

    def test_render_scrolled_out_not_shown(self) -> None:
        """render() only shows visible entries (not scrolled out)."""
        log = LogWindowWidget(max_size=2)
        for i in range(5):
            log.info(f"Message {i}")
        group = log.render()
        # 2 entries + separator = 3 renderables
        assert len(group.renderables) == 3

    def test_render_preserves_entry_order(self) -> None:
        """render() displays entries in order."""
        log = LogWindowWidget()
        log.success("A").warning("B").error("C")
        group = log.render()
        # After separator, entries in order
        renderable = group.renderables[1]  # Skip separator
        assert isinstance(renderable, Text)
        assert "A" in renderable.plain

    def test_render_different_levels_different_symbols(self) -> None:
        """render() shows different symbols for different levels."""
        log = LogWindowWidget(max_size=4)
        log.success("Success")
        log.warning("Warning")
        log.error("Error")
        log.info("Info")

        group = log.render()
        text_entries = [r for r in group.renderables if isinstance(r, Text)]

        # Should have symbols for each level
        assert any("✓" in str(t) for t in text_entries)
        assert any("⚠" in str(t) for t in text_entries)
        assert any("✗" in str(t) for t in text_entries)
        assert any("ℹ" in str(t) for t in text_entries)


class TestLogWindowWidgetJSON:
    """Tests for JSON serialization."""

    def test_to_json_returns_dict(self) -> None:
        """to_json() returns a dictionary."""
        log = LogWindowWidget()
        json_data = log.to_json()
        assert isinstance(json_data, dict)

    def test_to_json_has_type(self) -> None:
        """to_json() includes type field."""
        log = LogWindowWidget()
        json_data = log.to_json()
        assert json_data["type"] == "log_window"

    def test_to_json_has_metadata(self) -> None:
        """to_json() includes widget metadata."""
        log = LogWindowWidget(max_size=10)
        json_data = log.to_json()
        assert json_data["max_size"] == 10
        assert json_data["visible_count"] == 0
        assert json_data["total_count"] == 0

    def test_to_json_includes_visible_entries(self) -> None:
        """to_json() includes visible entries."""
        log = LogWindowWidget(max_size=2)
        log.success("A").warning("B").error("C")
        json_data = log.to_json()
        assert len(json_data["visible_entries"]) == 2
        assert json_data["visible_count"] == 2

    def test_to_json_includes_all_entries(self) -> None:
        """to_json() includes all entries (including scrolled out)."""
        log = LogWindowWidget(max_size=2)
        for i in range(5):
            log.info(f"Message {i}")
        json_data = log.to_json()
        assert len(json_data["all_entries"]) == 5
        assert json_data["total_count"] == 5

    def test_to_json_entry_structure(self) -> None:
        """to_json() entries have correct structure."""
        log = LogWindowWidget()
        log.success("Completed successfully")
        json_data = log.to_json()
        entry = json_data["visible_entries"][0]
        assert entry["level"] == "success"
        assert entry["message"] == "Completed successfully"
        assert isinstance(entry["timestamp"], float)

    def test_to_json_empty_widget(self) -> None:
        """to_json() handles empty widget."""
        log = LogWindowWidget()
        json_data = log.to_json()
        assert json_data["visible_count"] == 0
        assert json_data["total_count"] == 0
        assert len(json_data["visible_entries"]) == 0
        assert len(json_data["all_entries"]) == 0

    def test_to_json_preserves_entry_data(self) -> None:
        """to_json() preserves all entry data."""
        log = LogWindowWidget()
        log.error("Critical error").warning("Minor issue")
        json_data = log.to_json()
        entries = json_data["all_entries"]
        assert entries[0]["level"] == "error"
        assert entries[0]["message"] == "Critical error"
        assert entries[1]["level"] == "warning"
        assert entries[1]["message"] == "Minor issue"


class TestLogWindowWidgetEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_entry_with_special_characters(self) -> None:
        """LogWindowWidget handles special characters."""
        log = LogWindowWidget()
        log.info("Message with [special] & {characters}")
        assert log.visible_count == 1
        assert "[special]" in log._entries[0].message

    def test_entry_with_unicode(self) -> None:
        """LogWindowWidget handles unicode messages."""
        log = LogWindowWidget()
        log.success("完成中文消息")
        assert log.visible_count == 1
        assert "完成中文消息" in log._entries[0].message

    def test_entry_with_very_long_message(self) -> None:
        """LogWindowWidget handles very long messages."""
        long_msg = "A" * 1000
        log = LogWindowWidget()
        log.info(long_msg)
        assert log._entries[0].message == long_msg

    def test_many_entries_quick_succession(self) -> None:
        """LogWindowWidget handles rapid entry additions."""
        log = LogWindowWidget(max_size=5)
        for i in range(100):
            log.info(f"Message {i}")
        assert log.visible_count == 5
        assert log.total_count == 100

    def test_render_after_operations(self) -> None:
        """render() works correctly after various operations."""
        log = LogWindowWidget(max_size=3)
        log.success("A")
        log.warning("B")
        log.error("C")
        log.info("D")
        log.clear()
        log.success("E")

        group = log.render()
        assert log.visible_count == 1
        assert log._entries[0].message == "E"

    def test_json_after_clear(self) -> None:
        """to_json() works correctly after clear()."""
        log = LogWindowWidget()
        log.info("Message")
        log.clear()
        json_data = log.to_json()
        assert json_data["visible_count"] == 0
        assert json_data["total_count"] == 0


class TestLogWindowWidgetIntegration:
    """Integration tests combining multiple features."""

    def test_workflow_add_render_json(self) -> None:
        """Complete workflow: add entries, render, serialize."""
        log = LogWindowWidget(max_size=5)

        # Add entries
        log.success("Import started")
        log.warning("Skipped 10 duplicates")
        log.success("Import completed")

        # Render
        group = log.render()
        assert isinstance(group, Group)

        # Serialize
        json_data = log.to_json()
        assert json_data["visible_count"] == 3
        assert json_data["total_count"] == 3

    def test_scrolling_workflow(self) -> None:
        """Test workflow with entries scrolling out."""
        log = LogWindowWidget(max_size=3)

        # Add 5 entries
        for i in range(5):
            log.info(f"Message {i}")

        # Check scrolling behavior
        assert log.visible_count == 3
        assert log.total_count == 5

        # Render and verify
        group = log.render()
        assert isinstance(group, Group)

        # JSON includes all entries
        json_data = log.to_json()
        assert len(json_data["all_entries"]) == 5
        assert len(json_data["visible_entries"]) == 3

    def test_mixed_levels_workflow(self) -> None:
        """Test workflow with mixed log levels."""
        log = LogWindowWidget()

        log.info("Starting process")
        log.success("Step 1 completed")
        log.warning("Step 2 had issues")
        log.success("Step 3 completed")
        log.error("Step 4 failed")

        # Render shows all
        group = log.render()
        assert len(group.renderables) == 6  # 5 entries + separator

        # JSON preserves all levels
        json_data = log.to_json()
        levels = {e["level"] for e in json_data["all_entries"]}
        assert levels == {"info", "success", "warning", "error"}
