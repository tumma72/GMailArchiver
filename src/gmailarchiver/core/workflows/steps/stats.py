"""Stats steps for retrieving archive statistics.

This module provides steps for gathering archive statistics:
- GetArchiveStatsStep: Retrieve comprehensive archive statistics
"""

from dataclasses import dataclass, field
from typing import Any

from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class StatsInput:
    """Input for GetArchiveStatsStep."""

    verbose: bool = False
    runs_limit: int = 5


@dataclass
class StatsOutput:
    """Output from GetArchiveStatsStep."""

    schema_version: str
    database_size_bytes: int
    total_messages: int
    archive_files: list[str]
    recent_runs: list[dict[str, Any]] = field(default_factory=list)


class GetArchiveStatsStep:
    """Step that retrieves comprehensive archive statistics.

    Uses HybridStorage to gather statistics about the archive:
    - Schema version
    - Database size
    - Total message count
    - Archive files list
    - Recent archive runs

    Input: StatsInput with verbosity and limit settings
    Output: StatsOutput with all statistics
    """

    name = "get_archive_stats"
    description = "Retrieving archive statistics"

    def __init__(self, storage: HybridStorage) -> None:
        """Initialize with hybrid storage.

        Args:
            storage: HybridStorage instance for data access
        """
        self.storage = storage

    async def execute(
        self,
        context: StepContext,
        input_data: StatsInput | None = None,
        progress: ProgressReporter | None = None,
    ) -> StepResult[StatsOutput]:
        """Retrieve archive statistics.

        Args:
            context: Shared step context
            input_data: StatsInput with options (or None for defaults)
            progress: Optional progress reporter

        Returns:
            StepResult with StatsOutput containing statistics
        """
        # Normalize input
        if input_data is None:
            input_data = StatsInput()

        runs_limit = 10 if input_data.verbose else input_data.runs_limit

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Gathering statistics") as task:
                        stats = await self.storage.get_archive_stats()

                        # Get recent runs with appropriate limit
                        recent_runs = await self.storage.get_recent_runs(limit=runs_limit)

                        task.complete(f"{stats.total_messages:,} messages in archive")
            else:
                stats = await self.storage.get_archive_stats()
                recent_runs = await self.storage.get_recent_runs(limit=runs_limit)

            output = StatsOutput(
                schema_version=stats.schema_version,
                database_size_bytes=stats.database_size_bytes,
                total_messages=stats.total_messages,
                archive_files=stats.archive_files,
                recent_runs=recent_runs,
            )

            # Store in context for potential downstream use
            context.set("stats", output)
            context.set("verbose", input_data.verbose)

            return StepResult.ok(output)

        except Exception as e:
            return StepResult.fail(f"Failed to retrieve statistics: {e}")
