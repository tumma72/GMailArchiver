"""Utility functions for Gmail Archiver."""

import re
from datetime import datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta


def parse_age(age_str: str) -> datetime:
    """
    Parse age expressions like '3y', '6m', '2w', '30d' into datetime.

    Args:
        age_str: Age expression (e.g., '3y' for 3 years, '6m' for 6 months)

    Returns:
        datetime object representing the cutoff date

    Raises:
        ValueError: If the age format is invalid

    Examples:
        >>> parse_age('3y')  # 3 years ago
        >>> parse_age('6m')  # 6 months ago
        >>> parse_age('2w')  # 2 weeks ago
        >>> parse_age('30d')  # 30 days ago
    """
    match = re.match(r'^(\d+)([ymwd])$', age_str.lower())
    if not match:
        raise ValueError(
            f"Invalid age format: '{age_str}'. "
            "Expected format: number + unit (y/m/w/d). "
            "Examples: '3y', '6m', '2w', '30d'"
        )

    value, unit = int(match.group(1)), match.group(2)
    now = datetime.now()

    if unit == 'y':
        return now - relativedelta(years=value)
    elif unit == 'm':
        return now - relativedelta(months=value)
    elif unit == 'w':
        return now - timedelta(weeks=value)
    elif unit == 'd':
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
    return dt.strftime('%Y/%m/%d')


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
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
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
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]
