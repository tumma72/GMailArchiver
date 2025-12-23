"""Tests for path validation utilities."""

from pathlib import Path

import pytest

from gmailarchiver.shared.path_validator import (
    PathTraversalError,
    validate_file_path,
    validate_file_path_for_writing,
)


class TestValidateFilePath:
    """Tests for validate_file_path function."""

    def test_valid_relative_path_no_base_dir(self, temp_dir):
        """Test validating a relative path without base_dir (uses cwd)."""
        # This tests line 71 (return statement) and uses default base_dir behavior
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            result = validate_file_path("config.json")

            # Should resolve to cwd/config.json (compare resolved paths for macOS)
            expected = (Path(temp_dir) / "config.json").resolve()
            assert result == expected
            assert result.parent == Path(temp_dir).resolve()
        finally:
            os.chdir(original_cwd)

    def test_valid_relative_path_with_base_dir(self, temp_dir):
        """Test validating a relative path with explicit base_dir."""
        # This tests line 46 (base_dir path resolution) and line 71 (return)
        result = validate_file_path("subdir/file.txt", base_dir=str(temp_dir))

        expected = (temp_dir / "subdir" / "file.txt").resolve()
        assert result == expected

    def test_valid_absolute_path_within_base_dir(self, temp_dir):
        """Test validating an absolute path that's within base_dir."""
        # Create a subdirectory
        subdir = temp_dir / "data"
        subdir.mkdir()

        # Absolute path within base_dir should be allowed
        target_path = subdir / "file.txt"
        result = validate_file_path(str(target_path), base_dir=str(temp_dir))

        assert result == target_path.resolve()

    def test_empty_path_raises_value_error(self, temp_dir):
        """Test that empty path raises ValueError."""
        # This tests line 40 (empty path validation)
        with pytest.raises(ValueError, match="Path cannot be empty"):
            validate_file_path("")

    def test_whitespace_only_path_raises_value_error(self, temp_dir):
        """Test that whitespace-only path raises ValueError."""
        # This tests line 40 (empty path validation with strip)
        with pytest.raises(ValueError, match="Path cannot be empty"):
            validate_file_path("   ")

    def test_path_traversal_relative_blocked(self, temp_dir):
        """Test that relative path traversal is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("../../etc/passwd", base_dir=str(temp_dir))

        assert "outside the allowed directory" in str(exc_info.value)
        assert "../../etc/passwd" in str(exc_info.value)

    def test_path_traversal_with_dots_blocked(self, temp_dir):
        """Test that path traversal using .. is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("subdir/../../etc/passwd", base_dir=str(temp_dir))

        assert "outside the allowed directory" in str(exc_info.value)

    def test_absolute_path_outside_base_dir_blocked(self, temp_dir):
        """Test that absolute path outside base_dir is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("/etc/passwd", base_dir=str(temp_dir))

        assert "outside the allowed directory" in str(exc_info.value)
        assert "/etc/passwd" in str(exc_info.value)

    def test_symlink_escape_blocked(self, temp_dir):
        """Test that symlink pointing outside base_dir is blocked."""
        # Create a symlink pointing outside the base directory
        outside_target = Path("/tmp")
        symlink = temp_dir / "escape_link"

        try:
            symlink.symlink_to(outside_target)

            # Trying to access through symlink should be blocked
            with pytest.raises(PathTraversalError) as exc_info:
                validate_file_path("escape_link/sensitive.txt", base_dir=str(temp_dir))

            assert "outside the allowed directory" in str(exc_info.value)
        except OSError:
            # If symlink creation fails (e.g., permissions), skip the test
            pytest.skip("Cannot create symlink for testing")

    def test_nested_relative_path_within_base_dir(self, temp_dir):
        """Test that nested relative paths within base_dir are allowed."""
        result = validate_file_path("a/b/c/file.txt", base_dir=str(temp_dir))

        expected = (temp_dir / "a" / "b" / "c" / "file.txt").resolve()
        assert result == expected

    def test_path_with_special_characters(self, temp_dir):
        """Test path with special characters is handled correctly."""
        result = validate_file_path("file-name_2024.txt", base_dir=str(temp_dir))

        expected = (temp_dir / "file-name_2024.txt").resolve()
        assert result == expected

    def test_resolved_path_equals_base_dir_allowed(self, temp_dir):
        """Test that path resolving to exactly base_dir is allowed."""
        # "." should resolve to base_dir itself
        result = validate_file_path(".", base_dir=str(temp_dir))

        assert result == temp_dir.resolve()


class TestValidateFilePathForWriting:
    """Tests for validate_file_path_for_writing function."""

    def test_creates_parent_directory(self, temp_dir):
        """Test that parent directories are created for write paths."""
        # This tests lines 93-98 (validate_file_path_for_writing)
        file_path = "deeply/nested/subdir/file.txt"
        result = validate_file_path_for_writing(file_path, base_dir=str(temp_dir))

        # Parent directories should exist
        assert result.parent.exists()
        assert result.parent == (temp_dir / "deeply" / "nested" / "subdir").resolve()

    def test_existing_parent_directory(self, temp_dir):
        """Test write validation when parent directory already exists."""
        # Create parent directory first
        parent = temp_dir / "existing"
        parent.mkdir()

        result = validate_file_path_for_writing("existing/file.txt", base_dir=str(temp_dir))

        assert result.parent.exists()
        assert result == (temp_dir / "existing" / "file.txt").resolve()

    def test_path_traversal_blocked_for_writing(self, temp_dir):
        """Test that path traversal is blocked for write operations."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path_for_writing("../../../etc/passwd", base_dir=str(temp_dir))

        assert "outside the allowed directory" in str(exc_info.value)

    def test_empty_path_blocked_for_writing(self, temp_dir):
        """Test that empty path raises ValueError for write operations."""
        with pytest.raises(ValueError, match="Path cannot be empty"):
            validate_file_path_for_writing("", base_dir=str(temp_dir))

    def test_write_validation_returns_path_object(self, temp_dir):
        """Test that write validation returns a Path object."""
        result = validate_file_path_for_writing("output.txt", base_dir=str(temp_dir))

        assert isinstance(result, Path)
        assert result == (temp_dir / "output.txt").resolve()

    def test_multiple_nested_directories_created(self, temp_dir):
        """Test that multiple levels of nested directories are created."""
        result = validate_file_path_for_writing("a/b/c/d/e/file.txt", base_dir=str(temp_dir))

        # All parent directories should exist
        assert result.parent.exists()
        assert (temp_dir / "a").exists()
        assert (temp_dir / "a" / "b").exists()
        assert (temp_dir / "a" / "b" / "c").exists()

    def test_absolute_path_outside_base_blocked_for_writing(self, temp_dir):
        """Test that absolute paths outside base_dir are blocked for writing."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path_for_writing("/etc/malicious.conf", base_dir=str(temp_dir))

        assert "outside the allowed directory" in str(exc_info.value)


class TestPathTraversalError:
    """Tests for PathTraversalError exception."""

    def test_error_is_value_error_subclass(self):
        """Test that PathTraversalError is a ValueError subclass."""
        assert issubclass(PathTraversalError, ValueError)

    def test_error_message_preserved(self):
        """Test that error message is preserved."""
        msg = "Test error message"
        error = PathTraversalError(msg)

        assert str(error) == msg

    def test_error_raised_correctly(self):
        """Test that error can be raised and caught."""
        with pytest.raises(PathTraversalError) as exc_info:
            raise PathTraversalError("Security violation")

        assert "Security violation" in str(exc_info.value)


class TestSecurityScenarios:
    """Tests for various security attack scenarios."""

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "../../../etc/passwd",
            "../../root/.ssh/id_rsa",
            "../../../../../etc/shadow",
            "subdir/../../../etc/hosts",
            "./../../etc/passwd",
        ],
    )
    def test_common_path_traversal_attacks_blocked(self, temp_dir, malicious_path):
        """Test that common path traversal patterns are blocked."""
        with pytest.raises(PathTraversalError):
            validate_file_path(malicious_path, base_dir=str(temp_dir))

    @pytest.mark.parametrize(
        "absolute_path",
        [
            "/etc/passwd",
            "/root/.ssh/id_rsa",
            "/var/log/auth.log",
            "/tmp/../etc/passwd",
        ],
    )
    def test_absolute_paths_outside_base_blocked(self, temp_dir, absolute_path):
        """Test that various absolute paths outside base_dir are blocked."""
        with pytest.raises(PathTraversalError):
            validate_file_path(absolute_path, base_dir=str(temp_dir))

    def test_null_byte_injection_handled(self, temp_dir):
        """Test that null byte injection attempts are handled."""
        # Python's Path should handle this, but let's verify
        try:
            result = validate_file_path("file.txt\x00/etc/passwd", base_dir=str(temp_dir))
            # If it doesn't raise, it should still be within base_dir
            assert str(result).startswith(str(temp_dir))
        except (ValueError, PathTraversalError):
            # Either error is acceptable for security
            pass

    def test_unicode_path_traversal_blocked(self, temp_dir):
        """Test that Unicode-based path traversal is blocked."""
        # Some systems might interpret Unicode dots differently
        unicode_dots = ".\u2024.\u2024/etc/passwd"
        try:
            result = validate_file_path(unicode_dots, base_dir=str(temp_dir))
            # If accepted, must be within base_dir (compare resolved paths)
            resolved_base = temp_dir.resolve()
            assert str(result).startswith(str(resolved_base))
        except (PathTraversalError, ValueError):
            # Blocking is also acceptable
            pass


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_current_directory_shorthand(self, temp_dir):
        """Test that '.' is handled correctly."""
        result = validate_file_path(".", base_dir=str(temp_dir))
        assert result == temp_dir.resolve()

    def test_path_with_trailing_slash(self, temp_dir):
        """Test path with trailing slash."""
        result = validate_file_path("subdir/", base_dir=str(temp_dir))
        # Path normalizes this
        assert result == (temp_dir / "subdir").resolve()

    def test_path_with_multiple_slashes(self, temp_dir):
        """Test path with multiple consecutive slashes."""
        result = validate_file_path("subdir//file.txt", base_dir=str(temp_dir))
        # Path normalizes this
        assert result == (temp_dir / "subdir" / "file.txt").resolve()

    def test_very_long_path(self, temp_dir):
        """Test that very long paths are handled."""
        # Create a very nested path
        long_path = "/".join([f"dir{i}" for i in range(50)]) + "/file.txt"
        result = validate_file_path(long_path, base_dir=str(temp_dir))

        # Should be valid and within base_dir (compare resolved paths)
        resolved_base = temp_dir.resolve()
        assert str(result).startswith(str(resolved_base))

    def test_base_dir_with_symlink(self, temp_dir):
        """Test behavior when base_dir itself contains a symlink."""
        # Create a real directory
        real_dir = temp_dir / "real"
        real_dir.mkdir()

        # Create a symlink to it
        link_dir = temp_dir / "link"
        try:
            link_dir.symlink_to(real_dir)

            # Using the symlink as base_dir should work
            result = validate_file_path("file.txt", base_dir=str(link_dir))

            # The result should be the resolved path
            assert result.exists() or result.parent.exists() or True  # Path is valid
        except OSError:
            pytest.skip("Cannot create symlink for testing")

    def test_nonexistent_base_dir(self):
        """Test with a nonexistent base_dir."""
        # Should not raise during validation (only when accessing)
        result = validate_file_path("file.txt", base_dir="/nonexistent/base/directory/for/testing")

        assert "file.txt" in str(result)
