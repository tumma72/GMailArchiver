"""Integration tests verifying archive command uses widgets.

These tests call the actual archive command implementation and verify
that widgets are rendered. They should FAIL until archive.py is updated
to use widgets instead of direct OutputManager calls.

TDD Red Phase: These tests define the expected widget usage contract.
"""

from unittest.mock import MagicMock, patch

import pytest

from gmailarchiver.cli.commands.archive import (
    _handle_dry_run,
    _handle_validation_failure,
    _show_final_summary,
)
from gmailarchiver.core.workflows.archive import ArchiveResult


class TestArchiveCommandWidgetIntegration:
    """Test that archive command functions use widgets for output."""

    @pytest.fixture
    def mock_ctx(self):
        """Create mock CommandContext."""
        ctx = MagicMock()
        ctx.output = MagicMock()
        ctx.json_mode = False
        ctx.warning = MagicMock()
        ctx.info = MagicMock()
        ctx.success = MagicMock()
        ctx.show_report = MagicMock()
        ctx.suggest_next_steps = MagicMock()
        ctx.fail_and_exit = MagicMock()
        return ctx

    @pytest.fixture
    def success_result(self):
        """Create successful archive result."""
        return ArchiveResult(
            archived_count=25,
            skipped_count=3,
            duplicate_count=2,
            found_count=30,
            actual_file="archive_20241218.mbox",
            gmail_query="before:2022/01/01",
            interrupted=False,
            validation_passed=True,
            validation_details=None,
        )

    @pytest.fixture
    def dry_run_result(self):
        """Create dry run result."""
        return ArchiveResult(
            archived_count=0,
            skipped_count=5,
            duplicate_count=3,
            found_count=50,
            actual_file="archive.mbox",
            gmail_query="before:2022/01/01",
            interrupted=False,
            validation_passed=True,
            validation_details=None,
        )

    @pytest.fixture
    def validation_failure_result(self):
        """Create validation failure result."""
        return ArchiveResult(
            archived_count=10,
            skipped_count=0,
            duplicate_count=0,
            found_count=10,
            actual_file="archive.mbox",
            gmail_query="before:2022/01/01",
            interrupted=False,
            validation_passed=False,
            validation_details={
                "errors": ["Message count mismatch", "Checksum verification failed"],
                "count_check": False,
                "database_check": True,
                "integrity_check": False,
                "spot_check": True,
            },
        )

    def test_show_final_summary_uses_report_card(self, mock_ctx, success_result):
        """_show_final_summary should render a ReportCard widget."""
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.add_conditional_field = MagicMock(return_value=mock_card)
            mock_card.set_summary = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _show_final_summary(mock_ctx, success_result, "archive.mbox")

            # Verify ReportCard was instantiated
            MockReportCard.assert_called_once()

            # Verify render was called with output manager
            mock_card.render.assert_called_once_with(mock_ctx.output)

    def test_show_final_summary_card_contains_archived_count(self, mock_ctx, success_result):
        """ReportCard should include archived message count."""
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.add_conditional_field = MagicMock(return_value=mock_card)
            mock_card.set_summary = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _show_final_summary(mock_ctx, success_result, "archive.mbox")

            # Verify add_field was called with archived count
            field_calls = [str(c) for c in mock_card.add_field.call_args_list]
            assert any("25" in call for call in field_calls), (
                f"Expected archived count 25 in add_field calls: {field_calls}"
            )

    def test_handle_dry_run_uses_report_card(self, mock_ctx, dry_run_result):
        """_handle_dry_run should render a ReportCard widget."""
        with patch("gmailarchiver.cli.commands.archive.ReportCard") as MockReportCard:
            mock_card = MagicMock()
            mock_card.add_field = MagicMock(return_value=mock_card)
            mock_card.add_conditional_field = MagicMock(return_value=mock_card)
            mock_card.set_summary = MagicMock(return_value=mock_card)
            mock_card.render = MagicMock()
            MockReportCard.return_value = mock_card

            _handle_dry_run(mock_ctx, dry_run_result)

            # Verify ReportCard was instantiated with preview title
            MockReportCard.assert_called_once()
            call_args = MockReportCard.call_args[0][0]
            assert "preview" in call_args.lower() or "dry" in call_args.lower(), (
                f"Expected 'preview' or 'dry' in title, got: {call_args}"
            )

            # Verify render was called
            mock_card.render.assert_called_once_with(mock_ctx.output)

    def test_validation_failure_uses_error_panel(self, mock_ctx, validation_failure_result):
        """_handle_validation_failure should render an ErrorPanel widget."""
        with patch("gmailarchiver.cli.commands.archive.ErrorPanel") as MockErrorPanel:
            mock_error = MagicMock()
            mock_error.add_detail = MagicMock(return_value=mock_error)
            mock_error.add_details = MagicMock(return_value=mock_error)
            mock_error.with_suggestion = MagicMock(return_value=mock_error)
            mock_error.render = MagicMock()
            MockErrorPanel.return_value = mock_error

            _handle_validation_failure(mock_ctx, validation_failure_result, verbose=True)

            # Verify ErrorPanel was instantiated
            MockErrorPanel.assert_called_once()

            # Verify error details were added
            mock_error.add_details.assert_called()

            # Verify render was called
            mock_error.render.assert_called_once_with(mock_ctx.output)
