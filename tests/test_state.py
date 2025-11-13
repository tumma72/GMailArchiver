"""Tests for state tracking module."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.state import ArchiveState


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_archive_state.db'
        yield str(db_path)


class TestArchiveState:
    """Tests for ArchiveState class."""

    def test_init_creates_database(self, temp_db):
        """Test that initializing ArchiveState creates database and tables."""
        state = ArchiveState(temp_db)

        assert Path(temp_db).exists()

        # Check tables exist
        cursor = state.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert 'archived_messages' in tables
        assert 'archive_runs' in tables

        state.close()

    def test_mark_archived(self, temp_db):
        """Test marking a message as archived."""
        state = ArchiveState(temp_db)

        state.mark_archived(
            gmail_id='msg123',
            archive_file='test.mbox',
            subject='Test Email',
            from_addr='test@example.com',
            message_date='2025-01-01',
            checksum='abc123'
        )

        # Verify message was stored
        cursor = state.conn.execute(
            'SELECT * FROM archived_messages WHERE gmail_id = ?',
            ('msg123',)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == 'msg123'  # gmail_id
        assert row[2] == 'test.mbox'  # archive_file
        assert row[3] == 'Test Email'  # subject
        assert row[4] == 'test@example.com'  # from_addr
        assert row[5] == '2025-01-01'  # message_date
        assert row[6] == 'abc123'  # checksum

        state.close()

    def test_is_archived(self, temp_db):
        """Test checking if message is archived."""
        state = ArchiveState(temp_db)

        # Initially not archived
        assert not state.is_archived('msg123')

        # Mark as archived
        state.mark_archived('msg123', 'test.mbox')

        # Now should be archived
        assert state.is_archived('msg123')

        state.close()

    def test_get_archived_count(self, temp_db):
        """Test getting count of archived messages."""
        state = ArchiveState(temp_db)

        assert state.get_archived_count() == 0

        state.mark_archived('msg1', 'test.mbox')
        assert state.get_archived_count() == 1

        state.mark_archived('msg2', 'test.mbox')
        assert state.get_archived_count() == 2

        # Updating same message shouldn't increase count
        state.mark_archived('msg1', 'test.mbox', subject='Updated')
        assert state.get_archived_count() == 2

        state.close()

    def test_record_archive_run(self, temp_db):
        """Test recording an archive run."""
        state = ArchiveState(temp_db)

        run_id = state.record_archive_run(
            query='older_than:3y',
            messages_archived=100,
            archive_file='test.mbox'
        )

        assert run_id > 0

        # Verify run was stored
        cursor = state.conn.execute(
            'SELECT * FROM archive_runs WHERE run_id = ?',
            (run_id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[2] == 'older_than:3y'  # query
        assert row[3] == 100  # messages_archived
        assert row[4] == 'test.mbox'  # archive_file

        state.close()

    def test_get_archive_runs(self, temp_db):
        """Test getting recent archive runs."""
        state = ArchiveState(temp_db)

        # Add multiple runs
        state.record_archive_run('older_than:1y', 50, 'run1.mbox')
        state.record_archive_run('older_than:2y', 100, 'run2.mbox')
        state.record_archive_run('older_than:3y', 150, 'run3.mbox')

        # Get all runs
        runs = state.get_archive_runs(limit=10)
        assert len(runs) == 3

        # Should be in reverse chronological order
        assert runs[0]['archive_file'] == 'run3.mbox'
        assert runs[0]['messages_archived'] == 150

        # Test limit
        runs = state.get_archive_runs(limit=2)
        assert len(runs) == 2

        state.close()

    def test_get_archived_message_ids(self, temp_db):
        """Test getting all archived message IDs."""
        state = ArchiveState(temp_db)

        assert state.get_archived_message_ids() == set()

        state.mark_archived('msg1', 'test.mbox')
        state.mark_archived('msg2', 'test.mbox')
        state.mark_archived('msg3', 'test.mbox')

        ids = state.get_archived_message_ids()
        assert ids == {'msg1', 'msg2', 'msg3'}

        state.close()

    def test_get_archived_message_ids_for_file(self, temp_db):
        """Test getting message IDs for specific archive file."""
        state = ArchiveState(temp_db)

        # Add messages to different archives
        state.mark_archived('msg1', 'archive1.mbox')
        state.mark_archived('msg2', 'archive1.mbox')
        state.mark_archived('msg3', 'archive2.mbox')
        state.mark_archived('msg4', 'archive2.mbox')

        # Get IDs for specific file
        ids1 = state.get_archived_message_ids_for_file('archive1.mbox')
        assert ids1 == {'msg1', 'msg2'}

        ids2 = state.get_archived_message_ids_for_file('archive2.mbox')
        assert ids2 == {'msg3', 'msg4'}

        # Non-existent file
        ids3 = state.get_archived_message_ids_for_file('nonexistent.mbox')
        assert ids3 == set()

        state.close()

    def test_context_manager(self, temp_db):
        """Test using ArchiveState as context manager."""
        with ArchiveState(temp_db) as state:
            state.mark_archived('msg1', 'test.mbox')
            assert state.is_archived('msg1')

        # Connection should be closed after context
        # Verify by creating new connection
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute('SELECT COUNT(*) FROM archived_messages')
        count = cursor.fetchone()[0]
        assert count == 1
        conn.close()

    def test_mark_archived_replace(self, temp_db):
        """Test that mark_archived replaces existing records."""
        state = ArchiveState(temp_db)

        # Add initial message
        state.mark_archived(
            'msg1',
            'old_archive.mbox',
            subject='Old Subject',
            checksum='old_checksum'
        )

        # Update same message
        state.mark_archived(
            'msg1',
            'new_archive.mbox',
            subject='New Subject',
            checksum='new_checksum'
        )

        # Should only have one record
        assert state.get_archived_count() == 1

        # Should have updated values
        cursor = state.conn.execute(
            'SELECT archive_file, subject, checksum FROM archived_messages WHERE gmail_id = ?',
            ('msg1',)
        )
        row = cursor.fetchone()
        assert row[0] == 'new_archive.mbox'
        assert row[1] == 'New Subject'
        assert row[2] == 'new_checksum'

        state.close()
