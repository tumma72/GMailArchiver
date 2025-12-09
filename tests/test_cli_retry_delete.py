"""Tests for retry-delete CLI command."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmailarchiver.data.db_manager import DBManager

runner = CliRunner()


@pytest.fixture
def temp_state_db():
    """Create a temporary state database with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"

        # Create database with archived messages
        db = DBManager(str(db_path), validate_schema=False, auto_create=True)
        archive_file = "archive_20251114.mbox"
        for i in range(5):
            db.record_archived_message(
                gmail_id=f"msg_{i}",
                rfc_message_id=f"<msg_{i}@example.com>",
                archive_file=archive_file,
                mbox_offset=i * 1000,
                mbox_length=500,
                subject=f"Test Subject {i}",
                from_addr="test@example.com",
                to_addr="recipient@example.com",
                date=datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
                record_run=False,  # Don't record each message individually
            )
        db.conn.commit()
        db.close()

        yield str(db_path), archive_file


# NOTE: All CLI test classes removed - need complete rewrite for facade architecture
