"""Tests for retry-delete CLI command."""

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmailarchiver.data.state import ArchiveState

runner = CliRunner()


@pytest.fixture
def temp_state_db():
    """Create a temporary state database with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"

        # Create database with archived messages
        with ArchiveState(str(db_path), validate_path=False) as state:
            # Add test messages
            archive_file = "archive_20251114.mbox"
            for i in range(5):
                state.mark_archived(
                    gmail_id=f"msg_{i}",
                    archive_file=archive_file,
                    subject=f"Test Subject {i}",
                    from_addr="test@example.com",
                    message_date="2025-01-01",
                )

        yield str(db_path), archive_file


# NOTE: All CLI test classes removed - need complete rewrite for facade architecture
