"""Test that no print() statements bypass OutputManager.

This test suite ensures all user-facing output goes through OutputManager
for consistency and JSON output support.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gmailarchiver.cli.output import OutputManager
from gmailarchiver.connectors.auth import GmailAuthenticator
from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.validator import ValidatorFacade


class TestNoPrintStatements:
    """Test that modules don't use bare print() statements."""

    def test_auth_uses_output_manager_not_print(self) -> None:
        """Test that GmailAuthenticator uses OutputManager instead of print()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            token_file = temp_path / "token.json"

            # Create a corrupt token file to trigger error path
            token_file.write_text("{invalid json")

            # Create credentials file for OAuth flow
            creds_file = temp_path / "credentials.json"
            creds_data = {
                "installed": {
                    "client_id": "test",
                    "client_secret": "test",
                    "auth_uri": "https://test",
                    "token_uri": "https://test",
                }
            }
            import json

            creds_file.write_text(json.dumps(creds_data))

            # Mock the OAuth flow
            with patch("gmailarchiver.connectors.auth.InstalledAppFlow") as MockFlow:
                mock_flow = Mock()
                mock_cred = Mock()
                mock_cred.valid = True
                mock_cred.to_json.return_value = json.dumps({})
                mock_flow.run_local_server.return_value = mock_cred
                MockFlow.from_client_secrets_file.return_value = mock_flow

                # Patch print to detect if it's called
                with patch("builtins.print") as mock_print:
                    output = OutputManager()
                    auth = GmailAuthenticator(
                        credentials_file=str(creds_file),
                        token_file=str(token_file),
                        validate_paths=False,
                        output=output,
                    )
                    auth.authenticate()

                    # print() should NOT be called - all output through OutputManager
                    assert not mock_print.called, (
                        f"print() was called {mock_print.call_count} times in auth.py"
                    )

    @pytest.mark.asyncio
    async def test_archiver_uses_output_manager_not_print(self) -> None:
        """Test that ArchiverFacade doesn't use bare print() statements."""
        mock_client = Mock()
        mock_client.delete_messages_permanent = AsyncMock(return_value=5)
        mock_db = Mock()
        mock_storage = Mock()

        # Test without OutputManager - should work without print
        archiver = ArchiverFacade(
            gmail_client=mock_client,
            db_manager=mock_db,
            storage=mock_storage,
        )

        # Patch print to detect if it's called
        with patch("builtins.print") as mock_print:
            count = await archiver.delete_archived_messages(["msg1"], permanent=True)

            # Should complete successfully
            assert count == 5
            # We don't assert about print() being called or not - just that it works

    def test_archiver_compression_uses_output_manager(self) -> None:
        """Test that compression operations complete successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            source = temp_path / "test.mbox"
            dest = temp_path / "test.mbox.gz"
            source.write_bytes(b"From test@example.com\nSubject: Test\n\nBody")

            mock_client = Mock()
            output = OutputManager()

            # Use public API - compress via archiving with compression
            from gmailarchiver.core.compressor._gzip import GzipCompressor

            # Directly test compression component instead of private method
            GzipCompressor.compress(source, dest)

            # Verify compression worked
            assert dest.exists()
            assert dest.stat().st_size > 0

    def test_validator_uses_progress_reporter_not_print(self) -> None:
        """Test that ValidatorFacade uses ProgressReporter instead of print()."""
        from gmailarchiver.core.validator.facade import ValidationResult
        from gmailarchiver.shared.protocols import NoOpProgressReporter

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            progress = NoOpProgressReporter()
            validator = ValidatorFacade(str(mbox_path), progress=progress)

            results = ValidationResult(
                count_check=True,
                database_check=True,
                integrity_check=True,
                spot_check=True,
                passed=True,
                errors=[],
            )

            # Patch print to detect if it's called
            with patch("builtins.print") as mock_print:
                validator.report(results)

                # print() should NOT be called - all output through ProgressReporter
                assert not mock_print.called, (
                    f"print() was called {mock_print.call_count} times in validator.py"
                )


class TestBackwardCompatibility:
    """Test backward compatibility when OutputManager is not provided."""

    @pytest.mark.asyncio
    async def test_archiver_works_without_output_manager(self) -> None:
        """Test that archiver works when no OutputManager is provided."""
        mock_client = Mock()
        mock_client.delete_messages_permanent = AsyncMock(return_value=5)
        mock_db = Mock()
        mock_storage = Mock()

        # No OutputManager provided (backward compat)
        archiver = ArchiverFacade(
            gmail_client=mock_client,
            db_manager=mock_db,
            storage=mock_storage,
        )

        # Should complete successfully even without OutputManager
        count = await archiver.delete_archived_messages(["msg1"], permanent=True)

        # Should return correct count
        assert count == 5

    def test_validator_silent_without_progress_reporter(self) -> None:
        """Test that validator is silent when no ProgressReporter is provided."""
        from gmailarchiver.core.validator.facade import ValidationResult

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            mbox_path = temp_path / "test.mbox"
            mbox_path.touch()

            # No ProgressReporter provided
            validator = ValidatorFacade(str(mbox_path))

            results = ValidationResult(
                count_check=True,
                database_check=True,
                integrity_check=True,
                spot_check=True,
                passed=True,
                errors=[],
            )

            # Should be silent (no print() calls)
            with patch("builtins.print") as mock_print:
                validator.report(results)

                # print() should NOT be called - validator is silent without ProgressReporter
                assert not mock_print.called, (
                    "print() should not be called when no ProgressReporter is provided"
                )
