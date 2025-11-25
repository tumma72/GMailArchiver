"""Input validation utilities for user-provided data."""

import re
from pathlib import Path


class InvalidInputError(ValueError):
    """Raised when user input fails validation."""


def validate_gmail_query(query: str) -> str:
    """
    Validate Gmail search query to prevent injection attacks.

    Gmail queries support specific operators like:before:, after:, from:, to:, subject:, etc.
    This function ensures the query doesn't contain shell metacharacters or
    other potentially dangerous patterns.

    Args:
        query: The Gmail search query string

    Returns:
        The validated query string

    Raises:
        InvalidInputError: If the query contains dangerous patterns

    Examples:
        >>> validate_gmail_query('before:2022/01/01')  # Valid
        'before:2022/01/01'
        >>> validate_gmail_query('older_than:3y')  # Valid
        'older_than:3y'
        >>> validate_gmail_query('subject:test; rm -rf /')  # Invalid - raises error
    """
    if not query or not query.strip():
        raise InvalidInputError("Query cannot be empty")

    query = query.strip()

    # Check for shell metacharacters that could be dangerous
    # These should never appear in legitimate Gmail queries
    dangerous_chars = [";", "|", "&", "`", "$", "\n", "\r", "\0"]
    for char in dangerous_chars:
        if char in query:
            raise InvalidInputError(
                f"Invalid character '{repr(char)}' in Gmail query. "
                f"Query must be a valid Gmail search expression."
            )

    # Check for excessive length (Gmail query limit is ~1024 chars)
    if len(query) > 1024:
        raise InvalidInputError(f"Query too long ({len(query)} chars). Maximum is 1024 characters.")

    return query


def validate_age_expression(age: str) -> str:
    """
    Validate age expression or ISO date format.

    Accepts two formats:
    1. Relative age: number + unit (e.g., '3y', '6m', '2w', '30d')
    2. ISO date: YYYY-MM-DD (e.g., '2024-01-01')

    Args:
        age: Age expression or ISO date string

    Returns:
        The validated age expression or ISO date

    Raises:
        InvalidInputError: If the format is invalid

    Examples:
        >>> validate_age_expression('3y')           # Valid relative
        '3y'
        >>> validate_age_expression('2024-01-01')   # Valid ISO date
        '2024-01-01'
        >>> validate_age_expression('invalid')      # Invalid - raises error
    """
    if not age or not age.strip():
        raise InvalidInputError("Age expression cannot be empty")

    age = age.strip()

    # Try ISO date format first (YYYY-MM-DD)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", age):
        # Validate it's a real date
        try:
            from datetime import datetime

            datetime.strptime(age, "%Y-%m-%d")
            return age  # Valid ISO date
        except ValueError as e:
            raise InvalidInputError(f"Invalid ISO date: '{age}'. {str(e)}")

    # Try relative age format (number + unit)
    age_lower = age.lower()
    if not re.match(r"^\d+[ymwd]$", age_lower):
        raise InvalidInputError(
            f"Invalid age/date format: '{age}'. "
            "Expected formats:\n"
            "  - Relative age: number + unit (y/m/w/d). Examples: '3y', '6m', '2w', '30d'\n"
            "  - Exact date: ISO format (YYYY-MM-DD). Examples: '2024-01-01', '2023-06-15'"
        )

    # Extract number and check it's reasonable
    num_str = age_lower[:-1]
    try:
        num = int(num_str)
        if num <= 0:
            raise InvalidInputError(f"Age value must be positive, got: {num}")
        if num > 9999:
            raise InvalidInputError(f"Age value too large: {num}")
    except ValueError:
        raise InvalidInputError(f"Invalid age number: {num_str}")

    return age_lower


def validate_compression_format(format: str | None) -> str | None:
    """
    Validate compression format.

    Args:
        format: Compression format string or None

    Returns:
        The validated format or None

    Raises:
        InvalidInputError: If the format is invalid
    """
    if format is None:
        return None

    format = format.strip().lower()

    valid_formats = ["gzip", "lzma", "zstd"]
    if format not in valid_formats:
        raise InvalidInputError(
            f"Unsupported compression format: '{format}'. "
            f"Supported formats: {', '.join(valid_formats)}"
        )

    return format


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize a filename to be safe for the filesystem.

    Removes or replaces characters that are problematic on various filesystems.

    Args:
        filename: The filename to sanitize
        max_length: Maximum filename length (default 255)

    Returns:
        A sanitized filename

    Raises:
        InvalidInputError: If filename is empty or invalid

    Examples:
        >>> sanitize_filename('archive_2025.mbox')
        'archive_2025.mbox'
        >>> sanitize_filename('../../../etc/passwd')  # Removes path separators
        'etcpasswd'
    """
    if not filename or not filename.strip():
        raise InvalidInputError("Filename cannot be empty")

    # Remove any path components - get just the filename
    filename = Path(filename).name

    # Remove or replace problematic characters
    # Allowed: alphanumeric, underscore, hyphen, dot
    filename = re.sub(r"[^\w\-.]", "_", filename)

    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")

    # Ensure it's not empty after sanitization
    if not filename:
        raise InvalidInputError("Filename is empty after sanitization")

    # Truncate if too long, but preserve extension
    if len(filename) > max_length:
        name_part, ext_part = filename.rsplit(".", 1) if "." in filename else (filename, "")
        if ext_part:
            max_name_length = max_length - len(ext_part) - 1
            filename = name_part[:max_name_length] + "." + ext_part
        else:
            filename = filename[:max_length]

    return filename
