"""ValidationPanel widget for displaying multi-check validation results."""

from enum import Enum
from typing import TYPE_CHECKING, Any, Self

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager


class CheckStatus(Enum):
    """Status of a validation check."""

    PASSED = ("✓", "green")
    FAILED = ("✗", "red")
    SKIPPED = ("○", "dim")

    @property
    def symbol(self) -> str:
        """Return the status symbol."""
        return self.value[0]

    @property
    def style(self) -> str:
        """Return the Rich style for this status."""
        return self.value[1]


class ValidationPanel:
    """Displays multi-check validation results in a bordered panel.

    Uses fluent builder pattern for easy composition.
    Supports passed, failed, and skipped check states with optional details.

    Example:
        ValidationPanel("Archive Validation")
            .add_check("Count check", passed=True, detail="19,334 messages verified")
            .add_check("Database check", passed=True)
            .add_check("Integrity check", passed=False, detail="5 checksum mismatches")
            .add_check("Spot check", skipped=True, reason="Previous check failed")
            .render(ctx.output)

    Output:
        ╭── Archive Validation ──────────────────────────────────────────────╮
        │ ✓ Count check       19,334 messages verified                       │
        │ ✓ Database check    Passed                                         │
        │ ✗ Integrity check   5 checksum mismatches                          │
        │ ○ Spot check        Skipped (Previous check failed)                │
        ╰────────────────────────────────────────────────────────────────────╯

    With errors:
        ╭── Archive Validation ──────────────────────────────────────────────╮
        │ ✓ Count check       Passed                                         │
        │ ✗ Integrity check   5 checksum mismatches                          │
        │                                                                    │
        │ Errors:                                                            │
        │   • Message abc123 has invalid checksum                            │
        │   • Message def456 is corrupted                                    │
        ╰────────────────────────────────────────────────────────────────────╯
    """

    def __init__(self, title: str) -> None:
        """Initialize validation panel.

        Args:
            title: Panel title (e.g., "Archive Validation")
        """
        self.title = title
        self._checks: list[tuple[str, CheckStatus, str]] = []  # (name, status, detail)
        self._errors: list[str] = []

    def add_check(
        self,
        name: str,
        *,
        passed: bool | None = None,
        skipped: bool = False,
        detail: str | None = None,
        reason: str | None = None,
    ) -> Self:
        """Add a validation check result.

        Args:
            name: Check name (e.g., "Count check")
            passed: True if check passed, False if failed, None if skipped
            skipped: True if check was skipped (alternative to passed=None)
            detail: Optional detail shown on success/failure (e.g., "19,334 messages")
            reason: Optional reason for skipping (e.g., "Previous check failed")

        Returns:
            Self for fluent chaining

        Examples:
            .add_check("Count check", passed=True, detail="19,334 messages")
            .add_check("Integrity check", passed=False, detail="5 mismatches")
            .add_check("Spot check", skipped=True, reason="Previous check failed")
        """
        if skipped or passed is None:
            status = CheckStatus.SKIPPED
            display_detail = f"Skipped ({reason})" if reason else "Skipped"
        elif passed:
            status = CheckStatus.PASSED
            display_detail = detail if detail else "Passed"
        else:
            status = CheckStatus.FAILED
            display_detail = detail if detail else "Failed"

        self._checks.append((name, status, display_detail))
        return self

    def add_error(self, error: str) -> Self:
        """Add an error message to display below checks.

        Args:
            error: Error message

        Returns:
            Self for fluent chaining
        """
        self._errors.append(error)
        return self

    def add_errors(self, errors: list[str]) -> Self:
        """Add multiple error messages.

        Args:
            errors: List of error messages

        Returns:
            Self for fluent chaining
        """
        self._errors.extend(errors)
        return self

    @property
    def all_passed(self) -> bool:
        """Check if all validations passed (no failures).

        Returns:
            True if no checks failed (skipped checks are OK)
        """
        return all(status != CheckStatus.FAILED for _, status, _ in self._checks)

    @property
    def passed_count(self) -> int:
        """Count of passed checks."""
        return sum(1 for _, status, _ in self._checks if status == CheckStatus.PASSED)

    @property
    def failed_count(self) -> int:
        """Count of failed checks."""
        return sum(1 for _, status, _ in self._checks if status == CheckStatus.FAILED)

    @property
    def total_count(self) -> int:
        """Total number of checks."""
        return len(self._checks)

    def summary_text(self) -> str:
        """Generate a summary line like 'Passed 4/4 checks' or 'Failed 1/4 checks'.

        Returns:
            Summary string suitable for task completion message
        """
        if self.all_passed:
            return f"Passed {self.passed_count}/{self.total_count} checks"
        else:
            return f"Failed {self.failed_count}/{self.total_count} checks"

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, title, checks, and errors
        """
        checks_json = []
        for name, status, detail in self._checks:
            checks_json.append(
                {
                    "name": name,
                    "status": status.name.lower(),
                    "detail": detail,
                }
            )

        return {
            "type": "validation_panel",
            "title": self.title,
            "checks": checks_json,
            "errors": self._errors,
            "all_passed": self.all_passed,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
        }

    def _build_table(self) -> Table:
        """Build the Rich Table for checks.

        Returns:
            Rich Table with check results
        """
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Status", width=3)
        table.add_column("Check", style="bold", width=18)
        table.add_column("Detail", style="dim")

        for name, status, detail in self._checks:
            status_text = f"[{status.style}]{status.symbol}[/{status.style}]"
            table.add_row(status_text, name, detail)

        return table

    def render(self, output: OutputManager) -> None:
        """Render the validation panel using OutputManager.

        Args:
            output: OutputManager instance
        """
        if output.json_mode:
            output._json_events.append(
                {
                    "event": "validation_panel",
                    **self.to_json(),
                }
            )
            return

        if output.quiet or not output.console:
            return

        # Build content parts
        content_parts: list[Any] = [self._build_table()]

        # Add errors if present
        if self._errors:
            content_parts.append(Text())  # blank line
            content_parts.append(Text("Errors:", style="bold yellow"))
            for err in self._errors:
                content_parts.append(Text(f"  • {err}", style="dim"))

        # Determine panel style based on overall result
        border_style = "green" if self.all_passed else "red"

        panel = Panel(
            Group(*content_parts),
            title=f"[bold]{self.title}[/bold]",
            border_style=border_style,
            padding=(1, 2),
        )
        output.console.print()
        output.console.print(panel)
        output.console.print()

    def render_if_failures_or_verbose(
        self,
        output: OutputManager,
        verbose: bool = False,
    ) -> None:
        """Render only if there are failures OR verbose mode is enabled.

        This follows the UI_UX_CLI.md guideline: show validation panel on
        failures (always) or with --verbose (success case).

        Args:
            output: OutputManager instance
            verbose: Whether verbose mode is enabled
        """
        if not self.all_passed or verbose:
            self.render(output)
