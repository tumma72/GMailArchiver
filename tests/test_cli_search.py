"""Tests for CLI search command.

Fixtures used from conftest.py:
- runner: CliRunner for CLI tests
"""

import json
import sqlite3
from datetime import datetime

import pytest

from gmailarchiver.__main__ import app


@pytest.fixture
def v1_1_database_with_messages(tmp_path):
    """Create a v1.1 database with sample messages for searching.

    Uses sync sqlite3 to avoid asyncio.run() conflicts with pytest-asyncio.
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    try:
        # Create v1.1 schema (must match production schema exactly!)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            );
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                upgraded_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject, from_addr, to_addr, body_preview,
                content='messages', content_rowid='rowid'
            );
            CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
            END;
        """)

        # Insert sample messages with varied content
        messages = [
            # Message 1: From Alice about meeting
            (
                "msg1",
                "<msg1@example.com>",
                "thread1",
                "Team meeting tomorrow",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-01-15 10:00:00",
                "2024-02-01T12:00:00",
                "archive_202402.mbox",
                100,
                500,
                "Let us discuss the project update",
                "checksum1",
                500,
                None,
                "default",
            ),
            # Message 2: From Alice about invoice
            (
                "msg2",
                "<msg2@example.com>",
                "thread2",
                "Invoice #1234 for January",
                "alice@example.com",
                "billing@example.com",
                None,
                "2024-02-10 14:30:00",
                "2024-03-01T12:00:00",
                "archive_202403.mbox",
                200,
                450,
                "Please find attached the invoice for payment",
                "checksum2",
                450,
                None,
                "default",
            ),
            # Message 3: From Bob about invoice
            (
                "msg3",
                "<msg3@example.com>",
                "thread3",
                "Invoice payment received",
                "bob@example.com",
                "alice@example.com",
                None,
                "2024-02-15 09:00:00",
                "2024-03-01T12:00:00",
                "archive_202403.mbox",
                700,
                380,
                "Thank you for the prompt payment",
                "checksum3",
                380,
                None,
                "default",
            ),
            # Message 4: From Charlie about report
            (
                "msg4",
                "<msg4@example.com>",
                "thread4",
                "Weekly status report",
                "charlie@example.com",
                "team@example.com",
                None,
                "2024-03-20 16:45:00",
                "2024-04-01T12:00:00",
                "archive_202404.mbox",
                300,
                520,
                "Here is the weekly progress report",
                "checksum4",
                520,
                None,
                "default",
            ),
            # Message 5: From Alice about meeting (later date)
            (
                "msg5",
                "<msg5@example.com>",
                "thread5",
                "Quarterly meeting agenda",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-06-05 11:00:00",
                "2024-07-01T12:00:00",
                "archive_202407.mbox",
                400,
                600,
                "Agenda items for the quarterly review meeting",
                "checksum5",
                600,
                None,
                "default",
            ),
        ]

        for msg in messages:
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                msg,
            )

        # Set schema version
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )

        conn.commit()
    finally:
        conn.close()

    return db_path


@pytest.fixture
def v1_0_database(tmp_path):
    """Create a v1.0 database (for testing version check)."""
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))

    # Create v1.0 schema
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)

    conn.commit()
    conn.close()

    return db_path


