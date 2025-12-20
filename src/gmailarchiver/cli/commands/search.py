"""Search command implementation."""

import asyncio
from enum import Enum
from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import CLIProgressAdapter, ReportCard, SuggestionList
from gmailarchiver.cli.ui.widgets import TableWidget
from gmailarchiver.core.workflows.search import SearchConfig, SearchResult, SearchWorkflow


class SortOrder(str, Enum):
    """Sort order for search results."""

    descending = "descending"
    ascending = "ascending"


@with_context(requires_storage=True, requires_schema="1.1", operation_name="search")
def search(
    ctx: CommandContext,
    query: str = typer.Argument(..., help="Search query (Gmail syntax supported)"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of results"),
    sort: SortOrder = typer.Option(
        SortOrder.descending,
        "--sort",
        "-s",
        help="Sort order by date (descending=newest first, ascending=oldest first)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    with_preview: bool = typer.Option(
        False, "--with-preview", help="Include message body preview in results"
    ),
    with_message_id: bool = typer.Option(
        False, "--with-message-id", help="Include RFC Message-ID column in results"
    ),
    interactive: bool = typer.Option(
        False, "--interactive", help="Interactive mode for message selection and extraction"
    ),
) -> None:
    """
    Search archived messages.

    Supports Gmail-style query syntax with full-text search via BM25 ranking.
    Results are sorted by date (newest first by default).

    Examples:
        $ gmailarchiver search "from:sender@example.com"
        $ gmailarchiver search "subject:invoice" --limit 20
        $ gmailarchiver search "body:urgent" --json
        $ gmailarchiver search "meeting" --with-preview
        $ gmailarchiver search "project" --with-message-id
        $ gmailarchiver search "project" --sort ascending
        $ gmailarchiver search "project" --interactive
    """
    asyncio.run(
        _run_search(
            ctx=ctx,
            query=query,
            state_db=state_db,
            limit=limit,
            sort=sort,
            json_output=json_output,
            with_preview=with_preview,
            with_message_id=with_message_id,
            interactive=interactive,
        )
    )


async def _run_search(
    ctx: CommandContext,
    query: str,
    state_db: str,
    limit: int,
    sort: SortOrder,
    json_output: bool,
    with_preview: bool,
    with_message_id: bool,
    interactive: bool,
) -> None:
    """Async implementation of search command following thin client pattern."""
    # Phase 1: Validate inputs
    if interactive and json_output:
        ctx.fail_and_exit(
            title="Invalid Flags",
            message="--interactive cannot be used with --json",
            suggestion="Use either --interactive OR --json, not both",
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Phase 2: Create workflow and config
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = SearchWorkflow(ctx.storage, progress=progress)
    config = SearchConfig(query=query, limit=limit, sort_ascending=(sort == SortOrder.ascending))

    # Phase 3: Execute workflow with shared task sequence
    try:
        with progress.workflow_sequence(show_logs=False, max_logs=3):
            result = await workflow.run(config)
    except Exception as e:
        ctx.fail_and_exit(
            title="Search Error",
            message=f"Search failed: {e}",
            suggestion="Check database file integrity or run 'gmailarchiver doctor'",
        )

    # Phase 4: Handle results based on output mode
    if not result.messages:
        if not interactive:
            _handle_no_results(ctx, query)
        return

    # Sort results by date
    sorted_messages = _sort_by_date(result.messages, sort)

    if json_output:
        _handle_json_output(ctx, result, sorted_messages, with_preview)
        return

    if interactive:
        await _handle_interactive_mode(ctx, sorted_messages, query)
        return

    # Phase 5: Display results (table or list format)
    if with_preview:
        _display_results_with_preview(ctx, result, sorted_messages)
    else:
        _display_results_table(ctx, result, query, sorted_messages, with_message_id)

    # Show summary if truncated
    if result.total_count > len(result.messages):
        ctx.info(
            f"Showing {len(result.messages)} of {result.total_count:,} matches "
            f"(use --limit to see more)"
        )


def _handle_no_results(ctx: CommandContext, query: str) -> None:
    """Handle case where no results were found."""
    ctx.warning(f"No results found for: {query}")
    SuggestionList().add("Try a broader search term").add(
        "Check if messages are archived: gmailarchiver status"
    ).render(ctx.output)


def _sort_by_date(messages: list[dict[str, object]], sort: SortOrder) -> list[dict[str, object]]:
    """Sort messages by date.

    Args:
        messages: List of message dictionaries
        sort: Sort order (descending=newest first, ascending=oldest first)

    Returns:
        Sorted list of messages
    """
    from email.utils import parsedate_to_datetime

    def get_date_key(msg: dict[str, object]) -> str:
        """Extract sortable date string from message."""
        date_str = msg.get("date")
        if not date_str:
            return ""
        try:
            dt = parsedate_to_datetime(str(date_str))
            return dt.isoformat()
        except (ValueError, TypeError):
            return str(date_str)

    reverse = sort == SortOrder.descending
    return sorted(messages, key=get_date_key, reverse=reverse)


def _handle_json_output(
    ctx: CommandContext,
    result: SearchResult,
    messages: list[dict[str, object]],
    with_preview: bool,
) -> None:
    """Handle JSON output mode."""
    output_data = []
    for msg in messages:
        entry = {
            "gmail_id": msg.get("gmail_id"),
            "rfc_message_id": msg.get("rfc_message_id"),
            "subject": msg.get("subject"),
            "from_addr": msg.get("from_addr"),
            "to_addr": msg.get("to_addr"),
            "date": msg.get("date"),
            "archive_file": msg.get("archive_file"),
            "mbox_offset": msg.get("mbox_offset"),
            "relevance_score": msg.get("relevance_score"),
        }
        if with_preview:
            entry["body_preview"] = _truncate_preview(str(msg.get("body_preview", "")))
        output_data.append(entry)
    ctx.output.set_json_payload(output_data)


def _display_results_with_preview(
    ctx: CommandContext, result: SearchResult, messages: list[dict[str, object]]
) -> None:
    """Display results in list format with body preview."""
    ctx.info(f"\nSearch Results ({result.total_count} found)\n")
    for idx, msg in enumerate(messages, 1):
        preview = _truncate_preview(str(msg.get("body_preview", "")))
        subject = msg.get("subject") or "(no subject)"
        date_str = _format_date_short(msg.get("date"))

        ctx.info(f"{idx}. Date: {date_str or 'N/A'}")
        ctx.info(f"   From: {msg.get('from_addr')}")
        ctx.info(f"   Subject: {subject}")
        ctx.info(f"   RFC Message-ID: {msg.get('rfc_message_id')}")
        ctx.info(f"   Gmail ID: {msg.get('gmail_id') or 'N/A'}")
        ctx.info(f"   Archive: {msg.get('archive_file')}")
        ctx.info(f"   Preview: {preview}")
        ctx.info("")


def _format_date_short(date_str: object) -> str:
    """Format date as ISO with hour:minute (no seconds).

    Converts RFC 2822 format (e.g., 'Wed, 7 Dec 2022 14:36:47 +0100')
    to ISO format (e.g., '2022-12-07 14:36').
    """
    if not date_str:
        return ""

    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(str(date_str))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        # Fall back to truncation if parsing fails
        return str(date_str)[:16]


def _display_results_table(
    ctx: CommandContext,
    result: SearchResult,
    query: str,
    messages: list[dict[str, object]],
    with_message_id: bool = False,
) -> None:
    """Display results in table format using TableWidget.

    Column order: Date, From, Subject, [Message-ID]
    When with_message_id is True, adds a Message-ID column with content="full"
    so the full ID is visible (wraps if needed) for copy/paste into extract command.
    """
    table = TableWidget(title=f"Search Results for: {query}")

    # Add columns in order: Date, From, Subject, [Message-ID]
    # Date: fixed width, ISO format fits
    table.add_column("Date", content="cut", max_width=16)
    # From: can be truncated
    table.add_column("From", content="cut")
    # Subject: can be truncated, gets more space
    table.add_column("Subject", content="cut", ratio=2)

    if with_message_id:
        # Message-ID: must be fully visible for copy/paste
        table.add_column("Message-ID", content="full")

    # Add rows
    for msg in messages:
        row = [
            _format_date_short(msg.get("date")),
            str(msg.get("from_addr", "")),
            str(msg.get("subject", "") or "(no subject)"),
        ]
        if with_message_id:
            row.append(str(msg.get("rfc_message_id", "")))
        table.add_row(*row)

    table.render_to_output(ctx.output)


def _truncate_preview(preview: str | None, max_length: int = 200) -> str:
    """Truncate preview text to max length with ellipsis if needed."""
    if not preview:
        return "(no preview)"
    preview = preview.strip()
    if len(preview) > max_length:
        return preview[:max_length] + "..."
    return preview


async def _handle_interactive_mode(
    ctx: CommandContext, messages: list[dict[str, object]], query: str
) -> None:
    """Handle interactive message selection and extraction."""
    try:
        import questionary
    except ImportError:
        ctx.fail_and_exit(
            title="Missing Dependency",
            message="Interactive mode requires the 'questionary' package",
            suggestion="Install with: pip install questionary",
        )
        return

    # Build choice list
    choices = []
    for msg in messages:
        subject = str(msg.get("subject") or "(no subject)")
        from_addr = str(msg.get("from_addr") or "")
        date = str(msg.get("date") or "")
        gmail_id = str(msg.get("gmail_id") or "")
        label = f"{subject[:50]} - {from_addr[:30]} - {date[:19]}"
        choices.append(questionary.Choice(title=label, value=gmail_id))

    # Show interactive selection
    selected = questionary.checkbox(
        "Select messages to extract (space to select, enter to confirm):", choices=choices
    ).ask()

    if not selected or len(selected) == 0:
        ctx.info("No messages selected or cancelled.")
        return

    # Ask for output directory
    output_dir = questionary.path(
        "Output directory for extracted messages:",
        default="./extracted",
    ).ask()

    if not output_dir:
        ctx.info("Extraction cancelled.")
        return

    # Create output directory if needed
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Show summary (actual extraction would use MessageExtractor)
    ReportCard("Extraction Summary").add_field("Messages Selected", str(len(selected))).add_field(
        "Output Directory", str(output_dir)
    ).render(ctx.output)

    ctx.success(f"Selected {len(selected)} messages for extraction")
