"""Tests for DeduplicatorFacade (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.deduplicator.facade import DeduplicatorFacade
from gmailarchiver.data.db_manager import DBManager


@pytest.fixture
def test_db() -> Path:
    """Create test database with duplicates."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(str(db_path))

    # Create v1.1 schema
    conn.execute("""
        CREATE TABLE messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            mbox_offset INTEGER NOT NULL,
            mbox_length INTEGER NOT NULL,
            size_bytes INTEGER,
            archived_timestamp TIMESTAMP
        )
    """)

    # Create schema_version table
    conn.execute("""
        CREATE TABLE schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT
        )
    """)
    conn.execute("INSERT INTO schema_version VALUES ('1.1', datetime('now'))")

    # Insert duplicates
    conn.execute("""
        INSERT INTO messages VALUES
        ('gid1', '<msg1@test>', 'archive1.mbox', 0, 1024, 1024, '2024-01-01T10:00:00')
    """)
    conn.execute("""
        INSERT INTO messages VALUES
        ('gid2', '<msg1@test>', 'archive2.mbox', 0, 1024, 1024, '2024-01-02T10:00:00')
    """)
    conn.execute("""
        INSERT INTO messages VALUES
        ('gid3', '<msg1@test>', 'archive3.mbox', 0, 1024, 1024, '2024-01-03T10:00:00')
    """)

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


@pytest.mark.unit
class TestDeduplicatorFacade:
    """Test DeduplicatorFacade high-level interface."""

    @pytest.mark.asyncio
    async def test_find_duplicates(self, test_db: Path) -> None:
        """Test finding duplicates through facade."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        duplicates = await facade.find_duplicates()

        assert len(duplicates) == 1
        assert "<msg1@test>" in duplicates
        assert len(duplicates["<msg1@test>"]) == 3
        await db.close()

    @pytest.mark.asyncio
    async def test_generate_report(self, test_db: Path) -> None:
        """Test generating deduplication report."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        duplicates = await facade.find_duplicates()
        report = await facade.generate_report(duplicates)

        assert report.total_messages == 3
        assert report.duplicate_message_ids == 1
        assert report.total_duplicate_messages == 3
        assert report.messages_to_remove == 2  # Keep 1, remove 2
        assert report.space_recoverable == 2048  # 2 * 1024
        await db.close()

    @pytest.mark.asyncio
    async def test_deduplicate_dry_run(self, test_db: Path) -> None:
        """Test deduplication in dry-run mode."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        duplicates = await facade.find_duplicates()
        result = await facade.deduplicate(duplicates, strategy="newest", dry_run=True)

        assert result.messages_removed == 2
        assert result.messages_kept == 1
        assert result.space_saved == 2048
        assert result.dry_run is True

        # Verify messages still exist
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 3
        conn.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_deduplicate_actual(self, test_db: Path) -> None:
        """Test actual deduplication (removes from DB)."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        duplicates = await facade.find_duplicates()
        result = await facade.deduplicate(duplicates, strategy="newest", dry_run=False)

        assert result.messages_removed == 2
        assert result.dry_run is False

        # Verify messages were removed
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 1
        # Should keep gid3 (newest)
        cursor = conn.execute("SELECT gmail_id FROM messages")
        assert cursor.fetchone()[0] == "gid3"
        conn.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_deduplicate_largest_strategy(self, test_db: Path) -> None:
        """Test largest strategy."""
        # Update sizes
        conn = sqlite3.connect(str(test_db))
        conn.execute("UPDATE messages SET size_bytes = 512 WHERE gmail_id = 'gid1'")
        conn.execute("UPDATE messages SET size_bytes = 2048 WHERE gmail_id = 'gid2'")
        conn.execute("UPDATE messages SET size_bytes = 1024 WHERE gmail_id = 'gid3'")
        conn.commit()
        conn.close()

        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        duplicates = await facade.find_duplicates()
        result = await facade.deduplicate(duplicates, strategy="largest", dry_run=False)

        # Should keep gid2 (largest)
        conn = sqlite3.connect(str(test_db))
        cursor = conn.execute("SELECT gmail_id FROM messages")
        assert cursor.fetchone()[0] == "gid2"
        conn.close()
        await db.close()

    def test_missing_database_raises(self) -> None:
        """Test that missing database raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            DBManager("/nonexistent/database.db", auto_create=False)

    @pytest.mark.asyncio
    async def test_v10_schema_raises(self) -> None:
        """Test that v1.0 schema raises ValueError."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))
        # Create v1.0 schema (archived_messages table)
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        db = DBManager(str(db_path), validate_schema=False)
        await db.initialize()
        with pytest.raises(ValueError, match="requires v1.1"):
            await DeduplicatorFacade.create(db)

        await db.close()
        db_path.unlink()

    @pytest.mark.asyncio
    async def test_context_manager(self, test_db: Path) -> None:
        """Test context manager protocol."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        async with await DeduplicatorFacade.create(db) as facade:
            duplicates = await facade.find_duplicates()
            assert len(duplicates) == 1

        # Should not raise after closing
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_duplicates_deduplicate(self, test_db: Path) -> None:
        """Test deduplicating empty duplicates dict."""
        db = DBManager(str(test_db), validate_schema=False)
        await db.initialize()
        facade = await DeduplicatorFacade.create(db)

        result = await facade.deduplicate({}, strategy="newest", dry_run=False)

        assert result.messages_removed == 0
        assert result.messages_kept == 0
        assert result.space_saved == 0
        await db.close()
