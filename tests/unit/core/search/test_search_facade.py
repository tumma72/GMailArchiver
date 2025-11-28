"""Tests for SearchFacade (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.search.facade import SearchFacade


@pytest.fixture
def test_db() -> Path:
    """Create test database with messages."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(str(db_path))

    # Create messages table
    conn.execute("""
        CREATE TABLE messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            date TIMESTAMP,
            body_preview TEXT,
            archive_file TEXT,
            mbox_offset INTEGER
        )
    """)

    # Create FTS5 virtual table
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject, from_addr, to_addr, body_preview,
            content=messages,
            content_rowid=rowid
        )
    """)

    # Insert test data
    conn.execute("""
        INSERT INTO messages VALUES
        ('msg1', '<msg1@test>', 'Meeting Tomorrow', 'alice@test.com',
         'bob@test.com', '2024-01-01', 'Meeting at 10am', 'archive.mbox', 0)
    """)
    conn.execute("""
        INSERT INTO messages VALUES
        ('msg2', '<msg2@test>', 'Invoice #12345', 'vendor@test.com',
         'billing@test.com', '2024-01-02', 'Payment due', 'archive.mbox', 1024)
    """)
    conn.execute("""
        INSERT INTO messages VALUES
        ('msg3', '<msg3@test>', 'Project Update', 'alice@test.com',
         'team@test.com', '2024-01-03', 'Status report', 'archive.mbox', 2048)
    """)

    # Sync FTS index
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


class TestSearchFacade:
    """Test SearchFacade high-level interface."""

    def test_search_gmail_style_query(self, test_db: Path) -> None:
        """Test Gmail-style query parsing and execution."""
        facade = SearchFacade(str(test_db))

        results = facade.search("from:alice meeting")

        assert results.total_results >= 1
        assert any("Meeting" in r.subject for r in results.results)
        assert all("alice" in r.from_addr for r in results.results)

    def test_search_fulltext_only(self, test_db: Path) -> None:
        """Test fulltext search."""
        facade = SearchFacade(str(test_db))

        results = facade.search("invoice")

        assert results.total_results == 1
        assert results.results[0].subject == "Invoice #12345"

    def test_search_metadata_only(self, test_db: Path) -> None:
        """Test metadata-only search."""
        facade = SearchFacade(str(test_db))

        results = facade.search("from:alice")

        assert results.total_results == 2
        assert all("alice" in r.from_addr for r in results.results)

    def test_search_with_limit(self, test_db: Path) -> None:
        """Test limit parameter."""
        facade = SearchFacade(str(test_db))

        results = facade.search("from:alice", limit=1)

        assert results.total_results == 1
        assert len(results.results) == 1

    def test_search_tracks_execution_time(self, test_db: Path) -> None:
        """Test that execution time is tracked."""
        facade = SearchFacade(str(test_db))

        results = facade.search("meeting")

        assert results.execution_time_ms > 0

    def test_context_manager(self, test_db: Path) -> None:
        """Test context manager protocol."""
        with SearchFacade(str(test_db)) as facade:
            results = facade.search("meeting")
            assert results.total_results >= 1

        # Should not raise after closing
        # (facade.search would fail if called here)

    def test_missing_database_raises(self) -> None:
        """Test that missing database raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            SearchFacade("/nonexistent/database.db")

    def test_search_fulltext_direct(self, test_db: Path) -> None:
        """Test direct fulltext search method."""
        facade = SearchFacade(str(test_db))

        results = facade.search_fulltext("meeting")

        assert results.total_results >= 1
        assert any("Meeting" in r.subject for r in results.results)

    def test_search_metadata_direct(self, test_db: Path) -> None:
        """Test direct metadata search method."""
        facade = SearchFacade(str(test_db))

        results = facade.search_metadata(from_addr="alice")

        assert results.total_results == 2
        assert all("alice" in r.from_addr for r in results.results)

    def test_search_metadata_date_filters(self, test_db: Path) -> None:
        """Test metadata search with date filters."""
        facade = SearchFacade(str(test_db))

        results = facade.search_metadata(after="2024-01-02", before="2024-01-04")

        assert results.total_results == 2  # msg2 and msg3
        assert all(r.date >= "2024-01-02" for r in results.results)
