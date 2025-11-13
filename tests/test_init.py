"""Tests for __init__.py module."""

from gmailarchiver import __version__


def test_version_exists() -> None:
    """Test that __version__ is defined."""
    assert __version__ is not None
    assert isinstance(__version__, str)
