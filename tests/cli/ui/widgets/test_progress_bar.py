"""Tests for ProgressBarWidget - workflow progress display component."""

import time

from rich.text import Text

from gmailarchiver.cli.ui.widgets.progress_bar import (
    SPINNER_FRAMES,
    ProgressBarWidget,
)


class TestProgressBarWidgetBasics:
    """Tests for ProgressBarWidget basic functionality."""

    def test_initialization_defaults(self) -> None:
        """ProgressBarWidget initializes with default values."""
        bar = ProgressBarWidget("Archiving messages")
        assert bar.description == "Archiving messages"
        assert bar.total is None
        assert bar.completed == 0
        assert bar.is_running is True
        assert bar._is_complete is False
        assert bar._is_failed is False

    def test_initialization_with_total(self) -> None:
        """ProgressBarWidget can initialize with total."""
        bar = ProgressBarWidget("Processing", total=100)
        assert bar.total == 100
        assert bar.completed == 0

    def test_set_total(self) -> None:
        """set_total() sets the total."""
        bar = ProgressBarWidget("Task")
        bar.set_total(50)
        assert bar.total == 50

    def test_set_total_fluent_chaining(self) -> None:
        """set_total() returns self for fluent chaining."""
        bar = ProgressBarWidget("Task").set_total(100)
        assert bar.total == 100

    def test_advance_increments_completed(self) -> None:
        """advance() increments completed counter."""
        bar = ProgressBarWidget("Task", total=100)
        bar.advance()
        assert bar.completed == 1

    def test_advance_with_amount(self) -> None:
        """advance() can increment by custom amount."""
        bar = ProgressBarWidget("Task", total=100)
        bar.advance(25)
        assert bar.completed == 25

    def test_advance_multiple_times(self) -> None:
        """advance() can be called multiple times."""
        bar = ProgressBarWidget("Task", total=100)
        bar.advance().advance().advance()
        assert bar.completed == 3

    def test_set_progress_updates_both(self) -> None:
        """set_progress() updates completed and total."""
        bar = ProgressBarWidget("Task")
        bar.set_progress(50, 100)
        assert bar.completed == 50
        assert bar.total == 100

    def test_set_progress_only_completed(self) -> None:
        """set_progress() can update only completed."""
        bar = ProgressBarWidget("Task", total=100)
        bar.set_progress(75)
        assert bar.completed == 75
        assert bar.total == 100

    def test_complete_marks_complete(self) -> None:
        """complete() marks progress as complete."""
        bar = ProgressBarWidget("Task", total=100)
        bar.complete("Success!")
        assert bar._is_complete is True
        assert bar._complete_message == "Success!"
        assert bar.is_running is False

    def test_complete_without_message(self) -> None:
        """complete() works without message."""
        bar = ProgressBarWidget("Task")
        bar.complete()
        assert bar._is_complete is True
        assert bar._complete_message is None

    def test_complete_sets_progress_to_total(self) -> None:
        """complete() sets completed to total."""
        bar = ProgressBarWidget("Task", total=100)
        bar.complete()
        assert bar.completed == 100

    def test_fail_marks_failed(self) -> None:
        """fail() marks progress as failed."""
        bar = ProgressBarWidget("Task")
        bar.fail("Error occurred")
        assert bar._is_failed is True
        assert bar._fail_message == "Error occurred"
        assert bar.is_running is False

    def test_fail_without_message(self) -> None:
        """fail() works without message."""
        bar = ProgressBarWidget("Task")
        bar.fail()
        assert bar._is_failed is True
        assert bar._fail_message is None

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        bar = ProgressBarWidget("Task").set_total(100).advance(10).advance(5).set_progress(30)
        assert bar.total == 100
        assert bar.completed == 30


class TestProgressBarWidgetProgress:
    """Tests for progress tracking."""

    def test_determinate_progress_tracking(self) -> None:
        """Progress tracking works with known total."""
        bar = ProgressBarWidget("Process", total=1000)
        for _ in range(100):
            bar.advance()
        assert bar.completed == 100
        assert bar.total == 1000

    def test_indeterminate_progress(self) -> None:
        """Progress works without total."""
        bar = ProgressBarWidget("Loading")
        assert bar.total is None
        assert bar.is_running is True

    def test_completed_exceeds_total(self) -> None:
        """Progress handles completed > total gracefully."""
        bar = ProgressBarWidget("Task", total=100)
        bar.set_progress(150)
        assert bar.completed == 150
        assert bar.total == 100

    def test_progress_caps_at_100_percent(self) -> None:
        """Progress percentage is capped at 100%."""
        bar = ProgressBarWidget("Task", total=100).set_progress(150)
        text = bar.render()
        # Should not show > 100%
        plain_text = text.plain
        assert "100%" in plain_text or "100" in plain_text

    def test_zero_total_handled_gracefully(self) -> None:
        """Progress handles zero total gracefully."""
        bar = ProgressBarWidget("Task", total=0)
        text = bar.render()
        # Should render without division by zero error
        assert isinstance(text, Text)


