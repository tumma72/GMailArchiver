"""SuggestionList widget for displaying next-step suggestions."""

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager


class SuggestionList:
    """Displays contextual next-step suggestions.

    Uses fluent builder pattern for easy composition.
    Supports conditional suggestions that only appear when relevant.

    Example:
        SuggestionList()
            .with_context("Since 10 duplicates were found")
            .add("Review duplicates: gmailarchiver dedupe --dry-run")
            .add("Check status: gmailarchiver status")
            .add_if(has_errors, "Fix errors: gmailarchiver repair")
            .render(ctx.output)

    Output:
        💡 Since 10 duplicates were found, you might want to:
           • Review duplicates: gmailarchiver dedupe --dry-run
           • Check status: gmailarchiver status
    """

    def __init__(self, title: str = "Suggestions") -> None:
        """Initialize suggestion list.

        Args:
            title: Title for the suggestions section
        """
        self.title = title
        self._suggestions: list[str] = []
        self._context: str | None = None

    def with_context(self, context: str) -> Self:
        """Set contextual header for suggestions.

        Args:
            context: Context string (e.g., "Since 10 duplicates were found")

        Returns:
            Self for fluent chaining
        """
        self._context = context
        return self

    def add(self, suggestion: str) -> Self:
        """Add a suggestion.

        Args:
            suggestion: The suggestion text (usually a command example)

        Returns:
            Self for fluent chaining
        """
        self._suggestions.append(suggestion)
        return self

    def add_if(self, condition: bool, suggestion: str) -> Self:
        """Add a suggestion only if condition is true.

        Args:
            condition: Whether to add this suggestion
            suggestion: The suggestion text

        Returns:
            Self for fluent chaining
        """
        if condition:
            self._suggestions.append(suggestion)
        return self

    # Backward compatibility alias
    add_conditional = add_if

    def is_empty(self) -> bool:
        """Check if there are any suggestions.

        Returns:
            True if no suggestions have been added
        """
        return len(self._suggestions) == 0

    def to_list(self) -> list[str]:
        """Get suggestions as a list.

        Returns:
            List of suggestion strings
        """
        return list(self._suggestions)

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, title, context, and suggestions
        """
        return {
            "type": "suggestion_list",
            "title": self.title,
            "context": self._context,
            "suggestions": self._suggestions,
        }

    def render(self, output: OutputManager) -> None:
        """Render suggestions using OutputManager.

        Args:
            output: OutputManager instance
        """
        if self._suggestions:
            output.suggest_next_steps(self._suggestions)
