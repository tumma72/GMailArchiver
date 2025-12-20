"""Tests for status command implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.commands.status import (
    _display_recent_runs_table,
    _run_status,
)
from gmailarchiver.cli.ui.widgets import TableWidget
from gmailarchiver.core.workflows.status import StatusResult


class TestRunStatus:
    """Tests for async _run_status implementation."""

    @pytest.mark.asyncio
    async def test_run_status_requires_storage(self) -> None:
        """_run_status expects ctx.storage to be not None."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = None

        with pytest.raises(AssertionError):
            await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

    @pytest.mark.asyncio
    async def test_run_status_calls_workflow(self) -> None:
        """_run_status executes StatusWorkflow."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 1024
        mock_result.total_messages = 100
        mock_result.archive_files_count = 1
        mock_result.archive_files = ["archive.mbox"]
        mock_result.recent_runs = []

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

                # Verify workflow was called
                mock_workflow.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_status_json_output_mode(self) -> None:
        """_run_status outputs JSON when json_output=True."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 2048
        mock_result.total_messages = 200
        mock_result.archive_files_count = 2
        mock_result.archive_files = ["archive1.mbox", "archive2.mbox"]
        mock_result.recent_runs = [{"run_id": 1, "query": "test"}]

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                await _run_status(ctx=mock_ctx, verbose=False, json_output=True)

                # Verify JSON payload was set
                mock_output.set_json_payload.assert_called_once()
                call_args = mock_output.set_json_payload.call_args[0][0]
                assert call_args["schema_version"] == "1.1"
                assert call_args["total_messages"] == 200

    @pytest.mark.asyncio
    async def test_run_status_shows_report_card(self) -> None:
        """_run_status displays ReportCard with statistics."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 1024
        mock_result.total_messages = 42
        mock_result.archive_files_count = 1
        mock_result.archive_files = ["test.mbox"]
        mock_result.recent_runs = []

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                with patch("gmailarchiver.cli.commands.status.ReportCard") as MockCard:
                    mock_card = MagicMock()
                    MockCard.return_value = mock_card

                    await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

                    # Verify report card was created and rendered
                    MockCard.assert_called_once_with("Archive Status")
                    mock_card.render.assert_called_once_with(mock_output)

    @pytest.mark.asyncio
    async def test_run_status_handles_exception(self) -> None:
        """_run_status handles workflow exceptions."""
        import typer

        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui
        # Mock fail_and_exit to raise typer.Exit
        mock_ctx.fail_and_exit.side_effect = typer.Exit(1)

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(side_effect=Exception("Database error"))
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                with pytest.raises(typer.Exit):
                    await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

                # Verify fail_and_exit was called
                mock_ctx.fail_and_exit.assert_called_once()
                call_kwargs = mock_ctx.fail_and_exit.call_args[1]
                assert "Status Error" in call_kwargs.get("title", "")

    @pytest.mark.asyncio
    async def test_run_status_shows_recent_runs_table(self) -> None:
        """_run_status displays recent runs table when available."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 1024
        mock_result.total_messages = 100
        mock_result.archive_files_count = 1
        mock_result.archive_files = ["archive.mbox"]
        mock_result.recent_runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": "before:2024/01/01",
            }
        ]

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                with patch(
                    "gmailarchiver.cli.commands.status._display_recent_runs_table"
                ) as mock_display:
                    await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

                    # Verify table display was called
                    mock_display.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_status_no_recent_runs(self) -> None:
        """_run_status handles empty recent_runs gracefully."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 1024
        mock_result.total_messages = 0
        mock_result.archive_files_count = 0
        mock_result.archive_files = []
        mock_result.recent_runs = []

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                await _run_status(ctx=mock_ctx, verbose=False, json_output=False)

                # Verify warning was shown
                mock_ctx.warning.assert_called_once()


class TestDisplayRecentRunsTable:
    """Tests for _display_recent_runs_table helper."""

    def test_display_recent_runs_table_creates_widget(self) -> None:
        """_display_recent_runs_table creates TableWidget."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": "before:2024/01/01",
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify widget was created
            MockWidget.assert_called_once()
            mock_widget.render_to_output.assert_called_once()

    def test_display_recent_runs_table_non_verbose(self) -> None:
        """_display_recent_runs_table without verbose shows 5 runs."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": f"2024-01-{i:02d} 10:30:45",
                "messages_archived": i * 10,
                "archive_file": f"archive{i}.mbox",
                "query": f"query{i}",
            }
            for i in range(1, 11)
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify add_row was called 5 times (5 limit for non-verbose)
            add_row_count = mock_widget.add_row.call_count
            assert add_row_count == 5

    def test_display_recent_runs_table_verbose(self) -> None:
        """_display_recent_runs_table with verbose shows 10 runs."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": f"2024-01-{i:02d} 10:30:45",
                "messages_archived": i * 10,
                "archive_file": f"archive{i}.mbox",
                "query": f"query{i}",
            }
            for i in range(1, 16)
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=True)

            # Verify add_row was called 10 times (10 limit for verbose)
            add_row_count = mock_widget.add_row.call_count
            assert add_row_count == 10

    def test_display_recent_runs_table_columns_non_verbose(self) -> None:
        """_display_recent_runs_table columns for non-verbose mode."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": None,
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify columns added (no Query column in non-verbose)
            add_column_count = mock_widget.add_column.call_count
            assert add_column_count == 3  # Timestamp, Messages, Archive

    def test_display_recent_runs_table_columns_verbose(self) -> None:
        """_display_recent_runs_table columns for verbose mode."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": "before:2024/01/01",
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=True)

            # Verify columns added (includes Query column in verbose)
            add_column_count = mock_widget.add_column.call_count
            assert add_column_count == 4  # Timestamp, Messages, Archive, Query

    def test_display_recent_runs_table_truncates_timestamp(self) -> None:
        """_display_recent_runs_table truncates timestamp to 19 chars."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45.123456",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": None,
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Check that add_row was called with truncated timestamp
            call_args = mock_widget.add_row.call_args[0]
            timestamp = call_args[0]
            assert len(timestamp) == 19

    def test_display_recent_runs_table_query_truncation_verbose(self) -> None:
        """_display_recent_runs_table truncates query to 30 chars in verbose."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        long_query = "this is a very long query that should be truncated for display purposes"
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": long_query,
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=True)

            # Check that add_row was called with truncated query
            call_args = mock_widget.add_row.call_args[0]
            query = call_args[3]
            assert len(query) <= 30

    def test_display_recent_runs_table_empty_runs(self) -> None:
        """_display_recent_runs_table handles empty runs list."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = []

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify widget was still created (even with 0 rows)
            MockWidget.assert_called_once()

    def test_display_recent_runs_table_missing_fields(self) -> None:
        """_display_recent_runs_table handles missing fields gracefully."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                # Missing archive_file and query
            }
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify add_row was called (with empty strings for missing fields)
            mock_widget.add_row.assert_called_once()

    def test_display_recent_runs_table_title_reflects_count(self) -> None:
        """_display_recent_runs_table title shows actual run count."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        runs = [
            {
                "run_timestamp": "2024-01-15 10:30:45",
                "messages_archived": 50,
                "archive_file": "archive.mbox",
                "query": None,
            },
            {
                "run_timestamp": "2024-01-14 10:30:45",
                "messages_archived": 40,
                "archive_file": "archive.mbox",
                "query": None,
            },
        ]

        with patch("gmailarchiver.cli.commands.status.TableWidget") as MockWidget:
            mock_widget = MagicMock(spec=TableWidget)
            MockWidget.return_value = mock_widget

            _display_recent_runs_table(mock_ctx, runs, verbose=False)

            # Verify title includes count (showing last 2 runs)
            title_arg = MockWidget.call_args[1]["title"]
            assert "2" in title_arg or "Last" in title_arg


class TestStatusCommandIntegration:
    """Integration tests for status command."""

    @pytest.mark.asyncio
    async def test_status_workflow_called_with_correct_config(self) -> None:
        """Status command creates and uses StatusWorkflow correctly."""
        mock_storage = MagicMock()
        mock_output = MagicMock()
        mock_ui = MagicMock()
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.storage = mock_storage
        mock_ctx.output = mock_output
        mock_ctx.ui = mock_ui

        mock_result = MagicMock(spec=StatusResult)
        mock_result.schema_version = "1.1"
        mock_result.database_size_bytes = 1024
        mock_result.total_messages = 100
        mock_result.archive_files_count = 1
        mock_result.archive_files = ["archive.mbox"]
        mock_result.recent_runs = []

        with patch("gmailarchiver.cli.commands.status.StatusWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=mock_result)
            MockWorkflow.return_value = mock_workflow

            with patch("gmailarchiver.cli.commands.status.CLIProgressAdapter"):
                await _run_status(ctx=mock_ctx, verbose=True, json_output=False)

                # Verify workflow was created with storage
                MockWorkflow.assert_called_once()
