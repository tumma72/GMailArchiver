"""Performance benchmarks for archive consolidation."""

import mailbox
import tempfile
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest

from gmailarchiver.core.consolidator import ArchiveConsolidator
from gmailarchiver.data.migration import MigrationManager


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_db(temp_dir: Path) -> Path:
    """Create a test state database with v1.1 schema."""
    db_path = temp_dir / "test_state.db"

    # Create v1.1 schema using MigrationManager
    migrator = MigrationManager(db_path)
    conn = migrator._connect()
    migrator._create_enhanced_schema(conn)
    conn.commit()
    migrator._close()

    return db_path


def create_large_mbox(path: Path, num_messages: int, state_db: Path, offset: int = 0) -> None:
    """Create a large mbox file for testing with v1.1 schema."""
    mbox = mailbox.mbox(str(path))

    for i in range(num_messages):
        idx = offset + i
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{idx}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test Message {idx}"
        msg["Message-ID"] = f"<msg{idx}@example.com>"
        msg["Date"] = f"Wed, {10 + (idx % 20)} Jan 2024 12:00:00 +0000"
        msg.set_payload(f"Body of message {idx} with some content to make it realistic.")
        mbox.add(msg)

    mbox.close()

    # Add to database with v1.1 schema fields
    import sqlite3

    conn = sqlite3.connect(str(state_db))
    try:
        for i in range(num_messages):
            idx = offset + i
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr,
                 cc_addr, date, archived_timestamp, archive_file, mbox_offset,
                 mbox_length, body_preview, checksum, size_bytes, labels, account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"gmail{idx}",  # gmail_id
                    f"<msg{idx}@example.com>",  # rfc_message_id
                    f"thread{idx % 100}",  # thread_id (group messages into threads)
                    f"Test Message {idx}",  # subject
                    f"sender{idx}@example.com",  # from_addr
                    "recipient@example.com",  # to_addr
                    None,  # cc_addr
                    f"2024-01-{10 + (idx % 20)}T12:00:00Z",  # date
                    datetime.now().isoformat(),  # archived_timestamp
                    str(path),  # archive_file
                    idx * 200,  # mbox_offset (unique per message)
                    150,  # mbox_length
                    f"Body of message {idx}",  # body_preview
                    f"checksum{idx}",  # checksum
                    150,  # size_bytes
                    "[]",  # labels (empty JSON array)
                    "default",  # account_id
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_consolidate_10k_messages_performance(temp_dir: Path, state_db: Path) -> None:
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
        deduplicate=True,
    )

    # Verify performance target
    assert result.execution_time_ms < 60000, (
        f"Consolidation took {result.execution_time_ms:.0f}ms, expected < 60000ms (60 seconds)"
    )

    # Verify correctness
    assert result.total_messages == 10000
    assert result.messages_consolidated == 10000

    print(
        f"\n✓ Consolidated 10,000 messages in {result.execution_time_ms:.0f}ms "
        f"({result.execution_time_ms / 1000:.2f}s)"
    )


def test_consolidate_1k_messages_quick(temp_dir: Path, state_db: Path) -> None:
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
        deduplicate=True,
    )

    # Verify performance (should be under 10 seconds)
    assert result.execution_time_ms < 10000, (
        f"Consolidation took {result.execution_time_ms:.0f}ms, expected < 10000ms (10 seconds)"
    )

    # Verify correctness
    assert result.total_messages == 1000
    assert result.messages_consolidated == 1000

    print(
        f"\n✓ Consolidated 1,000 messages in {result.execution_time_ms:.0f}ms "
        f"({result.execution_time_ms / 1000:.2f}s)"
    )
