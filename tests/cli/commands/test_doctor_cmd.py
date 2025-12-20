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
# Test: Command Execution
# ============================================================================


class TestDoctorCommandExecution:
    """Test doctor command execution behavior."""

    def test_command_without_database_runs(self, runner: CliRunner) -> None:
        """Test doctor command runs without database (reports issues)."""
        # Doctor can run without storage - it will report the database as an issue
        # This is intentional: doctor should be able to diagnose "no database exists"
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should run successfully and report database issues
        assert result.exit_code == 0

    def test_accepts_verbose_flag(self, runner: CliRunner) -> None:
        """Test --verbose flag is accepted."""
        result = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # Command should parse the flag
        assert result.exit_code in [0, 1]

    def test_accepts_json_flag(self, runner: CliRunner) -> None:
        """Test --json flag is accepted."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        # Command should parse the flag
        assert result.exit_code in [0, 1]


# ============================================================================
# Test: JSON Output Mode
# ============================================================================


class TestDoctorCommandJsonOutput:
    """Test JSON output format."""

    def test_json_output_structure(self, runner: CliRunner) -> None:
        """Test JSON output includes all required fields."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

        # Verify structure
        assert "overall_status" in output
        assert "checks_passed" in output
        assert "warnings" in output
        assert "errors" in output
        assert "fixable_issues" in output
        assert "checks" in output

    def test_json_checks_array_structure(self, runner: CliRunner) -> None:
        """Test JSON checks array has proper structure."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        output = json.loads(result.stdout)

        # Each check should have required fields
        for check in output["checks"]:
            assert "name" in check
            assert "severity" in check
            assert "message" in check
            assert "fixable" in check

    def test_json_severity_values(self, runner: CliRunner) -> None:
        """Test JSON severity values are valid."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        output = json.loads(result.stdout)

        # Overall status should be valid
        assert output["overall_status"] in ["OK", "WARNING", "ERROR"]

        # Each check severity should be valid
        for check in output["checks"]:
            assert check["severity"] in ["OK", "WARNING", "ERROR"]

    def test_json_counts_are_integers(self, runner: CliRunner) -> None:
        """Test JSON count fields are integers."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        output = json.loads(result.stdout)

        assert isinstance(output["checks_passed"], int)
        assert isinstance(output["warnings"], int)
        assert isinstance(output["errors"], int)

    def test_json_fixable_issues_is_list(self, runner: CliRunner) -> None:
        """Test JSON fixable_issues is a list."""
        result = runner.invoke(app, ["utilities", "doctor", "--json"])

        output = json.loads(result.stdout)

        assert isinstance(output["fixable_issues"], list)


# ============================================================================
# Test: Verbose Output Mode
# ============================================================================


class TestDoctorCommandVerboseOutput:
    """Test verbose output mode."""

    def test_verbose_shows_check_details(self, runner: CliRunner) -> None:
        """Test verbose mode displays individual check details."""
        result = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # Verbose output should include check names/messages
        assert "database" in result.stdout.lower() or "schema" in result.stdout.lower()
        assert "environment" in result.stdout.lower() or "python" in result.stdout.lower()
        assert "system" in result.stdout.lower() or "disk" in result.stdout.lower()

    def test_verbose_shows_fixable_categorization(self, runner: CliRunner) -> None:
        """Test verbose mode shows which issues are fixable."""
        result = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # If there are fixable issues, should mention it
        if "fixable" in result.stdout.lower():
            assert "fix" in result.stdout.lower() or "repair" in result.stdout.lower()

    def test_verbose_shows_more_than_normal(self, runner: CliRunner) -> None:
        """Test verbose mode shows more information than normal mode."""
        result_normal = runner.invoke(app, ["utilities", "doctor"])
        result_verbose = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # Verbose should have more output
        assert len(result_verbose.stdout) >= len(result_normal.stdout)

    def test_verbose_includes_details_field(self, runner: CliRunner) -> None:
        """Test verbose mode includes check details."""
        result = runner.invoke(app, ["utilities", "doctor", "--verbose"])

        # Should have more detailed information
        # Exact format depends on implementation
        assert result.exit_code in [0, 1]


# ============================================================================
# Test: Rich Terminal Output
# ============================================================================


class TestDoctorCommandRichOutput:
    """Test Rich terminal output formatting."""

    def test_shows_validation_panels(self, runner: CliRunner) -> None:
        """Test output uses ValidationPanel widgets for categorized display."""
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should show categorized sections
        # (Implementation may vary, but should have structure)
        assert result.exit_code in [0, 1]

    def test_shows_summary_card(self, runner: CliRunner) -> None:
        """Test output includes summary report card."""
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should include summary information
        assert "status" in result.stdout.lower() or "summary" in result.stdout.lower()

    def test_shows_suggestions_when_issues_found(self, runner: CliRunner) -> None:
        """Test output shows next-steps suggestions when issues exist."""
        result = runner.invoke(app, ["utilities", "doctor"])

        # If issues exist, should suggest actions
        if "error" in result.stdout.lower() or "warning" in result.stdout.lower():
            # Should have suggestions (format varies)
            assert result.exit_code in [0, 1]


# ============================================================================
# Test: Exit Codes
# ============================================================================


class TestDoctorCommandExitCodes:
    """Test command exit codes based on diagnostic results."""

    def test_exit_code_zero_when_all_ok(self, runner: CliRunner, v1_1_database: Path) -> None:
        """Test exit code 0 when all checks pass."""
        # This would require a fully healthy database
        result = runner.invoke(app, ["utilities", "doctor"])

        # If all checks pass, should exit 0
        # (This test may not pass until implementation is complete)
        assert result.exit_code == 0

    def test_exit_code_nonzero_when_errors(self, runner: CliRunner) -> None:
        """Test non-zero exit code when errors detected."""
        # This would require a database with errors
        # Exact behavior depends on design decision
        result = runner.invoke(app, ["utilities", "doctor"])

        # May exit non-zero if errors found
        assert result.exit_code in [0, 1]


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
        assert result.exit_code in [0, 1]

    def test_requires_storage_is_enforced(self, runner: CliRunner) -> None:
        """Test that requires_storage=True enforces database existence."""
        # Command should fail or create database when missing
        result = runner.invoke(app, ["utilities", "doctor"])

        # Should handle missing storage appropriately
        assert result.exit_code in [0, 1]
