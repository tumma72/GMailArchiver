"""Tests for validate command CLI handler.

This module tests the validate command function that orchestrates:
- Archive file existence checking
- Database existence checking
- ValidateWorkflow execution
- Output formatting (Rich and JSON modes)
- Error handling and suggestions
"""

import mailbox
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from gmailarchiver.cli.commands.validate import validate
from gmailarchiver.core.workflows.validate import ValidateResult


class TestValidateCommand:
    """Test suite for validate command handler."""

    def test_validate_archive_not_found(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validate fails when archive file doesn't exist."""
        # Arrange
        nonexistent_archive = str(temp_dir / "nonexistent.mbox")

        # Act & Assert - typer.Exit raises click.exceptions.Exit
        with pytest.raises((SystemExit, Exception)) as exc_info:
            validate(
                archive_file=nonexistent_archive,
                state_db=v11_db,
                verbose=False,
                json_output=False,
            )

        # Typer.Exit uses exit_code, SystemExit uses code
        assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Verify error message in output
        captured = capfd.readouterr()
        assert "File Not Found" in captured.out or "not found" in captured.err.lower()

    def test_validate_database_not_found(self, temp_dir: Path, capfd) -> None:
        """Test validate fails when database doesn't exist."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"
        archive_file.touch()
        nonexistent_db = str(temp_dir / "nonexistent.db")

        # Act & Assert - typer.Exit raises click.exceptions.Exit
        with pytest.raises((SystemExit, Exception)) as exc_info:
            validate(
                archive_file=str(archive_file),
                state_db=nonexistent_db,
                verbose=False,
                json_output=False,
            )

        # Typer.Exit uses exit_code, SystemExit uses code
        assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Verify error message and suggestion
        captured = capfd.readouterr()
        output = captured.out + captured.err
        # The decorator outputs "State database not found" or "Database Not Found"
        assert "database" in output.lower() and "not found" in output.lower()
        # Should suggest running archive or import first
        assert "import" in output.lower() or "archive" in output.lower()

    def test_validate_success_with_mock(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test successful validation flow with mocked workflow."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock successful validation result
        mock_result = ValidateResult(
            passed=True,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=[],
            details=None,
        )

        # Mock the workflow to return success
        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act
            validate(
                archive_file=str(archive_file),
                state_db=v11_db,
                verbose=False,
                json_output=False,
            )

        # Assert
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "validation passed" in output.lower()

    def test_validate_failure_database_check(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure when database check fails."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock failed validation - database check failed
        mock_result = ValidateResult(
            passed=False,
            count_check=True,
            database_check=False,
            integrity_check=True,
            spot_check=True,
            errors=["Database check failed"],
            details=None,
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - verify suggestions are shown
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "import" in output.lower()

    def test_validate_failure_integrity_check(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure when integrity check fails."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock failed validation - integrity check failed
        mock_result = ValidateResult(
            passed=False,
            count_check=True,
            database_check=True,
            integrity_check=False,
            spot_check=True,
            errors=["Integrity check failed"],
            details=None,
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - verify corruption suggestion
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "corruption" in output.lower() or "re-downloading" in output.lower()

    def test_validate_failure_count_check(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure when count check fails."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock failed validation - count check failed
        mock_result = ValidateResult(
            passed=False,
            count_check=False,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=["Count mismatch"],
            details=None,
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - verify integrity/repair suggestions
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "verify-integrity" in output or "repair" in output

    def test_validate_verbose_mode(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation with verbose mode shows detailed report."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        mock_result = ValidateResult(
            passed=True,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=[],
            details={"expected_count": 1, "archive_file": str(archive_file)},
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act
            validate(
                archive_file=str(archive_file),
                state_db=v11_db,
                verbose=True,
                json_output=False,
            )

        # Assert - verbose mode should show validation report
        captured = capfd.readouterr()
        # In verbose mode with success, we should see the report

    def test_validate_json_output(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test successful validation with JSON output."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        mock_result = ValidateResult(
            passed=True,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=[],
            details={"extra": "data"},
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act
            validate(
                archive_file=str(archive_file),
                state_db=v11_db,
                verbose=False,
                json_output=True,
            )

        # Assert - verify JSON structure in output
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert '"passed": true' in output or '"passed":true' in output

    def test_validate_workflow_file_not_found_exception(
        self, temp_dir: Path, v11_db: str, capfd
    ) -> None:
        """Test validation handles FileNotFoundError from workflow."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = FileNotFoundError("Archive disappeared")

            # Act & Assert - FileNotFoundError causes graceful exit with error message
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - should show error message
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "Archive disappeared" in output or "not found" in output.lower()

    def test_validate_workflow_generic_exception(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation handles generic exceptions from workflow."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError("Validation error")

            # Act & Assert - Generic exceptions cause graceful exit with error message
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - should show error with suggestion
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "Validation error" in output or "Failed to validate" in output

    def test_validate_multiple_failure_types(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure with multiple check failures shows all relevant suggestions."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock validation failure with multiple issues
        mock_result = ValidateResult(
            passed=False,
            count_check=False,
            database_check=False,
            integrity_check=False,
            spot_check=False,
            errors=["Multiple failures"],
            details=None,
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - should show multiple suggestions
        captured = capfd.readouterr()
        output = captured.out + captured.err
        # Should suggest import for database check failure
        assert "import" in output.lower()

    def test_validate_spot_check_failure(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure when spot check fails."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock failed validation - spot check failed
        mock_result = ValidateResult(
            passed=False,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=False,
            errors=["Spot check failed"],
            details=None,
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Assert - verify repair suggestion
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "verify-integrity" in output or "repair" in output

    def test_validate_runs_with_verbose_flag(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation command respects verbose flag."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        mock_result = ValidateResult(
            passed=True,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=[],
            details={"extra": "verbose data"},
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act
            validate(
                archive_file=str(archive_file),
                state_db=v11_db,
                verbose=True,
                json_output=False,
            )

        # Assert - validation runs successfully with verbose flag
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "validation passed" in output.lower() or "✓" in output

    def test_validate_failure_always_shows_report(self, temp_dir: Path, v11_db: str, capfd) -> None:
        """Test validation failure always shows detailed report regardless of verbose flag."""
        # Arrange
        archive_file = temp_dir / "archive.mbox"

        # Create a valid mbox file
        mbox_obj = mailbox.mbox(str(archive_file))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Message"
        msg["Message-ID"] = "<test@example.com>"
        msg.set_payload("Test body")
        mbox_obj.add(msg)
        mbox_obj.close()

        # Mock failed validation with multiple errors
        mock_result = ValidateResult(
            passed=False,
            count_check=False,
            database_check=False,
            integrity_check=False,
            spot_check=False,
            errors=["Error 1", "Error 2"],
            details={"extra": "info"},
        )

        with patch(
            "gmailarchiver.core.workflows.validate.ValidateWorkflow.run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            # Act & Assert
            with pytest.raises((SystemExit, Exception)) as exc_info:
                validate(
                    archive_file=str(archive_file),
                    state_db=v11_db,
                    verbose=False,  # Not verbose, but should still show report
                    json_output=False,
                )

            # Typer.Exit uses exit_code, SystemExit uses code
            assert getattr(exc_info.value, "exit_code", getattr(exc_info.value, "code", None)) == 1

        # Detailed report should be shown on failure (regardless of verbose flag)
        captured = capfd.readouterr()
        # The report is shown through OutputManager's show_validation_report
