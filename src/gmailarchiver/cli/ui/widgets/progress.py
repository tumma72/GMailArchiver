"""ProgressSummary widget for displaying operation statistics."""

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from gmailarchiver.cli.output import OutputManager

from gmailarchiver.cli.ui.widgets.report_card import ReportCard


class ProgressSummary:
    """Displays summary statistics for completed operations.

    Uses fluent builder pattern for easy composition.

    Example:
        ProgressSummary("Import Complete")
            .add_stat("Imported", 1000, "green")
            .add_stat("Skipped", 50, "yellow")
            .add_stat_if(failed > 0, "Failed", failed, "red")
            .render(ctx.output)

    Output:
        Import Complete
           Imported     1,000
           Skipped      50
    """

    def __init__(self, title: str) -> None:
        """Initialize progress summary.

        Args:
            title: Summary title
        """
        self.title = title
        self._stats: list[tuple[str, int, str]] = []

    def add_stat(self, label: str, count: int, style: str = "") -> Self:
        """Add a statistic.

        Args:
            label: Stat label
            count: Numeric count
            style: Optional Rich style

        Returns:
            Self for fluent chaining
        """
        self._stats.append((label, count, style))
        return self

    def add_stat_if(self, condition: bool, label: str, count: int, style: str = "") -> Self:
        """Add a statistic only if condition is true.

        Args:
            condition: Whether to add this stat
            label: Stat label
            count: Numeric count
            style: Optional Rich style

        Returns:
            Self for fluent chaining
        """
        if condition:
            self._stats.append((label, count, style))
        return self

    # Backward compatibility alias
    add_conditional_stat = add_stat_if

    def to_report_card(self) -> ReportCard:
        """Convert to a ReportCard for rendering.

        Returns:
            ReportCard with stats as fields
        """
        card = ReportCard(self.title)
        for label, count, style in self._stats:
            card.add_field(label, f"{count:,}", style)
        return card

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with type, title, and stats
        """
        return {
            "type": "progress_summary",
            "title": self.title,
            "stats": {label: count for label, count, _ in self._stats},
        }

    def render(self, output: OutputManager) -> None:
        """Render using OutputManager.

        Args:
            output: OutputManager instance
        """
        self.to_report_card().render(output)
