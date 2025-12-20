"""Search steps for finding archived messages.

This module provides steps for searching the archive:
- SearchMessagesStep: Search messages using full-text search and filters
"""

from dataclasses import dataclass

from gmailarchiver.core.search._parser import QueryParser
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class SearchInput:
    """Input for SearchMessagesStep."""

    query: str
    limit: int = 50
    from_filter: str | None = None
    to_filter: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort_ascending: bool = False


@dataclass
class SearchOutput:
    """Output from SearchMessagesStep."""

    messages: list[dict[str, object]]
    total_count: int


class SearchMessagesStep:
    """Step that searches archived messages.

    Uses HybridStorage to search messages with full-text search
    and optional metadata filters.

    Input: SearchInput with query and filters
    Output: SearchOutput with matching messages and count
    """

    name = "search_messages"
    description = "Searching messages"

    def __init__(self, storage: HybridStorage) -> None:
        """Initialize with hybrid storage.

        Args:
            storage: HybridStorage instance for search access
        """
        self.storage = storage
        self._parser = QueryParser()

    async def execute(
        self,
        context: StepContext,
        input_data: SearchInput | None = None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[SearchOutput]:
        """Search messages in the archive.

        Args:
            context: Shared step context
            input_data: SearchInput with query and filters (or None for defaults)
            progress: Optional progress reporter

        Returns:
            StepResult with SearchOutput containing matches
        """
        # Normalize input
        if input_data is None:
            input_data = SearchInput(query="")

        # Parse Gmail-style query syntax (from:, to:, subject:, after:, before:)
        parsed = self._parser.parse(input_data.query)

        # Merge explicit filters with parsed query params
        # Explicit filters take precedence
        from_addr = input_data.from_filter or parsed.from_addr
        to_addr = input_data.to_filter or parsed.to_addr
        date_from = input_data.date_from or parsed.after
        date_to = input_data.date_to or parsed.before

        # Use fulltext terms as the query, not the original Gmail-style query
        fulltext_query = " ".join(parsed.fulltext_terms) if parsed.fulltext_terms else ""

        # Add wildcards for partial matching if not already present
        # This allows "from:alice" to match "alice@example.com"
        if from_addr and "%" not in from_addr:
            from_addr = f"%{from_addr}%"
        if to_addr and "%" not in to_addr:
            to_addr = f"%{to_addr}%"

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Searching messages") as task:
                        results = await self.storage.search_messages(
                            query=fulltext_query,
                            limit=input_data.limit,
                            from_addr=from_addr,
                            to_addr=to_addr,
                            date_from=date_from,
                            date_to=date_to,
                        )

                        if results.total_results > 0:
                            task.complete(
                                f"Found {results.total_results:,} messages "
                                f"(showing {len(results.results):,})"
                            )
                        else:
                            task.complete("No messages found")
            else:
                results = await self.storage.search_messages(
                    query=fulltext_query,
                    limit=input_data.limit,
                    from_addr=from_addr,
                    to_addr=to_addr,
                    date_from=date_from,
                    date_to=date_to,
                )

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

            # Apply sort if needed (default is descending/newest first)
            if input_data.sort_ascending:
                messages = sorted(messages, key=lambda m: str(m.get("date", "")))
            else:
                messages = sorted(messages, key=lambda m: str(m.get("date", "")), reverse=True)

            output = SearchOutput(
                messages=messages,
                total_count=results.total_results,
            )

            # Store in context for potential downstream use
            context.set("search_results", output)
            context.set("query", input_data.query)

            return StepResult.ok(output)

        except Exception as e:
            return StepResult.fail(f"Search failed: {e}")
