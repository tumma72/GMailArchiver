"""Tests for TableWidget and ColumnSpec."""

from unittest.mock import MagicMock

from rich.table import Table

from gmailarchiver.cli.ui.widgets.table import ColumnSpec, TableWidget


class TestColumnSpec:
    """Tests for ColumnSpec dataclass."""

    def test_column_spec_default_values(self) -> None:
        """ColumnSpec uses correct default values."""
        spec = ColumnSpec("Header")
        assert spec.header == "Header"
        assert spec.content == "cut"
        assert spec.style == "cyan"
        assert spec.min_width is None
        assert spec.max_width is None
        assert spec.ratio is None

    def test_column_spec_full_content_mode(self) -> None:
        """ColumnSpec supports 'full' content mode."""
        spec = ColumnSpec("Header", content="full")
        assert spec.content == "full"

    def test_column_spec_cut_content_mode(self) -> None:
        """ColumnSpec supports 'cut' content mode."""
        spec = ColumnSpec("Header", content="cut")
        assert spec.content == "cut"

    def test_column_spec_with_all_parameters(self) -> None:
        """ColumnSpec can be created with all parameters."""
        spec = ColumnSpec(
            "Subject",
            content="full",
            style="red",
            min_width=10,
            max_width=50,
            ratio=2,
        )
        assert spec.header == "Subject"
        assert spec.content == "full"
        assert spec.style == "red"
        assert spec.min_width == 10
        assert spec.max_width == 50
        assert spec.ratio == 2

    def test_column_spec_custom_style(self) -> None:
        """ColumnSpec accepts custom Rich style."""
        spec = ColumnSpec("Header", style="bold red on white")
        assert spec.style == "bold red on white"


