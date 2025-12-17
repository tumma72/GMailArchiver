"""Workflow for searching archived messages.

This module provides the async workflow for message search.
"""

import time
from dataclasses import dataclass

from gmailarchiver.core.search.facade import SearchFacade
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class SearchConfig:
    """Configuration for search operation."""

    query: str
    state_db: str
    limit: int = 50
    from_filter: str | None = None
    to_filter: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class SearchResult:
    """Result of search operation."""

    messages: list[dict[str, object]]
    total_count: int
    execution_time_ms: float


class SearchWorkflow:
    """Workflow for searching archived messages."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize search workflow.

        Args:
            storage: HybridStorage for database access
            progress: Optional ProgressReporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: SearchConfig) -> SearchResult:
        """Run the full search workflow.

        Args:
            config: SearchConfig with query and filters

        Returns:
            SearchResult with matching messages

        Raises:
            FileNotFoundError: If database doesn't exist
        """
        start_time = time.perf_counter()

        # Create search facade
        async with await SearchFacade.create(config.state_db) as search:
            # Execute search with UI feedback
            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task("Searching messages") as task:
                        results = await search.search(query=config.query, limit=config.limit)

                        if results.total_results > 0:
                            task.complete(
                                f"Found {results.total_results:,} messages "
                                f"(showing {len(results.results):,})"
                            )
                        else:
                            task.complete("No messages found")
            else:
                results = await search.search(query=config.query, limit=config.limit)

        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000

        # Convert search results to dict format
        messages: list[dict[str, object]] = [
            {
                "gmail_id": msg.gmail_id,
                "rfc_message_id": msg.rfc_message_id,
                "subject": msg.subject,
                "from_addr": msg.from_addr,
                "to_addr": msg.to_addr,
                "date": msg.date,
                "body_preview": msg.body_preview,
                "archive_file": msg.archive_file,
                "mbox_offset": msg.mbox_offset,
                "relevance_score": msg.relevance_score,
            }
            for msg in results.results
        ]

        return SearchResult(
            messages=messages,
            total_count=results.total_results,
            execution_time_ms=execution_time_ms,
        )
