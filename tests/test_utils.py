"""Tests for utility functions."""

from datetime import datetime

import pytest

from gmailarchiver.utils import (
    chunk_list,
    datetime_to_gmail_query,
    format_bytes,
    parse_age,
)


class TestParseAge:
    """Tests for parse_age function."""

    def test_parse_years(self) -> None:
        """Test parsing years."""
        result = parse_age('3y')
        assert isinstance(result, datetime)
        # Result should be approximately 3 years ago
        years_diff = (datetime.now() - result).days / 365
        assert 2.9 < years_diff < 3.1

    def test_parse_months(self) -> None:
        """Test parsing months."""
        result = parse_age('6m')
        assert isinstance(result, datetime)
        # Result should be approximately 6 months ago
        months_diff = (datetime.now() - result).days / 30
        assert 5.5 < months_diff < 6.5

    def test_parse_weeks(self) -> None:
        """Test parsing weeks."""
        result = parse_age('2w')
        assert isinstance(result, datetime)
        weeks_diff = (datetime.now() - result).days / 7
        assert 1.9 < weeks_diff < 2.1

    def test_parse_days(self) -> None:
        """Test parsing days."""
        result = parse_age('30d')
        assert isinstance(result, datetime)
        days_diff = (datetime.now() - result).days
        assert 29 <= days_diff <= 31

    def test_invalid_format(self) -> None:
        """Test invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid age format"):
            parse_age('invalid')

    def test_invalid_unit(self) -> None:
        """Test invalid unit raises ValueError."""
        with pytest.raises(ValueError, match="Invalid age format"):
            parse_age('3x')


class TestDatetimeToGmailQuery:
    """Tests for datetime_to_gmail_query function."""

    def test_format(self) -> None:
        """Test datetime formatting."""
        dt = datetime(2022, 1, 15)
        result = datetime_to_gmail_query(dt)
        assert result == '2022/01/15'


class TestFormatBytes:
    """Tests for format_bytes function."""

    def test_bytes(self) -> None:
        """Test formatting bytes."""
        assert format_bytes(500) == '500.0 B'

    def test_kilobytes(self) -> None:
        """Test formatting kilobytes."""
        assert format_bytes(1024) == '1.0 KB'

    def test_megabytes(self) -> None:
        """Test formatting megabytes."""
        assert format_bytes(1048576) == '1.0 MB'

    def test_gigabytes(self) -> None:
        """Test formatting gigabytes."""
        assert format_bytes(1073741824) == '1.0 GB'


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
