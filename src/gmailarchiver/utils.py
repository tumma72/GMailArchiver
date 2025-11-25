"""Utility functions for Gmail Archiver."""

import re
from datetime import datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta


def parse_age(age_str: str) -> datetime:
    """
    Parse age expressions or ISO dates into datetime.

    Accepts two formats:
    1. Relative age: number + unit (e.g., '3y', '6m', '2w', '30d')
    2. ISO date: YYYY-MM-DD (e.g., '2024-01-01')

    Args:
        age_str: Age expression or ISO date

    Returns:
        datetime object representing the cutoff date

    Raises:
        ValueError: If the format is invalid

    Examples:
        >>> parse_age('3y')           # 3 years ago (relative)
        >>> parse_age('6m')           # 6 months ago (relative)
        >>> parse_age('2024-01-01')   # January 1, 2024 (exact date)
        >>> parse_age('2023-06-15')   # June 15, 2023 (exact date)
    """
    # Phase 1: Try parsing as ISO date (YYYY-MM-DD)
    try:
        return datetime.strptime(age_str, "%Y-%m-%d")
    except ValueError:
        # Not a valid ISO date, continue to relative age parsing
        pass

    # Phase 2: Try parsing as relative age
    match = re.match(r"^(\d+)([ymwd])$", age_str.lower())
    if not match:
        raise ValueError(
            f"Invalid age/date format: '{age_str}'. "
            "Expected formats:\n"
            "  - Relative age: number + unit (y/m/w/d). Examples: '3y', '6m', '2w', '30d'\n"
            "  - Exact date: ISO format (YYYY-MM-DD). Examples: '2024-01-01', '2023-06-15'"
        )

    value, unit = int(match.group(1)), match.group(2)
    now = datetime.now()

    if unit == "y":
        return now - relativedelta(years=value)
    elif unit == "m":
        return now - relativedelta(months=value)
    elif unit == "w":
        return now - timedelta(weeks=value)
    elif unit == "d":
        return now - timedelta(days=value)
    else:
        raise ValueError(f"Unknown time unit: {unit}")


def datetime_to_gmail_query(dt: datetime) -> str:
    """
    Convert datetime to Gmail search query format.

    Args:
        dt: Datetime object

    Returns:
        Gmail query string in format 'YYYY/MM/DD'

    Examples:
        >>> dt = datetime(2022, 1, 15)
        >>> datetime_to_gmail_query(dt)
        '2022/01/15'
    """
    return dt.strftime("%Y/%m/%d")


def format_bytes(size: int) -> str:
    """
    Format bytes into human-readable string.

    Args:
        size: Size in bytes

    Returns:
        Human-readable size string

    Examples:
        >>> format_bytes(1024)
        '1.0 KB'
        >>> format_bytes(1048576)
        '1.0 MB'
    """
    size_float = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_float < 1024.0:
            return f"{size_float:.1f} {unit}"
        size_float /= 1024.0
    return f"{size_float:.1f} PB"


def chunk_list(lst: list[Any], chunk_size: int) -> list[list[Any]]:
    """
    Split a list into chunks of specified size.

    Args:
        lst: List to chunk
        chunk_size: Maximum size of each chunk

    Returns:
        List of chunked lists

    Examples:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]
