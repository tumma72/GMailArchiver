"""Tests for input validation utilities."""

import pytest

from gmailarchiver.shared.input_validator import (
    InvalidInputError,
    sanitize_filename,
    validate_age_expression,
    validate_compression_format,
    validate_gmail_query,
)


class TestValidateGmailQuery:
    """Tests for validate_gmail_query function."""

    def test_valid_before_query(self) -> None:
        """Test valid before: query."""
        result = validate_gmail_query("before:2022/01/01")
        assert result == "before:2022/01/01"

    def test_valid_older_than_query(self) -> None:
        """Test valid older_than: query."""
        result = validate_gmail_query("older_than:3y")
        assert result == "older_than:3y"

    def test_valid_complex_query(self) -> None:
        """Test valid complex query with multiple operators."""
        query = "from:user@example.com subject:test before:2022/01/01"
        result = validate_gmail_query(query)
        assert result == query

    def test_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = validate_gmail_query("  before:2022/01/01  ")
        assert result == "before:2022/01/01"

    def test_empty_query_raises_error(self) -> None:
        """Test that empty query raises error."""
        with pytest.raises(InvalidInputError, match="Query cannot be empty"):
            validate_gmail_query("")

    def test_whitespace_only_query_raises_error(self) -> None:
        """Test that whitespace-only query raises error."""
        with pytest.raises(InvalidInputError, match="Query cannot be empty"):
            validate_gmail_query("   ")

    def test_semicolon_raises_error(self) -> None:
        """Test that semicolon in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character.*;"):
            validate_gmail_query("before:2022/01/01; rm -rf /")

    def test_pipe_raises_error(self) -> None:
        """Test that pipe in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character.*\\|"):
            validate_gmail_query("before:2022/01/01 | cat")

    def test_ampersand_raises_error(self) -> None:
        """Test that ampersand in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character.*&"):
            validate_gmail_query("before:2022/01/01 && echo test")

    def test_backtick_raises_error(self) -> None:
        """Test that backtick in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character.*`"):
            validate_gmail_query("before:2022/01/01 `whoami`")

    def test_dollar_sign_raises_error(self) -> None:
        """Test that dollar sign in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character.*\\$"):
            validate_gmail_query("before:2022/01/01 $HOME")

    def test_newline_raises_error(self) -> None:
        """Test that newline in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character"):
            validate_gmail_query("before:2022/01/01\nrm -rf /")

    def test_carriage_return_raises_error(self) -> None:
        """Test that carriage return in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character"):
            validate_gmail_query("before:2022/01/01\rrm -rf /")

    def test_null_byte_raises_error(self) -> None:
        """Test that null byte in query raises error."""
        with pytest.raises(InvalidInputError, match="Invalid character"):
            validate_gmail_query("before:2022/01/01\0")

    def test_query_too_long_raises_error(self) -> None:
        """Test that query longer than 1024 chars raises error."""
        long_query = "a" * 1025
        with pytest.raises(InvalidInputError, match="Query too long.*1025.*Maximum is 1024"):
            validate_gmail_query(long_query)

    def test_query_exactly_1024_chars_is_valid(self) -> None:
        """Test that query of exactly 1024 chars is valid."""
        query = "a" * 1024
        result = validate_gmail_query(query)
        assert result == query


class TestValidateAgeExpression:
    """Tests for validate_age_expression function."""

    def test_valid_years(self) -> None:
        """Test valid year expression."""
        result = validate_age_expression("3y")
        assert result == "3y"

    def test_valid_months(self) -> None:
        """Test valid month expression."""
        result = validate_age_expression("6m")
        assert result == "6m"

    def test_valid_weeks(self) -> None:
        """Test valid week expression."""
        result = validate_age_expression("2w")
        assert result == "2w"

    def test_valid_days(self) -> None:
        """Test valid day expression."""
        result = validate_age_expression("30d")
        assert result == "30d"

    def test_uppercase_is_lowercased(self) -> None:
        """Test that uppercase is converted to lowercase."""
        result = validate_age_expression("3Y")
        assert result == "3y"

    def test_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        result = validate_age_expression("  3y  ")
        assert result == "3y"

    def test_empty_expression_raises_error(self) -> None:
        """Test that empty expression raises error."""
        with pytest.raises(InvalidInputError, match="Age expression cannot be empty"):
            validate_age_expression("")

    def test_whitespace_only_raises_error(self) -> None:
        """Test that whitespace-only expression raises error."""
        with pytest.raises(InvalidInputError, match="Age expression cannot be empty"):
            validate_age_expression("   ")

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*invalid"):
            validate_age_expression("invalid")

    def test_missing_unit_raises_error(self) -> None:
        """Test that missing unit raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*3.*Expected format"):
            validate_age_expression("3")

    def test_missing_number_raises_error(self) -> None:
        """Test that missing number raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*y"):
            validate_age_expression("y")

    def test_invalid_unit_raises_error(self) -> None:
        """Test that invalid unit raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*3x"):
            validate_age_expression("3x")

    def test_zero_age_raises_error(self) -> None:
        """Test that zero age raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age number: 0"):
            validate_age_expression("0y")

    def test_negative_age_raises_error(self) -> None:
        """Test that negative age raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*-3y"):
            validate_age_expression("-3y")

    def test_very_large_age_raises_error(self) -> None:
        """Test that age > 9999 raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age number: 10000"):
            validate_age_expression("10000y")

    def test_max_valid_age(self) -> None:
        """Test that age of 9999 is valid."""
        result = validate_age_expression("9999y")
        assert result == "9999y"

    def test_age_with_decimal_raises_error(self) -> None:
        """Test that age with decimal raises error."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format.*3.5y"):
            validate_age_expression("3.5y")

    # ISO date format tests (v1.3.2+)
    def test_valid_iso_date(self) -> None:
        """Test valid ISO date format (v1.3.2+)."""
        result = validate_age_expression("2024-01-01")
        assert result == "2024-01-01"

    def test_valid_iso_date_recent(self) -> None:
        """Test valid recent ISO date (v1.3.2+)."""
        result = validate_age_expression("2023-06-15")
        assert result == "2023-06-15"

    def test_valid_iso_date_old(self) -> None:
        """Test valid old ISO date (v1.3.2+)."""
        result = validate_age_expression("2000-12-31")
        assert result == "2000-12-31"

    def test_invalid_iso_date_format_raises_error(self) -> None:
        """Test that invalid ISO date format raises error (v1.3.2+)."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format"):
            validate_age_expression("2024/01/01")  # Wrong separator

    def test_invalid_iso_date_short_year_raises_error(self) -> None:
        """Test that short year raises error (v1.3.2+)."""
        with pytest.raises(InvalidInputError, match="Invalid age/date format"):
            validate_age_expression("24-01-01")  # Only 2 digit year

    def test_invalid_iso_date_month_raises_error(self) -> None:
        """Test that invalid month raises error (v1.3.2+)."""
        with pytest.raises(InvalidInputError, match="Invalid ISO date"):
            validate_age_expression("2024-13-01")  # Month 13

    def test_invalid_iso_date_day_raises_error(self) -> None:
        """Test that invalid day raises error (v1.3.2+)."""
        with pytest.raises(InvalidInputError, match="Invalid ISO date"):
            validate_age_expression("2024-02-30")  # Feb 30th

    def test_iso_date_preserves_case(self) -> None:
        """Test that ISO dates are not lowercased (v1.3.2+)."""
        result = validate_age_expression("2024-01-01")
        assert result == "2024-01-01"  # Not lowercased


class TestValidateCompressionFormat:
    """Tests for validate_compression_format function."""

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        result = validate_compression_format(None)
        assert result is None

    def test_gzip_is_valid(self) -> None:
        """Test that 'gzip' is valid."""
        result = validate_compression_format("gzip")
        assert result == "gzip"

    def test_lzma_is_valid(self) -> None:
        """Test that 'lzma' is valid."""
        result = validate_compression_format("lzma")
        assert result == "lzma"

    def test_zstd_is_valid(self) -> None:
        """Test that 'zstd' is valid."""
        result = validate_compression_format("zstd")
        assert result == "zstd"

    def test_uppercase_is_lowercased(self) -> None:
        """Test that uppercase is converted to lowercase."""
        result = validate_compression_format("GZIP")
        assert result == "gzip"

    def test_whitespace_is_stripped(self) -> None:
        """Test that whitespace is stripped."""
        result = validate_compression_format("  gzip  ")
        assert result == "gzip"

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises error."""
        with pytest.raises(
            InvalidInputError,
            match="Unsupported compression format.*bzip2.*Supported formats: gzip, lzma, zstd",
        ):
            validate_compression_format("bzip2")

    def test_empty_string_raises_error(self) -> None:
        """Test that empty string raises error."""
        with pytest.raises(InvalidInputError, match="Unsupported compression format"):
            validate_compression_format("")


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_valid_filename_unchanged(self) -> None:
        """Test that valid filename is unchanged."""
        result = sanitize_filename("archive_2025.mbox")
        assert result == "archive_2025.mbox"

    def test_filename_with_dashes(self) -> None:
        """Test filename with dashes."""
        result = sanitize_filename("my-archive-2025.mbox")
        assert result == "my-archive-2025.mbox"

    def test_removes_path_separators(self) -> None:
        """Test that path separators are removed."""
        result = sanitize_filename("../../../etc/passwd")
        assert result == "passwd"

    def test_replaces_spaces_with_underscores(self) -> None:
        """Test that spaces are replaced with underscores."""
        result = sanitize_filename("my archive file.mbox")
        assert result == "my_archive_file.mbox"

    def test_replaces_special_characters(self) -> None:
        """Test that special characters are replaced."""
        result = sanitize_filename("file@#$%^&*().mbox")
        assert result == "file_________.mbox"

    def test_removes_leading_dots(self) -> None:
        """Test that leading dots are removed."""
        result = sanitize_filename("...archive.mbox")
        assert result == "archive.mbox"

    def test_removes_trailing_dots(self) -> None:
        """Test that trailing dots are removed."""
        result = sanitize_filename("archive.mbox...")
        assert result == "archive.mbox"

    def test_replaces_leading_spaces(self) -> None:
        """Test that leading spaces are replaced with underscores, then stripped."""
        result = sanitize_filename("   archive.mbox")
        assert result == "___archive.mbox"

    def test_replaces_trailing_spaces(self) -> None:
        """Test that trailing spaces are replaced with underscores, then stripped."""
        result = sanitize_filename("archive.mbox   ")
        assert result == "archive.mbox___"

    def test_empty_filename_raises_error(self) -> None:
        """Test that empty filename raises error."""
        with pytest.raises(InvalidInputError, match="Filename cannot be empty"):
            sanitize_filename("")

    def test_whitespace_only_filename_raises_error(self) -> None:
        """Test that whitespace-only filename raises error."""
        with pytest.raises(InvalidInputError, match="Filename cannot be empty"):
            sanitize_filename("   ")

    def test_all_special_chars_becomes_underscores(self) -> None:
        """Test that filename with only special chars becomes underscores."""
        result = sanitize_filename("@#$%^&*()")
        assert result == "_________"

    def test_truncates_long_filename_preserving_extension(self) -> None:
        """Test that long filename is truncated while preserving extension."""
        long_name = "a" * 300
        result = sanitize_filename(f"{long_name}.mbox", max_length=255)
        assert len(result) == 255
        assert result.endswith(".mbox")
        assert result.startswith("a")

    def test_truncates_long_filename_without_extension(self) -> None:
        """Test that long filename without extension is truncated."""
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) == 255
        assert result == "a" * 255

    def test_filename_exactly_max_length(self) -> None:
        """Test that filename of exactly max length is unchanged."""
        filename = "a" * 255
        result = sanitize_filename(filename, max_length=255)
        assert result == filename

    def test_filename_with_multiple_dots(self) -> None:
        """Test filename with multiple dots preserves last extension."""
        result = sanitize_filename("archive.2025.01.13.mbox.gz")
        assert result == "archive.2025.01.13.mbox.gz"

    def test_long_filename_with_multiple_dots(self) -> None:
        """Test long filename with multiple dots preserves last extension."""
        long_name = "a" * 300
        result = sanitize_filename(f"{long_name}.tar.gz", max_length=20)
        assert len(result) == 20
        assert result.endswith(".gz")

    def test_custom_max_length(self) -> None:
        """Test custom max_length parameter."""
        result = sanitize_filename("a" * 100, max_length=50)
        assert len(result) == 50

    def test_preserves_alphanumeric_and_underscores(self) -> None:
        """Test that alphanumeric chars and underscores are preserved."""
        result = sanitize_filename("Archive_2025_01_13.mbox")
        assert result == "Archive_2025_01_13.mbox"

    def test_only_dots_and_spaces_becomes_underscores(self) -> None:
        """Test that filename with only dots and spaces becomes underscores after replacement."""
        result = sanitize_filename("... . . ...")
        # Dots and spaces replaced with underscores, then leading/trailing dots stripped
        assert "_" in result or result == ""

    def test_only_dots_raises_error(self) -> None:
        """Test that filename with only dots raises error after sanitization.

        Dots are preserved by the regex but stripped by strip(". "), resulting
        in empty filename which triggers the 'empty after sanitization' error.
        """
        with pytest.raises(InvalidInputError, match="Filename is empty after sanitization"):
            sanitize_filename(".....")
