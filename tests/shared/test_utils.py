"""Tests for utility functions in gmailarchiver.shared.utils."""

from datetime import datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta

from gmailarchiver.shared.utils import (
    chunk_list,
    datetime_to_gmail_query,
    format_bytes,
    parse_age,
)

# ============================================================================
# parse_age Tests
# ============================================================================


class TestParseAge:
    """Tests for parse_age function."""

    def test_parse_age_iso_date_format(self) -> None:
        """Test parsing ISO date format (YYYY-MM-DD)."""
        result = parse_age("2024-01-15")
        expected = datetime(2024, 1, 15)
        assert result == expected

    def test_parse_age_years(self) -> None:
        """Test parsing years relative age format."""
        result = parse_age("3y")
        expected = datetime.now() - relativedelta(years=3)
        # Compare with tolerance of 1 second
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_age_months(self) -> None:
        """Test parsing months relative age format."""
        result = parse_age("6m")
        expected = datetime.now() - relativedelta(months=6)
        # Compare with tolerance of 1 second
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_age_weeks(self) -> None:
        """Test parsing weeks relative age format."""
        result = parse_age("2w")
        expected = datetime.now() - timedelta(weeks=2)
        # Compare with tolerance of 1 second
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_age_days(self) -> None:
        """Test parsing days relative age format."""
        result = parse_age("30d")
        expected = datetime.now() - timedelta(days=30)
        # Compare with tolerance of 1 second
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_age_invalid_format(self) -> None:
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid age/date format"):
            parse_age("invalid")

    def test_parse_age_invalid_unit(self) -> None:
        """Test that invalid time unit raises ValueError."""
        with pytest.raises(ValueError, match="Invalid age/date format"):
            parse_age("5h")  # hours not supported

    def test_parse_age_missing_number(self) -> None:
        """Test that missing number raises ValueError."""
        with pytest.raises(ValueError, match="Invalid age/date format"):
            parse_age("y")

    def test_parse_age_case_insensitive(self) -> None:
        """Test that age parsing is case insensitive."""
        result_lower = parse_age("3y")
        result_upper = parse_age("3Y")
        # Both should produce same result within 1 second
        assert abs((result_lower - result_upper).total_seconds()) < 1

    @pytest.mark.parametrize(
        "age_str,unit,value",
        [
            ("1y", "years", 1),
            ("12m", "months", 12),
            ("4w", "weeks", 4),
            ("7d", "days", 7),
        ],
    )
    def test_parse_age_various_units(self, age_str: str, unit: str, value: int) -> None:
        """Test parsing various age formats with parametrize."""
        result = parse_age(age_str)
        now = datetime.now()

        if unit == "years":
            expected = now - relativedelta(years=value)
        elif unit == "months":
            expected = now - relativedelta(months=value)
        elif unit == "weeks":
            expected = now - timedelta(weeks=value)
        else:  # days
            expected = now - timedelta(days=value)

        # Compare with tolerance of 1 second
        assert abs((result - expected).total_seconds()) < 1


# ============================================================================
# datetime_to_gmail_query Tests
# ============================================================================


class TestDatetimeToGmailQuery:
    """Tests for datetime_to_gmail_query function."""

    def test_datetime_to_gmail_query_basic(self) -> None:
        """Test conversion of datetime to Gmail query format."""
        dt = datetime(2022, 1, 15, 14, 30, 0)
        result = datetime_to_gmail_query(dt)
        assert result == "2022/01/15"

    def test_datetime_to_gmail_query_single_digit_month(self) -> None:
        """Test that single digit months are zero-padded."""
        dt = datetime(2022, 3, 5)
        result = datetime_to_gmail_query(dt)
        assert result == "2022/03/05"

    def test_datetime_to_gmail_query_new_year(self) -> None:
        """Test conversion on January 1st."""
        dt = datetime(2024, 1, 1)
        result = datetime_to_gmail_query(dt)
        assert result == "2024/01/01"

    def test_datetime_to_gmail_query_end_of_year(self) -> None:
        """Test conversion on December 31st."""
        dt = datetime(2023, 12, 31)
        result = datetime_to_gmail_query(dt)
        assert result == "2023/12/31"


# ============================================================================
# format_bytes Tests
# ============================================================================