class TestProgressBarWidgetRendering:
    """Tests for Rich text rendering."""

    def test_render_returns_text(self) -> None:
        """render() returns Rich Text object."""
        bar = ProgressBarWidget("Test")
        text = bar.render()
        assert isinstance(text, Text)

    def test_render_running_shows_spinner(self) -> None:
        """Running progress shows spinner animation."""
        bar = ProgressBarWidget("Processing")
        text = bar.render(animation_frame=0)
        # Should show first spinner frame
        assert SPINNER_FRAMES[0] in text.plain

    def test_render_spinner_cycles_through_frames(self) -> None:
        """Spinner cycles through frames based on animation_frame."""
        bar = ProgressBarWidget("Processing")
        frames_shown = set()
        for frame_num in range(len(SPINNER_FRAMES)):
            text = bar.render(animation_frame=frame_num)
            frames_shown.add(text.plain[0])
        # Should show multiple different frames
        assert len(frames_shown) > 1

    def test_render_complete_shows_checkmark(self) -> None:
        """Complete progress shows ✓ (green)."""
        bar = ProgressBarWidget("Task").complete("Done")
        text = bar.render()
        assert "✓" in text.plain
        assert "Done" in text.plain

    def test_render_failed_shows_x(self) -> None:
        """Failed progress shows ✗ (red)."""
        bar = ProgressBarWidget("Task").fail("Error")
        text = bar.render()
        assert "✗" in text.plain
        assert "Error" in text.plain

    def test_render_indeterminate_shows_elapsed(self) -> None:
        """Indeterminate progress shows elapsed time."""
        bar = ProgressBarWidget("Loading")
        text = bar.render()
        plain_text = text.plain
        # Should show ellipsis and "elapsed"
        assert "..." in plain_text
        assert "elapsed" in plain_text

    def test_render_determinate_shows_bar(self) -> None:
        """Determinate progress shows progress bar."""
        bar = ProgressBarWidget("Task", total=100).set_progress(50)
        text = bar.render()
        plain_text = text.plain
        # Should show progress bar with brackets and percentage
        assert "[" in plain_text or "50" in plain_text

    def test_render_description_included(self) -> None:
        """Render includes task description."""
        bar = ProgressBarWidget("My Archiving Task")
        text = bar.render()
        assert "My Archiving Task" in text.plain

    def test_render_with_special_characters(self) -> None:
        """Render handles descriptions with special characters."""
        bar = ProgressBarWidget("Processing [important] & {special}")
        text = bar.render()
        assert isinstance(text, Text)

    def test_render_complete_without_message(self) -> None:
        """Render works for complete without message."""
        bar = ProgressBarWidget("Task").complete()
        text = bar.render()
        assert "✓" in text.plain

    def test_render_animation_wraps_correctly(self) -> None:
        """Animation frame wraps around correctly."""
        bar = ProgressBarWidget("Test")
        # Test with frame number beyond available frames
        for frame_num in range(len(SPINNER_FRAMES) * 3):
            text = bar.render(animation_frame=frame_num)
            # Should not raise an error
            assert isinstance(text, Text)


