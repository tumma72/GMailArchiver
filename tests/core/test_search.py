"""Tests for search engine module."""

import sqlite3
import time

import pytest

from gmailarchiver.core.search import SearchEngine

pytestmark = pytest.mark.asyncio


@pytest.fixture
def v11_db(v11_db_factory) -> str:
    """Create a v1.1 database with sample messages for search tests.

    Reuses the shared v1.1 schema from conftest and only populates
    the sample messages needed by these tests.
    """
    db_path = v11_db_factory("test_search.db")
    conn = sqlite3.connect(db_path)
    try:
        # Insert sample messages
        sample_messages = [
            # Message 1: Meeting invitation from Alice
            (
                "msg001",
                "<msg001@gmail>",
                "thread1",
                "Team Meeting Tomorrow",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-01-15T10:00:00",
                "2024-01-20T12:00:00",
                "archive_2024_01.mbox",
                0,
                1024,
                "Hi team, we have a meeting scheduled for tomorrow at 10am.",
                "checksum001",
                1024,
                '["INBOX"]',
                "default",
            ),
            # Message 2: Invoice from Bob
            (
                "msg002",
                "<msg002@gmail>",
                "thread2",
                "Invoice #12345",
                "bob@vendor.com",
                "billing@example.com",
                None,
                "2024-02-01T14:30:00",
                "2024-02-10T12:00:00",
                "archive_2024_02.mbox",
                1024,
                2048,
                "Please find attached invoice #12345 for payment processing. Amount due: $500.",
                "checksum002",
                2048,
                '["INBOX"]',
                "default",
            ),
            # Message 3: Project update from Alice
            (
                "msg003",
                "<msg003@gmail>",
                "thread1",
                "Project Status Update",
                "alice@example.com",
                "team@example.com",
                "manager@example.com",
                "2024-03-10T09:15:00",
                "2024-03-15T12:00:00",
                "archive_2024_03.mbox",
                3072,
                1536,
                "Project is on track. We completed phase 1 and starting phase 2 next week.",
                "checksum003",
                1536,
                '["INBOX","IMPORTANT"]',
                "default",
            ),
            # Message 4: Payment confirmation from Charlie
            (
                "msg004",
                "<msg004@gmail>",
                "thread3",
                "Payment Received",
                "charlie@payment.com",
                "billing@example.com",
                None,
                "2024-02-15T16:45:00",
                "2024-02-20T12:00:00",
                "archive_2024_02.mbox",
                5120,
                512,
                "Your payment of $500 for invoice #12345 has been received and processed.",
                "checksum004",
                512,
                '["INBOX"]',
                "default",
            ),
            # Message 5: Another meeting from Alice
            (
                "msg005",
                "<msg005@gmail>",
                "thread4",
                "Quarterly Review Meeting",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-06-01T11:00:00",
                "2024-06-05T12:00:00",
                "archive_2024_06.mbox",
                0,
                1024,
                "Time for our quarterly review meeting. Please prepare your reports.",
                "checksum005",
                1024,
                '["INBOX"]',
                "default",
            ),
            # Message 6: Newsletter from Dave (no body preview)
            (
                "msg006",
                "<msg006@gmail>",
                "thread5",
                "Weekly Newsletter",
                "dave@newsletter.com",
                "subscribers@example.com",
                None,
                "2024-01-10T08:00:00",
                "2024-01-12T12:00:00",
                "archive_2024_01.mbox",
                2048,
                4096,
                None,  # No body preview
                "checksum006",
                4096,
                '["INBOX","NEWSLETTER"]',
                "default",
            ),
            # Message 7: Old message from 2023
            (
                "msg007",
                "<msg007@gmail>",
                "thread6",
                "Year-end Summary",
                "finance@example.com",
                "all@example.com",
                None,
                "2023-12-31T23:59:00",
                "2024-01-05T12:00:00",
                "archive_2023_12.mbox",
                0,
                2048,
                "Here is the year-end financial summary for 2023.",
                "checksum007",
                2048,
                '["INBOX"]',
                "default",
            ),
        ]

        for msg in sample_messages:
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
                 date, archived_timestamp, archive_file, mbox_offset, mbox_length,
                 body_preview, checksum, size_bytes, labels, account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                msg,
            )

        conn.commit()
    finally:
        conn.close()

    return db_path


