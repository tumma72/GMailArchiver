"""Search result rendering methods for OutputManager."""

from pathlib import Path
from typing import Any


def _truncate_preview(preview: str | None, max_length: int = 200) -> str:
    """Truncate a preview string to max length, adding ellipsis if needed.

    Args:
        preview: The preview text (None becomes empty string)
        max_length: Maximum length before truncation

    Returns:
        Truncated preview or "(no preview)" if empty
    """
    if not preview:
        return "(no preview)"
    preview = preview.strip()
    if len(preview) > max_length:
        return preview[:max_length] + "..."
    return preview


def display_search_results_json(
    output_mgr: Any,  # OutputManager
    results: list[Any],  # list[SearchResultEntry]
    with_preview: bool = False,
) -> None:
    """Format search results for JSON output.

    Args:
        output_mgr: OutputManager instance
        results: List of search result entries
        with_preview: Include body_preview field in output
    """
    data: list[dict[str, Any]] = []
    for r in results:
        entry: dict[str, Any] = {
            "gmail_id": r.gmail_id,
            "rfc_message_id": r.rfc_message_id,
            "date": r.date,
            "from": r.from_addr,
            "to": r.to_addr,
            "subject": r.subject,
            "archive_file": r.archive_file,
            "mbox_offset": r.mbox_offset,
            "relevance_score": r.relevance_score,
        }
        if with_preview:
            entry["body_preview"] = _truncate_preview(r.body_preview)
        data.append(entry)
    output_mgr.set_json_payload(data)


def display_search_results_rich(
    output_mgr: Any,  # OutputManager
    results: list[Any],  # list[SearchResultEntry]
    total_results: int,
    with_preview: bool = False,
) -> None:
    """Format search results for Rich terminal output.

    Args:
        output_mgr: OutputManager instance
        results: List of search result entries
        total_results: Total number of results (for header)
        with_preview: Include preview in output
    """
    # This helper is intended for non-JSON, non-quiet modes only. JSON mode
    # is handled separately by ``display_search_results_json``.
    if getattr(output_mgr, "json_mode", False) or getattr(output_mgr, "quiet", False):
        return

    if not results:
        output_mgr.warning("No results found")
        return

    # Header
    output_mgr.info(f"\nSearch Results ({total_results} found)\n")

    if with_preview:
        # Display with preview (list format)
        for idx, result in enumerate(results, 1):
            preview = _truncate_preview(result.body_preview)
            subject = result.subject or "(no subject)"
            date_str = result.date[:10] if result.date else "N/A"

            output_mgr.info(f"{idx}. Subject: {subject}")
            output_mgr.info(f"   From: {result.from_addr}")
            output_mgr.info(f"   Date: {date_str}")
            output_mgr.info(f"   Preview: {preview}")
            output_mgr.info(f"   Gmail ID: {result.gmail_id}")
            output_mgr.info("")
    else:
        # Display in table format (default) via OutputManager.show_table
        headers = ["Date", "From", "Subject", "Archive"]
        rows: list[list[str]] = []

        for result in results:
            from_display = result.from_addr or ""
            if len(from_display) > 28:
                from_display = from_display[:28] + "..."

            subject_display = result.subject or "(no subject)"
            if len(subject_display) > 38:
                subject_display = subject_display[:38] + "..."

            archive_display = Path(result.archive_file).name

            rows.append(
                [
                    result.date[:10] if result.date else "N/A",
                    from_display,
                    subject_display,
                    archive_display,
                ]
            )

        # Use OutputManager to render the table (or record as JSON event in future)
        output_mgr.show_table(f"Search Results ({total_results} found)", headers, rows)
