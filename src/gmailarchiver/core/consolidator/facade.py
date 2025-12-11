"""Archive consolidation facade for merging multiple mbox files."""

import time
from dataclasses import dataclass
from pathlib import Path

from gmailarchiver.core.consolidator._merger import MessageMerger
from gmailarchiver.core.consolidator._sorter import MessageSorter
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage


@dataclass
class ConsolidationResult:
    """Result of consolidating multiple archives."""

    output_file: str
    source_files: list[str]
    total_messages: int
    duplicates_removed: int
    messages_consolidated: int
    execution_time_ms: float
    sort_applied: bool
    compression_used: str | None


class ArchiveConsolidator:
    """Consolidate multiple mbox archives into a single archive."""

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize consolidator with database manager.

        Args:
            db_manager: Database manager for state operations
        """
        self.db_manager = db_manager

    async def consolidate(
        self,
        source_archives: list[str | Path],
        output_archive: str | Path,
        sort_by_date: bool = True,
        deduplicate: bool = True,
        dedupe_strategy: str = "newest",
        compress: str | None = None,
    ) -> ConsolidationResult:
        """Consolidate multiple archives into one using atomic HybridStorage primitives.

        Args:
            source_archives: List of source archive paths to merge
            output_archive: Path to output consolidated archive
            sort_by_date: Sort messages chronologically by date
            deduplicate: Remove duplicate messages
            dedupe_strategy: Strategy for choosing which duplicate to keep
                ('newest', 'largest', 'first')
            compress: Compression format ('gzip', 'lzma', 'zstd', or None)

        Returns:
            ConsolidationResult with consolidation statistics

        Raises:
            ValueError: If source_archives is empty
            FileNotFoundError: If any source archive doesn't exist
        """
        start_time = time.perf_counter()

        # Validate inputs
        if not source_archives:
            raise ValueError("source_archives cannot be empty")

        # Convert paths
        source_paths = [Path(p) for p in source_archives]
        output_path = Path(output_archive)

        # Initialize components
        storage = HybridStorage(self.db_manager)
        merger = MessageMerger(storage)
        sorter = MessageSorter()

        try:
            # Phase 1: Read and merge messages
            messages = await merger.merge_archives(source_paths)
            total_messages = len(messages)

            # Phase 2: Sort if requested
            if sort_by_date:
                messages = sorter.sort_by_date(messages)

            # Phase 3: Deduplicate if requested
            duplicates_removed = 0
            duplicate_gmail_ids: list[str] = []
            if deduplicate:
                messages, duplicates_removed, duplicate_gmail_ids = sorter.deduplicate(
                    messages, dedupe_strategy
                )

            # Phase 4: Write using HybridStorage primitive
            offset_map = await storage.bulk_write_messages(messages, output_path, compress)

            # Phase 5: Update database atomically with deduplication
            updates = [
                {
                    "gmail_id": gmail_id,
                    "archive_file": str(output_path),
                    "mbox_offset": offset,
                    "mbox_length": length,
                }
                for rfc_id, (gmail_id, offset, length) in offset_map.items()
            ]

            await storage.bulk_update_archive_locations_with_dedup(updates, duplicate_gmail_ids)

            # Phase 6: Commit transaction
            await self.db_manager.commit()

            end_time = time.perf_counter()
            execution_time_ms = (end_time - start_time) * 1000

            return ConsolidationResult(
                output_file=str(output_path),
                source_files=[str(p) for p in source_paths],
                total_messages=total_messages,
                duplicates_removed=duplicates_removed,
                messages_consolidated=len(messages),
                execution_time_ms=execution_time_ms,
                sort_applied=sort_by_date,
                compression_used=compress,
            )
        except Exception:
            # Rollback on any error
            await self.db_manager.rollback()
            raise
