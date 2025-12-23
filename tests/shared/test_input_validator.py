"""Tests for input validation utilities."""

import pytest

from gmailarchiver.shared.input_validator import (
    InvalidInputError,
    sanitize_filename,
    validate_age_expression,
    validate_compression_format,
    validate_gmail_query,
)

# ============================================================================
# Gmail Query Validation Tests
# ============================================================================


class TestValidateGmailQuery:
    """Tests for validate_gmail_query function."""

    def test_valid_query_before_operator(self) -> None:
        """Test valid query with before: operator."""
        result = validate_gmail_query("before:2022/01/01")
        assert result == "before:2022/01/01"

    def test_valid_query_older_than_operator(self) -> None:
        """Test valid query with older_than: operator."""
        result = validate_gmail_query("older_than:3y")
        assert result == "older_than:3y"

    def test_valid_query_subject_operator(self) -> None:
        """Test valid query with subject: operator."""
        result = validate_gmail_query("subject:meeting notes")
        assert result == "subject:meeting notes"

    def test_valid_query_from_operator(self) -> None:
        """Test valid query with from: operator."""
        result = validate_gmail_query("from:alice@example.com")
        assert result == "from:alice@example.com"

    def test_valid_query_complex(self) -> None:
        """Test complex valid query with multiple operators."""
        result = validate_gmail_query("from:test@example.com subject:report before:2023/01/01")
        assert result == "from:test@example.com subject:report before:2023/01/01"

    def test_query_with_whitespace_stripped(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = validate_gmail_query("  before:2022/01/01  ")
        assert result == "before:2022/01/01"

    def test_empty_query_raises_error(self) -> None:
        """Test that empty query raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Query cannot be empty"):
            validate_gmail_query("")

    def test_whitespace_only_query_raises_error(self) -> None:
        """Test that whitespace-only query raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Query cannot be empty"):
            validate_gmail_query("   ")

    @pytest.mark.parametrize("dangerous_char", [";", "|", "&", "`", "$", "\n", "\r", "\0"])
    def test_dangerous_characters_raise_error(self, dangerous_char: str) -> None:
        """Test that dangerous shell metacharacters raise InvalidInputError."""
        query = f"before:2022/01/01{dangerous_char}rm -rf /"
        with pytest.raises(InvalidInputError, match="Invalid character .* in Gmail query"):
            validate_gmail_query(query)

    def test_query_too_long_raises_error(self) -> None:
        """Test that query exceeding 1024 characters raises InvalidInputError."""
        long_query = "a" * 1025
        with pytest.raises(InvalidInputError, match="Query too long .* Maximum is 1024 characters"):
            validate_gmail_query(long_query)

    def test_query_at_max_length_accepted(self) -> None:
        """Test that query at exactly 1024 characters is accepted."""
        max_query = "a" * 1024
        result = validate_gmail_query(max_query)
        assert result == max_query


# ============================================================================
# Age Expression Validation Tests
# ============================================================================


class TestValidateAgeExpression:
    """Tests for validate_age_expression function."""

    def test_valid_age_years(self) -> None:
        """Test valid age expression with years."""
        result = validate_age_expression("3y")
        assert result == "3y"

    def test_valid_age_months(self) -> None:
        """Test valid age expression with months."""
        result = validate_age_expression("6m")
        assert result == "6m"

    def test_valid_age_weeks(self) -> None:
        """Test valid age expression with weeks."""
        result = validate_age_expression("2w")
        assert result == "2w"

    def test_valid_age_days(self) -> None:
        """Test valid age expression with days."""
        result = validate_age_expression("30d")
        assert result == "30d"

    def test_valid_age_uppercase_converted_to_lowercase(self) -> None:
        """Test that uppercase age units are converted to lowercase."""
        result = validate_age_expression("3Y")
        assert result == "3y"

    def test_valid_age_mixed_case_converted_to_lowercase(self) -> None:
        """Test that mixed case age expressions are normalized."""
        result = validate_age_expression("6M")
        assert result == "6m"

    def test_valid_iso_date(self) -> None:
        """Test valid ISO date format."""
        result = validate_age_expression("2024-01-01")
        assert result == "2024-01-01"

    def test_valid_iso_date_future(self) -> None:
        """Test valid ISO date in future."""
        result = validate_age_expression("2025-12-31")
        assert result == "2025-12-31"

    def test_empty_age_raises_error(self) -> None:
        """Test that empty age expression raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Age expression cannot be empty"):
            validate_age_expression("")

    def test_whitespace_only_age_raises_error(self) -> None:
        """Test that whitespace-only age expression raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Age expression cannot be empty"):
            validate_age_expression("   ")

    def test_invalid_iso_date_raises_error(self) -> None:
        """Test that invalid ISO date raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Invalid ISO date"):
            validate_age_expression("2024-02-30")  # February doesn't have 30 days

    def test_invalid_iso_date_format_raises_error(self) -> None:
        """Test that malformed ISO date raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Invalid ISO date"):
            validate_age_expression("2024-13-01")  # Month 13 doesn't exist

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*Expected formats"):
            validate_age_expression("invalid")

    def test_invalid_unit_raises_error(self) -> None:
        """Test that invalid unit raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*Expected formats"):
            validate_age_expression("3x")  # 'x' is not a valid unit

    def test_negative_age_raises_error(self) -> None:
        """Test that negative age value raises InvalidInputError."""
        # Negative sign prevents regex match, so we get format error
        with pytest.raises(InvalidInputError, match="Invalid age/date format"):
            validate_age_expression("-3y")

    def test_zero_age_raises_error(self) -> None:
        """Test that zero age value raises InvalidInputError."""
        # Zero passes regex but the InvalidInputError gets caught by ValueError handler
        with pytest.raises(InvalidInputError, match="Invalid age number: 0"):
            validate_age_expression("0y")

    def test_age_too_large_raises_error(self) -> None:
        """Test that age value exceeding 9999 raises InvalidInputError."""
        # Large number passes regex but the InvalidInputError gets caught by ValueError handler
        with pytest.raises(InvalidInputError, match="Invalid age number: 10000"):
            validate_age_expression("10000y")

    def test_age_at_max_value_accepted(self) -> None:
        """Test that age at exactly 9999 is accepted."""
        result = validate_age_expression("9999y")
        assert result == "9999y"

    def test_non_numeric_age_raises_error(self) -> None:
        """Test that non-numeric age value raises InvalidInputError."""
        # Non-numeric fails regex validation
        with pytest.raises(InvalidInputError, match="Invalid age/date format"):
            validate_age_expression("abcy")

    def test_age_with_whitespace_stripped(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = validate_age_expression("  3y  ")
        assert result == "3y"


# ============================================================================
# Compression Format Validation Tests
# ============================================================================


class TestValidateCompressionFormat:
    """Tests for validate_compression_format function."""

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        result = validate_compression_format(None)
        assert result is None

    def test_valid_gzip_format(self) -> None:
        """Test valid gzip format."""
        result = validate_compression_format("gzip")
        assert result == "gzip"

    def test_valid_lzma_format(self) -> None:
        """Test valid lzma format."""
        result = validate_compression_format("lzma")
        assert result == "lzma"

    def test_valid_zstd_format(self) -> None:
        """Test valid zstd format."""
        result = validate_compression_format("zstd")
        assert result == "zstd"

    def test_uppercase_format_converted_to_lowercase(self) -> None:
        """Test that uppercase format is converted to lowercase."""
        result = validate_compression_format("GZIP")
        assert result == "gzip"

    def test_mixed_case_format_converted_to_lowercase(self) -> None:
        """Test that mixed case format is converted to lowercase."""
        result = validate_compression_format("GzIp")
        assert result == "gzip"

    def test_format_with_whitespace_stripped(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = validate_compression_format("  gzip  ")
        assert result == "gzip"

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises InvalidInputError."""
        with pytest.raises(
            InvalidInputError, match="Unsupported compression format.*Supported formats"
        ):
            validate_compression_format("bz2")

    def test_empty_string_raises_error(self) -> None:
        """Test that empty string raises InvalidInputError."""
        with pytest.raises(
            InvalidInputError, match="Unsupported compression format.*Supported formats"
        ):
            validate_compression_format("")


# ============================================================================
# Filename Sanitization Tests
# ============================================================================


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_valid_filename_unchanged(self) -> None:
        """Test that valid filename remains unchanged."""
        result = sanitize_filename("archive_2025.mbox")
        assert result == "archive_2025.mbox"

    def test_filename_with_hyphen(self) -> None:
        """Test filename with hyphen."""
        result = sanitize_filename("my-archive.mbox")
        assert result == "my-archive.mbox"

    def test_filename_with_underscore(self) -> None:
        """Test filename with underscore."""
        result = sanitize_filename("my_archive.mbox")
        assert result == "my_archive.mbox"

    def test_filename_with_dots(self) -> None:
        """Test filename with multiple dots."""
        result = sanitize_filename("archive.v1.2.mbox")
        assert result == "archive.v1.2.mbox"

    def test_path_traversal_removed(self) -> None:
        """Test that path traversal components are removed."""
        # Path.name extracts just the basename
        result = sanitize_filename("../../../etc/passwd")
        assert result == "passwd"

    def test_absolute_path_converted_to_basename(self) -> None:
        """Test that absolute path is converted to basename."""
        result = sanitize_filename("/absolute/path/to/file.mbox")
        assert result == "file.mbox"

    def test_special_characters_replaced(self) -> None:
        """Test that special characters are replaced with underscores."""
        result = sanitize_filename("file@name#with%special.mbox")
        assert result == "file_name_with_special.mbox"

    def test_spaces_replaced_with_underscores(self) -> None:
        """Test that spaces are replaced with underscores."""
        result = sanitize_filename("my archive file.mbox")
        assert result == "my_archive_file.mbox"

    def test_leading_dots_removed(self) -> None:
        """Test that leading dots are removed."""
        result = sanitize_filename("...archive.mbox")
        assert result == "archive.mbox"

    def test_trailing_dots_removed(self) -> None:
        """Test that trailing dots are removed."""
        result = sanitize_filename("archive.mbox...")
        assert result == "archive.mbox"

    def test_leading_spaces_replaced_then_stripped(self) -> None:
        """Test that leading spaces are replaced with underscores then stripped."""
        # Spaces are replaced with underscores before stripping
        result = sanitize_filename("   archive.mbox")
        assert result == "___archive.mbox"

    def test_trailing_spaces_replaced_then_stripped(self) -> None:
        """Test that trailing spaces are replaced with underscores then stripped."""
        # Spaces are replaced with underscores, then dots/spaces are stripped
        # But underscores remain
        result = sanitize_filename("archive.mbox   ")
        assert result == "archive.mbox___"

    def test_empty_filename_raises_error(self) -> None:
        """Test that empty filename raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Filename cannot be empty"):
            sanitize_filename("")

    def test_whitespace_only_filename_raises_error(self) -> None:
        """Test that whitespace-only filename raises InvalidInputError."""
        with pytest.raises(InvalidInputError, match="Filename cannot be empty"):
            sanitize_filename("   ")

    def test_filename_empty_after_sanitization_raises_error(self) -> None:
        """Test that filename that becomes empty after sanitization raises error."""
        with pytest.raises(InvalidInputError, match="Filename is empty after sanitization"):
            sanitize_filename("...")  # Only dots, will be stripped

    def test_long_filename_truncated(self) -> None:
        """Test that filename exceeding max length is truncated."""
        long_name = "a" * 300 + ".mbox"
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) <= 255
        assert result.endswith(".mbox")

    def test_long_filename_preserves_extension(self) -> None:
        """Test that extension is preserved when truncating long filename."""
        long_name = "a" * 300 + ".mbox.gz"
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) <= 255
        assert result.endswith(".gz")

    def test_long_filename_without_extension_truncated(self) -> None:
        """Test that filename without extension is truncated."""
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) == 255

    def test_custom_max_length(self) -> None:
        """Test sanitization with custom max length."""
        long_name = "a" * 100 + ".mbox"
        result = sanitize_filename(long_name, max_length=50)
        assert len(result) <= 50
        assert result.endswith(".mbox")
