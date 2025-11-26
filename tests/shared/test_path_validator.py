"""Tests for path validation module."""

import tempfile
from pathlib import Path

import pytest

from gmailarchiver.shared.path_validator import (
    PathTraversalError,
    validate_file_path,
    validate_file_path_for_writing,
)


class TestValidateFilePath:
    """Tests for validate_file_path function."""

    def test_simple_relative_path(self):
        """Test validation of simple relative path in current directory."""
        result = validate_file_path("test.txt")
        expected = Path.cwd() / "test.txt"
        assert result == expected

    def test_relative_path_with_subdirectory(self):
        """Test validation of relative path with subdirectory."""
        result = validate_file_path("data/config.json")
        expected = Path.cwd() / "data" / "config.json"
        assert result == expected

    def test_absolute_path_within_cwd(self):
        """Test validation of absolute path within current directory."""
        test_path = Path.cwd() / "test" / "file.txt"
        result = validate_file_path(str(test_path))
        assert result == test_path

    def test_path_traversal_attack_relative(self):
        """Test that path traversal with ../ is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("../../etc/passwd")
        assert "outside the allowed directory" in str(exc_info.value)

    def test_path_traversal_attack_mixed(self):
        """Test that mixed path traversal is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("data/../../etc/passwd")
        assert "outside the allowed directory" in str(exc_info.value)

    def test_absolute_path_outside_base_dir(self):
        """Test that absolute path outside base directory is blocked."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_file_path("/etc/passwd", base_dir=str(Path.cwd()))
        assert "outside the allowed directory" in str(exc_info.value)

    def test_custom_base_dir_valid(self):
        """Test validation with custom base directory for valid path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_file_path("test.txt", base_dir=tmpdir)
            expected = (Path(tmpdir) / "test.txt").resolve()
            assert result == expected

    def test_custom_base_dir_invalid(self):
        """Test validation with custom base directory for invalid path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathTraversalError):
                validate_file_path("/etc/passwd", base_dir=tmpdir)

    def test_empty_path(self):
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_file_path("")
        assert "cannot be empty" in str(exc_info.value)

    def test_whitespace_only_path(self):
        """Test that whitespace-only path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_file_path("   ")
        assert "cannot be empty" in str(exc_info.value)

    def test_path_with_dot_component(self):
        """Test that path with . component is resolved correctly."""
        result = validate_file_path("./data/./config.json")
        expected = Path.cwd() / "data" / "config.json"
        assert result == expected

    def test_symlink_within_base_dir(self):
        """Test that symlinks within base directory are allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a file and a symlink to it
            target_file = tmpdir_path / "target.txt"
            target_file.write_text("test")
            link_file = tmpdir_path / "link.txt"
            link_file.symlink_to(target_file)

            # Validate the symlink
            result = validate_file_path("link.txt", base_dir=tmpdir)
            # Result should resolve to the target file
            assert result == target_file.resolve()

    def test_symlink_outside_base_dir(self):
        """Test that symlinks pointing outside base directory are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a symlink pointing outside the base directory
            link_file = tmpdir_path / "evil_link.txt"
            try:
                link_file.symlink_to("/etc/passwd")

                # Attempt to validate the symlink
                with pytest.raises(PathTraversalError):
                    validate_file_path("evil_link.txt", base_dir=tmpdir)
            except OSError:
                # On some systems, creating symlinks might fail
                pytest.skip("Cannot create symlinks on this system")

    def test_nonexistent_path_is_allowed(self):
        """Test that nonexistent paths are allowed (for file creation)."""
        result = validate_file_path("nonexistent_file.txt")
        expected = Path.cwd() / "nonexistent_file.txt"
        assert result == expected
        # Note: The file doesn't need to exist

    def test_path_with_tilde_expansion(self):
        """Test that tilde expansion is handled."""
        # Note: Path.resolve() doesn't expand ~, but Path.expanduser() does
        # For security, we should NOT expand ~, so this should work relative to cwd
        result = validate_file_path("~/test.txt")
        # This should be treated as a subdirectory named ~
        expected = Path.cwd() / "~" / "test.txt"
        assert result == expected


class TestValidateFilePathForWriting:
    """Tests for validate_file_path_for_writing function."""

    def test_creates_parent_directory(self):
        """Test that parent directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "subdir" / "test.txt"

            # Parent shouldn't exist yet
            assert not file_path.parent.exists()

            # Validate for writing
            result = validate_file_path_for_writing(
                str(file_path.relative_to(tmpdir)), base_dir=tmpdir
            )

            # Parent should now exist
            assert result.parent.exists()
            assert result.parent.is_dir()

    def test_existing_parent_directory(self):
        """Test with existing parent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = "test.txt"

            result = validate_file_path_for_writing(file_path, base_dir=tmpdir)
            expected = (Path(tmpdir) / file_path).resolve()

            assert result == expected
            assert result.parent.exists()

    def test_nested_directory_creation(self):
        """Test creation of nested directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = "a/b/c/d/test.txt"

            result = validate_file_path_for_writing(file_path, base_dir=tmpdir)

            # All parent directories should exist
            assert result.parent.exists()
            expected = (Path(tmpdir) / file_path).resolve()
            assert result == expected

    def test_path_traversal_blocked_for_writing(self):
        """Test that path traversal is blocked even for writing."""
        with pytest.raises(PathTraversalError):
            validate_file_path_for_writing("../../etc/passwd")

    def test_empty_path_for_writing(self):
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError):
            validate_file_path_for_writing("")


class TestPathTraversalScenarios:
    """Additional security-focused tests for various attack vectors."""

    def test_null_byte_injection(self):
        """Test that null byte injection attempts are handled."""
        # Python's Path should handle this, but let's verify
        try:
            result = validate_file_path("test.txt\x00.ini")
            # If we get here, the null byte was handled
            assert "\x00" not in str(result)
        except (ValueError, OSError):
            # This is acceptable - the path is rejected
            pass

    def test_multiple_slashes(self):
        """Test that multiple slashes are normalized."""
        result = validate_file_path("data///config.json")
        expected = Path.cwd() / "data" / "config.json"
        assert result == expected

    def test_backslash_on_unix(self):
        """Test that backslashes are handled correctly."""
        # On Unix, backslash is a valid filename character
        # On Windows, it's a path separator
        result = validate_file_path("test\\file.txt")
        # Path should normalize this based on OS
        assert Path.cwd() in result.parents or result.parent == Path.cwd()

    def test_unicode_in_path(self):
        """Test that Unicode characters in paths are handled."""
        result = validate_file_path("测试文件.txt")
        expected = Path.cwd() / "测试文件.txt"
        assert result == expected

    def test_special_windows_names(self):
        """Test handling of special Windows device names."""
        # On Unix, these are just regular filenames
        # On Windows, they might be special
        try:
            result = validate_file_path("CON.txt")
            assert Path.cwd() in result.parents or result.parent == Path.cwd()
        except (ValueError, OSError):
            # Windows might reject these - that's fine
            pass

    def test_very_long_path(self):
        """Test handling of very long paths."""
        # Create a very long but valid path
        long_name = "a" * 200 + ".txt"
        try:
            result = validate_file_path(long_name)
            expected = Path.cwd() / long_name
            assert result == expected
        except OSError:
            # Some filesystems have length limits - that's acceptable
            pass

    def test_path_with_spaces(self):
        """Test that paths with spaces are handled correctly."""
        result = validate_file_path("my documents/test file.txt")
        expected = Path.cwd() / "my documents" / "test file.txt"
        assert result == expected
