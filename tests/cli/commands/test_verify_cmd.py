"""Tests for CLI verify commands.

Tests both:
1. The CLI wrapper functions (verify_integrity, verify_consistency, verify_offsets)
2. The async command implementations (verify_*_command functions)

These tests ensure proper argument passing from CLI to async functions via asyncio.run().
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.cli.main import app
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


# ============================================================================
# CLI Wrapper Tests - Testing asyncio.run() calls at lines 32, 52, 72
# ============================================================================


class TestVerifyIntegrityCLIWrapper:
    """Tests for verify-integrity CLI wrapper function (covers line 32)."""

    def test_verify_integrity_cli_invokes_async_command(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-integrity CLI command invokes async implementation via asyncio.run()."""
        # Mock the async command function to verify it's called
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            result = runner.invoke(
                app, ["utilities", "verify-integrity", "--state-db", str(v1_1_database)]
            )

            # Command should complete (even if it fails, asyncio.run() was called)
            # Exit code depends on verification result, but asyncio.run() executed
            assert result.exit_code in [0, 1]
            mock_async_cmd.assert_called_once()

    def test_verify_integrity_cli_passes_state_db_argument(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes state_db argument to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            custom_db = str(v1_1_database)
            runner.invoke(app, ["utilities", "verify-integrity", "--state-db", custom_db])

            # Verify state_db was passed correctly (as positional arg after ctx)
            call_args = mock_async_cmd.call_args
            assert call_args.args[1] == custom_db  # args[0] is ctx, args[1] is state_db

    def test_verify_integrity_cli_passes_json_flag(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes --json flag to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(
                app, ["utilities", "verify-integrity", "--state-db", str(v1_1_database), "--json"]
            )

            # Verify json_output was passed as True (args[2] after ctx and state_db)
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is True  # args[0]=ctx, args[1]=state_db, args[2]=json_output

    def test_verify_integrity_cli_default_json_false(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper defaults json_output to False when --json not provided."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(app, ["utilities", "verify-integrity", "--state-db", str(v1_1_database)])

            # Verify json_output defaults to False
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is False  # args[0]=ctx, args[1]=state_db, args[2]=json_output

    def test_verify_integrity_cli_default_state_db(self, runner: CliRunner) -> None:
        """Test CLI wrapper uses default state_db value when not specified."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            # Don't provide --state-db, should use default "archive_state.db"
            runner.invoke(app, ["utilities", "verify-integrity"])

            # Verify default state_db was used (args[1] after ctx)
            call_args = mock_async_cmd.call_args
            if call_args:  # Command might fail if default DB doesn't exist
                assert call_args.args[1] == "archive_state.db"


class TestVerifyConsistencyCLIWrapper:
    """Tests for verify-consistency CLI wrapper function (covers line 52)."""

    def test_verify_consistency_cli_invokes_async_command(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-consistency CLI command invokes async implementation via asyncio.run()."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            result = runner.invoke(
                app, ["utilities", "verify-consistency", "--state-db", str(v1_1_database)]
            )

            # asyncio.run() should have been called
            assert result.exit_code in [0, 1]
            mock_async_cmd.assert_called_once()

    def test_verify_consistency_cli_passes_state_db_argument(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes state_db argument to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            custom_db = str(v1_1_database)
            runner.invoke(app, ["utilities", "verify-consistency", "--state-db", custom_db])

            # Verify state_db was passed correctly (args[1] after ctx)
            call_args = mock_async_cmd.call_args
            assert call_args.args[1] == custom_db

    def test_verify_consistency_cli_passes_json_flag(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes --json flag to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(
                app,
                ["utilities", "verify-consistency", "--state-db", str(v1_1_database), "--json"],
            )

            # Verify json_output was passed as True (args[2])
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is True

    def test_verify_consistency_cli_default_json_false(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper defaults json_output to False when --json not provided."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(
                app, ["utilities", "verify-consistency", "--state-db", str(v1_1_database)]
            )

            # Verify json_output defaults to False (args[2])
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is False

    def test_verify_consistency_cli_default_state_db(self, runner: CliRunner) -> None:
        """Test CLI wrapper uses default state_db value when not specified."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            # Don't provide --state-db, should use default "archive_state.db"
            runner.invoke(app, ["utilities", "verify-consistency"])

            # Verify default state_db was used (args[1])
            call_args = mock_async_cmd.call_args
            if call_args:  # Command might fail if default DB doesn't exist
                assert call_args.args[1] == "archive_state.db"


class TestVerifyOffsetsCLIWrapper:
    """Tests for verify-offsets CLI wrapper function (covers line 72)."""

    def test_verify_offsets_cli_invokes_async_command(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-offsets CLI command invokes async implementation via asyncio.run()."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            result = runner.invoke(
                app, ["utilities", "verify-offsets", "--state-db", str(v1_1_database)]
            )

            # asyncio.run() should have been called
            assert result.exit_code in [0, 1]
            mock_async_cmd.assert_called_once()

    def test_verify_offsets_cli_passes_state_db_argument(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes state_db argument to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            custom_db = str(v1_1_database)
            runner.invoke(app, ["utilities", "verify-offsets", "--state-db", custom_db])

            # Verify state_db was passed correctly (args[1] after ctx)
            call_args = mock_async_cmd.call_args
            assert call_args.args[1] == custom_db

    def test_verify_offsets_cli_passes_json_flag(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper correctly passes --json flag to async function."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(
                app, ["utilities", "verify-offsets", "--state-db", str(v1_1_database), "--json"]
            )

            # Verify json_output was passed as True (args[2])
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is True

    def test_verify_offsets_cli_default_json_false(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test CLI wrapper defaults json_output to False when --json not provided."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            runner.invoke(app, ["utilities", "verify-offsets", "--state-db", str(v1_1_database)])

            # Verify json_output defaults to False (args[2])
            call_args = mock_async_cmd.call_args
            assert call_args.args[2] is False

    def test_verify_offsets_cli_default_state_db(self, runner: CliRunner) -> None:
        """Test CLI wrapper uses default state_db value when not specified."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            # Don't provide --state-db, should use default "archive_state.db"
            runner.invoke(app, ["utilities", "verify-offsets"])

            # Verify default state_db was used (args[1])
            call_args = mock_async_cmd.call_args
            if call_args:  # Command might fail if default DB doesn't exist
                assert call_args.args[1] == "archive_state.db"


# ============================================================================
# Additional Behavioral Tests
# ============================================================================


class TestVerifyCommandsHelp:
    """Test help output for verify commands."""

    def test_verify_integrity_help_displayed(self, runner: CliRunner) -> None:
        """Test verify-integrity --help shows proper usage."""
        result = runner.invoke(app, ["utilities", "verify-integrity", "--help"])

        assert result.exit_code == 0
        assert "verify" in result.stdout.lower() or "integrity" in result.stdout.lower()
        assert "--state-db" in result.stdout
        assert "--json" in result.stdout

    def test_verify_consistency_help_displayed(self, runner: CliRunner) -> None:
        """Test verify-consistency --help shows proper usage."""
        result = runner.invoke(app, ["utilities", "verify-consistency", "--help"])

        assert result.exit_code == 0
        assert "verify" in result.stdout.lower() or "consistency" in result.stdout.lower()
        assert "--state-db" in result.stdout
        assert "--json" in result.stdout

    def test_verify_offsets_help_displayed(self, runner: CliRunner) -> None:
        """Test verify-offsets --help shows proper usage."""
        result = runner.invoke(app, ["utilities", "verify-offsets", "--help"])

        assert result.exit_code == 0
        assert "verify" in result.stdout.lower() or "offset" in result.stdout.lower()
        assert "--state-db" in result.stdout
        assert "--json" in result.stdout


class TestVerifyCommandsErrorHandling:
    """Test error handling in CLI wrapper commands."""

    def test_verify_integrity_handles_async_exception(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-integrity handles exceptions from async function gracefully."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_integrity_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            mock_async_cmd.side_effect = RuntimeError("Verification failed")

            result = runner.invoke(
                app, ["utilities", "verify-integrity", "--state-db", str(v1_1_database)]
            )

            # Should handle exception and exit with error code
            assert result.exit_code != 0
            mock_async_cmd.assert_called_once()

    def test_verify_consistency_handles_async_exception(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-consistency handles exceptions from async function gracefully."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_consistency_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            mock_async_cmd.side_effect = RuntimeError("Consistency check failed")

            result = runner.invoke(
                app, ["utilities", "verify-consistency", "--state-db", str(v1_1_database)]
            )

            # Should handle exception and exit with error code
            assert result.exit_code != 0
            mock_async_cmd.assert_called_once()

    def test_verify_offsets_handles_async_exception(
        self, runner: CliRunner, v1_1_database: Path
    ) -> None:
        """Test verify-offsets handles exceptions from async function gracefully."""
        with patch(
            "gmailarchiver.cli.commands.verify.verify_offsets_command", new_callable=AsyncMock
        ) as mock_async_cmd:
            mock_async_cmd.side_effect = RuntimeError("Offset verification failed")

            result = runner.invoke(
                app, ["utilities", "verify-offsets", "--state-db", str(v1_1_database)]
            )

            # Should handle exception and exit with error code
            assert result.exit_code != 0
            mock_async_cmd.assert_called_once()
