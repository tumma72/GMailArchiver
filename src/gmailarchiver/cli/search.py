"""Search command implementation."""

from pathlib import Path

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.core.workflows.search import SearchConfig, SearchWorkflow


def _truncate_preview(preview: str | None, max_length: int = 200) -> str:
    """Truncate preview text to max length with ellipsis if needed."""
    if not preview:
        return "(no preview)"
    preview = preview.strip()
    if len(preview) > max_length:
        return preview[:max_length] + "..."
    return preview


async def search_command(
    ctx: CommandContext,
    query: str,
    state_db: str,
    limit: int,
    json_output: bool,
    with_preview: bool = False,
    interactive: bool = False,
) -> None:
    """Async implementation of the search command."""
    # Validate flag combinations
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
    workflow = SearchWorkflow(ctx.storage)
    config = SearchConfig(query=query, state_db=state_db, limit=limit)

    try:
        result = await workflow.run(config)
    except Exception as e:
        ctx.fail_and_exit(
            title="Search Error",
            message=f"Search failed: {e}",
            suggestion="Check database file integrity or run 'gmailarchiver doctor'",
        )
        return

    if not result.messages:
        if not interactive:
            ctx.warning(f"No results found for: {query}")
        return

    # Handle JSON output mode
    if json_output:
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
        # Use OutputManager's set_json_payload to avoid wrapper issues
        ctx.output.set_json_payload(output_data)
        return

    # Handle interactive mode
    if interactive:
        await _handle_interactive_mode(ctx, result.messages, query)
        return

    # Handle regular display with optional preview
    if with_preview:
        # Display with preview (list format)
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
    else:
        # Display in table format
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

    # Show count summary
    if result.total_count > len(result.messages):
        ctx.info(
            f"Showing {len(result.messages)} of {result.total_count:,} matches "
            f"(use --limit to see more)"
        )


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
        # Type narrowing: msg is dict[str, object]
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

    # Extract selected messages
    ctx.info(f"\nExtracting {len(selected)} messages to {output_dir}...")

    # For now, just show summary (actual extraction would need MessageExtractor)
    ctx.info(f"Selected {len(selected)} messages for extraction")
    ctx.info(f"Output directory: {output_dir}")