class TestFormatBytes:
    """Tests for format_bytes function."""

    def test_format_bytes_zero(self) -> None:
        """Test formatting zero bytes."""
        result = format_bytes(0)
        assert result == "0.0 B"

    def test_format_bytes_bytes(self) -> None:
        """Test formatting bytes (< 1024)."""
        result = format_bytes(500)
        assert result == "500.0 B"

    def test_format_bytes_exact_kb(self) -> None:
        """Test formatting exactly 1 KB."""
        result = format_bytes(1024)
        assert result == "1.0 KB"

    def test_format_bytes_kb(self) -> None:
        """Test formatting kilobytes."""
        result = format_bytes(2048)
        assert result == "2.0 KB"

    def test_format_bytes_mb(self) -> None:
        """Test formatting megabytes."""
        result = format_bytes(1048576)  # 1 MB
        assert result == "1.0 MB"

    def test_format_bytes_gb(self) -> None:
        """Test formatting gigabytes."""
        result = format_bytes(1073741824)  # 1 GB
        assert result == "1.0 GB"

    def test_format_bytes_tb(self) -> None:
        """Test formatting terabytes."""
        result = format_bytes(1099511627776)  # 1 TB
        assert result == "1.0 TB"

    def test_format_bytes_pb(self) -> None:
        """Test formatting petabytes."""
        result = format_bytes(1125899906842624)  # 1 PB
        assert result == "1.0 PB"

    def test_format_bytes_large_pb(self) -> None:
        """Test formatting very large petabyte values."""
        result = format_bytes(5 * 1125899906842624)  # 5 PB
        assert result == "5.0 PB"

    def test_format_bytes_fractional_mb(self) -> None:
        """Test formatting fractional megabytes."""
        result = format_bytes(1572864)  # 1.5 MB
        assert result == "1.5 MB"

    @pytest.mark.parametrize(
        "size,expected",
        [
            (0, "0.0 B"),
            (1, "1.0 B"),
            (1023, "1023.0 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1048576, "1.0 MB"),
            (1073741824, "1.0 GB"),
            (1099511627776, "1.0 TB"),
            (1125899906842624, "1.0 PB"),
            (10 * 1125899906842624, "10.0 PB"),
        ],
    )
    def test_format_bytes_parametrized(self, size: int, expected: str) -> None:
        """Test various byte sizes with parametrize."""
        result = format_bytes(size)
        assert result == expected


# ============================================================================
# chunk_list Tests
# ============================================================================


class TestChunkList:
    """Tests for chunk_list function."""

    def test_chunk_list_basic(self) -> None:
        """Test basic list chunking."""
        result = chunk_list([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunk_list_exact_division(self) -> None:
        """Test chunking when list divides evenly."""
        result = chunk_list([1, 2, 3, 4, 5, 6], 3)
        assert result == [[1, 2, 3], [4, 5, 6]]

    def test_chunk_list_single_chunk(self) -> None:
        """Test when chunk size is larger than list."""
        result = chunk_list([1, 2, 3], 10)
        assert result == [[1, 2, 3]]

    def test_chunk_list_chunk_size_one(self) -> None:
        """Test chunking with size 1."""
        result = chunk_list([1, 2, 3], 1)
        assert result == [[1], [2], [3]]

    def test_chunk_list_empty_list(self) -> None:
        """Test chunking an empty list."""
        result = chunk_list([], 5)
        assert result == []

    def test_chunk_list_strings(self) -> None:
        """Test chunking a list of strings."""
        result = chunk_list(["a", "b", "c", "d"], 2)
        assert result == [["a", "b"], ["c", "d"]]

    def test_chunk_list_mixed_types(self) -> None:
        """Test chunking a list with mixed types."""
        result = chunk_list([1, "two", 3.0, None, True], 2)
        assert result == [[1, "two"], [3.0, None], [True]]

    @pytest.mark.parametrize(
        "lst,chunk_size,expected",
        [
            ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]]),
            ([1, 2, 3, 4, 5, 6], 3, [[1, 2, 3], [4, 5, 6]]),
            ([1], 1, [[1]]),
            ([], 5, []),
            ([1, 2], 10, [[1, 2]]),
        ],
    )
    def test_chunk_list_parametrized(
        self, lst: list, chunk_size: int, expected: list[list]
    ) -> None:
        """Test various chunking scenarios with parametrize."""
        result = chunk_list(lst, chunk_size)
        assert result == expected
