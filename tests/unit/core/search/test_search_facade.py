"""Tests for SearchFacade (TDD)."""

import sqlite3

import pytest

from gmailarchiver.core.search.facade import SearchFacade


@pytest.fixture
def test_db(v11_db_factory) -> str:
    """Create test database with messages using v1.1 schema."""
    db_path = v11_db_factory("test_search_facade.db")

    # Insert test data
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
            "Invoice #12345",
            "vendor@test.com",
            "billing@test.com",
            None,
            "2024-01-02",
            "2024-01-02T12:00:00",
            "archive.mbox",
            1024,
            2048,
            "Payment due",
            "checksum2",
            2048,
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
            "msg3",
            "<msg3@test>",
            "thread3",
            "Project Update",
            "alice@test.com",
            "team@test.com",
            None,
            "2024-01-03",
            "2024-01-03T12:00:00",
            "archive.mbox",
            2048,
            1024,
            "Status report",
            "checksum3",
            1024,
            '["INBOX"]',
            "default",
        ),
    )
    conn.commit()
    conn.close()

    return db_path


@pytest.mark.unit
class TestSearchFacade:
    """Test SearchFacade high-level interface."""

    @pytest.mark.asyncio
    async def test_search_gmail_style_query(self, test_db: str) -> None:
        """Test Gmail-style query parsing and execution."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search("from:alice meeting")

        assert results.total_results >= 1
        assert any("Meeting" in r.subject for r in results.results)
        assert all("alice" in r.from_addr for r in results.results)
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_fulltext_only(self, test_db: str) -> None:
        """Test fulltext search."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search("invoice")

        assert results.total_results == 1
        assert results.results[0].subject == "Invoice #12345"
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_metadata_only(self, test_db: str) -> None:
        """Test metadata-only search."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search("from:alice")

        assert results.total_results == 2
        assert all("alice" in r.from_addr for r in results.results)
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_with_limit(self, test_db: str) -> None:
        """Test limit parameter - total_results shows actual count, results respects limit."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search("from:alice", limit=1)

        # total_results shows the actual total (2 messages from alice)
        assert results.total_results == 2
        # But only 1 result returned due to limit
        assert len(results.results) == 1
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_tracks_execution_time(self, test_db: str) -> None:
        """Test that execution time is tracked."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search("meeting")

        assert results.execution_time_ms > 0
        await facade.close()

    @pytest.mark.asyncio
    async def test_context_manager(self, test_db: str) -> None:
        """Test context manager protocol."""
        async with await SearchFacade.create(test_db) as facade:
            results = await facade.search("meeting")
            assert results.total_results >= 1

        # Should not raise after closing
        # (facade.search would fail if called here)

    @pytest.mark.asyncio
    async def test_missing_database_raises(self) -> None:
        """Test that missing database raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await SearchFacade.create("/nonexistent/database.db")

    @pytest.mark.asyncio
    async def test_search_fulltext_direct(self, test_db: str) -> None:
        """Test direct fulltext search method."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search_fulltext("meeting")

        assert results.total_results >= 1
        assert any("Meeting" in r.subject for r in results.results)
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_metadata_direct(self, test_db: str) -> None:
        """Test direct metadata search method."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search_metadata(from_addr="alice")

        assert results.total_results == 2
        assert all("alice" in r.from_addr for r in results.results)
        await facade.close()

    @pytest.mark.asyncio
    async def test_search_metadata_date_filters(self, test_db: str) -> None:
        """Test metadata search with date filters."""
        facade = await SearchFacade.create(test_db)

        results = await facade.search_metadata(after="2024-01-02", before="2024-01-04")

        assert results.total_results == 2  # msg2 and msg3
        assert all(r.date >= "2024-01-02" for r in results.results)
        await facade.close()