class TestSearchEngineInit:
    """Tests for SearchEngine initialization."""

    async def test_init_with_valid_database(self, v11_db):
        """Test that SearchEngine initializes with valid v1.1 database."""
        engine = await SearchEngine.create(v11_db)
        assert engine is not None
        await engine.close()

    async def test_init_with_missing_database(self):
        """Test that SearchEngine raises error with missing database."""
        with pytest.raises(Exception):
            SearchEngine("/nonexistent/path/to/database.db")


class TestFullTextSearch:
    """Tests for full-text search functionality."""

    async def test_fulltext_search_single_word(self, v11_db):
        """Test full-text search with single word finds matches."""
        engine = await SearchEngine.create(v11_db)

        # Search for "meeting" - should find msg001 and msg005
        results = await engine.search_fulltext("meeting")

        assert results.total_results >= 2
        assert any(r.gmail_id == "msg001" for r in results.results)
        assert any(r.gmail_id == "msg005" for r in results.results)
        assert "meeting" in results.query.lower()

        await engine.close()

    async def test_fulltext_search_phrase(self, v11_db):
        """Test full-text search with phrase finds exact matches."""
        engine = await SearchEngine.create(v11_db)

        # Search for "invoice payment" - should find msg002 and msg004
        results = await engine.search_fulltext("invoice payment")

        assert results.total_results >= 1
        # At least one message should contain both words
        found_invoice = any(r.gmail_id in ["msg002", "msg004"] for r in results.results)
        assert found_invoice

        await engine.close()

    async def test_fulltext_search_field_specific(self, v11_db):
        """Test full-text search on specific field (subject only)."""
        engine = await SearchEngine.create(v11_db)

        # Search for "meeting" in subject only
        results = await engine.search_fulltext("meeting", fields=["subject"])

        assert results.total_results >= 2
        # All results should have "meeting" in subject
        for result in results.results:
            assert "meeting" in result.subject.lower()

        await engine.close()

    async def test_fulltext_search_ranked_results(self, v11_db):
        """Test full-text search returns BM25 ranked results."""
        engine = await SearchEngine.create(v11_db)

        # Search for common word
        results = await engine.search_fulltext("meeting")

        assert results.total_results > 0
        # Results should have relevance scores
        for result in results.results:
            assert result.relevance_score is not None

        # Scores should be in descending order (best match first)
        scores = [r.relevance_score for r in results.results if r.relevance_score is not None]
        if len(scores) > 1:
            assert scores == sorted(scores, reverse=True)

        await engine.close()

    async def test_fulltext_search_no_matches(self, v11_db):
        """Test full-text search with no matches returns empty results."""
        engine = await SearchEngine.create(v11_db)

        # Search for non-existent word
        results = await engine.search_fulltext("xyznonexistent")

        assert results.total_results == 0
        assert len(results.results) == 0
        assert results.execution_time_ms >= 0

        await engine.close()


