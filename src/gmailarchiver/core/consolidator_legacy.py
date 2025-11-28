"""Archive consolidation for merging multiple mbox files."""

import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

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

    def __init__(self, state_db_path: str) -> None:
        """Initialize consolidator with database path."""
        self.state_db_path = state_db_path

    def consolidate(
        self,
        source_archives: list[str | Path],
        output_archive: str | Path,
        sort_by_date: bool = True,
        deduplicate: bool = True,
        dedupe_strategy: str = "newest",
        compress: str | None = None,
    ) -> ConsolidationResult:
        """
        Consolidate multiple archives into one using atomic HybridStorage primitives.

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
            ValueError: If source_archives is empty or dedupe_strategy is invalid
            FileNotFoundError: If any source archive doesn't exist
        """
        start_time = time.perf_counter()

        # Validate inputs
        if not source_archives:
            raise ValueError("source_archives cannot be empty")

        valid_strategies = ("newest", "largest", "first")
        if deduplicate and dedupe_strategy not in valid_strategies:
            raise ValueError(
                f"Invalid dedupe_strategy: {dedupe_strategy}. Must be one of {valid_strategies}"
            )

        # Convert paths
        source_paths = [Path(p) for p in source_archives]
        output_path = Path(output_archive)

        # Verify source files exist
        for source_path in source_paths:
            if not source_path.exists():
                raise FileNotFoundError(f"Source archive not found: {source_path}")

        # Use HybridStorage primitives for atomic consolidation
        db_manager = DBManager(self.state_db_path, validate_schema=False)
        storage = HybridStorage(db_manager)

        try:
            # Phase 1: Read messages using HybridStorage primitive
            messages = storage.read_messages_from_archives(source_paths)
            total_messages = len(messages)

            # Phase 2: Sort if requested (business logic in consolidator)
            if sort_by_date:
                messages = self._sort_messages(messages)

            # Phase 3: Deduplicate if requested (business logic in consolidator)
            duplicates_removed = 0
            duplicate_gmail_ids: list[str] = []
            if deduplicate:
                messages, duplicates_removed, duplicate_gmail_ids = self._deduplicate_messages(
                    messages, dedupe_strategy
                )

            # Phase 4: Write using HybridStorage primitive
            offset_map = storage.bulk_write_messages(messages, output_path, compress)

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

            storage.bulk_update_archive_locations_with_dedup(updates, duplicate_gmail_ids)

            # Phase 6: Commit transaction
            db_manager.commit()

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
            db_manager.rollback()
            raise
        finally:
            db_manager.close()

    def _parse_date(self, date_str: str) -> float:
        """Parse email Date header to timestamp."""
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except (ValueError, TypeError):
            # Return epoch for invalid dates (sorts to beginning)
            return 0.0

    def _sort_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort messages by date timestamp."""
        # Parse dates and attach timestamps for sorting
        for msg_dict in messages:
            date_str = msg_dict.get("date", "")
            msg_dict["timestamp"] = self._parse_date(date_str)

        # Sort by timestamp
        return sorted(messages, key=lambda m: m["timestamp"])

    def _deduplicate_messages(
        self, messages: list[dict[str, Any]], strategy: str
    ) -> tuple[list[dict[str, Any]], int, list[str]]:
        """
        Remove duplicates using specified strategy.

        Returns:
            Tuple of (deduplicated_messages, duplicates_removed, duplicate_gmail_ids)
        """
        # Group by Message-ID
        by_message_id: dict[str, list[dict[str, Any]]] = {}
        for msg_dict in messages:
            msg_id = msg_dict["rfc_message_id"]
            if msg_id not in by_message_id:
                by_message_id[msg_id] = []
            by_message_id[msg_id].append(msg_dict)

        # Apply strategy to duplicates
        kept_messages = []
        duplicates_removed = 0
        duplicate_gmail_ids: list[str] = []

        for msg_id, msg_list in by_message_id.items():
            if len(msg_list) == 1:
                # No duplicates
                kept_messages.append(msg_list[0])
            else:
                # Apply strategy
                if strategy == "newest":
                    # Parse dates for comparison
                    for msg_dict in msg_list:
                        if "timestamp" not in msg_dict:
                            msg_dict["timestamp"] = self._parse_date(msg_dict.get("date", ""))
                    kept = max(msg_list, key=lambda m: m["timestamp"])
                elif strategy == "largest":
                    kept = max(msg_list, key=lambda m: m["size"])
                else:  # 'first'
                    kept = msg_list[0]

                kept_messages.append(kept)
                duplicates_removed += len(msg_list) - 1

                # Track duplicate gmail_ids for database deletion
                for msg_dict in msg_list:
                    if msg_dict is not kept:
                        duplicate_gmail_ids.append(msg_dict["gmail_id"])

        return kept_messages, duplicates_removed, duplicate_gmail_ids
