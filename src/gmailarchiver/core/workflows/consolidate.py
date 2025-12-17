"""Workflow for consolidating multiple archives.

This workflow coordinates the consolidation of multiple mbox files into
a single archive with optional deduplication and sorting.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gmailarchiver.core.consolidator.facade import ArchiveConsolidator
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ConsolidateConfig:
    """Configuration for consolidate operation."""

    source_files: list[str]
    output_file: str
    dedupe: bool = True
    sort_by_date: bool = True
    compress: str | None = None
    dedupe_strategy: str = "newest"


@dataclass
class ConsolidateResult:
    """Result of consolidate operation."""

    output_file: str
    messages_count: int
    source_files_count: int
    duplicates_removed: int
    sort_applied: bool
    compression_used: str | None


class ConsolidateWorkflow:
    """Workflow for consolidating multiple archives into one."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize consolidate workflow.

        Args:
            storage: HybridStorage instance for data operations
            progress: Optional progress reporter for status updates
        """
        self.storage = storage
        self.progress = progress
        # Initialize facade with storage's db_manager
        self.consolidator = ArchiveConsolidator(db_manager=storage.db)

    async def run(self, config: ConsolidateConfig) -> ConsolidateResult:
        """Run the full consolidation workflow.

        Args:
            config: ConsolidateConfig with consolidation settings

        Returns:
            ConsolidateResult with operation statistics
        """
        # Validate source files exist
        source_paths = [Path(f) for f in config.source_files]
        missing_files = [str(p) for p in source_paths if not p.exists()]
        if missing_files:
            raise FileNotFoundError(f"Source files not found: {', '.join(missing_files)}")

        if not source_paths:
            raise ValueError("No source files specified")

        # Report start
        if self.progress:
            self.progress.info(
                f"Consolidating {len(source_paths)} archives into {config.output_file}"
            )
            if config.dedupe:
                self.progress.info(f"Deduplication enabled (strategy: {config.dedupe_strategy})")
            if config.sort_by_date:
                self.progress.info("Messages will be sorted by date")
            if config.compress:
                self.progress.info(f"Compression: {config.compress}")

        # Execute consolidation with progress reporting
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task(
                    f"Consolidating {len(source_paths)} archives", total=len(source_paths)
                ) as task:
                    result = await self.consolidator.consolidate(
                        source_archives=cast(list[str | Path], source_paths),
                        output_archive=config.output_file,
                        sort_by_date=config.sort_by_date,
                        deduplicate=config.dedupe,
                        dedupe_strategy=config.dedupe_strategy,
                        compress=config.compress,
                    )

                    msg_parts = [f"{result.messages_consolidated:,} messages"]
                    if result.duplicates_removed > 0:
                        msg_parts.append(f"{result.duplicates_removed:,} duplicates removed")
                    task.complete(", ".join(msg_parts))
        else:
            result = await self.consolidator.consolidate(
                source_archives=cast(list[str | Path], source_paths),
                output_archive=config.output_file,
                sort_by_date=config.sort_by_date,
                deduplicate=config.dedupe,
                dedupe_strategy=config.dedupe_strategy,
                compress=config.compress,
            )

        return ConsolidateResult(
            output_file=result.output_file,
            messages_count=result.messages_consolidated,
            source_files_count=len(result.source_files),
            duplicates_removed=result.duplicates_removed,
            sort_applied=result.sort_applied,
            compression_used=result.compression_used,
        )
