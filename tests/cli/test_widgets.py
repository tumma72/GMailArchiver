"""Tests for CLI widgets."""

from unittest.mock import MagicMock

from gmailarchiver.cli.ui import (
    ErrorPanel,
    ProgressSummary,
    ReportCard,
    SuggestionList,
)


class TestReportCard:
    """Tests for ReportCard widget."""

    def test_add_field(self) -> None:
        """add_field adds field to report."""
        card = ReportCard("Test Report")
        card.add_field("Label", "Value")
        assert card.to_dict() == {"Label": "Value"}

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        card = ReportCard("Test").add_field("A", "1").add_field("B", "2").add_field("C", "3")
        assert len(card.to_dict()) == 3

    def test_add_conditional_field_true(self) -> None:
        """add_conditional_field adds field when condition is True."""
        card = ReportCard("Test")
        card.add_conditional_field(True, "Shown", "yes")
        assert "Shown" in card.to_dict()

    def test_add_conditional_field_false(self) -> None:
        """add_conditional_field skips field when condition is False."""
        card = ReportCard("Test")
        card.add_conditional_field(False, "Hidden", "no")
        assert "Hidden" not in card.to_dict()

    def test_set_summary(self) -> None:
        """set_summary stores summary text."""
        card = ReportCard("Test").set_summary("Summary line")
        assert card._summary == "Summary line"

    def test_to_dict_preserves_order(self) -> None:
        """to_dict returns fields in order added."""
        card = ReportCard("Test").add_field("First", "1").add_field("Second", "2")
        keys = list(card.to_dict().keys())
        assert keys == ["First", "Second"]

    def test_render_calls_show_report(self) -> None:
        """render calls OutputManager.show_report."""
        card = ReportCard("My Report").add_field("Key", "Value")
        mock_output = MagicMock()
        card.render(mock_output)
        mock_output.show_report.assert_called_once_with("My Report", {"Key": "Value"}, None)

    def test_render_with_summary(self) -> None:
        """render passes summary wrapped in dict to show_report."""
        card = ReportCard("Report").set_summary("Done!")
        mock_output = MagicMock()
        card.render(mock_output)
        mock_output.show_report.assert_called_once_with("Report", {}, {"summary": "Done!"})


class TestSuggestionList:
    """Tests for SuggestionList widget."""

    def test_add_suggestion(self) -> None:
        """add adds suggestion to list."""
        suggestions = SuggestionList()
        suggestions.add("Run command A")
        assert suggestions.to_list() == ["Run command A"]

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        suggestions = SuggestionList().add("First").add("Second")
        assert len(suggestions.to_list()) == 2

    def test_add_conditional_true(self) -> None:
        """add_conditional adds suggestion when condition is True."""
        suggestions = SuggestionList()
        suggestions.add_conditional(True, "Shown")
        assert "Shown" in suggestions.to_list()

    def test_add_conditional_false(self) -> None:
        """add_conditional skips suggestion when condition is False."""
        suggestions = SuggestionList()
        suggestions.add_conditional(False, "Hidden")
        assert "Hidden" not in suggestions.to_list()

    def test_is_empty_true(self) -> None:
        """is_empty returns True when no suggestions."""
        suggestions = SuggestionList()
        assert suggestions.is_empty() is True

    def test_is_empty_false(self) -> None:
        """is_empty returns False when suggestions exist."""
        suggestions = SuggestionList().add("Something")
        assert suggestions.is_empty() is False

    def test_render_calls_suggest_next_steps(self) -> None:
        """render calls OutputManager.suggest_next_steps."""
        suggestions = SuggestionList().add("Do this")
        mock_output = MagicMock()
        suggestions.render(mock_output)
        mock_output.suggest_next_steps.assert_called_once_with(["Do this"])

    def test_render_empty_does_not_call(self) -> None:
        """render does nothing when list is empty."""
        suggestions = SuggestionList()
        mock_output = MagicMock()
        suggestions.render(mock_output)
        mock_output.suggest_next_steps.assert_not_called()


