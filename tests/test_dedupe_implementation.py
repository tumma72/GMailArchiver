"""Tests for dedupe command implementation.

Tests the async implementation layer for deduplication operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.dedupe import dedupe_command
from gmailarchiver.core.workflows.dedupe import DedupeResult


class TestDedupeCommand:
    """Tests for dedupe_command async implementation."""

    @pytest.mark.asyncio
    async def test_dedupe_database_not_found(self, tmp_path):
        """Test dedupe fails when database doesn't exist."""
        import typer

        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_ctx.fail_and_exit.side_effect = typer.Exit(1)
        nonexistent_db = str(tmp_path / "nonexistent.db")

        with pytest.raises(typer.Exit):
            await dedupe_command(
                ctx=mock_ctx,
                state_db=nonexistent_db,
                dry_run=False,
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args[1]
        assert "Database Not Found" in call_args["title"]

    @pytest.mark.asyncio
    async def test_dedupe_no_archives(self, tmp_path, v11_db):
        """Test dedupe fails when no archives in database."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_storage.db._conn.execute.return_value = AsyncMock(fetchall=AsyncMock(return_value=[]))
        mock_ctx.storage = mock_storage

        await dedupe_command(
            ctx=mock_ctx,
            state_db=v11_db,
            dry_run=False,
            json_output=False,
        )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args[1]
        assert "No Archives Found" in call_args["title"]

    @pytest.mark.asyncio
    async def test_dedupe_no_duplicates_found(self, tmp_path, v11_db):
        """Test dedupe when no duplicates are found."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        # Mock workflow
        with patch("gmailarchiver.cli.dedupe.DedupeWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=DedupeResult)
            mock_result.duplicates_found = 0
            mock_result.duplicates_removed = 0
            mock_result.messages_kept = 100

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

            await dedupe_command(
                ctx=mock_ctx,
                state_db=v11_db,
                dry_run=False,
                json_output=False,
            )

            # Should complete task and show info message
            mock_task.complete.assert_called_once()
            mock_ctx.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedupe_dry_run_with_duplicates(self, tmp_path, v11_db):
        """Test dedupe dry run mode with duplicates found."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        # Mock workflow
        with patch("gmailarchiver.cli.dedupe.DedupeWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=DedupeResult)
            mock_result.duplicates_found = 5
            mock_result.duplicates_removed = 0
            mock_result.messages_kept = 95

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

            await dedupe_command(
                ctx=mock_ctx,
                state_db=v11_db,
                dry_run=True,
                json_output=False,
            )

            # Should show warning for dry run
            mock_ctx.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedupe_actual_run_with_duplicates(self, tmp_path, v11_db):
        """Test dedupe actual run with duplicates removed."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_ctx.output = MagicMock()
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        # Mock workflow
        with patch("gmailarchiver.cli.dedupe.DedupeWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=DedupeResult)
            mock_result.duplicates_found = 5
            mock_result.duplicates_removed = 5
            mock_result.messages_kept = 95

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

            await dedupe_command(
                ctx=mock_ctx,
                state_db=v11_db,
                dry_run=False,
                json_output=False,
            )

            # Should show success message
            mock_ctx.success.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedupe_workflow_exception(self, tmp_path, v11_db):
        """Test dedupe handles workflow exceptions."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        # Mock workflow to raise exception
        with patch("gmailarchiver.cli.dedupe.DedupeWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow
            mock_workflow.run = AsyncMock(side_effect=RuntimeError("Corrupted database"))

            # Mock task sequence
            mock_task_seq = MagicMock()
            mock_task = MagicMock()
            mock_task.__enter__ = MagicMock(return_value=mock_task)
            mock_task.__exit__ = MagicMock(return_value=None)
            mock_task_seq.task = MagicMock(return_value=mock_task)
            mock_task_seq.__enter__ = MagicMock(return_value=mock_task_seq)
            mock_task_seq.__exit__ = MagicMock(return_value=None)
            mock_ctx.ui.task_sequence = MagicMock(return_value=mock_task_seq)

            await dedupe_command(
                ctx=mock_ctx,
                state_db=v11_db,
                dry_run=False,
                json_output=False,
            )

            # Should fail task and exit
            mock_task.fail.assert_called_once()
            mock_ctx.fail_and_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedupe_with_json_output(self, tmp_path, v11_db):
        """Test dedupe with JSON output flag."""
        mock_ctx = MagicMock(spec=CommandContext)
        mock_storage = AsyncMock()
        mock_ctx.storage = mock_storage
        mock_ctx.ui = MagicMock()

        # Mock database cursor
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("archive1.mbox",)])
        mock_storage.db._conn.execute = AsyncMock(return_value=cursor)

        # Mock workflow
        with patch("gmailarchiver.cli.dedupe.DedupeWorkflow") as MockWorkflow:
            mock_workflow = AsyncMock()
            MockWorkflow.return_value = mock_workflow

            mock_result = MagicMock(spec=DedupeResult)
            mock_result.duplicates_found = 0
            mock_result.duplicates_removed = 0
            mock_result.messages_kept = 100

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

            # json_output flag should be passed through command context
            await dedupe_command(
                ctx=mock_ctx,
                state_db=v11_db,
                dry_run=False,
                json_output=True,
            )

            # Should still execute workflow
            mock_workflow.run.assert_called_once()
