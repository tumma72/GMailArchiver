"""Tests for CLI verify commands.

Tests the async command implementations for verification operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.output import OutputManager
from gmailarchiver.cli.verify import (
    verify_consistency_command,
    verify_integrity_command,
    verify_offsets_command,
)
from gmailarchiver.core.workflows.verify import VerifyResult, VerifyType


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock CommandContext for testing."""
    ctx = MagicMock(spec=CommandContext)
    ctx.output = MagicMock(spec=OutputManager)
    ctx.storage = MagicMock()
    ctx.json_mode = False
    ctx.success = MagicMock()
    ctx.warning = MagicMock()
    ctx.fail_and_exit = MagicMock()
    ctx.ui = MagicMock()
    # Mock task_sequence context manager
    task_seq = MagicMock()
    task = MagicMock()
    task.__enter__ = MagicMock(return_value=task)
    task.__exit__ = MagicMock(return_value=None)
    task_seq.__enter__ = MagicMock(return_value=task_seq)
    task_seq.__exit__ = MagicMock(return_value=None)
    task_seq.task = MagicMock(return_value=task)
    ctx.ui.task_sequence = MagicMock(return_value=task_seq)
    return ctx


class TestVerifyIntegrityCommand:
    """Tests for verify-integrity command."""

    @pytest.mark.asyncio
    async def test_verify_integrity_success(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test successful integrity verification."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        result = VerifyResult(
            verify_type=VerifyType.INTEGRITY.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_integrity_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=False,
            )

            mock_workflow.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_integrity_database_not_found(self, mock_ctx: MagicMock) -> None:
        """Test verify-integrity fails when database doesn't exist."""
        # Make fail_and_exit raise to simulate actual behavior
        mock_ctx.fail_and_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            await verify_integrity_command(
                ctx=mock_ctx,
                state_db="/nonexistent/path.db",
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()
        call_args = mock_ctx.fail_and_exit.call_args
        assert "Database Not Found" in call_args.kwargs.get("title", "")

    @pytest.mark.asyncio
    async def test_verify_integrity_json_output(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test verify-integrity with JSON output."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        mock_ctx.json_mode = True

        result = VerifyResult(
            verify_type=VerifyType.INTEGRITY.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_integrity_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=True,
            )

            mock_workflow.run.assert_called_once()


class TestVerifyConsistencyCommand:
    """Tests for verify-consistency command."""

    @pytest.mark.asyncio
    async def test_verify_consistency_success(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test successful consistency verification."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        result = VerifyResult(
            verify_type=VerifyType.CONSISTENCY.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_consistency_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=False,
            )

            mock_workflow.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_consistency_database_not_found(self, mock_ctx: MagicMock) -> None:
        """Test verify-consistency fails when database doesn't exist."""
        # Make fail_and_exit raise to simulate actual behavior
        mock_ctx.fail_and_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            await verify_consistency_command(
                ctx=mock_ctx,
                state_db="/nonexistent/path.db",
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_consistency_json_output(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test verify-consistency with JSON output."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        mock_ctx.json_mode = True

        result = VerifyResult(
            verify_type=VerifyType.CONSISTENCY.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_consistency_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=True,
            )

            mock_workflow.run.assert_called_once()


class TestVerifyOffsetsCommand:
    """Tests for verify-offsets command."""

    @pytest.mark.asyncio
    async def test_verify_offsets_success(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test successful offsets verification."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        result = VerifyResult(
            verify_type=VerifyType.OFFSETS.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_offsets_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=False,
            )

            mock_workflow.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_offsets_database_not_found(self, mock_ctx: MagicMock) -> None:
        """Test verify-offsets fails when database doesn't exist."""
        # Make fail_and_exit raise to simulate actual behavior
        mock_ctx.fail_and_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            await verify_offsets_command(
                ctx=mock_ctx,
                state_db="/nonexistent/path.db",
                json_output=False,
            )

        mock_ctx.fail_and_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_offsets_json_output(self, mock_ctx: MagicMock, tmp_path) -> None:
        """Test verify-offsets with JSON output."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        mock_ctx.json_mode = True

        result = VerifyResult(
            verify_type=VerifyType.OFFSETS.value,
            passed=True,
            issues_found=0,
            issues=[],
        )

        with patch("gmailarchiver.cli.verify.VerifyWorkflow") as MockWorkflow:
            mock_workflow = MagicMock()
            mock_workflow.run = AsyncMock(return_value=result)
            MockWorkflow.return_value = mock_workflow

            await verify_offsets_command(
                ctx=mock_ctx,
                state_db=str(db_path),
                json_output=True,
            )

            mock_workflow.run.assert_called_once()