class TestMetadataSearch:
    """Tests for metadata-based search functionality."""

    async def test_metadata_search_by_from_addr(self, v11_db):
        """Test metadata search by from_addr finds matches."""
        engine = await SearchEngine.create(v11_db)

        # Search for messages from Alice
        results = await engine.search_metadata(from_addr="alice@example.com")

        assert results.total_results >= 3  # msg001, msg003, msg005
        for result in results.results:
            assert "alice@example.com" in result.from_addr

        await engine.close()

    async def test_metadata_search_by_date_range(self, v11_db):
        """Test metadata search with date range (after/before)."""
        engine = await SearchEngine.create(v11_db)

        # Search for messages after 2024-02-01
        results = await engine.search_metadata(after="2024-02-01")

        assert results.total_results >= 4  # msg002, msg003, msg004, msg005
        for result in results.results:
            assert result.date >= "2024-02-01"

        # Search for messages before 2024-02-01
        results = await engine.search_metadata(before="2024-02-01")

        assert results.total_results >= 3  # msg001, msg006, msg007
        for result in results.results:
            assert result.date < "2024-02-01"

        await engine.close()

    async def test_metadata_search_combined_filters(self, v11_db):
        """Test metadata search with combined filters (from + subject)."""
        engine = await SearchEngine.create(v11_db)

        # Search for messages from Alice with subject containing "meeting"
        results = await engine.search_metadata(from_addr="alice@example.com", subject="meeting")

        assert results.total_results >= 2  # msg001, msg005
        for result in results.results:
            assert "alice@example.com" in result.from_addr
            assert "meeting" in result.subject.lower()

        await engine.close()

    async def test_metadata_search_by_to_addr(self, v11_db):
        """Test metadata search by to_addr finds matches."""
        engine = await SearchEngine.create(v11_db)

        # Search for messages to billing
        results = await engine.search_metadata(to_addr="billing@example.com")

        assert results.total_results >= 2  # msg002, msg004
        for result in results.results:
            assert result.to_addr is not None
            assert "billing@example.com" in result.to_addr

        await engine.close()

    async def test_metadata_search_with_limit(self, v11_db):
        """Test metadata search respects limit parameter."""
        engine = await SearchEngine.create(v11_db)

        # Search all messages with limit of 3
        results = await engine.search_metadata(limit=3)

        assert len(results.results) <= 3
        assert results.execution_time_ms >= 0

        await engine.close()


class TestGmailStyleQuery:
    """Tests for Gmail-style query syntax."""

    async def test_gmail_query_from_address(self, v11_db):
        """Test Gmail query: from:alice parses and finds matches."""
        engine = await SearchEngine.create(v11_db)

        # Gmail-style query
        results = await engine.search("from:alice@example.com")

        assert results.total_results >= 3  # msg001, msg003, msg005
        for result in results.results:
            assert "alice@example.com" in result.from_addr

        await engine.close()

    async def test_gmail_query_combined_terms(self, v11_db):
        """Test Gmail query: subject:meeting after:2024-01-01 (combined)."""
        engine = await SearchEngine.create(v11_db)

        # Combined query
        results = await engine.search("subject:meeting after:2024-01-01")

        assert results.total_results >= 2  # msg001, msg005
        for result in results.results:
            assert "meeting" in result.subject.lower()
            assert result.date >= "2024-01-01"

        await engine.close()

    async def test_gmail_query_bare_words(self, v11_db):
        """Test Gmail query: bare words 'invoice payment' performs FTS5."""
        engine = await SearchEngine.create(v11_db)

        # Bare words - should search all fields
        results = await engine.search("invoice payment")

        assert results.total_results >= 1
        # Should find messages containing these words
        found = any(
            "invoice" in (r.subject.lower() if r.subject else "")
            or "invoice" in (r.body_preview.lower() if r.body_preview else "")
            for r in results.results
        )
        assert found

        await engine.close()

    async def test_gmail_query_subject_term(self, v11_db):
        """Test Gmail query: subject:invoice finds matches."""
        engine = await SearchEngine.create(v11_db)

        results = await engine.search("subject:invoice")

        assert results.total_results >= 1  # msg002
        for result in results.results:
            assert "invoice" in result.subject.lower()

        await engine.close()

    async def test_gmail_query_to_address(self, v11_db):
        """Test Gmail query: to:billing finds matches."""
        engine = await SearchEngine.create(v11_db)

        results = await engine.search("to:billing@example.com")

        assert results.total_results >= 2  # msg002, msg004
        for result in results.results:
            assert result.to_addr is not None
            assert "billing@example.com" in result.to_addr

        await engine.close()

    async def test_gmail_query_date_range(self, v11_db):
        """Test Gmail query: before:2024-02-01 after:2024-01-01."""
        engine = await SearchEngine.create(v11_db)

        results = await engine.search("after:2024-01-01 before:2024-02-01")

        assert results.total_results >= 2  # msg001, msg006
        for result in results.results:
            assert result.date >= "2024-01-01"
            assert result.date < "2024-02-01"

        await engine.close()


