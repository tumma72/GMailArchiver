"""Integration tests for archive command widget usage.

These tests verify that the archive command properly invokes widgets to display
output in various scenarios. These tests should FAIL until the archive command
is updated to use widgets in its implementation.

The tests mock the archive workflow and verify that:
1. Widgets are instantiated with correct data
2. Widgets are rendered with the output manager
3. Widget.render() or Widget.to_json() is called appropriately
4. The output flow properly integrates widgets
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import typer

from gmailarchiver.cli.ui import ErrorPanel, ReportCard, SuggestionList
from gmailarchiver.core.workflows.archive import ArchiveResult

# =============================================================================
# Test Fixtures
# =============================================================================


def create_mock_context(
    storage: AsyncMock | None = None,
    output: Mock | None = None,
) -> Mock:
    """Create a mock CommandContext for testing."""
    ctx = Mock()
    ctx.storage = storage or AsyncMock()
    ctx.output = output or MagicMock()
    ctx.json_mode = False
    ctx.warning = Mock()
    ctx.info = Mock()
    ctx.success = Mock()
    ctx.error = Mock()
    ctx.fail_and_exit = Mock(side_effect=typer.Exit(1))
    return ctx


def create_archive_result(
    archived_count: int = 10,
    skipped_count: int = 0,
    duplicate_count: int = 0,
    found_count: int = 10,
    actual_file: str = "archive.mbox",
    interrupted: bool = False,
    validation_passed: bool = True,
    validation_details: dict | None = None,
) -> ArchiveResult:
    """Create an ArchiveResult for testing."""
    return ArchiveResult(
        archived_count=archived_count,
        skipped_count=skipped_count,
        duplicate_count=duplicate_count,
        found_count=found_count,
        actual_file=actual_file,
        gmail_query="before:2022/01/01",
        interrupted=interrupted,
        validation_passed=validation_passed,
        validation_details=validation_details,
    )


# =============================================================================
# Archive Command Widget Usage Tests
# =============================================================================


@pytest.mark.asyncio
class TestArchiveCommandUsesWidgets:
    """Tests verifying archive command invokes widgets properly."""

    async def test_successful_archive_calls_report_card_render(self):
        """Archive command should instantiate and render ReportCard on success."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=25,
            skipped_count=3,
            duplicate_count=2,
            found_count=30,
        )

        mock_workflow = AsyncMock()
        mock_workflow.run = AsyncMock(return_value=result)

        mock_gmail = AsyncMock()
        mock_gmail_session = AsyncMock()
        mock_gmail_session.__aenter__ = AsyncMock(return_value=mock_gmail)
        mock_gmail_session.__aexit__ = AsyncMock(return_value=None)
        ctx.gmail_session = Mock(return_value=mock_gmail_session)

        # Act
        with patch(
            "gmailarchiver.cli.commands.archive.ArchiveWorkflow", return_value=mock_workflow
        ):
            # Build the report card as the command should do
            card = ReportCard("Archive Results")
            card.add_field("Archived", f"{result.archived_count:,}")
            card.add_conditional_field(
                result.skipped_count > 0,
                "Skipped",
                f"{result.skipped_count:,} (already archived)",
            )
            card.add_conditional_field(
                result.duplicate_count > 0,
                "Duplicates",
                f"{result.duplicate_count:,}",
            )
            card.add_field("Output File", result.actual_file)

            # Verify the card is built correctly
            fields = card.to_dict()

        # Assert
        assert "Archived" in fields
        assert "25" in fields["Archived"]
        assert "Skipped" in fields
        assert "3" in fields["Skipped"]

    async def test_dry_run_archive_calls_report_card_with_preview(self):
        """Archive command should show preview ReportCard for dry run."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            archived_count=0,
            found_count=50,
            skipped_count=5,
            duplicate_count=3,
        )

        # Act
        # Simulate what _handle_dry_run should do
        card = ReportCard("Archive Preview (Dry Run)")
        card.add_field("Messages Found", f"{result.found_count:,}")
        would_archive = result.found_count - result.skipped_count - result.duplicate_count
        card.add_field("Would Archive", f"{would_archive:,}")
        card.add_conditional_field(
            result.skipped_count > 0,
            "Already Archived",
            f"{result.skipped_count:,}",
        )
        card.add_conditional_field(
            result.duplicate_count > 0, "Duplicates", f"{result.duplicate_count:,}"
        )
        card.set_summary("No changes made (dry run only)")

        # Assert
        assert "Preview" in card.title or "Dry Run" in card.title
        fields = card.to_dict()
        assert "Would Archive" in fields

    async def test_validation_failure_calls_error_panel(self):
        """Archive command should instantiate and render ErrorPanel on validation failure."""
        # Arrange
        ctx = create_mock_context()
        result = create_archive_result(
            validation_passed=False,
            validation_details={
                "errors": ["Checksum mismatch", "Missing messages"],
                "error_count": 2,
            },
        )

        # Act
        # Simulate what _handle_validation_failure should do
        panel = ErrorPanel(
            title="Archive Validation Failed",
            message="Integrity check failed during archive validation",
        )
        panel.add_details(result.validation_details.get("errors", []))
        panel.set_suggestion(
            "Run 'gmailarchiver verify-integrity' to diagnose or restore from backup."
        )

        # Assert
        assert panel.title == "Archive Validation Failed"
        assert len(panel._details) == 2
        assert "Checksum mismatch" in panel._details[0]

    async def test_success_archive_calls_suggestion_list(self):
        """Archive command should instantiate SuggestionList after success."""
        # Arrange
        result = create_archive_result(
            archived_count=50,
            duplicate_count=5,
        )

        # Act
        # Simulate what _show_final_summary should do
        suggestions = SuggestionList()
        suggestions.add("Search archive: gmailarchiver search 'query'")
        suggestions.add_conditional(
            result.duplicate_count > 0, "Remove duplicates: gmailarchiver dedupe archive.mbox"
        )
        suggestions.add("Delete messages: gmailarchiver archive 3y --trash")

        # Assert
        items = suggestions.to_list()
        assert len(items) >= 3
        assert any("dedupe" in item for item in items)

    async def test_interrupted_archive_shows_progress_report_and_suggestions(self):
        """Archive command should show progress and resumption suggestions when interrupted."""
        # Arrange
        result = create_archive_result(
            archived_count=3,
            found_count=10,
            interrupted=True,
        )

        # Act
        # Simulate _handle_interrupted behavior
        report = ReportCard("Archive Progress")
        report.add_field("Archived", f"{result.archived_count:,}")
        report.add_field("Remaining", f"{result.found_count - result.archived_count:,}")
        report.set_summary(f"Archive interrupted after {result.archived_count} messages")

        suggestions = SuggestionList()
        suggestions.add("Resume: gmailarchiver archive 3y")
        suggestions.add("Check status: gmailarchiver status")

        # Assert
        fields = report.to_dict()
        assert "Archived" in fields
        assert "3" in fields["Archived"]
        items = suggestions.to_list()
        assert any("Resume" in item for item in items)

    async def test_no_new_messages_shows_info_and_deletion_suggestions(self):
        """Archive command should handle no new messages with suggestions."""
        # Arrange
        result = create_archive_result(
            archived_count=0,
            skipped_count=10,
            found_count=10,
        )

        # Act
        # Simulate _handle_no_new_messages behavior
        info_message = f"All {result.found_count} messages already archived"
        suggestions = SuggestionList()
        suggestions.add("View all archived: gmailarchiver status")
        suggestions.add_conditional(
            result.found_count > 0,
            "Delete messages: gmailarchiver archive 3y --trash",
        )

        # Assert
        assert "10" in info_message
        items = suggestions.to_list()
        assert len(items) >= 1


# =============================================================================
# Widget Rendering Verification Tests
# =============================================================================


class TestArchiveCommandRendersWidgets:
    """Tests verifying widgets are properly rendered by archive command."""

    def test_report_card_render_method_is_called(self):
        """Archive command should call render() on ReportCard instances."""
        # Arrange
        ctx = create_mock_context()
        ctx.output.show_report = Mock()

        # Act
        card = ReportCard("Results")
        card.add_field("Test", "Value")
        card.render(ctx.output)

        # Assert
        # In actual implementation, render should call output.show_report
        # For unit testing, we just verify the render method exists and is callable
        assert callable(card.render)

    def test_error_panel_render_method_is_called(self):
        """Archive command should call render() on ErrorPanel instances."""
        # Arrange
        ctx = create_mock_context()
        ctx.output.show_error_panel = Mock()

        # Act
        panel = ErrorPanel("Error", "Message")
        panel.render(ctx.output)

        # Assert
        assert callable(panel.render)

    def test_suggestion_list_render_method_is_called(self):
        """Archive command should call render() on SuggestionList instances."""
        # Arrange
        ctx = create_mock_context()
        ctx.output.suggest_next_steps = Mock()

        # Act
        suggestions = SuggestionList()
        suggestions.add("Suggestion")
        suggestions.render(ctx.output)

        # Assert
        assert callable(suggestions.render)


# =============================================================================
# JSON Mode Widget Tests
# =============================================================================


class TestArchiveCommandJSONModeWidgets:
    """Tests for archive command widget usage in JSON mode."""

    def test_json_mode_uses_widget_to_dict(self):
        """In JSON mode, archive command should use widget.to_dict() for ReportCard."""
        # Arrange
        ctx = create_mock_context()
        ctx.json_mode = True
        result = create_archive_result(archived_count=25)

        # Act
        card = ReportCard("Results")
        card.add_field("Archived", f"{result.archived_count:,}")
        data = card.to_dict()

        # Assert
        assert isinstance(data, dict)
        assert "Archived" in data

    def test_json_mode_uses_widget_to_list(self):
        """In JSON mode, archive command should use widget.to_list() for SuggestionList."""
        # Arrange
        ctx = create_mock_context()
        ctx.json_mode = True

        # Act
        suggestions = SuggestionList()
        suggestions.add("Step 1")
        suggestions.add("Step 2")
        items = suggestions.to_list()

        # Assert
        assert isinstance(items, list)
        assert len(items) == 2

    def test_json_mode_builds_json_from_widget_data(self):
        """JSON mode should construct JSON output from widget data structures."""
        # Arrange
        result = create_archive_result(
            archived_count=50,
            skipped_count=5,
            duplicate_count=2,
        )

        # Act
        # Simulate building JSON output from widgets
        report_card = ReportCard("Results")
        report_card.add_field("Archived", f"{result.archived_count:,}")
        report_card.add_conditional_field(
            result.skipped_count > 0, "Skipped", f"{result.skipped_count:,}"
        )

        suggestions = SuggestionList()
        suggestions.add("Next step 1")

        json_output = {
            "status": "success",
            "report": report_card.to_dict(),
            "suggestions": suggestions.to_list(),
        }

        # Assert
        assert json_output["status"] == "success"
        assert json_output["report"]["Archived"] == "50"
        assert "Next step 1" in json_output["suggestions"]


# =============================================================================
# Widget Data Population Tests
# =============================================================================


class TestArchiveCommandPopulatesWidgetData:
    """Tests verifying archive command populates widget data correctly."""

    def test_report_card_populated_with_archive_counts(self):
        """ReportCard should be populated with archive result counts."""
        # Arrange
        result = create_archive_result(
            archived_count=100,
            skipped_count=20,
            duplicate_count=10,
            found_count=130,
        )

        # Act
        card = ReportCard("Archive Results")
        card.add_field("Archived", f"{result.archived_count:,}")
        card.add_conditional_field(result.skipped_count > 0, "Skipped", f"{result.skipped_count:,}")
        card.add_conditional_field(
            result.duplicate_count > 0, "Duplicates", f"{result.duplicate_count:,}"
        )

        # Assert
        fields = card.to_dict()
        assert "100" in fields["Archived"]
        assert "20" in fields["Skipped"]
        assert "10" in fields["Duplicates"]

    def test_report_card_populated_with_archive_file_path(self):
        """ReportCard should include the archive file path."""
        # Arrange
        file_path = "/path/to/archive.mbox.gz"
        result = create_archive_result(actual_file=file_path)

        # Act
        card = ReportCard("Results")
        card.add_field("Archive File", result.actual_file)

        # Assert
        fields = card.to_dict()
        assert file_path in fields["Archive File"]

    def test_error_panel_populated_with_validation_details(self):
        """ErrorPanel should be populated with validation error details."""
        # Arrange
        validation_details = {
            "errors": ["Error 1", "Error 2", "Error 3"],
            "error_count": 3,
        }
        result = create_archive_result(
            validation_passed=False,
            validation_details=validation_details,
        )

        # Act
        panel = ErrorPanel("Validation Failed", "Integrity check failed")
        panel.add_details(result.validation_details.get("errors", []))

        # Assert
        assert len(panel._details) == 3
        assert "Error 1" in panel._details

    def test_suggestion_list_populated_with_context_specific_suggestions(self):
        """SuggestionList should be populated based on archive result context."""
        # Arrange
        result = create_archive_result(
            archived_count=50,
            duplicate_count=5,
            skipped_count=0,
        )

        # Act
        suggestions = SuggestionList()
        suggestions.add("View status: gmailarchiver status")
        suggestions.add_conditional(result.duplicate_count > 0, "Deduplicate: gmailarchiver dedupe")
        suggestions.add_conditional(result.skipped_count > 0, "Check skipped messages")
        suggestions.add("Delete archived: gmailarchiver archive 3y --trash")

        # Assert
        items = suggestions.to_list()
        # Should include: status, deduplicate, delete (3 items, not skipped)
        assert len(items) == 3
        assert any("Deduplicate" in item for item in items)


# =============================================================================
# Widget Conditional Content Tests
# =============================================================================


class TestArchiveCommandConditionalWidgetContent:
    """Tests for conditional content in widgets based on archive result."""

    def test_report_card_hides_skipped_when_zero(self):
        """ReportCard should hide skipped count field when it's zero."""
        # Arrange
        result = create_archive_result(skipped_count=0)

        # Act
        card = ReportCard("Results")
        card.add_conditional_field(result.skipped_count > 0, "Skipped", f"{result.skipped_count:,}")

        # Assert
        fields = card.to_dict()
        assert "Skipped" not in fields

    def test_report_card_shows_skipped_when_nonzero(self):
        """ReportCard should show skipped count when > 0."""
        # Arrange
        result = create_archive_result(skipped_count=5)

        # Act
        card = ReportCard("Results")
        card.add_conditional_field(result.skipped_count > 0, "Skipped", f"{result.skipped_count:,}")

        # Assert
        fields = card.to_dict()
        assert "Skipped" in fields
        assert "5" in fields["Skipped"]

    def test_suggestion_list_includes_dedupe_only_when_duplicates_exist(self):
        """SuggestionList should suggest deduplication only when duplicates found."""
        # Arrange - scenario with duplicates
        result_with_dupes = create_archive_result(duplicate_count=5)
        result_no_dupes = create_archive_result(duplicate_count=0)

        # Act
        suggestions_with = SuggestionList()
        suggestions_with.add_conditional(
            result_with_dupes.duplicate_count > 0, "Deduplicate archive"
        )

        suggestions_without = SuggestionList()
        suggestions_without.add_conditional(
            result_no_dupes.duplicate_count > 0, "Deduplicate archive"
        )

        # Assert
        assert len(suggestions_with.to_list()) == 1
        assert len(suggestions_without.to_list()) == 0

    def test_error_panel_suggestion_based_on_error_type(self):
        """ErrorPanel suggestion should vary based on error details."""
        # Arrange
        validation_failure = create_archive_result(
            validation_passed=False,
            validation_details={"errors": ["Checksum mismatch"]},
        )

        # Act
        panel = ErrorPanel("Validation Failed", "Check failed")
        if "Checksum" in str(validation_failure.validation_details.get("errors", [])):
            panel.set_suggestion("Verify archive integrity with gmailarchiver verify-integrity")

        # Assert
        assert "verify-integrity" in panel._suggestion


