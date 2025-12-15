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

    if with_preview:
        # Display with preview (list format) - includes all details
        output_mgr.info(f"\nSearch Results ({total_results} found)\n")
        for idx, result in enumerate(results, 1):
            preview = _truncate_preview(result.body_preview)
            subject = result.subject or "(no subject)"

            output_mgr.info(f"{idx}. Subject: {subject}")
            output_mgr.info(f"   From: {result.from_addr}")
            output_mgr.info(f"   Date: {result.date or 'N/A'}")
            output_mgr.info(f"   RFC Message-ID: {result.rfc_message_id}")
            output_mgr.info(f"   Gmail ID: {result.gmail_id or 'N/A'}")
            output_mgr.info(f"   Archive: {result.archive_file}")
            output_mgr.info(f"   Preview: {preview}")
            output_mgr.info("")
    else:
        # Display in table format using smart table with full terminal width
        # Key columns (never truncated): Message ID, From, Archive
        # Truncatable columns: Subject (gets remaining space)
        column_specs = [
            {"header": "RFC Message-ID", "key": True, "style": "dim", "no_wrap": True},
            {"header": "Date", "key": True, "style": "cyan", "no_wrap": True},
            {"header": "From", "key": True, "style": "cyan"},
            {"header": "Subject", "key": False, "style": "white", "ratio": 2},
            {"header": "Archive", "key": True, "style": "dim"},
        ]

        rows: list[list[str]] = []
        for result in results:
            rows.append(
                [
                    result.rfc_message_id or "(no id)",
                    result.date or "N/A",
                    result.from_addr or "",
                    result.subject or "(no subject)",
                    Path(result.archive_file).name,
                ]
            )

        # Use smart table for full-width, intelligent column sizing
        output_mgr.show_smart_table(
            f"Search Results ({total_results} found)",
            column_specs,
            rows,
        )
