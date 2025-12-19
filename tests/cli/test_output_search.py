"""Tests for search result rendering methods in _output_search module."""

from unittest.mock import MagicMock

import pytest

from gmailarchiver.cli._output_search import (
    _truncate_preview,
    display_search_results_json,
    display_search_results_rich,
)
from gmailarchiver.core.search._types import MessageSearchResult

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_output_manager() -> MagicMock:
    """Create a mock OutputManager instance."""
    mgr = MagicMock()
    mgr.json_mode = False
    mgr.quiet = False
    return mgr


@pytest.fixture
def sample_search_result() -> MessageSearchResult:
    """Create a sample search result."""
    return MessageSearchResult(
        gmail_id="msg123",
        rfc_message_id="<test@example.com>",
        subject="Test Message",
        from_addr="sender@example.com",
        to_addr="recipient@example.com",
        date="2024-01-01T00:00:00",
        body_preview="This is a test message body with some content.",
        archive_file="/path/to/archive.mbox",
        mbox_offset=0,
        relevance_score=0.95,
    )


@pytest.fixture
def sample_search_result_no_preview() -> MessageSearchResult:
    """Create a search result with no preview."""
    return MessageSearchResult(
        gmail_id="msg456",
        rfc_message_id="<no_preview@example.com>",
        subject="No Preview Message",
        from_addr="sender@example.com",
        to_addr="recipient@example.com",
        date="2024-01-02T00:00:00",
        body_preview=None,
        archive_file="/path/to/archive.mbox",
        mbox_offset=100,
        relevance_score=0.85,
    )


@pytest.fixture
def sample_search_result_no_subject() -> MessageSearchResult:
    """Create a search result with no subject."""
    return MessageSearchResult(
        gmail_id="msg789",
        rfc_message_id="<no_subject@example.com>",
        subject=None,
        from_addr="sender@example.com",
        to_addr="recipient@example.com",
        date="2024-01-03T00:00:00",
        body_preview="Message without subject",
        archive_file="/path/to/archive.mbox",
        mbox_offset=200,
        relevance_score=0.75,
    )


@pytest.fixture
def long_preview_text() -> str:
    """Create a long preview text for truncation testing."""
    return "A" * 300  # Longer than default max_length of 200


# ============================================================================
# Tests for _truncate_preview()
# ============================================================================


class TestTruncatePreview:
    """Tests for the _truncate_preview function."""

    def test_truncate_preview_none_returns_no_preview(self) -> None:
        """Test that None input returns '(no preview)'."""
        result = _truncate_preview(None)
        assert result == "(no preview)"

    def test_truncate_preview_empty_string_returns_no_preview(self) -> None:
        """Test that empty string returns '(no preview)'."""
        result = _truncate_preview("")
        assert result == "(no preview)"

    def test_truncate_preview_whitespace_only_returns_empty_string(self) -> None:
        """Test that whitespace-only string after strip returns empty string."""
        # The initial check `if not preview:` passes because whitespace is truthy,
        # but after strip() the result is an empty string
        result = _truncate_preview("   \n\t  ")
        assert result == ""

    def test_truncate_preview_short_text_returned_unchanged(self) -> None:
        """Test that short text is returned as-is."""
        text = "Short preview"
        result = _truncate_preview(text)
        assert result == text

    def test_truncate_preview_text_at_max_length_unchanged(self) -> None:
        """Test that text at max_length is returned unchanged."""
        text = "A" * 200  # Exactly max_length
        result = _truncate_preview(text)
        assert result == text

    def test_truncate_preview_long_text_truncated_with_ellipsis(
        self, long_preview_text: str
    ) -> None:
        """Test that long text is truncated with ellipsis."""
        result = _truncate_preview(long_preview_text)
        assert len(result) == 203  # 200 chars + "..."
        assert result.endswith("...")
        assert result == "A" * 200 + "..."

    def test_truncate_preview_custom_max_length(self) -> None:
        """Test truncation with custom max_length."""
        text = "A" * 100
        result = _truncate_preview(text, max_length=50)
        assert result == "A" * 50 + "..."
        assert len(result) == 53

    def test_truncate_preview_strips_whitespace(self) -> None:
        """Test that whitespace is stripped before truncation."""
        text = "  Test message  "
        result = _truncate_preview(text)
        assert result == "Test message"

    def test_truncate_preview_preserves_internal_whitespace(self) -> None:
        """Test that internal whitespace is preserved."""
        text = "Test  message  with   spaces"
        result = _truncate_preview(text)
        assert result == text

    def test_truncate_preview_multiline_text_truncated(self) -> None:
        """Test that multiline text is truncated correctly."""
        text = "Line 1\nLine 2\n" + "A" * 250
        result = _truncate_preview(text)
        assert len(result) <= 203
        assert result.endswith("...")


