"""Tests for progress estimation and ETA calculation.

This module tests the ProgressTracker class that provides:
- ETA (Estimated Time of Arrival) calculation
- Elapsed time tracking
- Rate calculation with exponential moving average
- Format strings with elapsed<remaining, rate
- Unit selection (msg/s, MB/s, items/s)
- Edge case handling
"""

import time
from unittest.mock import patch

from gmailarchiver.cli.output import ProgressTracker


class TestProgressTrackerInitialization:
    """Test ProgressTracker initialization."""

    def test_init_with_total(self) -> None:
        """Test initialization with known total."""
        tracker = ProgressTracker(total=100, unit="msg")
        assert tracker.total == 100
        assert tracker.unit == "msg"
        assert tracker.completed == 0
        assert tracker._start_time is None
        assert tracker._smoothed_rate is None

    def test_init_without_total(self) -> None:
        """Test initialization without known total."""
        tracker = ProgressTracker(unit="items")
        assert tracker.total is None
        assert tracker.unit == "items"
        assert tracker.completed == 0

    def test_init_default_unit(self) -> None:
        """Test initialization with default unit."""
        tracker = ProgressTracker(total=50)
        assert tracker.unit == "items"


class TestProgressTrackerStart:
    """Test ProgressTracker start method."""

    def test_start_records_time(self) -> None:
        """Test that start() records the start time."""
        tracker = ProgressTracker(total=100)
        start_before = time.perf_counter()
        tracker.start()
        start_after = time.perf_counter()

        assert tracker._start_time is not None
        assert start_before <= tracker._start_time <= start_after

    def test_start_resets_completed(self) -> None:
        """Test that start() resets completed count."""
        tracker = ProgressTracker(total=100)
        tracker.completed = 50
        tracker.start()
        assert tracker.completed == 0


class TestProgressTrackerUpdate:
    """Test ProgressTracker update method."""

    def test_update_increments_completed(self) -> None:
        """Test that update() increments completed count."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(25)
        assert tracker.completed == 25
        tracker.update(25)
        assert tracker.completed == 50

    def test_update_with_advance(self) -> None:
        """Test update with advance parameter."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(advance=10)
        assert tracker.completed == 10
        tracker.update(advance=5)
        assert tracker.completed == 15

    def test_update_calculates_rate(self) -> None:
        """Test that update() calculates processing rate."""
        tracker = ProgressTracker(total=100)

        # Mock time to control rate calculation
        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()

            # Simulate 50 items in 10 seconds (5 items/s)
            mock_time.return_value = 10.0
            tracker.update(50)

            # Rate should be approximately 5.0 items/s
            assert tracker._smoothed_rate is not None
            assert abs(tracker._smoothed_rate - 5.0) < 0.1


class TestProgressTrackerElapsed:
    """Test elapsed time calculation."""

    def test_get_elapsed_before_start(self) -> None:
        """Test elapsed time before starting."""
        tracker = ProgressTracker(total=100)
        assert tracker.get_elapsed() == 0.0

    def test_get_elapsed_after_start(self) -> None:
        """Test elapsed time after starting."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        time.sleep(0.1)
        elapsed = tracker.get_elapsed()
        assert elapsed >= 0.1
        assert elapsed < 0.5  # Should be close to 0.1s

    def test_get_elapsed_format_seconds(self) -> None:
        """Test elapsed time formatting for seconds."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 45.0

            elapsed_str = tracker.get_elapsed_formatted()
            assert elapsed_str == "00:45"

    def test_get_elapsed_format_minutes(self) -> None:
        """Test elapsed time formatting for minutes."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 125.0  # 2m 5s

            elapsed_str = tracker.get_elapsed_formatted()
            assert elapsed_str == "02:05"

    def test_get_elapsed_format_hours(self) -> None:
        """Test elapsed time formatting for hours."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 3725.0  # 1h 2m 5s

            elapsed_str = tracker.get_elapsed_formatted()
            assert elapsed_str == "01:02:05"


