"""Table widget with flexible column configuration.

This widget provides intelligent table rendering with:
- Column content modes: "full" (must show complete content) or "cut" (can truncate)
- Automatic terminal width expansion
- Overflow strategy: compress cut columns first, then wrap full columns
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from rich.table import Table

if TYPE_CHECKING:
    from ..adapters import CLIProgressAdapter


@dataclass
class ColumnSpec:
    """Specification for a table column.

    Attributes:
        header: Column header text
        content: How to handle content overflow:
            - "full": Content must be fully visible (wraps if needed)
            - "cut": Content can be truncated with ellipsis
        style: Rich style string (default: "cyan")
        min_width: Minimum column width (optional)
        max_width: Maximum column width (optional, only for content="cut")
        ratio: Relative width ratio for flexible sizing (optional)
    """

    header: str
    content: Literal["full", "cut"] = "cut"
    style: str = "cyan"
    min_width: int | None = None
    max_width: int | None = None
    ratio: int | None = None


@dataclass
class TableWidget:
    """Flexible table widget with intelligent column sizing.

    Features:
    - Expands to full terminal width by default
    - Columns with content="full" are never truncated (wrap if needed)
    - Columns with content="cut" are truncated with ellipsis when space is limited
    - Overflow strategy: compress "cut" columns first, then wrap "full" columns

    Example:
        table = TableWidget(
            title="Search Results",
            columns=[
                ColumnSpec("Subject", content="cut", ratio=2),
                ColumnSpec("From", content="cut"),
                ColumnSpec("Date", content="cut", max_width=16),
                ColumnSpec("Message-ID", content="full"),
            ]
        )
        table.add_row(
            "Meeting notes...", "alice@example.com", "2024-01-15 10:30", "<msg123@example.com>"
        )
        table.render(adapter)
    """

    title: str
    columns: list[ColumnSpec] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    expand: bool = True

    def add_column(
        self,
        header: str,
        content: Literal["full", "cut"] = "cut",
        style: str = "cyan",
        min_width: int | None = None,
        max_width: int | None = None,
        ratio: int | None = None,
    ) -> TableWidget:
        """Add a column specification.

        Args:
            header: Column header text
            content: "full" (never truncate) or "cut" (can truncate)
            style: Rich style string
            min_width: Minimum column width
            max_width: Maximum column width (only for content="cut")
            ratio: Relative width ratio

        Returns:
            Self for method chaining
        """
        self.columns.append(
            ColumnSpec(
                header=header,
                content=content,
                style=style,
                min_width=min_width,
                max_width=max_width,
                ratio=ratio,
            )
        )
        return self

    def add_row(self, *values: Any) -> TableWidget:
        """Add a row of data.

        Args:
            *values: Cell values (will be converted to strings)

        Returns:
            Self for method chaining
        """
        self.rows.append([str(v) for v in values])
        return self

    def add_rows(self, rows: Sequence[Sequence[Any]]) -> TableWidget:
        """Add multiple rows of data.

        Args:
            rows: List of rows, each row is a sequence of cell values

        Returns:
            Self for method chaining
        """
        for row in rows:
            self.rows.append([str(v) for v in row])
        return self

    def render(self, adapter: CLIProgressAdapter) -> None:
        """Render the table using the CLI adapter.

        Args:
            adapter: CLIProgressAdapter for output
        """
        # Convert to column_specs format for show_smart_table
        column_specs = []
        for col in self.columns:
            spec: dict[str, Any] = {
                "header": col.header,
                "key": col.content == "full",  # key=True means don't truncate
                "style": col.style,
            }
            if col.min_width is not None:
                spec["min_width"] = col.min_width
            if col.max_width is not None:
                spec["max_width"] = col.max_width
            if col.ratio is not None:
                spec["ratio"] = col.ratio

            # Override overflow behavior based on content mode
            if col.content == "full":
                spec["overflow"] = "fold"  # Wrap to multiple lines
                spec["no_wrap"] = False
            else:
                spec["overflow"] = "ellipsis"  # Truncate with ...
                spec["no_wrap"] = True

            column_specs.append(spec)

        adapter._output.show_smart_table(
            title=self.title,
            column_specs=column_specs,
            rows=self.rows,
            expand=self.expand,
        )

    def render_to_output(self, output: Any) -> None:
        """Render the table directly to OutputManager.

        Args:
            output: OutputManager instance
        """
        # Convert to column_specs format for show_smart_table
        column_specs = []
        for col in self.columns:
            spec: dict[str, Any] = {
                "header": col.header,
                "key": col.content == "full",
                "style": col.style,
            }
            if col.min_width is not None:
                spec["min_width"] = col.min_width
            if col.max_width is not None:
                spec["max_width"] = col.max_width
            if col.ratio is not None:
                spec["ratio"] = col.ratio

            if col.content == "full":
                spec["overflow"] = "fold"
                spec["no_wrap"] = False
            else:
                spec["overflow"] = "ellipsis"
                spec["no_wrap"] = True

            column_specs.append(spec)

        output.show_smart_table(
            title=self.title,
            column_specs=column_specs,
            rows=self.rows,
            expand=self.expand,
        )

    def build_rich_table(self) -> Table:
        """Build a Rich Table object directly.

        Returns:
            Configured Rich Table
        """
        table = Table(title=self.title, expand=self.expand, show_lines=False)

        for col in self.columns:
            overflow: Literal["fold", "ellipsis"]
            if col.content == "full":
                overflow = "fold"
                no_wrap = False
            else:
                overflow = "ellipsis"
                no_wrap = True

            table.add_column(
                col.header,
                style=col.style,
                overflow=overflow,
                no_wrap=no_wrap,
                min_width=col.min_width,
                max_width=col.max_width,
                ratio=col.ratio,
            )

        for row in self.rows:
            table.add_row(*row)

        return table
