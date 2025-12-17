"""Deduplication workflow for Gmail Archiver.

This workflow coordinates finding and removing duplicate messages across archives.
"""

from dataclasses import dataclass

from gmailarchiver.core.deduplicator._scanner import MessageInfo
from gmailarchiver.core.deduplicator.facade import (
    DeduplicationResult,
    DeduplicatorFacade,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class DedupeConfig:
    """Configuration for dedupe operation."""

    archive_files: list[str]  # files to deduplicate
    dry_run: bool = False
    output_file: str | None = None  # if None, modifies in place
    strategy: str = "newest"  # Which copy to keep: newest, largest, first


@dataclass
class DedupeResult:
    """Result of dedupe operation."""

    duplicates_found: int
    duplicates_removed: int
    messages_kept: int
    space_saved: int
    dry_run: bool
    output_file: str | None


class DedupeWorkflow:
    """Workflow for deduplicating messages across archives."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize dedupe workflow.

        Args:
            storage: HybridStorage instance for data access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: DedupeConfig) -> DedupeResult:
        """Execute the deduplication workflow.

        Args:
            config: Deduplication configuration

        Returns:
            DedupeResult with operation outcomes

        Raises:
            ValueError: If database schema is not v1.1+ or strategy is invalid
        """
        # 1. Initialize facade
        dedup = await DeduplicatorFacade.create(self.storage.db)

        # 2. Find duplicates
        duplicates = await self._find_duplicates(dedup)

        if not duplicates:
            return DedupeResult(
                duplicates_found=0,
                duplicates_removed=0,
                messages_kept=0,
                space_saved=0,
                dry_run=config.dry_run,
                output_file=config.output_file,
            )

        # 3. Deduplicate
        result = await self._deduplicate_messages(dedup, duplicates, config)

        return DedupeResult(
            duplicates_found=len(duplicates),
            duplicates_removed=result.messages_removed,
            messages_kept=result.messages_kept,
            space_saved=result.space_saved,
            dry_run=config.dry_run,
            output_file=config.output_file,
        )

    async def _find_duplicates(self, dedup: DeduplicatorFacade) -> dict[str, list[MessageInfo]]:
        """Find duplicates with UI feedback."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task("Scanning for duplicates") as task:
                    duplicates = await dedup.find_duplicates()
                    if duplicates:
                        task.complete(f"Found {len(duplicates):,} duplicate groups")
                    else:
                        task.complete("No duplicates found")
                    return duplicates
        else:
            return await dedup.find_duplicates()

    async def _deduplicate_messages(
        self,
        dedup: DeduplicatorFacade,
        duplicates: dict[str, list[MessageInfo]],
        config: DedupeConfig,
    ) -> DeduplicationResult:
        """Deduplicate messages with UI feedback."""
        if self.progress:
            with self.progress.task_sequence() as seq:
                desc = "Preview deduplication" if config.dry_run else "Removing duplicates"
                with seq.task(desc) as task:
                    result = await dedup.deduplicate(
                        duplicates, strategy=config.strategy, dry_run=config.dry_run
                    )
                    if config.dry_run:
                        task.complete(f"Would remove {result.messages_removed:,} duplicates")
                    else:
                        task.complete(f"Removed {result.messages_removed:,} duplicates")
                    return result
        else:
            return await dedup.deduplicate(
                duplicates, strategy=config.strategy, dry_run=config.dry_run
            )
