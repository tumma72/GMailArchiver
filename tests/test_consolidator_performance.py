"""Performance benchmarks for archive consolidation."""

import mailbox
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.consolidator import ArchiveConsolidator
from gmailarchiver.state import ArchiveState


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_db(temp_dir):
    """Create a test state database."""
    db_path = temp_dir / "test_state.db"

    # Initialize database with schema (disable path validation for tests)
    with ArchiveState(str(db_path), validate_path=False) as state:
        # Ensure tables exist
        state.conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER,
                archived_timestamp TEXT,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT
            )
        ''')
        state.conn.commit()

    return db_path


def create_large_mbox(path: Path, num_messages: int, state_db: Path, offset: int = 0) -> None:
    """Create a large mbox file for testing."""
    mbox = mailbox.mbox(str(path))

    for i in range(num_messages):
        idx = offset + i
        msg = mailbox.mboxMessage()
        msg['From'] = f'sender{idx}@example.com'
        msg['To'] = 'recipient@example.com'
        msg['Subject'] = f'Test Message {idx}'
        msg['Message-ID'] = f'<msg{idx}@example.com>'
        msg['Date'] = f'Wed, {10 + (idx % 20)} Jan 2024 12:00:00 +0000'
        msg.set_payload(f'Body of message {idx} with some content to make it realistic.')
        mbox.add(msg)

    mbox.close()

    # Add to database
    with ArchiveState(str(state_db), validate_path=False) as state:
        for i in range(num_messages):
            idx = offset + i
            state.conn.execute('''
                INSERT INTO messages
                (gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length,
                 archived_timestamp, subject, from_addr, message_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                f'gmail{idx}',
                f'<msg{idx}@example.com>',
                str(path),
                0,
                100,
                '2024-01-01T00:00:00Z',
                f'Test Message {idx}',
                f'sender{idx}@example.com',
                f'2024-01-{10 + (idx % 20)}'
            ))
        state.conn.commit()


def test_consolidate_10k_messages_performance(temp_dir, state_db):
    """Test consolidation of 10,000 messages completes in under 60 seconds."""
    # Create two archives with 5k messages each
    mbox1 = temp_dir / "archive1.mbox"
    mbox2 = temp_dir / "archive2.mbox"

    create_large_mbox(mbox1, 5000, state_db, offset=0)
    create_large_mbox(mbox2, 5000, state_db, offset=5000)

    # Consolidate
    consolidator = ArchiveConsolidator(str(state_db))
    output_path = temp_dir / "consolidated.mbox"

    result = consolidator.consolidate(
        source_archives=[mbox1, mbox2],
        output_archive=output_path,
        sort_by_date=True,
        deduplicate=True
    )

    # Verify performance target
    assert result.execution_time_ms < 60000, (
        f"Consolidation took {result.execution_time_ms:.0f}ms, "
        f"expected < 60000ms (60 seconds)"
    )

    # Verify correctness
    assert result.total_messages == 10000
    assert result.messages_consolidated == 10000

    print(f"\n✓ Consolidated 10,000 messages in {result.execution_time_ms:.0f}ms "
          f"({result.execution_time_ms / 1000:.2f}s)")


def test_consolidate_1k_messages_quick(temp_dir, state_db):
    """Test consolidation of 1,000 messages completes quickly."""
    # Create two archives with 500 messages each
    mbox1 = temp_dir / "archive1.mbox"
    mbox2 = temp_dir / "archive2.mbox"

    create_large_mbox(mbox1, 500, state_db, offset=0)
    create_large_mbox(mbox2, 500, state_db, offset=500)

    # Consolidate
    consolidator = ArchiveConsolidator(str(state_db))
    output_path = temp_dir / "consolidated.mbox"

    result = consolidator.consolidate(
        source_archives=[mbox1, mbox2],
        output_archive=output_path,
        sort_by_date=True,
        deduplicate=True
    )

    # Verify performance (should be under 10 seconds)
    assert result.execution_time_ms < 10000, (
        f"Consolidation took {result.execution_time_ms:.0f}ms, "
        f"expected < 10000ms (10 seconds)"
    )

    # Verify correctness
    assert result.total_messages == 1000
    assert result.messages_consolidated == 1000

    print(f"\n✓ Consolidated 1,000 messages in {result.execution_time_ms:.0f}ms "
          f"({result.execution_time_ms / 1000:.2f}s)")
