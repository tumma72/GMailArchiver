"""Tests for search executor module (TDD)."""

import sqlite3
from collections.abc import AsyncGenerator

import pytest

from gmailarchiver.core.search._executor import SearchExecutor
from gmailarchiver.core.search._parser import QueryParams
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage


@pytest.fixture
def test_db(v11_db_factory) -> str:
    """Create test database with FTS5 support using v1.1 schema."""
    db_path = v11_db_factory("test_search_executor.db")

    # Add test data
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO messages
        (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
         date, archived_timestamp, archive_file, mbox_offset, mbox_length,
         body_preview, checksum, size_bytes, labels, account_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg1",
            "<msg1@test>",
            "thread1",
            "Meeting Tomorrow",
            "alice@test.com",
            "bob@test.com",
            None,
            "2024-01-01",
            "2024-01-01T12:00:00",
            "archive.mbox",
            0,
            1024,
            "Meeting at 10am",
            "checksum1",
            1024,
            '["INBOX"]',
            "default",
        ),
    )
    conn.execute(
        """
        INSERT INTO messages
        (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
         date, archived_timestamp, archive_file, mbox_offset, mbox_length,
         body_preview, checksum, size_bytes, labels, account_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg2",
            "<msg2@test>",
            "thread2",
            "Invoice",
            "vendor@test.com",
            "billing@test.com",
            None,
            "2024-01-02",
            "2024-01-02T12:00:00",
            "archive.mbox",
            1024,
            2048,
            "Invoice #12345",
            "checksum2",
            2048,
            '["INBOX"]',
            "default",
        ),
    )
    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
async def storage(test_db: str) -> AsyncGenerator[HybridStorage]:
    """Create HybridStorage for test database.

    Uses async fixture to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    db_manager = DBManager(test_db, validate_schema=False)
    await db_manager.initialize()
    storage = HybridStorage(db_manager, preload_rfc_ids=False)

    yield storage

    # Cleanup
    await db_manager.close()


@pytest.mark.unit
class TestSearchExecutor:
    """Test search execution."""

    @pytest.mark.asyncio
    async def test_execute_fulltext_search(self, storage: HybridStorage) -> None:
        """Test executing fulltext search."""
        executor = SearchExecutor(storage)
        params = QueryParams(
            fulltext_terms=["meeting"], fts_query="meeting", original_query="meeting"
        )

        results = await executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert len(results.results) == 1
        assert results.results[0].gmail_id == "msg1"
        assert results.results[0].subject == "Meeting Tomorrow"

    @pytest.mark.asyncio
    async def test_execute_metadata_search(self, storage: HybridStorage) -> None:
        """Test executing metadata-only search."""
        executor = SearchExecutor(storage)
        params = QueryParams(
            fulltext_terms=[],
            fts_query="",
            original_query="from:alice",
            from_addr="alice",
        )

        results = await executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert results.results[0].from_addr == "alice@test.com"

    @pytest.mark.asyncio
    async def test_execute_hybrid_search(self, storage: HybridStorage) -> None:
        """Test executing hybrid FTS + metadata search."""
        executor = SearchExecutor(storage)
        params = QueryParams(
            fulltext_terms=["invoice"],
            fts_query="invoice",
            original_query="from:vendor invoice",
            from_addr="vendor",
        )

        results = await executor.execute(params, limit=100, offset=0)

        assert results.total_results == 1
        assert results.results[0].subject == "Invoice"
        assert "vendor" in results.results[0].from_addr

    @pytest.mark.asyncio
    async def test_execute_with_limit(self, storage: HybridStorage) -> None:
        """Test limit parameter - total_results shows actual count, results respects limit."""
        executor = SearchExecutor(storage)
        params = QueryParams(fulltext_terms=[], fts_query="", original_query="")

        results = await executor.execute(params, limit=1, offset=0)

        # total_results shows the actual total count in database (2 messages)
        assert results.total_results == 2
        # But only 1 result returned due to limit
        assert len(results.results) == 1

    @pytest.mark.asyncio
    async def test_execute_tracks_time(self, storage: HybridStorage) -> None:
        """Test that execution time is tracked."""
        executor = SearchExecutor(storage)
        params = QueryParams(
            fulltext_terms=["meeting"], fts_query="meeting", original_query="meeting"
        )

        results = await executor.execute(params, limit=100, offset=0)

        assert results.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_execute_invalid_fts_query(self, storage: HybridStorage) -> None:
        """Test handling of invalid FTS query."""
        executor = SearchExecutor(storage)
        params = QueryParams(
            fulltext_terms=["invalid:query"],
            fts_query="invalid:query",
            original_query="invalid:query",
        )

        # Should return empty results rather than crash
        results = await executor.execute(params, limit=100, offset=0)

        assert results.total_results == 0
        assert len(results.results) == 0