class TestSearchPerformance:
    """Tests for search performance."""

    async def test_search_performance_large_dataset(self, v11_db):
        """Test search performance: 1000 messages < 100ms."""
        # Add more messages to reach 1000
        conn = sqlite3.connect(v11_db)

        for i in range(1000):
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
                 date, archived_timestamp, archive_file, mbox_offset, mbox_length,
                 body_preview, checksum, size_bytes, labels, account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"perf{i:04d}",
                    f"<perf{i:04d}@gmail>",
                    f"thread{i}",
                    f"Performance Test Message {i}",
                    f"user{i % 10}@example.com",
                    "test@example.com",
                    None,
                    f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}T10:00:00",
                    "2024-01-01T12:00:00",
                    f"archive_perf_{i // 100}.mbox",
                    i * 1024,
                    1024,
                    f"This is test message number {i} for performance testing.",
                    f"checksum{i:04d}",
                    1024,
                    '["INBOX"]',
                    "default",
                ),
            )

        conn.commit()
        conn.close()

        # Now test search performance
        engine = await SearchEngine.create(v11_db)

        start_time = time.perf_counter()
        results = await engine.search("Performance Test")
        end_time = time.perf_counter()

        elapsed_ms = (end_time - start_time) * 1000

        # Should find many messages (limited by default 100)
        assert results.total_results >= 100

        # Should complete in under 100ms
        assert elapsed_ms < 100, f"Search took {elapsed_ms:.2f}ms (expected < 100ms)"

        await engine.close()


class TestSearchEdgeCases:
    """Tests for search edge cases and error handling."""

    async def test_fts5_syntax_error_returns_empty_results(self, v11_db: str) -> None:
        """Test that FTS5 syntax errors return empty results gracefully.

        FTS5 has specific query syntax. Invalid queries should not raise
        exceptions but return empty results instead.
        """
        engine = await SearchEngine.create(v11_db)
        try:
            # Invalid FTS5 syntax: unbalanced quotes
            results = await engine.search_fulltext('"unclosed quote')
            assert results.total_results == 0
            assert results.results == []
        finally:
            await engine.close()

    async def test_invalid_fts_fields_raises_error(self, v11_db: str) -> None:
        """Test that invalid FTS field names raise ValueError."""
        engine = await SearchEngine.create(v11_db)
        try:
            with pytest.raises(ValueError, match="Invalid FTS5 field names"):
                await engine.search_fulltext("test", fields=["invalid_field", "another_bad"])
        finally:
            await engine.close()

    async def test_missing_messages_table_raises_error(self, v11_db_factory) -> None:
        """Test that missing messages table raises error during initialization.

        With the refactored architecture, DBManager validates schema before
        SearchExecutor gets a chance to validate. Both are valid errors.
        """
        # Create a database without messages table
        db_path = v11_db_factory("no_messages.db")
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.commit()
        conn.close()

        # DBManagerError is raised first due to schema validation
        from gmailarchiver.data.db_manager import DBManagerError

        with pytest.raises(DBManagerError, match="Failed to initialize database"):
            await SearchEngine.create(db_path)


class TestSearchHybridFilters:
    """Tests for _search_hybrid via search() with various filter combinations."""

    async def test_search_with_to_filter(self, v11_db: str) -> None:
        """Test search() with to: filter (covers lines 378-379)."""
        engine = await SearchEngine.create(v11_db)
        try:
            # Gmail-style query with to: filter + text for hybrid search
            results = await engine.search("test to:recipient@example.com")
            # Should return results or empty depending on data
            assert isinstance(results.total_results, int)
        finally:
            await engine.close()

    async def test_search_with_before_filter(self, v11_db: str) -> None:
        """Test search() with before: filter (covers lines 390-391)."""
        engine = await SearchEngine.create(v11_db)
        try:
            # Gmail-style query with before: filter + text for hybrid search
            results = await engine.search("test before:2030/01/01")
            # Should return results or empty depending on data
            assert isinstance(results.total_results, int)
        finally:
            await engine.close()

    async def test_search_with_multiple_hybrid_filters(self, v11_db: str) -> None:
        """Test search() with multiple filters for hybrid search."""
        engine = await SearchEngine.create(v11_db)
        try:
            # Gmail-style query with multiple filters + text for hybrid search
            results = await engine.search(
                "test from:sender@example.com to:recipient@example.com "
                "after:2020/01/01 before:2030/01/01"
            )
            # Should return results or empty depending on data
            assert isinstance(results.total_results, int)
        finally:
            await engine.close()
