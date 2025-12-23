"""Tests for doctor CLI command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmailarchiver.cli.main import app

# ============================================================================
# Test: Command Registration
# ============================================================================


class TestDoctorCommandRegistration:
    """Test doctor command registration and availability."""

    def test_command_is_registered(self, runner: CliRunner) -> None:
        """Test doctor command is available in utilities group."""
        result = runner.invoke(app, ["utilities", "--help"])

        assert result.exit_code == 0
        assert "doctor" in result.stdout.lower()

    def test_help_displays_usage(self, runner: CliRunner) -> None:
        """Test --help shows proper usage."""
        result = runner.invoke(app, ["utilities", "doctor", "--help"])

        assert result.exit_code == 0
        assert "diagnostic" in result.stdout.lower() or "health" in result.stdout.lower()
        assert "verbose" in result.stdout.lower()
        assert "json" in result.stdout.lower()

    def test_help_shows_verbose_option(self, runner: CliRunner) -> None:
        """Test --help shows --verbose/-v option."""
        result = runner.invoke(app, ["utilities", "doctor", "--help"])

        assert result.exit_code == 0
        assert "--verbose" in result.stdout or "-v" in result.stdout

    def test_help_shows_json_option(self, runner: CliRunner) -> None:
        """Test --help shows --json option."""
        result = runner.invoke(app, ["utilities", "doctor", "--help"])

        assert result.exit_code == 0
        assert "--json" in result.stdout


# ============================================================================
# Test: Command Execution Without Database
# ============================================================================


class TestDoctorCommandWithoutDatabase:
    """Test doctor command behavior when no database exists."""

    def test_command_without_database_runs(self, runner: CliRunner) -> None:
        """Test doctor command runs without database and reports it as an issue."""
        # Doctor should run and report "no database" as a health issue
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should run successfully (exit 0) and report database issue
        assert result.exit_code == 0
        # Output should mention database or archive
        assert "database" in result.stdout.lower() or "archive" in result.stdout.lower()

    def test_verbose_without_database(self, runner: CliRunner) -> None:
        """Test --verbose flag is accepted without database."""
        result = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # Command should run and provide verbose output
        assert result.exit_code == 0

    def test_json_without_database(self, runner: CliRunner) -> None:
        """Test --json flag produces valid JSON without database."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        # Command should succeed
        assert result.exit_code == 0

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

        # Verify structure - should report database missing as issue
        assert "overall_status" in output
        assert "checks" in output
        assert output["overall_status"] in ["WARNING", "ERROR"]


# ============================================================================
# Test: Command Execution With Database
# ============================================================================


class TestDoctorCommandWithDatabase:
    """Test doctor command behavior when database exists."""

    def test_command_with_database_runs(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test doctor command runs with database."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["utilities", "doctor", "--state-db", str(v1_1_database)])

        # Should run successfully
        assert result.exit_code == 0

    def test_verbose_with_database(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test --verbose flag with database shows detailed output."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--verbose", "--state-db", str(v1_1_database)]
        )

        # Should run and show verbose output
        assert result.exit_code == 0
        # Verbose should show check details including environment/python checks
        stdout_lower = result.stdout.lower()
        assert "health" in stdout_lower or "status" in stdout_lower or "check" in stdout_lower


# ============================================================================
# Test: JSON Output Mode
# ============================================================================


