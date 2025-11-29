"""Tests for duplicate resolver module (TDD)."""

import pytest

from gmailarchiver.core.deduplicator._resolver import DuplicateResolver, Resolution
from gmailarchiver.core.deduplicator._scanner import MessageInfo


class TestDuplicateResolver:
    """Test duplicate resolution strategies."""

    def test_resolve_newest_strategy(self) -> None:
        """Test 'newest' strategy keeps message with latest timestamp."""
        messages = [
            MessageInfo("gid1", "archive1.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
            MessageInfo("gid2", "archive2.mbox", 0, 1024, 1024, "2024-01-03T10:00:00"),
            MessageInfo("gid3", "archive3.mbox", 0, 1024, 1024, "2024-01-02T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="newest")

        assert resolution.keep.gmail_id == "gid2"  # Latest timestamp
        assert len(resolution.remove) == 2
        assert "gid1" in [m.gmail_id for m in resolution.remove]
        assert "gid3" in [m.gmail_id for m in resolution.remove]

    def test_resolve_largest_strategy(self) -> None:
        """Test 'largest' strategy keeps message with most bytes."""
        messages = [
            MessageInfo("gid1", "archive1.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
            MessageInfo("gid2", "archive2.mbox", 0, 2048, 2048, "2024-01-02T10:00:00"),
            MessageInfo("gid3", "archive3.mbox", 0, 512, 512, "2024-01-03T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="largest")

        assert resolution.keep.gmail_id == "gid2"  # Largest size
        assert len(resolution.remove) == 2

    def test_resolve_first_strategy(self) -> None:
        """Test 'first' strategy keeps message from alphabetically first archive."""
        messages = [
            MessageInfo("gid1", "archive_c.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
            MessageInfo("gid2", "archive_a.mbox", 0, 1024, 1024, "2024-01-02T10:00:00"),
            MessageInfo("gid3", "archive_b.mbox", 0, 1024, 1024, "2024-01-03T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="first")

        assert resolution.keep.gmail_id == "gid2"  # archive_a.mbox
        assert len(resolution.remove) == 2

    def test_resolve_invalid_strategy_raises(self) -> None:
        """Test that invalid strategy raises ValueError."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
        ]

        resolver = DuplicateResolver()

        with pytest.raises(ValueError, match="Invalid strategy"):
            resolver.resolve(messages, strategy="invalid")

    def test_resolve_single_message(self) -> None:
        """Test resolution with single message (nothing to remove)."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="newest")

        assert resolution.keep.gmail_id == "gid1"
        assert len(resolution.remove) == 0

    def test_resolve_calculates_space_saved(self) -> None:
        """Test that space saved is calculated correctly."""
        messages = [
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
            MessageInfo("gid2", "archive.mbox", 0, 2048, 2048, "2024-01-02T10:00:00"),
            MessageInfo("gid3", "archive.mbox", 0, 512, 512, "2024-01-03T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="newest")

        # Keep gid2, remove gid1 (1024) and gid3 (512)
        assert resolution.space_saved == 1024 + 2048

    def test_resolve_newest_presorted(self) -> None:
        """Test newest strategy with pre-sorted messages (DESC)."""
        messages = [
            MessageInfo("gid3", "archive.mbox", 0, 1024, 1024, "2024-01-03T10:00:00"),
            MessageInfo("gid2", "archive.mbox", 0, 1024, 1024, "2024-01-02T10:00:00"),
            MessageInfo("gid1", "archive.mbox", 0, 1024, 1024, "2024-01-01T10:00:00"),
        ]

        resolver = DuplicateResolver()
        resolution = resolver.resolve(messages, strategy="newest")

        # Should keep first (gid3, already sorted DESC)
        assert resolution.keep.gmail_id == "gid3"


class TestResolution:
    """Test Resolution dataclass."""

    def test_resolution_contains_all_fields(self) -> None:
        """Test that Resolution contains all required fields."""
        keep = MessageInfo("keep", "archive.mbox", 0, 1024, 1024, "2024-01-01")
        remove = [MessageInfo("remove1", "archive.mbox", 1024, 512, 512, "2024-01-02")]

        resolution = Resolution(keep=keep, remove=remove, space_saved=512)

        assert resolution.keep.gmail_id == "keep"
        assert len(resolution.remove) == 1
        assert resolution.space_saved == 512