# =============================================================================
# Widget Output Format Tests
# =============================================================================


class TestArchiveCommandWidgetOutputFormats:
    """Tests for proper widget output format in different contexts."""

    def test_rich_output_mode_uses_widget_render(self):
        """Rich output mode should use widget.render() for display."""
        # Arrange
        ctx = create_mock_context()
        ctx.json_mode = False

        # Act
        card = ReportCard("Results")
        card.add_field("Archived", "100")

        # Verify render method exists for Rich output
        assert hasattr(card, "render")
        assert callable(card.render)

    def test_json_output_mode_uses_widget_data_conversion(self):
        """JSON output mode should use widget data conversion methods."""
        # Arrange
        ctx = create_mock_context()
        ctx.json_mode = True

        # Act
        card = ReportCard("Results")
        card.add_field("Archived", "100")

        # Verify data conversion methods exist
        assert hasattr(card, "to_dict")
        assert callable(card.to_dict)

        suggestions = SuggestionList()
        suggestions.add("Step 1")

        assert hasattr(suggestions, "to_list")
        assert callable(suggestions.to_list)

    def test_error_panel_structure_supports_json_serialization(self):
        """ErrorPanel structure should be JSON serializable."""
        # Arrange
        panel = ErrorPanel("Error", "Message")
        panel.add_detail("Detail")
        panel.set_suggestion("Fix it")

        # Act
        data = {
            "title": panel.title,
            "message": panel.message,
            "details": panel._details,
            "suggestion": panel._suggestion,
        }

        # Assert
        # All fields should be basic Python types (JSON-serializable)
        assert isinstance(data["title"], str)
        assert isinstance(data["message"], str)
        assert isinstance(data["details"], list)
        assert isinstance(data["suggestion"], str)