# ============================================================================
# Tests for display_search_results_json()
# ============================================================================


class TestDisplaySearchResultsJson:
    """Tests for the display_search_results_json function."""

    def test_display_search_results_json_empty_results(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test JSON output with empty results list."""
        display_search_results_json(mock_output_manager, [])

        mock_output_manager.set_json_payload.assert_called_once_with([])

    def test_display_search_results_json_single_result(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test JSON output with a single result."""
        display_search_results_json(mock_output_manager, [sample_search_result])

        mock_output_manager.set_json_payload.assert_called_once()
        payload = mock_output_manager.set_json_payload.call_args[0][0]
        assert len(payload) == 1
        assert payload[0]["gmail_id"] == "msg123"
        assert payload[0]["rfc_message_id"] == "<test@example.com>"
        assert payload[0]["subject"] == "Test Message"
        assert payload[0]["from"] == "sender@example.com"
        assert payload[0]["to"] == "recipient@example.com"
        assert payload[0]["archive_file"] == "/path/to/archive.mbox"
        assert payload[0]["mbox_offset"] == 0
        assert payload[0]["relevance_score"] == 0.95

    def test_display_search_results_json_without_preview(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test JSON output without preview field."""
        display_search_results_json(mock_output_manager, [sample_search_result], with_preview=False)

        payload = mock_output_manager.set_json_payload.call_args[0][0]
        assert "body_preview" not in payload[0]

    def test_display_search_results_json_with_preview(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test JSON output with preview field included."""
        display_search_results_json(mock_output_manager, [sample_search_result], with_preview=True)

        payload = mock_output_manager.set_json_payload.call_args[0][0]
        assert "body_preview" in payload[0]
        assert payload[0]["body_preview"] == sample_search_result.body_preview

    def test_display_search_results_json_preview_truncation(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test that preview is truncated in JSON output."""
        long_result = MessageSearchResult(
            gmail_id="msg_long",
            rfc_message_id="<long@example.com>",
            subject="Long Preview",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            date="2024-01-01T00:00:00",
            body_preview="A" * 300,  # Longer than max
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.95,
        )

        display_search_results_json(mock_output_manager, [long_result], with_preview=True)

        payload = mock_output_manager.set_json_payload.call_args[0][0]
        preview = payload[0]["body_preview"]
        assert preview.endswith("...")
        assert len(preview) <= 203

    def test_display_search_results_json_no_preview_for_none(
        self,
        mock_output_manager: MagicMock,
        sample_search_result_no_preview: MessageSearchResult,
    ) -> None:
        """Test JSON output with None preview results in '(no preview)'."""
        display_search_results_json(
            mock_output_manager, [sample_search_result_no_preview], with_preview=True
        )

        payload = mock_output_manager.set_json_payload.call_args[0][0]
        assert payload[0]["body_preview"] == "(no preview)"

    def test_display_search_results_json_multiple_results(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
        sample_search_result_no_preview: MessageSearchResult,
    ) -> None:
        """Test JSON output with multiple results."""
        results = [sample_search_result, sample_search_result_no_preview]
        display_search_results_json(mock_output_manager, results)

        payload = mock_output_manager.set_json_payload.call_args[0][0]
        assert len(payload) == 2
        assert payload[0]["gmail_id"] == "msg123"
        assert payload[1]["gmail_id"] == "msg456"

    def test_display_search_results_json_includes_all_required_fields(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test that all required fields are included in JSON output."""
        display_search_results_json(mock_output_manager, [sample_search_result])

        payload = mock_output_manager.set_json_payload.call_args[0][0][0]
        required_fields = {
            "gmail_id",
            "rfc_message_id",
            "date",
            "from",
            "to",
            "subject",
            "archive_file",
            "mbox_offset",
            "relevance_score",
        }
        assert required_fields.issubset(payload.keys())


# ============================================================================
# Tests for display_search_results_rich()
# ============================================================================


class TestDisplaySearchResultsRich:
    """Tests for the display_search_results_rich function."""

    def test_display_search_results_rich_json_mode_returns_early(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that JSON mode returns without output."""
        mock_output_manager.json_mode = True
        display_search_results_rich(mock_output_manager, [sample_search_result], total_results=1)

        mock_output_manager.info.assert_not_called()
        mock_output_manager.warning.assert_not_called()
        mock_output_manager.show_smart_table.assert_not_called()

    def test_display_search_results_rich_quiet_mode_returns_early(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that quiet mode returns without output."""
        mock_output_manager.quiet = True
        display_search_results_rich(mock_output_manager, [sample_search_result], total_results=1)

        mock_output_manager.info.assert_not_called()
        mock_output_manager.warning.assert_not_called()
        mock_output_manager.show_smart_table.assert_not_called()

    def test_display_search_results_rich_empty_results_shows_warning(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that empty results shows warning."""
        display_search_results_rich(mock_output_manager, [], total_results=0)

        mock_output_manager.warning.assert_called_once_with("No results found")

    def test_display_search_results_rich_empty_results_returns_after_warning(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that no further output after warning for empty results."""
        display_search_results_rich(mock_output_manager, [], total_results=0)

        mock_output_manager.info.assert_not_called()
        mock_output_manager.show_smart_table.assert_not_called()

    def test_display_search_results_rich_with_preview_list_format(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test list format when preview is enabled."""
        display_search_results_rich(
            mock_output_manager, [sample_search_result], total_results=1, with_preview=True
        )

        # Should call info multiple times (header, then details for each result)
        assert mock_output_manager.info.call_count >= 7
        # Should NOT use table format
        mock_output_manager.show_smart_table.assert_not_called()

    def test_display_search_results_rich_with_preview_header(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that preview format includes search results header."""
        display_search_results_rich(
            mock_output_manager, [sample_search_result], total_results=5, with_preview=True
        )

        calls = mock_output_manager.info.call_args_list
        # First info call should have the header
        assert any("Search Results (5 found)" in str(call_args) for call_args in calls)

    def test_display_search_results_rich_with_preview_displays_all_fields(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that preview format displays all result fields."""
        display_search_results_rich(
            mock_output_manager, [sample_search_result], total_results=1, with_preview=True
        )

        call_args_str = str(mock_output_manager.info.call_args_list)
        # Check that key information is displayed
        assert "Subject:" in call_args_str
        assert "From:" in call_args_str
        assert "Date:" in call_args_str
        assert "RFC Message-ID:" in call_args_str
        assert "Gmail ID:" in call_args_str
        assert "Archive:" in call_args_str
        assert "Preview:" in call_args_str

    def test_display_search_results_rich_with_preview_no_subject_shows_placeholder(
        self,
        mock_output_manager: MagicMock,
        sample_search_result_no_subject: MessageSearchResult,
    ) -> None:
        """Test that missing subject is shown as placeholder."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result_no_subject],
            total_results=1,
            with_preview=True,
        )

        call_args_str = str(mock_output_manager.info.call_args_list)
        assert "(no subject)" in call_args_str

    def test_display_search_results_rich_without_preview_table_format(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test table format when preview is disabled."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=1,
            with_preview=False,
        )

        # Should call show_smart_table
        mock_output_manager.show_smart_table.assert_called_once()

    def test_display_search_results_rich_without_preview_no_info_calls(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that info is not called when using table format."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=1,
            with_preview=False,
        )

        # Table format should not use info()
        mock_output_manager.info.assert_not_called()

    def test_display_search_results_rich_table_format_title(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test that table includes proper title."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=42,
            with_preview=False,
        )

        args = mock_output_manager.show_smart_table.call_args
        title = args[0][0]
        assert "Search Results (42 found)" in title

    def test_display_search_results_rich_table_format_column_specs(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test that table has correct column specifications."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=1,
            with_preview=False,
        )

        args = mock_output_manager.show_smart_table.call_args
        column_specs = args[0][1]
        headers = [spec["header"] for spec in column_specs]

        assert "RFC Message-ID" in headers
        assert "Date" in headers
        assert "From" in headers
        assert "Subject" in headers
        assert "Archive" in headers

    def test_display_search_results_rich_table_format_row_data(
        self, mock_output_manager: MagicMock, sample_search_result: MessageSearchResult
    ) -> None:
        """Test that table contains correct row data."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=1,
            with_preview=False,
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        assert len(rows) == 1
        # Row should have: rfc_message_id, date, from, subject, archive_file
        assert "<test@example.com>" in rows[0][0]
        assert "2024-01-01T00:00:00" in rows[0][1]
        assert "sender@example.com" in rows[0][2]
        assert "Test Message" in rows[0][3]
        assert "archive.mbox" in rows[0][4]

    def test_display_search_results_rich_table_format_missing_subject(
        self,
        mock_output_manager: MagicMock,
        sample_search_result_no_subject: MessageSearchResult,
    ) -> None:
        """Test that missing subject shows placeholder in table."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result_no_subject],
            total_results=1,
            with_preview=False,
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        # Subject column (index 3) should have placeholder
        assert "(no subject)" in rows[0][3]

    def test_display_search_results_rich_table_format_missing_message_id(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that missing rfc_message_id shows placeholder in table."""
        result = MessageSearchResult(
            gmail_id="msg_no_id",
            rfc_message_id=None,  # type: ignore
            subject="Test",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            date="2024-01-01T00:00:00",
            body_preview="preview",
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.9,
        )

        display_search_results_rich(
            mock_output_manager, [result], total_results=1, with_preview=False
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        # RFC Message-ID column (index 0) should have placeholder
        assert "(no id)" in rows[0][0]

    def test_display_search_results_rich_table_format_missing_date(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that missing date shows placeholder in table."""
        result = MessageSearchResult(
            gmail_id="msg_no_date",
            rfc_message_id="<test@example.com>",
            subject="Test",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            date=None,  # type: ignore
            body_preview="preview",
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.9,
        )

        display_search_results_rich(
            mock_output_manager, [result], total_results=1, with_preview=False
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        # Date column (index 1) should have N/A
        assert "N/A" in rows[0][1]

    def test_display_search_results_rich_table_extracts_archive_basename(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that archive column shows just filename, not full path."""
        display_search_results_rich(
            mock_output_manager,
            [sample_search_result],
            total_results=1,
            with_preview=False,
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        # Archive column (index 4) should be just the filename
        assert rows[0][4] == "archive.mbox"
        assert "/" not in rows[0][4]

    def test_display_search_results_rich_with_multiple_results_list_format(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
        sample_search_result_no_preview: MessageSearchResult,
    ) -> None:
        """Test list format with multiple results."""
        results = [sample_search_result, sample_search_result_no_preview]
        display_search_results_rich(
            mock_output_manager, results, total_results=2, with_preview=True
        )

        # Should have info calls for both results
        assert mock_output_manager.info.call_count > 1

    def test_display_search_results_rich_with_multiple_results_table_format(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
        sample_search_result_no_preview: MessageSearchResult,
    ) -> None:
        """Test table format with multiple results."""
        results = [sample_search_result, sample_search_result_no_preview]
        display_search_results_rich(
            mock_output_manager, results, total_results=2, with_preview=False
        )

        args = mock_output_manager.show_smart_table.call_args
        rows = args[0][2]

        assert len(rows) == 2
        assert rows[0][0] == "<test@example.com>"
        assert rows[1][0] == "<no_preview@example.com>"

    def test_display_search_results_rich_with_preview_numbered_entries(
        self,
        mock_output_manager: MagicMock,
        sample_search_result: MessageSearchResult,
    ) -> None:
        """Test that list format numbers entries."""
        display_search_results_rich(
            mock_output_manager, [sample_search_result], total_results=1, with_preview=True
        )

        call_args_str = str(mock_output_manager.info.call_args_list)
        # First entry should be numbered as "1."
        assert "1." in call_args_str

    def test_display_search_results_rich_with_preview_empty_from_handled(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that empty from_addr is handled in list format."""
        result = MessageSearchResult(
            gmail_id="msg_no_from",
            rfc_message_id="<test@example.com>",
            subject="Test",
            from_addr="",  # Empty from
            to_addr="recipient@example.com",
            date="2024-01-01T00:00:00",
            body_preview="preview",
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.9,
        )

        display_search_results_rich(
            mock_output_manager, [result], total_results=1, with_preview=True
        )

        mock_output_manager.info.assert_called()

    def test_display_search_results_rich_with_preview_no_gmail_id_handled(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that missing gmail_id is handled in list format."""
        result = MessageSearchResult(
            gmail_id=None,  # type: ignore
            rfc_message_id="<test@example.com>",
            subject="Test",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            date="2024-01-01T00:00:00",
            body_preview="preview",
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.9,
        )

        display_search_results_rich(
            mock_output_manager, [result], total_results=1, with_preview=True
        )

        call_args_str = str(mock_output_manager.info.call_args_list)
        assert "N/A" in call_args_str

    def test_display_search_results_rich_with_preview_missing_date_handled(
        self, mock_output_manager: MagicMock
    ) -> None:
        """Test that missing date is handled in list format."""
        result = MessageSearchResult(
            gmail_id="msg_no_date",
            rfc_message_id="<test@example.com>",
            subject="Test",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            date=None,  # type: ignore
            body_preview="preview",
            archive_file="/path/to/archive.mbox",
            mbox_offset=0,
            relevance_score=0.9,
        )

        display_search_results_rich(
            mock_output_manager, [result], total_results=1, with_preview=True
        )

        call_args_str = str(mock_output_manager.info.call_args_list)
        assert "N/A" in call_args_str
