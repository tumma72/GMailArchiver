"""Tests for search executor module (TDD)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gmailarchiver.core.search._executor import SearchExecutor
from gmailarchiver.core.search._parser import QueryParams


@pytest.fixture
def test_db() -> Path:
    """Create test database with FTS5 support."""
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
        ('msg2', '<msg2@test>', 'Invoice', 'vendor@test.com',
         'billing@test.com', '2024-01-02', 'Invoice #12345', 'archive.mbox', 1024)
    """)

    # Sync FTS index
    conn.execute("""
        INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')
    """)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink()


class TestSearchExecutor:
    """Test search execution."""

    def test_execute_fulltext_search(self, test_db: Path) -> None:
        """Test executing fulltext search."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(
            fulltext_terms=["meeting"], fts_query="meeting", original_query="meeting"
        )

        results = executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert len(results.results) == 1
        assert results.results[0].gmail_id == "msg1"
        assert results.results[0].subject == "Meeting Tomorrow"

    def test_execute_metadata_search(self, test_db: Path) -> None:
        """Test executing metadata-only search."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(
            fulltext_terms=[],
            fts_query="",
            original_query="from:alice",
            from_addr="alice",
        )

        results = executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert results.results[0].from_addr == "alice@test.com"

    def test_execute_hybrid_search(self, test_db: Path) -> None:
        """Test executing hybrid FTS + metadata search."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(
            fulltext_terms=["invoice"],
            fts_query="invoice",
            original_query="from:vendor invoice",
            from_addr="vendor",
        )

        results = executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert results.results[0].subject == "Invoice"
        assert "vendor" in results.results[0].from_addr

    def test_execute_with_limit(self, test_db: Path) -> None:
        """Test limit parameter."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(fulltext_terms=[], fts_query="", original_query="")

        results = executor.execute(params, limit=1, offset=0)

        assert results.total_results == 1
        assert len(results.results) == 1

    def test_execute_tracks_time(self, test_db: Path) -> None:
        """Test that execution time is tracked."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(
            fulltext_terms=["meeting"], fts_query="meeting", original_query="meeting"
        )

        results = executor.execute(params, limit=100, offset=0)

        assert results.execution_time_ms > 0

    def test_execute_invalid_fts_query(self, test_db: Path) -> None:
        """Test handling of invalid FTS query."""
        executor = SearchExecutor(str(test_db))
        params = QueryParams(
            fulltext_terms=["invalid:query"],
            fts_query="invalid:query",
            original_query="invalid:query",
        )

        # Should return empty results rather than crash
        results = executor.execute(params, limit=100, offset=0)

        assert results.total_results == 0
        assert len(results.results) == 0
