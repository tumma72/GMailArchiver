"""Tests for cli.widgets re-export module (deprecated)."""

from gmailarchiver.cli.widgets import (
    ErrorPanel,
    ProgressSummary,
    ReportCard,
    SuggestionList,
)


class TestWidgetsDeprecatedImports:
    """Tests for backward compatibility imports from cli.widgets."""

    def test_report_card_imported(self) -> None:
        """ReportCard is available for import."""
        card = ReportCard("Test")
        assert card.title == "Test"
        assert hasattr(card, "add_field")
        assert hasattr(card, "render")

    def test_suggestion_list_imported(self) -> None:
        """SuggestionList is available for import."""
        suggestions = SuggestionList()
        assert hasattr(suggestions, "add")
        assert hasattr(suggestions, "render")
        assert hasattr(suggestions, "to_list")

    def test_error_panel_imported(self) -> None:
        """ErrorPanel is available for import."""
        error = ErrorPanel("Error", "Message")
        assert error.title == "Error"
        assert error.message == "Message"
        assert hasattr(error, "add_detail")
        assert hasattr(error, "render")

    def test_progress_summary_imported(self) -> None:
        """ProgressSummary is available for import."""
        summary = ProgressSummary("Summary")
        assert summary.title == "Summary"
        assert hasattr(summary, "add_stat")
        assert hasattr(summary, "render")

    def test_all_symbols_exported(self) -> None:
        """All expected symbols are in module __all__."""
        from gmailarchiver import cli

        assert hasattr(cli.widgets, "__all__")
        all_symbols = cli.widgets.__all__
        assert "ReportCard" in all_symbols
        assert "SuggestionList" in all_symbols
        assert "ErrorPanel" in all_symbols
        assert "ProgressSummary" in all_symbols

    def test_widget_classes_have_expected_methods(self) -> None:
        """Widget classes have expected public methods."""
        # ReportCard
        assert hasattr(ReportCard, "add_field")
        assert hasattr(ReportCard, "add_conditional_field")
        assert hasattr(ReportCard, "set_summary")
        assert hasattr(ReportCard, "render")

        # SuggestionList
        assert hasattr(SuggestionList, "add")
        assert hasattr(SuggestionList, "add_conditional")
        assert hasattr(SuggestionList, "is_empty")
        assert hasattr(SuggestionList, "render")

        # ErrorPanel
        assert hasattr(ErrorPanel, "add_detail")
        assert hasattr(ErrorPanel, "add_details")
        assert hasattr(ErrorPanel, "set_suggestion")
        assert hasattr(ErrorPanel, "render")

        # ProgressSummary
        assert hasattr(ProgressSummary, "add_stat")
        assert hasattr(ProgressSummary, "add_conditional_stat")
        assert hasattr(ProgressSummary, "render")