class TestErrorPanel:
    """Tests for ErrorPanel widget."""

    def test_basic_error(self) -> None:
        """ErrorPanel stores title and message."""
        error = ErrorPanel("Error Title", "Error message")
        assert error.title == "Error Title"
        assert error.message == "Error message"

    def test_add_detail(self) -> None:
        """add_detail adds to details list."""
        error = ErrorPanel("Error", "Message")
        error.add_detail("Detail 1")
        assert error._details == ["Detail 1"]

    def test_add_details(self) -> None:
        """add_details adds multiple details."""
        error = ErrorPanel("Error", "Message")
        error.add_details(["D1", "D2", "D3"])
        assert error._details == ["D1", "D2", "D3"]

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        error = ErrorPanel("Error", "Message").add_detail("Detail").set_suggestion("Fix it")
        assert len(error._details) == 1
        assert error._suggestion == "Fix it"

    def test_set_suggestion(self) -> None:
        """set_suggestion stores suggestion."""
        error = ErrorPanel("Error", "Message")
        error.set_suggestion("Try this instead")
        assert error._suggestion == "Try this instead"

    def test_render_calls_show_error_panel(self) -> None:
        """render calls OutputManager.show_error_panel."""
        error = ErrorPanel("Title", "Message").add_detail("Detail").set_suggestion("Suggestion")
        mock_output = MagicMock()
        error.render(mock_output)
        mock_output.show_error_panel.assert_called_once_with(
            title="Title",
            message="Message",
            details=["Detail"],
            suggestion="Suggestion",
        )

    def test_render_without_details(self) -> None:
        """render passes None for empty details."""
        error = ErrorPanel("Title", "Message")
        mock_output = MagicMock()
        error.render(mock_output)
        mock_output.show_error_panel.assert_called_once_with(
            title="Title",
            message="Message",
            details=None,
            suggestion=None,
        )


class TestProgressSummary:
    """Tests for ProgressSummary widget."""

    def test_add_stat(self) -> None:
        """add_stat adds statistic."""
        summary = ProgressSummary("Summary")
        summary.add_stat("Imported", 100)
        assert len(summary._stats) == 1

    def test_fluent_chaining(self) -> None:
        """Methods return self for fluent chaining."""
        summary = ProgressSummary("Summary").add_stat("A", 1).add_stat("B", 2)
        assert len(summary._stats) == 2

    def test_add_conditional_stat_true(self) -> None:
        """add_conditional_stat adds stat when condition is True."""
        summary = ProgressSummary("Summary")
        summary.add_conditional_stat(True, "Shown", 10)
        assert len(summary._stats) == 1

    def test_add_conditional_stat_false(self) -> None:
        """add_conditional_stat skips stat when condition is False."""
        summary = ProgressSummary("Summary")
        summary.add_conditional_stat(False, "Hidden", 0)
        assert len(summary._stats) == 0

    def test_to_report_card(self) -> None:
        """to_report_card converts to ReportCard."""
        summary = ProgressSummary("Summary").add_stat("Count", 42)
        card = summary.to_report_card()
        assert card.title == "Summary"
        assert "Count" in card.to_dict()
        assert "42" in card.to_dict()["Count"]

    def test_render_calls_show_report(self) -> None:
        """render uses ReportCard to call show_report."""
        summary = ProgressSummary("Summary").add_stat("Items", 10)
        mock_output = MagicMock()
        summary.render(mock_output)
        mock_output.show_report.assert_called_once()
        call_args = mock_output.show_report.call_args
        assert call_args[0][0] == "Summary"  # title
        assert "Items" in call_args[0][1]  # data dict


class TestWidgetIntegration:
    """Integration tests for widget composition."""

    def test_report_with_suggestions(self) -> None:
        """ReportCard and SuggestionList can be used together."""
        mock_output = MagicMock()

        # Build and render report
        report = ReportCard("Import Results").add_field("Imported", "100").add_field("Skipped", "5")
        report.render(mock_output)

        # Build and render suggestions
        suggestions = (
            SuggestionList()
            .add("Search: gmailarchiver search 'query'")
            .add_conditional(True, "Status: gmailarchiver status")
        )
        suggestions.render(mock_output)

        assert mock_output.show_report.called
        assert mock_output.suggest_next_steps.called

    def test_conditional_workflow(self) -> None:
        """Widgets handle conditional content correctly."""
        imported = 100
        skipped = 0
        errors: list[str] = []

        report = (
            ReportCard("Results")
            .add_field("Imported", f"{imported:,}")
            .add_conditional_field(skipped > 0, "Skipped", f"{skipped:,}")
        )

        suggestions = (
            SuggestionList().add("View status").add_conditional(len(errors) > 0, "Fix errors")
        )

        # Should only have "Imported" field
        assert "Skipped" not in report.to_dict()

        # Should only have "View status" suggestion
        assert len(suggestions.to_list()) == 1
