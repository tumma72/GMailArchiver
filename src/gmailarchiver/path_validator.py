"""Path validation utilities to prevent path traversal attacks."""

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a path traversal attack is detected."""


def validate_file_path(path: str, base_dir: str | None = None) -> Path:
    """
    Validate and resolve a file path to prevent path traversal attacks.

    This function ensures that the resolved path is within the allowed directory
    (base_dir or current working directory) and prevents access to parent directories
    through path traversal patterns like '../'.

    Args:
        path: The file path to validate (can be relative or absolute)
        base_dir: The base directory to restrict paths to. If None, uses current
                  working directory.

    Returns:
        A resolved Path object that is guaranteed to be within base_dir

    Raises:
        PathTraversalError: If the path attempts to escape the base directory
        ValueError: If the path is empty or invalid

    Examples:
        >>> # Valid paths
        >>> validate_file_path('config.json')  # Returns cwd/config.json
        >>> validate_file_path('/tmp/data/file.txt', '/tmp')  # Returns /tmp/data/file.txt

        >>> # Invalid paths (will raise PathTraversalError)
        >>> validate_file_path('../../../etc/passwd')
        >>> validate_file_path('/etc/passwd', '/home/user')
    """
    if not path or not path.strip():
        raise ValueError("Path cannot be empty")

    # Determine the base directory
    if base_dir is None:
        base_dir_path = Path.cwd()
    else:
        base_dir_path = Path(base_dir).resolve()

    # Convert input path to Path object
    input_path = Path(path)

    # If path is relative, combine with base_dir before resolving
    # If path is absolute, use it directly
    if input_path.is_absolute():
        resolved_path = input_path.resolve()
    else:
        # Resolve relative to base_dir
        resolved_path = (base_dir_path / input_path).resolve()

    # Check if resolved path is within base directory
    # This prevents path traversal attacks
    try:
        # relative_to() will raise ValueError if resolved_path is not
        # a descendant of base_dir_path
        resolved_path.relative_to(base_dir_path)
    except ValueError:
        raise PathTraversalError(
            f"Path '{path}' resolves to '{resolved_path}' which is outside "
            f"the allowed directory '{base_dir_path}'"
        ) from None

    return resolved_path


def validate_file_path_for_writing(path: str, base_dir: str | None = None) -> Path:
    """
    Validate a file path for writing operations.

    Like validate_file_path, but also ensures the parent directory exists
    or can be created. This is useful for output files.

    Args:
        path: The file path to validate
        base_dir: The base directory to restrict paths to

    Returns:
        A validated Path object ready for writing

    Raises:
        PathTraversalError: If the path attempts to escape the base directory
        ValueError: If the path is empty or invalid
        OSError: If the parent directory cannot be created
    """
    validated_path = validate_file_path(path, base_dir)

    # Ensure parent directory exists
    validated_path.parent.mkdir(parents=True, exist_ok=True)

    return validated_path
