"""Workflow for retrieving archive status.

This workflow retrieves comprehensive statistics about the archive using
the GetArchiveStatsStep for consistent architecture with other workflows.
"""

from dataclasses import dataclass, field
from typing import Any

from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.steps.stats import GetArchiveStatsStep, StatsInput
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class StatusConfig:
    """Configuration for status operation."""

    verbose: bool = False
    runs_limit: int = 5


@dataclass
class StatusResult:
    """Result of status operation."""

    schema_version: str
    database_size_bytes: int
    total_messages: int
    archive_files: list[str]
    recent_runs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def archive_files_count(self) -> int:
        """Return count of archive files."""
        return len(self.archive_files)


class StatusWorkflow:
    """Workflow for retrieving archive status.

    Uses Step composition via WorkflowComposer:
    1. GetArchiveStatsStep - Retrieve statistics from storage
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize status workflow.

        Args:
            storage: HybridStorage instance for data access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress
        self._stats_step = GetArchiveStatsStep(storage)

    async def run(self, config: StatusConfig) -> StatusResult:
        """Run the status workflow.

        Args:
            config: StatusConfig with options

        Returns:
            StatusResult with archive statistics
        """
        # Build workflow
        workflow = WorkflowComposer("status").add_step(self._stats_step)

        # Create input
        stats_input = StatsInput(
            verbose=config.verbose,
            runs_limit=config.runs_limit,
        )

        # Execute workflow
        context = await workflow.run(stats_input, progress=self.progress)

        # Extract result from context
        stats = context.get("stats")
        if stats is None:
            raise RuntimeError("Stats step did not produce output")

        return StatusResult(
            schema_version=stats.schema_version,
            database_size_bytes=stats.database_size_bytes,
            total_messages=stats.total_messages,
            archive_files=stats.archive_files,
            recent_runs=stats.recent_runs,
        )
