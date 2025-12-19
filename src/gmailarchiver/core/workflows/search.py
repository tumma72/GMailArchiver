"""Workflow for searching archived messages.

This workflow provides message search functionality using
the SearchMessagesStep for consistent architecture with other workflows.
"""

import time
from dataclasses import dataclass

from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.steps.search import SearchInput, SearchMessagesStep
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class SearchConfig:
    """Configuration for search operation."""

    query: str
    limit: int = 50
    from_filter: str | None = None
    to_filter: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort_ascending: bool = False


@dataclass
class SearchResult:
    """Result of search operation."""

    messages: list[dict[str, object]]
    total_count: int
    execution_time_ms: float


class SearchWorkflow:
    """Workflow for searching archived messages.

    Uses Step composition via WorkflowComposer:
    1. SearchMessagesStep - Search messages with full-text search
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize search workflow.

        Args:
            storage: HybridStorage instance for data access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress
        self._search_step = SearchMessagesStep(storage)

    async def run(self, config: SearchConfig) -> SearchResult:
        """Run the search workflow.

        Args:
            config: SearchConfig with query and filters

        Returns:
            SearchResult with matching messages and execution time
        """
        start_time = time.perf_counter()

        # Build workflow
        workflow = WorkflowComposer("search").add_step(self._search_step)

        # Create input
        search_input = SearchInput(
            query=config.query,
            limit=config.limit,
            from_filter=config.from_filter,
            to_filter=config.to_filter,
            date_from=config.date_from,
            date_to=config.date_to,
            sort_ascending=config.sort_ascending,
        )

        # Execute workflow
        context = await workflow.run(search_input, progress=self.progress)

        # Extract result from context
        search_results = context.get("search_results")
        if search_results is None:
            raise RuntimeError("Search step did not produce output")

        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000

        return SearchResult(
            messages=search_results.messages,
            total_count=search_results.total_count,
            execution_time_ms=execution_time_ms,
        )
