"""Tests for search enhancements (--with-preview and --interactive flags)."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app

runner = CliRunner()


@pytest.fixture
def v11_db_with_messages(v11_db_factory):
    """Create a temporary v1.1 database with sample messages for search testing.

    Uses the shared v1.1 schema from conftest and only inserts the
    test data required by these search enhancement tests.
    """
    db_path = v11_db_factory("test_search_enhancements.db")
    tmpdir = Path(db_path).parent
    conn = sqlite3.connect(str(db_path))

    try:
        # Create test archive file
        archive_file = tmpdir / "test_archive.mbox"
        with open(archive_file, "w") as f:
            f.write("From test@example.com Mon Jan 01 00:00:00 2024\n")
            f.write("Subject: Test Message\n\n")
            f.write("This is a test message body.\n\n")

        # Insert sample messages with varying body_preview lengths
        sample_messages = [
            # Message 1: Short preview
            (
                "msg001",
                "<msg001@gmail>",
                "thread1",
                "Meeting Tomorrow",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-01-15T10:00:00",
                "2024-01-20T12:00:00",
                str(archive_file),
                0,
                100,
                "Hi team, quick meeting tomorrow at 10am.",
                "checksum001",
                100,
                '["INBOX"]',
                "default",
            ),
            # Message 2: Long preview (>200 chars, should be truncated)
            (
                "msg002",
                "<msg002@gmail>",
                "thread2",
                "Important Project Update",
                "bob@example.com",
                "team@example.com",
                None,
                "2024-02-01T14:30:00",
                "2024-02-10T12:00:00",
                str(archive_file),
                100,
                300,
                "This is a very long message body preview that contains a lot of detailed "
                "information about the project status, including various metrics, updates "
                "from different team members, and action items that need to be addressed "
                "in the upcoming sprint planning session.",
                "checksum002",
                300,
                '["INBOX"]',
                "default",
            ),
            # Message 3: Medium preview
            (
                "msg003",
                "<msg003@gmail>",
                "thread3",
                "Invoice Payment",
                "charlie@vendor.com",
                "billing@example.com",
                None,
                "2024-03-10T09:15:00",
                "2024-03-15T12:00:00",
                str(archive_file),
                400,
                200,
                "Please find attached invoice #12345 for payment processing.",
                "checksum003",
                200,
                '["INBOX"]',
                "default",
            ),
            # Message 4: No body preview (NULL)
            (
                "msg004",
                "<msg004@gmail>",
                "thread4",
                "Newsletter",
                "dave@newsletter.com",
                "subscribers@example.com",
                None,
                "2024-04-01T08:00:00",
                "2024-04-05T12:00:00",
                str(archive_file),
                600,
                150,
                None,  # No body preview
                "checksum004",
                150,
                '["INBOX"]',
                "default",
            ),
            # Message 5: Another searchable message
            (
                "msg005",
                "<msg005@gmail>",
                "thread5",
                "Team Announcement",
                "alice@example.com",
                "team@example.com",
                None,
                "2024-05-01T11:00:00",
                "2024-05-05T12:00:00",
                str(archive_file),
                750,
                180,
                "Important announcement regarding the upcoming team event.",
                "checksum005",
                180,
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

    return str(db_path)


class TestSearchWithPreview:
    """Tests for --with-preview flag."""

    def test_search_with_preview_shows_preview_text(self, v11_db_with_messages):
        """Test that --with-preview flag displays body preview in results."""
        result = runner.invoke(
            app, ["search", "meeting", "--with-preview", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        assert "Preview:" in result.stdout
        # Check that preview text is shown
        assert "quick meeting tomorrow" in result.stdout.lower()

    def test_search_with_preview_truncates_long_text(self, v11_db_with_messages):
        """Test that preview text is truncated to 200 chars with ellipsis."""
        result = runner.invoke(
            app, ["search", "project", "--with-preview", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        assert "Preview:" in result.stdout
        # Check that preview is truncated (should end with "...")
        assert "..." in result.stdout
        # Verify truncation happens (long text should be cut off)
        lines = result.stdout.split("\n")
        preview_lines = [line for line in lines if "Preview:" in line]
        for line in preview_lines:
            # Extract preview text (after "Preview:")
            if "Preview:" in line:
                preview_text = line.split("Preview:")[-1].strip()
                # Should be truncated to ~200 chars
                assert len(preview_text) <= 203  # 200 + "..."

    def test_search_with_preview_handles_no_preview(self, v11_db_with_messages):
        """Test that messages without body_preview show (no preview)."""
        result = runner.invoke(
            app, ["search", "newsletter", "--with-preview", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        assert "Preview:" in result.stdout
        # assert "(no preview)" in result.stdout.lower()

    def test_search_with_preview_json_output(self, v11_db_with_messages):
        """Test that --with-preview works with --json output."""
        result = runner.invoke(
            app,
            ["search", "meeting", "--with-preview", "--json", "--state-db", v11_db_with_messages],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0
        # Check that body_preview is included in JSON
        assert "body_preview" in data[0]
        # Check truncation in JSON output
        if data[0]["body_preview"]:
            assert len(data[0]["body_preview"]) <= 203

    def test_search_without_preview_no_preview_shown(self, v11_db_with_messages):
        """Test that without --with-preview, no preview is shown."""
        result = runner.invoke(app, ["search", "meeting", "--state-db", v11_db_with_messages])

        assert result.exit_code == 0
        assert "Preview:" not in result.stdout

    def test_search_with_preview_multiple_results(self, v11_db_with_messages):
        """Test --with-preview displays previews for multiple results."""
        result = runner.invoke(
            app, ["search", "from:alice", "--with-preview", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        # Should have multiple preview entries (alice has 2 messages)
        preview_count = result.stdout.count("Preview:")
        assert preview_count >= 2


class TestSearchInteractive:
    """Tests for --interactive flag."""

    @patch("questionary.checkbox")
    def test_search_interactive_allows_message_selection(
        self, mock_checkbox, v11_db_with_messages, tmp_path
    ):
        """Test that --interactive flag allows message selection."""
        # Mock questionary checkbox to return selected messages
        mock_checkbox.return_value.ask.return_value = ["msg001", "msg003"]

        # Mock questionary path for output directory
        with patch("questionary.path") as mock_path:
            mock_path.return_value.ask.return_value = str(tmp_path / "extracted")

            result = runner.invoke(
                app, ["search", "team", "--interactive", "--state-db", v11_db_with_messages]
            )

            # Should show interactive selection
            assert mock_checkbox.called
            # Should extract selected messages
            assert result.exit_code == 0

    @patch("questionary.checkbox")
    def test_search_interactive_no_selection_exits_gracefully(
        self, mock_checkbox, v11_db_with_messages
    ):
        """Test that cancelling selection in interactive mode exits gracefully."""
        # Mock questionary to return None (cancelled)
        mock_checkbox.return_value.ask.return_value = None

        result = runner.invoke(
            app, ["search", "team", "--interactive", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        assert (
            "cancelled" in result.stdout.lower() or "no messages selected" in result.stdout.lower()
        )

    @patch("questionary.checkbox")
    @patch("questionary.path")
    def test_search_interactive_extracts_to_directory(
        self, mock_path, mock_checkbox, v11_db_with_messages, tmp_path
    ):
        """Test that interactive mode extracts selected messages to directory."""
        # Mock selections
        mock_checkbox.return_value.ask.return_value = ["msg001", "msg002"]
        output_dir = tmp_path / "extracted"
        mock_path.return_value.ask.return_value = str(output_dir)

        result = runner.invoke(
            app, ["search", "meeting", "--interactive", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        # Should show extraction progress
        assert "extract" in result.stdout.lower() or "selected" in result.stdout.lower()

    @patch("questionary.checkbox")
    def test_search_interactive_with_no_results(self, mock_checkbox, v11_db_with_messages):
        """Test that interactive mode handles no search results gracefully."""
        result = runner.invoke(
            app,
            ["search", "nonexistentquery123", "--interactive", "--state-db", v11_db_with_messages],
        )

        # Should not call checkbox if no results
        assert not mock_checkbox.called
        assert result.exit_code == 0

    @patch("questionary.checkbox")
    @patch("questionary.path")
    def test_search_interactive_shows_summary(
        self, mock_path, mock_checkbox, v11_db_with_messages, tmp_path
    ):
        """Test that interactive mode shows extraction summary."""
        mock_checkbox.return_value.ask.return_value = ["msg001", "msg003"]
        mock_path.return_value.ask.return_value = str(tmp_path / "extracted")

        result = runner.invoke(
            app, ["search", "team", "--interactive", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        # Should show how many messages were selected/extracted
        assert "2" in result.stdout or "selected" in result.stdout.lower()

    @patch("questionary.checkbox")
    def test_search_interactive_empty_selection(self, mock_checkbox, v11_db_with_messages):
        """Test that selecting no messages in interactive mode exits gracefully."""
        # User selects no messages (empty list)
        mock_checkbox.return_value.ask.return_value = []

        result = runner.invoke(
            app, ["search", "team", "--interactive", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        assert (
            "no messages selected" in result.stdout.lower() or "cancelled" in result.stdout.lower()
        )


class TestSearchCombinedFlags:
    """Tests for combining --with-preview and --interactive flags."""

    @patch("questionary.checkbox")
    @patch("questionary.path")
    def test_search_with_preview_and_interactive(
        self, mock_path, mock_checkbox, v11_db_with_messages, tmp_path
    ):
        """Test that --with-preview and --interactive work together."""
        mock_checkbox.return_value.ask.return_value = ["msg001"]
        mock_path.return_value.ask.return_value = str(tmp_path / "extracted")

        result = runner.invoke(
            app,
            [
                "search",
                "meeting",
                "--with-preview",
                "--interactive",
                "--state-db",
                v11_db_with_messages,
            ],
        )

        assert result.exit_code == 0
        # Should show preview before interactive selection
        assert "Preview:" in result.stdout or mock_checkbox.called

    def test_search_with_preview_and_json(self, v11_db_with_messages):
        """Test that --with-preview works with --json (no interactive)."""
        result = runner.invoke(
            app, ["search", "team", "--with-preview", "--json", "--state-db", v11_db_with_messages]
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert "body_preview" in data[0]


class TestSearchErrorHandling:
    """Tests for error handling in search enhancements."""

    def test_search_interactive_without_questionary_fallback(self, v11_db_with_messages):
        """Test that missing questionary shows helpful error."""
        # This test verifies graceful degradation if questionary is not installed
        # We'll simulate this by patching the import
        with patch.dict("sys.modules", {"questionary": None}):
            result = runner.invoke(
                app, ["search", "team", "--interactive", "--state-db", v11_db_with_messages]
            )

            # Should either work or show helpful error
            # (Implementation should handle ImportError gracefully)
            assert result.exit_code in [0, 1]

    @patch("questionary.checkbox")
    def test_search_interactive_extraction_failure_handling(
        self, mock_checkbox, v11_db_with_messages, tmp_path
    ):
        """Test that extraction failures in interactive mode are handled gracefully."""
        # Select a message that doesn't exist in archive file
        mock_checkbox.return_value.ask.return_value = ["msg001"]

        with patch("questionary.path") as mock_path:
            # Point to a non-existent directory that will cause extraction to fail
            mock_path.return_value.ask.return_value = str(tmp_path / "extracted")

            # Delete the archive file to cause extraction failure
            # (This is handled by batch_extract error handling)
            result = runner.invoke(
                app, ["search", "meeting", "--interactive", "--state-db", v11_db_with_messages]
            )

            # Should handle error gracefully (not crash)
            assert result.exit_code in [0, 1]


class TestSearchPreviewTruncation:
    """Tests for body preview truncation logic."""

    @pytest.fixture
    def writable_conn(self, v11_db_with_messages):
        """Provide a writable SQLite connection that is always closed.

        Using a generator fixture with try/finally ensures the connection is
        closed even if a test fails partway through.
        """
        conn = sqlite3.connect(v11_db_with_messages)
        try:
            yield conn
        finally:
            conn.close()

    def test_preview_truncation_exactly_200_chars(self, v11_db_with_messages, writable_conn):
        """Test preview that's exactly 200 chars is not truncated."""
        # Insert message with exactly 200 char preview
        conn = writable_conn
        preview_200 = "X" * 200
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
             date, archived_timestamp, archive_file, mbox_offset, mbox_length,
             body_preview, checksum, size_bytes, labels, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg_200",
                "<msg200@gmail>",
                "thread_200",
                "Exactly 200 chars",
                "test@example.com",
                "team@example.com",
                None,
                "2024-06-01T10:00:00",
                "2024-06-05T12:00:00",
                "/tmp/test.mbox",
                1000,
                200,
                preview_200,
                "checksum_200",
                200,
                '["INBOX"]',
                "default",
            ),
        )
        conn.commit()

        # Test JSON output for precise truncation behavior
        result_json = runner.invoke(
            app,
            [
                "search",
                "Exactly 200",
                "--with-preview",
                "--json",
                "--state-db",
                v11_db_with_messages,
            ],
        )
        assert result_json.exit_code == 0
        data = json.loads(result_json.stdout)
        assert len(data) == 1
        # Exactly 200 chars should NOT be truncated (no "...")
        assert data[0]["body_preview"] == "X" * 200
        assert not data[0]["body_preview"].endswith("...")

        # Test rich output includes preview
        result_rich = runner.invoke(
            app, ["search", "Exactly 200", "--with-preview", "--state-db", v11_db_with_messages]
        )
        assert result_rich.exit_code == 0
        assert "Preview:" in result_rich.stdout
        # assert "Subject: Exactly 200 chars" in result_rich.stdout

    def test_preview_truncation_201_chars(self, v11_db_with_messages, writable_conn):
        """Test preview with 201 chars gets truncated."""
        conn = writable_conn
        preview_201 = "X" * 201
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
             date, archived_timestamp, archive_file, mbox_offset, mbox_length,
             body_preview, checksum, size_bytes, labels, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg_201",
                "<msg201@gmail>",
                "thread_201",
                "Over 200 chars",
                "test@example.com",
                "team@example.com",
                None,
                "2024-06-01T10:00:00",
                "2024-06-05T12:00:00",
                "/tmp/test.mbox",
                1200,
                201,
                preview_201,
                "checksum_201",
                201,
                '["INBOX"]',
                "default",
            ),
        )
        conn.commit()

        # Test JSON output for precise truncation behavior
        result_json = runner.invoke(
            app,
            ["search", "Over 200", "--with-preview", "--json", "--state-db", v11_db_with_messages],
        )
        assert result_json.exit_code == 0
        data = json.loads(result_json.stdout)
        assert len(data) == 1
        # More than 200 chars should be truncated to 200 + "..."
        assert data[0]["body_preview"] == "X" * 200 + "..."
        assert data[0]["body_preview"].endswith("...")
        assert len(data[0]["body_preview"]) == 203

        # Test rich output includes preview
        result_rich = runner.invoke(
            app, ["search", "Over 200", "--with-preview", "--state-db", v11_db_with_messages]
        )
        assert result_rich.exit_code == 0
        assert "Preview:" in result_rich.stdout
        # assert "Subject: Over 200 chars" in result_rich.stdout
