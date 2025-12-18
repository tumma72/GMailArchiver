"""ErrorPanel widget for displaying error messages."""

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager


class ErrorPanel:
    """Displays error with details and actionable suggestions.

    Uses fluent builder pattern for easy composition.

    Example:
        ErrorPanel("Validation Failed")
            .with_message("Archive validation did not pass")
            .add_detail("Count mismatch: expected 100, got 95")
            .add_detail("Missing messages: 5")
            .with_suggestion("Check disk space and run validation again")
            .render(ctx.output)

    Output:
        ╭── Validation Failed ─────────────────────────────────╮
        │ Archive validation did not pass                      │
        │                                                      │
        │ • Count mismatch: expected 100, got 95               │
        │ • Missing messages: 5                                │
        │                                                      │
        │ Suggestion: Check disk space and run validation again│
        ╰──────────────────────────────────────────────────────╯
    """

    def __init__(self, title: str, message: str | None = None) -> None:
        """Initialize error panel.

        Args:
            title: Error title (e.g., "Validation Failed")
            message: Main error message (can also be set via with_message)
        """
        self.title = title
        self.message = message or ""
        self._details: list[str] = []
        self._suggestion: str | None = None

    def with_message(self, message: str) -> Self:
        """Set the main error message.

        Args:
            message: Main error message

        Returns:
            Self for fluent chaining
        """
        self.message = message
        return self

    def add_detail(self, detail: str) -> Self:
        """Add a detail to the error.

        Args:
            detail: Detail string

        Returns:
            Self for fluent chaining
        """
        self._details.append(detail)
        return self

    def add_details(self, details: list[str]) -> Self:
        """Add multiple details.

        Args:
            details: List of detail strings

        Returns:
            Self for fluent chaining
        """
        self._details.extend(details)
        return self

    def with_suggestion(self, suggestion: str) -> Self:
        """Set the suggestion for fixing the error.

        Args:
            suggestion: Suggestion text

        Returns:
            Self for fluent chaining
        """
        self._suggestion = suggestion
        return self

    # Backward compatibility alias
    set_suggestion = with_suggestion

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, title, message, details, suggestion
        """
        return {
            "type": "error_panel",
            "title": self.title,
            "message": self.message,
            "details": self._details,
            "suggestion": self._suggestion,
        }

    def render(self, output: OutputManager) -> None:
        """Render error using OutputManager.

        Args:
            output: OutputManager instance
        """
        output.show_error_panel(
            title=self.title,
            message=self.message,
            details=self._details if self._details else None,
            suggestion=self._suggestion,
        )