class TestProgressTrackerETA:
    """Test ETA (Estimated Time of Arrival) calculation."""

    def test_calculate_eta_before_start(self) -> None:
        """Test ETA before starting returns None."""
        tracker = ProgressTracker(total=100)
        assert tracker.calculate_eta() is None

    def test_calculate_eta_without_total(self) -> None:
        """Test ETA without known total returns None."""
        tracker = ProgressTracker()
        tracker.start()
        tracker.update(50)
        assert tracker.calculate_eta() is None

    def test_calculate_eta_no_progress(self) -> None:
        """Test ETA with no progress returns None."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        assert tracker.calculate_eta() is None

    def test_calculate_eta_below_minimum_samples(self) -> None:
        """Test ETA below minimum sample size returns None."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(3)  # Less than minimum 5 items
        assert tracker.calculate_eta() is None

    def test_calculate_eta_at_50_percent(self) -> None:
        """Test ETA calculation at 50% complete."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()

            # 50% complete in 30 seconds -> expect 30 more seconds
            mock_time.return_value = 30.0
            tracker.update(50)

            eta = tracker.calculate_eta()
            assert eta is not None
            # Should be close to 30s (50% remaining at same rate)
            assert abs(eta - 30.0) < 5.0

    def test_calculate_eta_at_90_percent(self) -> None:
        """Test ETA calculation at 90% complete."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()

            # 90% complete in 90 seconds -> expect ~10 more seconds
            mock_time.return_value = 90.0
            tracker.update(90)

            eta = tracker.calculate_eta()
            assert eta is not None
            # Should be close to 10s (10% remaining at same rate)
            assert abs(eta - 10.0) < 5.0

    def test_calculate_eta_formatted(self) -> None:
        """Test formatted ETA string."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 30.0
            tracker.update(50)

            eta_str = tracker.get_eta_formatted()
            assert eta_str == "00:30"


class TestProgressTrackerRate:
    """Test rate calculation and smoothing."""

    def test_get_rate_before_start(self) -> None:
        """Test rate before starting returns None."""
        tracker = ProgressTracker(total=100)
        assert tracker.get_rate() is None

    def test_get_rate_no_progress(self) -> None:
        """Test rate with no progress returns None."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        assert tracker.get_rate() is None

    def test_get_rate_simple_calculation(self) -> None:
        """Test simple rate calculation."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()

            # 50 items in 10 seconds = 5 items/s
            mock_time.return_value = 10.0
            tracker.update(50)

            rate = tracker.get_rate()
            assert rate is not None
            assert abs(rate - 5.0) < 0.1

    def test_get_rate_exponential_smoothing(self) -> None:
        """Test that rate uses exponential moving average."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()

            # First update: 10 items in 10 seconds = 1 item/s
            mock_time.return_value = 10.0
            tracker.update(10)
            rate1 = tracker.get_rate()

            # Second update: 40 more items in 10 seconds = 4 items/s current
            mock_time.return_value = 20.0
            tracker.update(50)
            rate2 = tracker.get_rate()

            # Smoothed rate should be between 1 and 4
            assert rate1 is not None
            assert rate2 is not None
            assert rate1 < rate2  # Rate increased
            assert rate2 > 1.0 and rate2 < 4.0  # Smoothed between old and new

    def test_get_rate_formatted_messages(self) -> None:
        """Test formatted rate for messages."""
        tracker = ProgressTracker(total=100, unit="msg")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 10.0
            tracker.update(50)

            rate_str = tracker.get_rate_formatted()
            assert "msg/s" in rate_str
            assert "5.0" in rate_str or "5.00" in rate_str

    def test_get_rate_formatted_megabytes(self) -> None:
        """Test formatted rate for megabytes."""
        tracker = ProgressTracker(total=100, unit="MB")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 5.0
            tracker.update(25)

            rate_str = tracker.get_rate_formatted()
            assert "MB/s" in rate_str
            assert "5.0" in rate_str or "5.00" in rate_str