class TestProgressBarWidgetProgressBar:
    """Tests for progress bar visual rendering."""

    def test_bar_shows_percentage(self) -> None:
        """Progress bar shows percentage."""
        bar = ProgressBarWidget("Task", total=100).set_progress(67)
        text = bar.render()
        assert "67%" in text.plain

    def test_bar_shows_count(self) -> None:
        """Progress bar shows completed/total count."""
        bar = ProgressBarWidget("Task", total=2000).set_progress(1234)
        text = bar.render()
        plain_text = text.plain
        # Should show count with thousands formatting
        assert "1,234" in plain_text or "1234" in plain_text
        assert "2,000" in plain_text or "2000" in plain_text

    def test_bar_shows_separator_bullets(self) -> None:
        """Progress bar uses • separator between components."""
        bar = ProgressBarWidget("Task", total=1000).set_progress(500)
        text = bar.render()
        plain_text = text.plain
        # Should have bullet separators
        assert "•" in plain_text

    def test_bar_0_percent(self) -> None:
        """Progress bar shows 0% correctly."""
        bar = ProgressBarWidget("Task", total=100).set_progress(0)
        text = bar.render()
        assert "0%" in text.plain

    def test_bar_100_percent(self) -> None:
        """Progress bar shows 100% correctly."""
        bar = ProgressBarWidget("Task", total=100).set_progress(100)
        text = bar.render()
        assert "100%" in text.plain

    def test_bar_partial_progress(self) -> None:
        """Progress bar shows partial progress correctly."""
        bar = ProgressBarWidget("Task", total=100).set_progress(33)
        text = bar.render()
        assert "33%" in text.plain

    def test_bar_width_customizable(self) -> None:
        """Progress bar width can be customized."""
        bar = ProgressBarWidget("Task", total=100, bar_width=20)
        assert bar.bar_width == 20

    def test_bar_with_thousands_formatting(self) -> None:
        """Progress bar formats large numbers with thousands separator."""
        bar = ProgressBarWidget("Task", total=100000).set_progress(12345)
        text = bar.render()
        plain_text = text.plain
        # Should show thousands formatted numbers
        assert "12,345" in plain_text or "12345" in plain_text
        assert "100,000" in plain_text or "100000" in plain_text


class TestProgressBarWidgetETACalculation:
    """Tests for ETA calculation."""

    def test_eta_not_available_without_progress(self) -> None:
        """ETA unavailable when completed is 0."""
        bar = ProgressBarWidget("Task", total=100)
        eta = bar._calculate_eta()
        assert eta is None

    def test_eta_not_available_without_total(self) -> None:
        """ETA unavailable without total."""
        bar = ProgressBarWidget("Task").set_progress(50)
        eta = bar._calculate_eta()
        assert eta is None

    def test_eta_seconds_format(self) -> None:
        """ETA shows seconds for quick tasks."""
        bar = ProgressBarWidget("Task", total=100).set_progress(50)
        # Simulate completion took 0.1 seconds
        bar.start_time = time.time() - 0.1
        eta = bar._calculate_eta()
        assert eta is not None
        assert "remaining" in eta

    def test_eta_minutes_format(self) -> None:
        """ETA shows minutes:seconds for longer tasks."""
        bar = ProgressBarWidget("Task", total=1000).set_progress(10)
        # Simulate 1 second elapsed (processing 10 items)
        # Remaining: 990 items at 10/sec = 99 seconds = 1m 39s
        bar.start_time = time.time() - 1.0
        eta = bar._calculate_eta()
        assert eta is not None
        assert "remaining" in eta
        assert "m" in eta or "s" in eta

    def test_eta_hours_format(self) -> None:
        """ETA shows hours for very long tasks."""
        bar = ProgressBarWidget("Task", total=100000).set_progress(100)
        # Simulate 10 seconds elapsed
        bar.start_time = time.time() - 10.0
        eta = bar._calculate_eta()
        assert eta is not None
        assert "remaining" in eta

    def test_eta_includes_remaining_text(self) -> None:
        """ETA includes 'remaining' text."""
        bar = ProgressBarWidget("Task", total=100).set_progress(50)
        bar.start_time = time.time() - 1.0
        eta = bar._calculate_eta()
        assert eta is not None
        assert "remaining" in eta

    def test_eta_in_render_output(self) -> None:
        """ETA appears in rendered output when available."""
        bar = ProgressBarWidget("Task", total=1000).set_progress(100)
        bar.start_time = time.time() - 1.0
        text = bar.render()
        plain_text = text.plain
        assert "remaining" in plain_text


class TestProgressBarWidgetTimeFormatting:
    """Tests for time formatting utilities."""

    def test_format_time_seconds(self) -> None:
        """_format_time() shows seconds for short durations."""
        bar = ProgressBarWidget("Task")
        result = bar._format_time(30)
        assert result == "30s"

    def test_format_time_minutes_seconds(self) -> None:
        """_format_time() shows minutes:seconds for medium durations."""
        bar = ProgressBarWidget("Task")
        result = bar._format_time(150)  # 2m 30s
        assert "m" in result
        assert "s" in result
        assert "2" in result
        assert "30" in result

    def test_format_time_hours_minutes(self) -> None:
        """_format_time() shows hours:minutes for long durations."""
        bar = ProgressBarWidget("Task")
        result = bar._format_time(5400)  # 1h 30m
        assert "h" in result
        assert "m" in result
        assert "1" in result

    def test_format_time_zero_seconds(self) -> None:
        """_format_time() handles zero seconds."""
        bar = ProgressBarWidget("Task")
        result = bar._format_time(0)
        assert result == "0s"

    def test_format_time_fractional_seconds(self) -> None:
        """_format_time() handles fractional seconds."""
        bar = ProgressBarWidget("Task")
        result = bar._format_time(2.7)
        assert "s" in result

    def test_format_elapsed_includes_elapsed_text(self) -> None:
        """_format_elapsed() includes 'elapsed' text."""
        bar = ProgressBarWidget("Task")
        result = bar._format_elapsed(30)
        assert "elapsed" in result
        assert "30s" in result

    def test_format_time_at_boundaries(self) -> None:
        """_format_time() handles boundary values correctly."""
        bar = ProgressBarWidget("Task")
        # 60 seconds -> should switch to minute format
        result = bar._format_time(60)
        assert "m" in result or "1m" in result
        # 3600 seconds -> should switch to hour format
        result = bar._format_time(3600)
        assert "h" in result or "1h" in result