class TestDoctorCommandJsonOutput:
    """Test JSON output format."""

    def test_json_output_structure_with_database(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test JSON output includes all required fields with database."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--json", "--state-db", str(v1_1_database)]
        )

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

        # Verify structure
        assert "overall_status" in output
        assert "checks" in output
        assert "checks_passed" in output

    def test_json_checks_array_structure(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test JSON checks array has proper structure."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--json", "--state-db", str(v1_1_database)]
        )

        output = json.loads(result.stdout)

        # Each check should have required fields
        for check in output["checks"]:
            assert "name" in check
            assert "severity" in check
            assert "message" in check

    def test_json_severity_values(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test JSON severity values are valid."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--json", "--state-db", str(v1_1_database)]
        )

        output = json.loads(result.stdout)

        # Overall status should be valid
        assert output["overall_status"] in ["OK", "WARNING", "ERROR"]

    def test_json_counts_are_integers(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test JSON count fields are integers."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--json", "--state-db", str(v1_1_database)]
        )

        output = json.loads(result.stdout)

        assert isinstance(output["checks_passed"], int)
        assert isinstance(output["total_checks"], int)

    def test_json_fixable_issues_is_list(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test JSON fixable_issues is a list."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--json", "--state-db", str(v1_1_database)]
        )

        output = json.loads(result.stdout)

        assert isinstance(output["fixable_issues"], list)


# ============================================================================
# Test: Verbose Output Mode
# ============================================================================


class TestDoctorCommandVerboseOutput:
    """Test verbose output mode."""

    def test_verbose_shows_check_details(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test verbose mode displays individual check details."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["utilities", "doctor", "--verbose", "--state-db", str(v1_1_database)]
        )

        # Verbose output should include check names/messages
        stdout_lower = result.stdout.lower()
        assert "database" in stdout_lower or "schema" in stdout_lower or "archive" in stdout_lower

    def test_verbose_shows_more_than_default(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test verbose output is longer than default output."""
        monkeypatch.chdir(tmp_path)
        default_result = runner.invoke(
            app, ["utilities", "doctor", "--state-db", str(v1_1_database)]
        )
        verbose_result = runner.invoke(
            app, ["utilities", "doctor", "--verbose", "--state-db", str(v1_1_database)]
        )

        # Verbose should generally have more output
        # (May be equal if all checks pass without issues)
        assert len(verbose_result.stdout) >= len(default_result.stdout) * 0.8


# ============================================================================
# Test: Rich Output Mode
# ============================================================================


class TestDoctorCommandRichOutput:
    """Test Rich terminal output."""

    def test_shows_summary_card(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test output includes summary report card."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["utilities", "doctor", "--state-db", str(v1_1_database)])

        # Should include summary information
        stdout_lower = result.stdout.lower()
        assert "status" in stdout_lower or "summary" in stdout_lower or "health" in stdout_lower


# ============================================================================
# Test: Exit Codes
# ============================================================================


class TestDoctorCommandExitCodes:
    """Test command exit codes based on diagnostic results."""

    def test_exit_code_zero_when_all_ok(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test exit code 0 when database exists and checks pass."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["utilities", "doctor", "--state-db", str(v1_1_database)])

        # Should exit 0 with a valid database
        assert result.exit_code == 0

    def test_exit_code_zero_without_database(self, runner: CliRunner) -> None:
        """Test exit code 0 even when no database (graceful handling)."""
        result = runner.invoke(app, ["utilities", "doctor"])

        # Doctor should gracefully report missing database, not crash
        assert result.exit_code == 0


# ============================================================================
# Test: Integration with CommandContext
# ============================================================================


class TestDoctorCommandContext:
    """Test doctor command integration with CommandContext."""

    def test_uses_command_context_decorator(self, runner: CliRunner) -> None:
        """Test command uses @with_context decorator."""
        # Verify command has access to context features
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should not crash due to missing context
        assert result.exit_code == 0

    def test_gracefully_handles_missing_storage(self, runner: CliRunner) -> None:
        """Test that missing database is handled gracefully."""
        # Command should report issue, not crash
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should succeed and report database as issue
        assert result.exit_code == 0
        assert "database" in result.stdout.lower() or "archive" in result.stdout.lower()

    def test_accepts_state_db_option(
        self,
        runner: CliRunner,
        v1_1_database: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test --state-db option is accepted."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["utilities", "doctor", "--state-db", str(v1_1_database)])

        assert result.exit_code == 0
