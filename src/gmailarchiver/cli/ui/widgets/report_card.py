"""ReportCard widget for displaying key-value reports."""

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager


class ReportCard:
    """Displays a key-value report with title.

    Uses fluent builder pattern for easy composition.

    Example:
        ReportCard("Archive Summary")
            .with_emoji("📦")
            .add_field("Archived", "42 messages")
            .add_field("File", "archive_20251201.mbox")
            .add_field_if(skipped > 0, "Skipped", f"{skipped:,}")
            .render(ctx.output)

    Output:
        📦 Archive Summary
           Archived     42 messages
           File         archive_20251201.mbox
           Skipped      10
    """

    def __init__(self, title: str) -> None:
        """Initialize report card.

        Args:
            title: Title displayed at the top of the report
        """
        self.title = title
        self._fields: list[tuple[str, str, str]] = []  # (label, value, style)
        self._summary: str | None = None
        self._emoji: str | None = None

    def with_emoji(self, emoji: str) -> Self:
        """Set title emoji.

        Args:
            emoji: Emoji character (e.g., '📦')

        Returns:
            Self for fluent chaining
        """
        self._emoji = emoji
        return self

    def add_field(self, label: str, value: Any, style: str = "") -> Self:
        """Add a field to the report.

        Args:
            label: Field label (left column)
            value: Field value (right column)
            style: Optional Rich style for the value

        Returns:
            Self for fluent chaining
        """
        self._fields.append((label, str(value), style))
        return self

    def add_field_if(self, condition: bool, label: str, value: Any, style: str = "") -> Self:
        """Add a field only if condition is true.

        Args:
            condition: Whether to add this field
            label: Field label
            value: Field value
            style: Optional Rich style

        Returns:
            Self for fluent chaining
        """
        if condition:
            self._fields.append((label, str(value), style))
        return self

    # Backward compatibility alias
    add_conditional_field = add_field_if

    def set_summary(self, summary: str) -> Self:
        """Set a summary line below the report.

        Args:
            summary: Summary text

        Returns:
            Self for fluent chaining
        """
        self._summary = summary
        return self

    def to_dict(self) -> dict[str, str]:
        """Convert fields to dictionary for OutputManager.show_report.

        Returns:
            Dictionary of label -> value
        """
        return {label: value for label, value, _ in self._fields}

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, title, and fields
        """
        return {
            "type": "report_card",
            "title": self.title,
            "emoji": self._emoji,
            "fields": self.to_dict(),
            "summary": self._summary,
        }

    def render(self, output: OutputManager) -> None:
        """Render the report using OutputManager.

        Args:
            output: OutputManager instance
        """
        title = f"{self._emoji} {self.title}" if self._emoji else self.title
        data = self.to_dict()
        summary_dict = {"summary": self._summary} if self._summary else None
        output.show_report(title, data, summary_dict)