class TestProgressTrackerProgressString:
    """Test complete progress string generation."""

    def test_get_progress_string_before_start(self) -> None:
        """Test progress string before starting."""
        tracker = ProgressTracker(total=100)
        progress_str = tracker.get_progress_string()
        assert progress_str == ""

    def test_get_progress_string_no_eta_yet(self) -> None:
        """Test progress string with insufficient data for ETA."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(2)  # Below minimum 5 items

        progress_str = tracker.get_progress_string()
        # Should show elapsed but no ETA
        assert "00:0" in progress_str  # Some elapsed time
        assert "<" not in progress_str  # No ETA separator

    def test_get_progress_string_with_eta(self) -> None:
        """Test complete progress string with ETA."""
        tracker = ProgressTracker(total=100, unit="msg")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 30.0
            tracker.update(50)

            progress_str = tracker.get_progress_string()
            # Should have format: [elapsed<remaining, rate]
            assert "[" in progress_str and "]" in progress_str
            assert "<" in progress_str  # ETA separator
            assert "msg/s" in progress_str
            assert "00:30" in progress_str  # Elapsed time

    def test_get_progress_string_format(self) -> None:
        """Test progress string matches expected format."""
        tracker = ProgressTracker(total=100, unit="items")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 60.0
            tracker.update(50)

            progress_str = tracker.get_progress_string()
            # Expected: [01:00<01:00, 0.83 items/s]
            assert progress_str.startswith("[")
            assert progress_str.endswith("]")
            assert "<" in progress_str
            assert "," in progress_str
            assert "items/s" in progress_str


class TestProgressTrackerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_elapsed_time(self) -> None:
        """Test handling of zero elapsed time."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            # No time passed
            tracker.update(50)

            # Should handle gracefully without division by zero
            rate = tracker.get_rate()
            # Very high rate or None is acceptable
            assert rate is None or rate > 0

    def test_very_fast_processing(self) -> None:
        """Test very fast processing (high rate)."""
        tracker = ProgressTracker(total=1000, unit="msg")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            # 1000 items in 0.1 seconds = 10000 items/s
            mock_time.return_value = 0.1
            tracker.update(100)

            rate = tracker.get_rate()
            assert rate is not None
            assert rate > 100  # Very high rate

    def test_very_slow_processing(self) -> None:
        """Test very slow processing (low rate)."""
        tracker = ProgressTracker(total=100, unit="msg")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            # 5 items in 100 seconds = 0.05 items/s
            mock_time.return_value = 100.0
            tracker.update(5)

            rate = tracker.get_rate()
            assert rate is not None
            assert rate < 1.0  # Very low rate
            assert rate > 0

    def test_single_item_completion(self) -> None:
        """Test completion of single item."""
        tracker = ProgressTracker(total=1, unit="file")

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 0.0
            tracker.start()
            mock_time.return_value = 1.0
            tracker.update(1)

            # Should handle single item gracefully
            assert tracker.completed == 1
            rate = tracker.get_rate()
            assert rate is not None

    def test_completion_beyond_total(self) -> None:
        """Test handling of completed > total."""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(150)  # More than total

        # Should handle gracefully
        assert tracker.completed == 150
        # ETA should be None or 0 when past total
        eta = tracker.calculate_eta()
        assert eta is None or eta <= 0

    def test_negative_time_handling(self) -> None:
        """Test handling of potential negative time calculations."""
        tracker = ProgressTracker(total=100)

        with patch("time.perf_counter") as mock_time:
            mock_time.return_value = 100.0
            tracker.start()
            # Simulate clock going backwards (system time adjustment)
            mock_time.return_value = 50.0
            tracker.update(25)

            # Should handle gracefully without errors
            elapsed = tracker.get_elapsed()
            assert elapsed >= 0  # Never negative