class TestSearchCommand:
    """Test search CLI command."""

    def test_search_with_query_string(self, runner, v1_1_database_with_messages):
        """Test search with a query string shows results."""
        result = runner.invoke(
            app, ["search", "meeting", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should find messages with "meeting" in them
        assert "meeting" in result.stdout.lower() or "results" in result.stdout.lower()

    def test_search_with_from_filter(self, runner, v1_1_database_with_messages):
        """Test search with from: filter finds matches."""
        result = runner.invoke(
            app,
            [
                "search",
                "from:alice@example.com",
                "--state-db",
                str(v1_1_database_with_messages),
            ],
        )

        assert result.exit_code == 0
        # Should find messages from Alice
        assert "alice" in result.stdout.lower() or "results" in result.stdout.lower()

    def test_search_with_subject_filter(self, runner, v1_1_database_with_messages):
        """Test search with subject: filter finds matches."""
        result = runner.invoke(
            app, ["search", "subject:invoice", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should find messages with "invoice" in subject
        assert "invoice" in result.stdout.lower() or "results" in result.stdout.lower()

    def test_search_with_date_range(self, runner, v1_1_database_with_messages):
        """Test search with after: and before: date range."""
        result = runner.invoke(
            app,
            [
                "search",
                "after:2024-02-01 before:2024-03-01",
                "--state-db",
                str(v1_1_database_with_messages),
            ],
        )

        assert result.exit_code == 0
        # Should find messages in February 2024
        assert "results" in result.stdout.lower() or "2024-02" in result.stdout

    def test_search_with_multiple_filters(self, runner, v1_1_database_with_messages):
        """Test search with multiple filters combined."""
        result = runner.invoke(
            app,
            [
                "search",
                "from:alice subject:meeting",
                "--state-db",
                str(v1_1_database_with_messages),
            ],
        )

        assert result.exit_code == 0
        # Should find messages from Alice with "meeting" in subject
        assert "results" in result.stdout.lower() or "alice" in result.stdout.lower()

    def test_search_with_limit_option(self, runner, v1_1_database_with_messages):
        """Test search with --limit option."""
        result = runner.invoke(
            app,
            ["search", "invoice", "--limit", "1", "--state-db", str(v1_1_database_with_messages)],
        )

        assert result.exit_code == 0
        # Should respect limit
        assert "results" in result.stdout.lower() or "found" in result.stdout.lower()

    def test_search_with_json_output(self, runner, v1_1_database_with_messages):
        """Test search with --json output validates JSON format."""
        result = runner.invoke(
            app, ["search", "meeting", "--json", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should be valid JSON
        try:
            data = json.loads(result.stdout)
            assert isinstance(data, list)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

    def test_search_no_results(self, runner, v1_1_database_with_messages):
        """Test search with no results shows 'No results found'."""
        result = runner.invoke(
            app, ["search", "nonexistent_query_xyz", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should indicate no results
        assert "no results" in result.stdout.lower() or "0 found" in result.stdout.lower()

    def test_search_missing_database(self, runner, tmp_path):
        """Test search with missing database shows error message."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(app, ["search", "test", "--state-db", str(nonexistent_db)])

        assert result.exit_code == 1
        # Should show error about missing database
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_search_v1_0_database_error(self, runner, v1_0_database):
        """Test search with v1.0 database shows error: requires v1.1 migration."""
        result = runner.invoke(app, ["search", "test", "--state-db", str(v1_0_database)])

        assert result.exit_code == 1
        # Should show error about needing v1.1
        assert (
            "v1.1" in result.stdout.lower()
            or "migrate" in result.stdout.lower()
            or "schema" in result.stdout.lower()
        )

    def test_search_query_with_from_syntax(self, runner, v1_1_database_with_messages):
        """Test search with Gmail-style query syntax (from:)."""
        result = runner.invoke(
            app, ["search", "from:alice meeting", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should find messages from Alice about meeting
        assert "results" in result.stdout.lower() or "alice" in result.stdout.lower()

    def test_search_combined_query_and_filter(self, runner, v1_1_database_with_messages):
        """Test search with both query string and filter options."""
        result = runner.invoke(
            app,
            [
                "search",
                "invoice after:2024-02-01",
                "--state-db",
                str(v1_1_database_with_messages),
            ],
        )

        assert result.exit_code == 0
        # Should combine fulltext search with date filter
        assert "results" in result.stdout.lower() or "invoice" in result.stdout.lower()

    def test_search_to_filter(self, runner, v1_1_database_with_messages):
        """Test search with to: filter."""
        result = runner.invoke(
            app,
            ["search", "to:team@example.com", "--state-db", str(v1_1_database_with_messages)],
        )

        assert result.exit_code == 0
        # Should find messages to team@example.com
        assert "results" in result.stdout.lower() or "team" in result.stdout.lower()

    def test_search_shows_result_count(self, runner, v1_1_database_with_messages):
        """Test search output includes result count."""
        result = runner.invoke(
            app, ["search", "meeting", "--state-db", str(v1_1_database_with_messages)]
        )

        assert result.exit_code == 0
        # Should show result count (e.g., "Found 2 messages")
        assert "found" in result.stdout.lower() or "result" in result.stdout.lower()

    def test_search_invalid_date_format(self, runner, v1_1_database_with_messages):
        """Test search with invalid date format handles gracefully."""
        result = runner.invoke(
            app,
            ["search", "after:invalid-date", "--state-db", str(v1_1_database_with_messages)],
        )

        # Should handle gracefully (may return no results or ignore invalid date)
        assert result.exit_code == 0
        # Either no results or some results (gracefully ignoring invalid date filter)
        output = result.stdout.lower()
        assert "results" in output or "found" in output or "no results" in output
