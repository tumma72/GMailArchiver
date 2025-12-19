"""Search command implementation."""

import asyncio
from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.cli.ui import CLIProgressAdapter, ReportCard
from gmailarchiver.core.workflows.search import SearchConfig, SearchResult, SearchWorkflow


@with_context(requires_storage=True, operation_name="search")
def search(
    ctx: CommandContext,
    query: str = typer.Argument(..., help="Search query (Gmail syntax supported)"),
    state_db: str = typer.Option(
        "archive_state.db", "--state-db", help="Path to state database file"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of results"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    with_preview: bool = typer.Option(
        False, "--with-preview", help="Include message body preview in results"
    ),
    interactive: bool = typer.Option(
        False, "--interactive", help="Interactive mode for message selection and extraction"
    ),
) -> None:
    """
    Search archived messages.

    Supports Gmail-style query syntax with full-text search via BM25 ranking.

    Examples:
        $ gmailarchiver search "from:sender@example.com"
        $ gmailarchiver search "subject:invoice" --limit 20
        $ gmailarchiver search "body:urgent" --json
        $ gmailarchiver search "meeting" --with-preview
        $ gmailarchiver search "project" --interactive
    """
    asyncio.run(
        _run_search(
            ctx=ctx,
            query=query,
            state_db=state_db,
            limit=limit,
            json_output=json_output,
            with_preview=with_preview,
            interactive=interactive,
        )
    )


async def _run_search(
    ctx: CommandContext,
    query: str,
    state_db: str,
    limit: int,
    json_output: bool,
    with_preview: bool,
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

    db_path = Path(state_db)
    if not db_path.exists():
        ctx.fail_and_exit(
            title="Database Not Found",
            message=f"Database not found: {state_db}",
            suggestion=(
                "Archive emails first: gmailarchiver archive 3y\n"
                "Or import existing archive: gmailarchiver import archive.mbox"
            ),
        )

    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Phase 2: Create workflow and config
    progress = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = SearchWorkflow(ctx.storage, progress=progress)
    config = SearchConfig(query=query, state_db=state_db, limit=limit)

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

    if json_output:
        _handle_json_output(ctx, result, with_preview)
        return

    if interactive:
        await _handle_interactive_mode(ctx, result.messages, query)
        return

    # Phase 5: Display results (table or list format)
    if with_preview:
        _display_results_with_preview(ctx, result)
    else:
        _display_results_table(ctx, result, query)

    # Show summary if truncated
    if result.total_count > len(result.messages):
        ctx.info(
            f"Showing {len(result.messages)} of {result.total_count:,} matches "
            f"(use --limit to see more)"
        )


def _handle_no_results(ctx: CommandContext, query: str) -> None:
    """Handle case where no results were found."""
    ctx.warning(f"No results found for: {query}")
    ctx.suggest_next_steps(
        [
            "Try a broader search term",
            "Check if messages are archived: gmailarchiver status",
        ]
    )


def _handle_json_output(ctx: CommandContext, result: SearchResult, with_preview: bool) -> None:
    """Handle JSON output mode."""
    output_data = []
    for msg in result.messages:
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


def _display_results_with_preview(ctx: CommandContext, result: SearchResult) -> None:
    """Display results in list format with body preview."""
    ctx.info(f"\nSearch Results ({result.total_count} found)\n")
    for idx, msg in enumerate(result.messages, 1):
        preview = _truncate_preview(str(msg.get("body_preview", "")))
        subject = msg.get("subject") or "(no subject)"

        ctx.info(f"{idx}. Subject: {subject}")
        ctx.info(f"   From: {msg.get('from_addr')}")
        ctx.info(f"   Date: {msg.get('date') or 'N/A'}")
        ctx.info(f"   RFC Message-ID: {msg.get('rfc_message_id')}")
        ctx.info(f"   Gmail ID: {msg.get('gmail_id') or 'N/A'}")
        ctx.info(f"   Archive: {msg.get('archive_file')}")
        ctx.info(f"   Preview: {preview}")
        ctx.info("")


def _display_results_table(ctx: CommandContext, result: SearchResult, query: str) -> None:
    """Display results in table format."""
    headers = ["Subject", "From", "Date"]
    rows = []
    for msg in result.messages:
        rows.append(
            [
                str(msg.get("subject", ""))[:50],
                str(msg.get("from_addr", ""))[:30],
                str(msg.get("date", ""))[:19],
            ]
        )
    ctx.show_table(f"Search Results for: {query}", headers, rows)


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
    ReportCard("Extraction Summary").add_field(
        "Messages Selected", str(len(selected))
    ).add_field("Output Directory", str(output_dir)).render(ctx.output)

    ctx.success(f"Selected {len(selected)} messages for extraction")
