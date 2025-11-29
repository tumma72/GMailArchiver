"""Data types for search module."""

from dataclasses import dataclass


@dataclass
class MessageSearchResult:
    """Single message search result."""

    gmail_id: str
    rfc_message_id: str
    subject: str
    from_addr: str
    to_addr: str | None
    date: str
    body_preview: str | None
    archive_file: str
    mbox_offset: int
    relevance_score: float | None


@dataclass
class SearchResults:
    """Search results container."""

    total_results: int
    results: list[MessageSearchResult]
    query: str
    execution_time_ms: float
