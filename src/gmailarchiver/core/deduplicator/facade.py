"""Deduplicator facade - simplified interface for duplicate management.

Coordinates scanning, resolution, and removal of duplicate messages.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from gmailarchiver.data.db_manager import DBManager

from ._remover import DuplicateRemover
from ._resolver import DuplicateResolver
from ._scanner import DuplicateScanner, MessageInfo


@dataclass
class DeduplicationReport:
    """Report on deduplication analysis."""

    total_messages: int
    duplicate_message_ids: int
    total_duplicate_messages: int
    messages_to_remove: int
    space_recoverable: int
    breakdown_by_archive: dict[str, dict[str, Any]]


@dataclass
class DeduplicationResult:
    """Result of deduplication operation."""

    messages_removed: int
    messages_kept: int
    space_saved: int
    dry_run: bool


class DeduplicatorFacade:
    """
    Simplified interface for finding and removing duplicate messages.

    Uses RFC 2822 Message-ID for 100% precision deduplication.
    Supports multiple resolution strategies: newest, largest, first.

    Example:
        >>> db = DBManager("state.db")
        >>> await db.initialize()
        >>> async with await DeduplicatorFacade.create(db) as dedup:
        ...     duplicates = await dedup.find_duplicates()
        ...     report = await dedup.generate_report(duplicates)
        ...     print(f"Found {report.duplicate_message_ids} duplicate groups")
        ...     result = await dedup.deduplicate(duplicates, strategy="newest", dry_run=True)
    """

    def __init__(self, db: DBManager, schema_version: str) -> None:
        """
        Initialize deduplicator facade (internal - use create() instead).

        Args:
            db: DBManager instance for database operations
            schema_version: Validated schema version

        Raises:
            ValueError: If database is not v1.1+ schema
        """
        self.db = db

        # For backward compatibility, store db_path
        self.db_path = str(db.db_path)

        # Initialize internal modules
        self._scanner = DuplicateScanner(db)
        self._resolver = DuplicateResolver()
        self._remover = DuplicateRemover(db)

    @classmethod
    async def create(cls, db: DBManager) -> Self:
        """
        Create and initialize deduplicator facade.

        Args:
            db: Initialized DBManager instance

        Returns:
            Initialized DeduplicatorFacade instance

        Raises:
            ValueError: If database is not v1.1+ schema
        """
        # Verify v1.1+ schema (supports both v1.1 and v1.2)
        # If schema_version wasn't set (validate_schema=False), try to get it
        if not hasattr(db, "schema_version") or db.schema_version is None:
            # Manually validate schema to get version
            try:
                schema_version = await db._validate_schema_version()
            except Exception as e:
                raise ValueError(
                    f"DeduplicatorFacade requires v1.1+ database schema. "
                    f"Schema validation failed: {e}"
                ) from e
        else:
            schema_version = db.schema_version

        if schema_version not in ("1.1", "1.2"):
            raise ValueError(
                f"DeduplicatorFacade requires v1.1+ database schema, "
                f"found: {schema_version}. Run migration first."
            )

        return cls(db, schema_version)

    async def find_duplicates(self) -> dict[str, list[MessageInfo]]:
        """
        Find all duplicate messages grouped by rfc_message_id.

        Uses SQL GROUP BY for efficient duplicate detection.
        Only includes Message-IDs that appear 2+ times.

        Returns:
            Dict mapping rfc_message_id to list of MessageInfo (locations)

        Example:
            >>> duplicates = await facade.find_duplicates()
            >>> for msg_id, locations in duplicates.items():
            ...     print(f"{msg_id}: {len(locations)} copies")
        """
        return await self._scanner.find_duplicates()

    async def generate_report(
        self, duplicates: dict[str, list[MessageInfo]]
    ) -> DeduplicationReport:
        """
        Generate report showing deduplication analysis.

        Args:
            duplicates: From find_duplicates()

        Returns:
            DeduplicationReport with statistics

        Example:
            >>> duplicates = await facade.find_duplicates()
            >>> report = await facade.generate_report(duplicates)
            >>> print(f"Can save {report.space_recoverable} bytes")
        """
        # Get total message count
        total_messages = await self.db.get_message_count()

        if not duplicates:
            return DeduplicationReport(
                total_messages=total_messages,
                duplicate_message_ids=0,
                total_duplicate_messages=0,
                messages_to_remove=0,
                space_recoverable=0,
                breakdown_by_archive={},
            )

        # Calculate statistics
        duplicate_message_ids = len(duplicates)
        total_duplicate_messages = sum(len(msgs) for msgs in duplicates.values())
        messages_to_remove = total_duplicate_messages - duplicate_message_ids

        # Calculate space recoverable and breakdown
        space_recoverable = 0
        breakdown: dict[str, dict[str, Any]] = {}

        for rfc_id, messages in duplicates.items():
            # Use resolver to determine which to keep (using largest strategy for report)
            resolution = self._resolver.resolve(messages, strategy="largest")

            for msg in resolution.remove:
                space_recoverable += msg.size_bytes

                # Track by archive file
                if msg.archive_file not in breakdown:
                    breakdown[msg.archive_file] = {
                        "messages_to_remove": 0,
                        "space_recoverable": 0,
                    }

                breakdown[msg.archive_file]["messages_to_remove"] += 1
                breakdown[msg.archive_file]["space_recoverable"] += msg.size_bytes

        return DeduplicationReport(
            total_messages=total_messages,
            duplicate_message_ids=duplicate_message_ids,
            total_duplicate_messages=total_duplicate_messages,
            messages_to_remove=messages_to_remove,
            space_recoverable=space_recoverable,
            breakdown_by_archive=breakdown,
        )

    async def deduplicate(
        self,
        duplicates: dict[str, list[MessageInfo]],
        strategy: str = "newest",
        dry_run: bool = True,
    ) -> DeduplicationResult:
        """
        Remove duplicates using specified strategy.

        Args:
            duplicates: From find_duplicates()
            strategy: Which copy to keep ('newest', 'largest', 'first')
            dry_run: If True, only report what would be done

        Returns:
            DeduplicationResult with counts and space saved

        Raises:
            ValueError: If strategy is invalid

        Example:
            >>> duplicates = await facade.find_duplicates()
            >>> result = await facade.deduplicate(duplicates, strategy="newest", dry_run=True)
            >>> print(f"Would remove {result.messages_removed} messages")
        """
        if not duplicates:
            return DeduplicationResult(
                messages_removed=0, messages_kept=0, space_saved=0, dry_run=dry_run
            )

        # Resolve each duplicate group
        all_to_remove: list[MessageInfo] = []
        total_space_saved = 0

        for rfc_id, messages in duplicates.items():
            resolution = self._resolver.resolve(messages, strategy=strategy)
            all_to_remove.extend(resolution.remove)
            total_space_saved += resolution.space_saved

        messages_removed = len(all_to_remove)
        messages_kept = len(duplicates)  # One per group

        # Execute removal
        if all_to_remove:
            await self._remover.remove_messages(all_to_remove, dry_run=dry_run)

        return DeduplicationResult(
            messages_removed=messages_removed,
            messages_kept=messages_kept,
            space_saved=total_space_saved,
            dry_run=dry_run,
        )

    async def close(self) -> None:
        """Close all database connections.

        Note: Database connection is managed by DBManager,
        not by this facade. This method exists for backward compatibility.
        """
        pass

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()
