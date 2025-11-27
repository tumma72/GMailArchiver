"""Tests for utility functions."""

from datetime import datetime, timedelta

import pytest

from gmailarchiver.shared.utils import (
    chunk_list,
    datetime_to_gmail_query,
    format_bytes,
    parse_age,
)


class TestParseAge:
    """Tests for parse_age function."""

    def test_parse_years(self) -> None:
        """Test parsing years."""
        result = parse_age("3y")
        assert isinstance(result, datetime)
        # Result should be approximately 3 years ago
        years_diff = (datetime.now() - result).days / 365
        assert 2.9 < years_diff < 3.1

    def test_parse_months(self) -> None:
        """Test parsing months."""
        result = parse_age("6m")
        assert isinstance(result, datetime)
        # Result should be approximately 6 months ago
        months_diff = (datetime.now() - result).days / 30
        assert 5.5 < months_diff < 6.5

    def test_parse_weeks(self) -> None:
        """Test parsing weeks."""
        result = parse_age("2w")
        assert isinstance(result, datetime)
        weeks_diff = (datetime.now() - result).days / 7
        assert 1.9 < weeks_diff < 2.1

    def test_parse_days(self) -> None:
        """Test parsing days."""
        result = parse_age("30d")
        assert isinstance(result, datetime)
        days_diff = (datetime.now() - result).days
        assert 29 <= days_diff <= 31

    @pytest.mark.parametrize(
        "date_str, expected_dt",
        [
            ("2024-01-01", datetime(2024, 1, 1, 0, 0)),
            ("2023-06-15", datetime(2023, 6, 15, 0, 0)),
            ("2022-12-31", datetime(2022, 12, 31, 0, 0)),
            ("2024-02-29", datetime(2024, 2, 29, 0, 0)),  # Leap year
            ("2023-01-31", datetime(2023, 1, 31, 0, 0)),  # Month boundary
            ("2023-03-31", datetime(2023, 3, 31, 0, 0)),  # Month boundary
        ],
    )
    def test_parse_valid_iso_date(self, date_str: str, expected_dt: datetime) -> None:
        """Test parsing valid ISO 8601 dates (YYYY-MM-DD)."""
        result = parse_age(date_str)
        assert result == expected_dt

    def test_parse_zero_day_relative_age(self) -> None:
        """Test parsing '0d' returns a time very close to now."""
        result = parse_age("0d")
        # The difference should be fractions of a second
        assert datetime.now() - result < timedelta(seconds=1)

    @pytest.mark.parametrize("age_str", ["1Y", "2M", "3W", "30D"])
    def test_parse_relative_age_case_insensitive(self, age_str: str) -> None:
        """Test that relative age parsing is case-insensitive."""
        # This test just ensures no exception is raised for uppercase units
        result = parse_age(age_str)
        assert isinstance(result, datetime)

    def test_parse_iso_date_lenient_padding(self) -> None:
        """Test that ISO dates without zero-padding are accepted (lenient parsing)."""
        # Python's strptime accepts dates without zero-padding
        result = parse_age("2024-1-1")
        assert result == datetime(2024, 1, 1, 0, 0)

    @pytest.mark.parametrize(
        "invalid_str",
        [
            "invalid",
            "3x",  # Invalid unit
            "2024",  # Ambiguous, not a full date or relative age
            "2024-13-01",  # Invalid month
            "2024-02-30",  # Invalid day
            "2023-02-29",  # Invalid day in non-leap year
            "2024/01/01",  # Wrong separator
            "01-01-2024",  # Wrong order
            "24-01-01",  # Two-digit year
        ],
    )
    def test_invalid_formats_raise_helpful_error(self, invalid_str: str) -> None:
        """Test that various invalid formats raise a ValueError with a helpful message."""
        with pytest.raises(ValueError, match="Invalid age/date format"):
            parse_age(invalid_str)


class TestDatetimeToGmailQuery:
    """Tests for datetime_to_gmail_query function."""

    def test_format(self) -> None:
        """Test datetime formatting."""
        dt = datetime(2022, 1, 15)
        result = datetime_to_gmail_query(dt)
        assert result == "2022/01/15"


class TestFormatBytes:
    """Tests for format_bytes function."""

    def test_bytes(self) -> None:
        """Test formatting bytes."""
        assert format_bytes(500) == "500.0 B"

    def test_kilobytes(self) -> None:
        """Test formatting kilobytes."""
        assert format_bytes(1024) == "1.0 KB"

    def test_megabytes(self) -> None:
        """Test formatting megabytes."""
        assert format_bytes(1048576) == "1.0 MB"

    def test_gigabytes(self) -> None:
        """Test formatting gigabytes."""
        assert format_bytes(1073741824) == "1.0 GB"

    def test_terabytes(self) -> None:
        """Test formatting terabytes."""
        assert format_bytes(1099511627776) == "1.0 TB"

    def test_petabytes(self) -> None:
        """Test formatting petabytes (values exceeding TB)."""
        # 1.5 PB = 1.5 * 1024^5 bytes
        assert format_bytes(1688849860263936) == "1.5 PB"


class TestChunkList:
    """Tests for chunk_list function."""

    def test_even_chunks(self) -> None:
        """Test chunking list evenly."""
        lst = [1, 2, 3, 4, 5, 6]
        result = chunk_list(lst, 2)
        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_uneven_chunks(self) -> None:
        """Test chunking list unevenly."""
        lst = [1, 2, 3, 4, 5]
        result = chunk_list(lst, 2)
        assert result == [[1, 2], [3, 4], [5]]

    def test_empty_list(self) -> None:
        """Test chunking empty list."""
        result = chunk_list([], 2)
        assert result == []

    def test_single_chunk(self) -> None:
        """Test when chunk size is larger than list."""
        lst = [1, 2, 3]
        result = chunk_list(lst, 10)
        assert result == [[1, 2, 3]]