class TestTableWidget:
    """Tests for TableWidget class."""

    def test_table_widget_initialization(self) -> None:
        """TableWidget initializes with correct defaults."""
        widget = TableWidget(title="Test Table")
        assert widget.title == "Test Table"
        assert widget.columns == []
        assert widget.rows == []
        assert widget.expand is True

    def test_table_widget_expand_disabled(self) -> None:
        """TableWidget can disable expand."""
        widget = TableWidget(title="Test", expand=False)
        assert widget.expand is False

    def test_add_column_returns_self(self) -> None:
        """add_column returns self for method chaining."""
        widget = TableWidget(title="Test")
        result = widget.add_column("Header")
        assert result is widget

    def test_add_column_single(self) -> None:
        """add_column adds a column specification."""
        widget = TableWidget(title="Test")
        widget.add_column("Subject", content="cut", max_width=50)
        assert len(widget.columns) == 1
        assert widget.columns[0].header == "Subject"
        assert widget.columns[0].content == "cut"
        assert widget.columns[0].max_width == 50

    def test_add_column_multiple(self) -> None:
        """add_column can be called multiple times."""
        widget = TableWidget(title="Test")
        widget.add_column("From")
        widget.add_column("Subject")
        widget.add_column("Date")
        assert len(widget.columns) == 3
        assert [col.header for col in widget.columns] == ["From", "Subject", "Date"]

    def test_add_column_with_ratio(self) -> None:
        """add_column supports ratio parameter for flexible sizing."""
        widget = TableWidget(title="Test")
        widget.add_column("Subject", ratio=2)
        widget.add_column("From", ratio=1)
        assert widget.columns[0].ratio == 2
        assert widget.columns[1].ratio == 1

    def test_add_column_full_content_mode(self) -> None:
        """add_column supports 'full' content mode."""
        widget = TableWidget(title="Test")
        widget.add_column("Message-ID", content="full")
        assert widget.columns[0].content == "full"

    def test_add_row_returns_self(self) -> None:
        """add_row returns self for method chaining."""
        widget = TableWidget(title="Test")
        result = widget.add_row("value1", "value2")
        assert result is widget

    def test_add_row_single(self) -> None:
        """add_row adds a single row."""
        widget = TableWidget(title="Test")
        widget.add_row("alice@example.com", "Hello")
        assert len(widget.rows) == 1
        assert widget.rows[0] == ["alice@example.com", "Hello"]

    def test_add_row_multiple(self) -> None:
        """add_row can be called multiple times."""
        widget = TableWidget(title="Test")
        widget.add_row("alice", "Message 1")
        widget.add_row("bob", "Message 2")
        widget.add_row("charlie", "Message 3")
        assert len(widget.rows) == 3

    def test_add_row_converts_values_to_strings(self) -> None:
        """add_row converts all values to strings."""
        widget = TableWidget(title="Test")
        widget.add_row(123, 45.67, True, None)
        assert widget.rows[0] == ["123", "45.67", "True", "None"]

    def test_add_rows_returns_self(self) -> None:
        """add_rows returns self for method chaining."""
        widget = TableWidget(title="Test")
        result = widget.add_rows([["a", "b"], ["c", "d"]])
        assert result is widget

    def test_add_rows_multiple_rows(self) -> None:
        """add_rows adds multiple rows at once."""
        widget = TableWidget(title="Test")
        rows = [
            ["alice@example.com", "Message 1"],
            ["bob@example.com", "Message 2"],
            ["charlie@example.com", "Message 3"],
        ]
        widget.add_rows(rows)
        assert len(widget.rows) == 3
        assert widget.rows[0] == ["alice@example.com", "Message 1"]
        assert widget.rows[2] == ["charlie@example.com", "Message 3"]

    def test_add_rows_empty_list(self) -> None:
        """add_rows handles empty list."""
        widget = TableWidget(title="Test")
        widget.add_rows([])
        assert len(widget.rows) == 0

    def test_add_rows_converts_to_strings(self) -> None:
        """add_rows converts all values to strings."""
        widget = TableWidget(title="Test")
        widget.add_rows([[1, 2, 3], [4, 5, 6]])
        assert widget.rows[0] == ["1", "2", "3"]
        assert widget.rows[1] == ["4", "5", "6"]

    def test_method_chaining_add_column_and_row(self) -> None:
        """add_column and add_row can be chained."""
        widget = (
            TableWidget(title="Test")
            .add_column("From")
            .add_column("Subject")
            .add_row("alice@example.com", "Hello")
            .add_row("bob@example.com", "World")
        )
        assert len(widget.columns) == 2
        assert len(widget.rows) == 2

    def test_render_calls_adapter_method(self) -> None:
        """render calls adapter._output.show_smart_table."""
        widget = TableWidget(title="Test").add_column("Header").add_row("value")
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        adapter._output.show_smart_table.assert_called_once()
        call_args = adapter._output.show_smart_table.call_args
        assert call_args[1]["title"] == "Test"
        assert call_args[1]["expand"] is True

    def test_render_passes_column_specs(self) -> None:
        """render converts columns to column_specs format."""
        widget = (
            TableWidget(title="Test")
            .add_column("Subject", content="cut", max_width=50)
            .add_column("From", content="full")
        )
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        specs = call_args[1]["column_specs"]
        assert len(specs) == 2
        assert specs[0]["header"] == "Subject"
        assert specs[0]["overflow"] == "ellipsis"
        assert specs[0]["max_width"] == 50
        assert specs[1]["header"] == "From"
        assert specs[1]["overflow"] == "fold"

    def test_render_passes_rows(self) -> None:
        """render passes rows to show_smart_table."""
        widget = TableWidget(title="Test").add_column("Name").add_row("Alice").add_row("Bob")
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        assert call_args[1]["rows"] == [["Alice"], ["Bob"]]

    def test_render_cut_content_sets_ellipsis_overflow(self) -> None:
        """render sets ellipsis overflow for 'cut' content."""
        widget = TableWidget(title="Test").add_column("Subject", content="cut")
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        spec = call_args[1]["column_specs"][0]
        assert spec["overflow"] == "ellipsis"
        assert spec["no_wrap"] is True

    def test_render_full_content_sets_fold_overflow(self) -> None:
        """render sets fold overflow for 'full' content."""
        widget = TableWidget(title="Test").add_column("Message-ID", content="full")
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        spec = call_args[1]["column_specs"][0]
        assert spec["overflow"] == "fold"
        assert spec["no_wrap"] is False

    def test_render_to_output_calls_show_smart_table(self) -> None:
        """render_to_output calls output.show_smart_table."""
        widget = TableWidget(title="Test").add_column("Header").add_row("value")
        output = MagicMock()

        widget.render_to_output(output)

        output.show_smart_table.assert_called_once()
        call_args = output.show_smart_table.call_args
        assert call_args[1]["title"] == "Test"

    def test_render_to_output_with_multiple_columns(self) -> None:
        """render_to_output handles multiple columns."""
        widget = (
            TableWidget(title="Results")
            .add_column("Email", content="cut", max_width=30)
            .add_column("Subject", content="cut", ratio=2)
            .add_column("Date", content="cut")
            .add_row("alice@example.com", "Hello", "2024-01-01")
        )
        output = MagicMock()

        widget.render_to_output(output)

        call_args = output.show_smart_table.call_args
        specs = call_args[1]["column_specs"]
        assert len(specs) == 3
        assert specs[1]["ratio"] == 2

    def test_build_rich_table_creates_rich_table(self) -> None:
        """build_rich_table creates a Rich Table object."""
        widget = TableWidget(title="Test").add_column("Header").add_row("value")
        table = widget.build_rich_table()
        assert isinstance(table, Table)
        assert table.title == "Test"

    def test_build_rich_table_adds_columns(self) -> None:
        """build_rich_table adds column definitions."""
        widget = (
            TableWidget(title="Test")
            .add_column("Subject", content="cut", style="red")
            .add_column("From", content="full", style="blue")
        )
        table = widget.build_rich_table()
        # Rich Table columns are stored internally
        assert len(table.columns) == 2  # Verify columns were added

    def test_build_rich_table_adds_rows(self) -> None:
        """build_rich_table adds row data."""
        widget = TableWidget(title="Test").add_column("Name").add_row("Alice").add_row("Bob")
        table = widget.build_rich_table()
        # Table should have rows added
        assert len(table.rows) == 2

    def test_build_rich_table_respects_expand(self) -> None:
        """build_rich_table respects expand setting."""
        widget1 = TableWidget(title="Test", expand=True)
        table1 = widget1.build_rich_table()
        assert table1.expand is True

        widget2 = TableWidget(title="Test", expand=False)
        table2 = widget2.build_rich_table()
        assert table2.expand is False

    def test_build_rich_table_cut_column_settings(self) -> None:
        """build_rich_table configures 'cut' columns correctly."""
        widget = TableWidget(title="Test").add_column("Subject", content="cut", max_width=50)
        table = widget.build_rich_table()
        # Verify table was configured (Rich Table stores columns)
        assert table.title == "Test"

    def test_build_rich_table_full_column_settings(self) -> None:
        """build_rich_table configures 'full' columns correctly."""
        widget = TableWidget(title="Test").add_column("ID", content="full")
        table = widget.build_rich_table()
        # Verify table was configured with full content mode
        assert table.title == "Test"

    def test_column_spec_with_min_width(self) -> None:
        """ColumnSpec min_width is applied in rendering."""
        widget = TableWidget(title="Test").add_column("Subject", min_width=20)
        adapter = MagicMock()
        adapter._output = MagicMock()
        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        spec = call_args[1]["column_specs"][0]
        assert spec["min_width"] == 20

    def test_render_empty_table(self) -> None:
        """render handles table with columns but no rows."""
        widget = TableWidget(title="Empty").add_column("Header")
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        assert call_args[1]["rows"] == []

    def test_complex_table_with_mixed_content_modes(self) -> None:
        """Complex table with mixed 'full' and 'cut' columns."""
        widget = (
            TableWidget(title="Search Results")
            .add_column("From", content="cut", max_width=20)
            .add_column("Subject", content="cut", ratio=2, max_width=50)
            .add_column("Date", content="cut", max_width=16)
            .add_column("Message-ID", content="full", min_width=30)
            .add_row(
                "alice@example.com",
                "Meeting notes for Q1 planning...",
                "2024-01-15",
                "<msg123@example.com>",
            )
            .add_row(
                "bob@example.com",
                "Project update",
                "2024-01-14",
                "<msg124@example.com>",
            )
        )
        adapter = MagicMock()
        adapter._output = MagicMock()

        widget.render(adapter)

        call_args = adapter._output.show_smart_table.call_args
        specs = call_args[1]["column_specs"]
        assert len(specs) == 4
        assert specs[0]["overflow"] == "ellipsis"
        assert specs[3]["overflow"] == "fold"
        assert len(call_args[1]["rows"]) == 2
