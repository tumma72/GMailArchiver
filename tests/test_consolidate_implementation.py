"""Tests for consolidate command implementation.

Tests the async implementation layer for consolidate operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.consolidate import consolidate_command
from gmailarchiver.core.workflows.consolidate import ConsolidateResult


class TestConsolidateCommand:
    """Tests for consolidate_command async implementation."""

    @pytest.mark.asyncio
    async def test_consolidate_database_not_found(self, tmp_path):
        """Test consolidate fails when database doesn't exist."""
        import typer

        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_ctx.fail_and_exit.side_effect = typer.Exit(1)
        output_file = str(tmp_path / "output.mbox")
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(typer.Exit):
            await consolidate_command(
                ctx=mock_ctx,
                output_file=output_file,
                state_db=nonexistent_db,
                deduplicate=False,
                sort_by_date=False,
                compress=None,
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args[1]
        assert "Database Not Found" in call_args["title"]

    @pytest.mark.asyncio
    async def test_consolidate_output_file_exists(self, tmp_path):
        """Test consolidate fails when output file already exists."""
        import typer

        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_ctx.fail_and_exit.side_effect = typer.Exit(1)

        # Create database
        db_file = tmp_path / "test.db"
        db_file.touch()

        # Create existing output file
        output_file = tmp_path / "output.mbox"
        output_file.touch()

        with pytest.raises(typer.Exit):
            await consolidate_command(
                ctx=mock_ctx,
                output_file=str(output_file),
                state_db=str(db_file),
                deduplicate=False,
                sort_by_date=False,
                compress=None,
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args[1]
        assert "Output File Exists" in call_args["title"]

    @pytest.mark.asyncio
    async def test_consolidate_no_archives(self, tmp_path, v11_db):
        """Test consolidate fails when no archives in database."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_storage.db._conn.execute.return_value = AsyncMock(fetchall=AsyncMock(return_value=[]))
        mock_ctx.storage = mock_storage

        output_file = str(tmp_path / "output.mbox")

        await consolidate_command(
            ctx=mock_ctx,
            output_file=output_file,
            state_db=v11_db,
            deduplicate=False,
            sort_by_date=False,
            compress=None,
            json_output=False,
        )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args[1]
        assert "No Archives Found" in call_args["title"]

    @pytest.mark.asyncio
    async def test_consolidate_workflow_execution(self, tmp_path, v11_db):
        """Test consolidate executes workflow with correct config."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",), ("archive2.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        output_file = str(tmp_path / "output.mbox")

        # Mock workflow
        with patch("gmailarchiver.cli.consolidate.ConsolidateWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=ConsolidateResult)
            mock_result.messages_count = 100
            mock_result.source_files_count = 2
            mock_result.duplicates_removed = 0
            mock_result.sort_applied = False
            mock_result.output_file = output_file

            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock task sequence context managers
            mock_task_seq = MagicMock()
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=None)
            mock_task_seq.task = MagicMock(return_value=mock_task)
            mock_task_seq.__enter__ = MagicMock(return_value=mock_task_seq)
            mock_task_seq.__exit__ = MagicMock(return_value=None)
            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_task_seq)

            await consolidate_command(
                ctx=mock_ctx,
                output_file=output_file,
                state_db=v11_db,
                deduplicate=False,
                sort_by_date=False,
                compress=None,
                json_output=False,
            )

            mock_workflow.run.assert_called_once()
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidate_workflow_exception(self, tmp_path, v11_db):
        """Test consolidate handles workflow exceptions."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        output_file = str(tmp_path / "output.mbox")

        # Mock workflow to raise exception
        with patch("gmailarchiver.cli.consolidate.ConsolidateWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow
            mock_workflow.run = AsyncMock(side_effect=RuntimeError("Disk full"))

            # Mock task sequence
            mock_task_seq = MagicMock()
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=None)
            mock_task_seq.task = MagicMock(return_value=mock_task)
            mock_task_seq.__enter__ = MagicMock(return_value=mock_task_seq)
            mock_task_seq.__exit__ = MagicMock(return_value=None)
            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_task_seq)

            await consolidate_command(
                ctx=mock_ctx,
                output_file=output_file,
                state_db=v11_db,
                deduplicate=False,
                sort_by_date=False,
                compress=None,
                json_output=False,
            )

            mock_task.fail.assert_called_once()
            mock_ctx.fail_and_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidate_with_deduplicate(self, tmp_path, v11_db):
        """Test consolidate with deduplicate flag."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        output_file = str(tmp_path / "output.mbox")

        with patch("gmailarchiver.cli.consolidate.ConsolidateWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=ConsolidateResult)
            mock_result.messages_count = 100
            mock_result.source_files_count = 1
            mock_result.duplicates_removed = 10
            mock_result.sort_applied = False
            mock_result.output_file = output_file

            mock_workflow.run = AsyncMock(return_value=mock_result)

            # Mock task sequence
            mock_task_seq = MagicMock()
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=None)
            mock_task_seq.task = MagicMock(return_value=mock_task)
            mock_task_seq.__enter__ = MagicMock(return_value=mock_task_seq)
            mock_task_seq.__exit__ = MagicMock(return_value=None)
            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_task_seq)

            await consolidate_command(
                ctx=mock_ctx,
                output_file=output_file,
                state_db=v11_db,
                deduplicate=True,
                sort_by_date=False,
                compress="gzip",
                json_output=False,
            )

            # Verify config passed to workflow
            config = mock_workflow.run.call_args[0][0]
            assert config.dedupe is True
            assert config.compress == "gzip"