class TestProgressBarWidgetJSON:
    """Tests for JSON serialization."""

    def test_to_json_running_determinate(self) -> None:
        """to_json serializes running determinate progress."""
        bar = ProgressBarWidget("Process", total=100).set_progress(50)
        json_data = bar.to_json()
        assert json_data["type"] == "progress_bar"
        assert json_data["description"] == "Process"
        assert json_data["completed"] == 50
        assert json_data["total"] == 100
        assert json_data["percent"] == 50.0
        assert json_data["is_complete"] is False
        assert json_data["is_failed"] is False

    def test_to_json_running_indeterminate(self) -> None:
        """to_json serializes running indeterminate progress."""
        bar = ProgressBarWidget("Loading")
        json_data = bar.to_json()
        assert json_data["type"] == "progress_bar"
        assert json_data["description"] == "Loading"
        assert json_data["completed"] == 0
        assert json_data["total"] is None
        assert json_data["percent"] is None
        assert json_data["is_complete"] is False
        assert json_data["is_failed"] is False

    def test_to_json_complete(self) -> None:
        """to_json serializes completed progress."""
        bar = ProgressBarWidget("Task", total=100).complete("Success!")
        json_data = bar.to_json()
        assert json_data["is_complete"] is True
        assert json_data["is_failed"] is False
        assert json_data["complete_message"] == "Success!"
        assert json_data["fail_message"] is None

    def test_to_json_failed(self) -> None:
        """to_json serializes failed progress."""
        bar = ProgressBarWidget("Task", total=100).fail("Error occurred")
        json_data = bar.to_json()
        assert json_data["is_complete"] is False
        assert json_data["is_failed"] is True
        assert json_data["fail_message"] == "Error occurred"
        assert json_data["complete_message"] is None

    def test_to_json_zero_total(self) -> None:
        """to_json handles zero total."""
        bar = ProgressBarWidget("Task", total=0).set_progress(0)
        json_data = bar.to_json()
        assert json_data["total"] == 0
        # percent will be None or 0 depending on None check
        assert json_data["percent"] is None or json_data["percent"] == 0

    def test_to_json_large_numbers(self) -> None:
        """to_json handles large numbers."""
        bar = ProgressBarWidget("Huge", total=1000000).set_progress(123456)
        json_data = bar.to_json()
        assert json_data["total"] == 1000000
        assert json_data["completed"] == 123456
        assert json_data["percent"] == 12.3456


class TestProgressBarWidgetEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_description_with_unicode(self) -> None:
        """Widget handles descriptions with unicode."""
        bar = ProgressBarWidget("Processing 你好 items")
        text = bar.render()
        assert isinstance(text, Text)

    def test_long_description(self) -> None:
        """Widget handles very long descriptions."""
        long_desc = "A" * 200
        bar = ProgressBarWidget(long_desc)
        text = bar.render()
        assert isinstance(text, Text)

    def test_complete_message_with_unicode(self) -> None:
        """Widget handles completion messages with unicode."""
        bar = ProgressBarWidget("Task").complete("完成！ Success!")
        text = bar.render()
        assert isinstance(text, Text)

    def test_fail_message_with_unicode(self) -> None:
        """Widget handles failure messages with unicode."""
        bar = ProgressBarWidget("Task").fail("错误 Error!")
        text = bar.render()
        assert isinstance(text, Text)

    def test_status_transitions_allowed(self) -> None:
        """Widget allows certain state transitions."""
        bar = ProgressBarWidget("Task", total=100)
        # Start running
        assert bar.is_running is True
        # Complete it
        bar.complete("Done")
        assert bar.is_running is False
        # Can still render after complete
        text = bar.render()
        assert "✓" in text.plain

    def test_multiple_advances_accumulate(self) -> None:
        """Multiple advances accumulate correctly."""
        bar = ProgressBarWidget("Task", total=1000)
        for i in range(100):
            bar.advance(10)
        assert bar.completed == 1000

    def test_render_after_complete_shows_final_state(self) -> None:
        """Render after complete shows final state."""
        bar = ProgressBarWidget("Task", total=100)
        bar.set_progress(50).complete("Half done?")
        text = bar.render()
        plain_text = text.plain
        assert "✓" in plain_text
        assert "Half done?" in plain_text

    def test_render_after_fail_shows_final_state(self) -> None:
        """Render after fail shows final state."""
        bar = ProgressBarWidget("Task", total=100)
        bar.set_progress(50).fail("Failed at 50%")
        text = bar.render()
        plain_text = text.plain
        assert "✗" in plain_text
        assert "Failed at 50%" in plain_text

    def test_animation_frame_beyond_spinner_length(self) -> None:
        """Animation frame beyond spinner length wraps correctly."""
        bar = ProgressBarWidget("Task")
        # Test with very large frame numbers
        for frame_num in [100, 1000, 10000]:
            text = bar.render(animation_frame=frame_num)
            assert isinstance(text, Text)

    def test_negative_completed_handled(self) -> None:
        """Widget handles negative completed values."""
        bar = ProgressBarWidget("Task", total=100)
        bar.completed = -10  # Shouldn't happen, but test gracefully handling
        text = bar.render()
        assert isinstance(text, Text)

    def test_custom_bar_width(self) -> None:
        """Widget respects custom bar width."""
        bar1 = ProgressBarWidget("A", total=100, bar_width=10)
        bar2 = ProgressBarWidget("B", total=100, bar_width=30)
        assert bar1.bar_width == 10
        assert bar2.bar_width == 30


class TestProgressBarWidgetRealWorldScenarios:
    """Tests for real-world usage scenarios."""

    def test_gmail_archive_scenario(self) -> None:
        """Simulates archiving Gmail messages."""
        total_messages = 2000
        bar = ProgressBarWidget("Archiving messages", total=total_messages)

        # Process in batches
        for batch in range(10):
            bar.advance(200)

        assert bar.completed == 2000
        text = bar.render()
        assert "Archiving messages" in text.plain
        assert "100%" in text.plain

    def test_import_with_unknown_total_scenario(self) -> None:
        """Simulates import when total is unknown initially."""
        bar = ProgressBarWidget("Importing messages")
        bar.start_time = time.time() - 5  # Simulate 5 seconds elapsed

        # Later, we find out the total
        bar.set_total(500).set_progress(123)

        text = bar.render()
        plain_text = text.plain
        assert "Importing messages" in plain_text
        assert "123" in plain_text or "123" in plain_text

    def test_rapid_progress_updates(self) -> None:
        """Handles rapid progress updates without issues."""
        bar = ProgressBarWidget("Processing", total=10000)

        # Simulate rapid updates
        for i in range(100):
            bar.set_progress(i * 100)
            # Shouldn't cause errors
            text = bar.render(animation_frame=i % 10)
            assert isinstance(text, Text)

        assert bar.completed == 9900

    def test_spinner_animation_over_time(self) -> None:
        """Simulates spinner animation over time."""
        bar = ProgressBarWidget("Authenticating with Gmail")

        frames_rendered = []
        for frame in range(20):
            text = bar.render(animation_frame=frame)
            frames_rendered.append(text.plain[0])

        # Should have shown multiple different spinner frames
        unique_frames = set(frames_rendered)
        assert len(unique_frames) > 1

    def test_progress_bar_animation_with_eta(self) -> None:
        """Simulates progress bar with ETA updating."""
        bar = ProgressBarWidget("Long task", total=100)
        bar.start_time = time.time() - 10  # 10 seconds ago

        # Advance through task
        for i in range(1, 11):
            bar.set_progress(i * 10)
            text = bar.render()
            plain_text = text.plain
            assert "remaining" in plain_text or "%" in plain_text

    def test_transition_from_indeterminate_to_determinate(self) -> None:
        """Transitions from indeterminate to determinate progress."""
        bar = ProgressBarWidget("Processing")
        # Start indeterminate
        text1 = bar.render()
        assert "elapsed" in text1.plain

        # Later discover total
        bar.set_total(100).set_progress(25)
        text2 = bar.render()
        plain_text = text2.plain
        assert "25%" in plain_text or "25" in plain_text
