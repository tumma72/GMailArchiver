"""Search facade - simplified interface for message search.

Coordinates query parsing and execution for Gmail-style searches.
"""

from pathlib import Path
from typing import Self

from ...data.db_manager import DBManager
from ...data.hybrid_storage import HybridStorage
from ._executor import SearchExecutor
from ._parser import QueryParser
from ._types import SearchResults


class SearchFacade:
    """
    Simplified interface for searching archived messages.

    Supports Gmail-style query syntax:
    - from:alice@example.com
    - to:bob@example.com
    - subject:meeting
    - after:2024-01-01
    - before:2024-12-31
    - Bare words perform full-text search

    Example:
        >>> async with await SearchFacade.create("state.db") as search:
        ...     results = search.search("from:alice meeting after:2024-01-01")
        ...     print(f"Found {results.total_results} messages")
    """

    def __init__(
        self,
        db_manager: DBManager,
        storage: HybridStorage,
        executor: SearchExecutor,
        db_path: str,
    ) -> None:
        """
        Initialize search facade (internal - use create() instead).

        Args:
            db_manager: Initialized DBManager instance
            storage: HybridStorage instance
            executor: SearchExecutor instance
            db_path: Path to database (for reference)
        """
        self._db_manager = db_manager
        self._storage = storage
        self._executor = executor
        self.db_path = db_path
        self._parser = QueryParser()

    @classmethod
    async def create(cls, state_db_path: str) -> Self:
        """
        Create and initialize search facade.

        Args:
            state_db_path: Path to SQLite state database

        Returns:
            Initialized SearchFacade instance

        Raises:
            FileNotFoundError: If database doesn't exist
        """
        db_path = Path(state_db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {state_db_path}")

        # Create and initialize DBManager
        db_manager = DBManager(state_db_path)
        await db_manager.initialize()

        # Create HybridStorage for database access (architecture gateway)
        storage = HybridStorage(db_manager, preload_rfc_ids=False)

        # Set row_factory for SearchExecutor's SQL queries
        import sqlite3

        if db_manager.conn is None:
            raise RuntimeError("Database connection not initialized")
        db_manager.conn.row_factory = sqlite3.Row

        executor = await SearchExecutor.create(storage)

        return cls(db_manager, storage, executor, state_db_path)

    async def search(self, query: str, limit: int = 100, offset: int = 0) -> SearchResults:
        """
        Execute Gmail-style search query.

        Args:
            query: Gmail-style search query
            limit: Maximum results to return
            offset: Result offset for pagination

        Returns:
            SearchResults with matching messages

        Example:
            >>> results = await facade.search("from:alice subject:meeting project")
            >>> for msg in results.results:
            ...     print(f"{msg.subject} - {msg.from_addr}")
        """
        # Parse query
        params = self._parser.parse(query)

        # Execute search
        results = await self._executor.execute(params, limit=limit, offset=offset)

        return results

    async def search_fulltext(
        self, text: str, fields: list[str] | None = None, limit: int = 100
    ) -> SearchResults:
        """
        Direct full-text search (FTS5).

        Args:
            text: Search text
            fields: Specific fields to search (subject, from_addr, to_addr, body_preview)
            limit: Maximum results to return

        Returns:
            SearchResults with BM25 ranked results

        Example:
            >>> results = await facade.search_fulltext("invoice payment")
            >>> print(f"Found {results.total_results} messages")
        """
        # Build FTS query
        if fields:
            # Validate fields
            invalid = set(fields) - self._executor.VALID_FTS_FIELDS
            if invalid:
                raise ValueError(f"Invalid FTS5 field names: {invalid}")
            fts_query = f"{{{' '.join(fields)}}}: {text}"
        else:
            fts_query = text

        # Execute
        from ._parser import QueryParams

        params = QueryParams(fulltext_terms=[text], fts_query=fts_query, original_query=text)
        return await self._executor.execute(params, limit=limit, offset=0)

    async def search_metadata(
        self,
        from_addr: str | None = None,
        to_addr: str | None = None,
        subject: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> SearchResults:
        """
        Structured metadata search.

        Args:
            from_addr: Filter by from address (partial match)
            to_addr: Filter by to address (partial match)
            subject: Filter by subject (partial match)
            after: Filter by date >= (ISO format)
            before: Filter by date < (ISO format)
            limit: Maximum results to return

        Returns:
            SearchResults ordered by date

        Example:
            >>> results = await facade.search_metadata(
            ...     from_addr="alice",
            ...     after="2024-01-01"
            ... )
        """
        from ._parser import QueryParams

        params = QueryParams(
            fulltext_terms=[],
            fts_query="",
            original_query="metadata search",
            from_addr=from_addr,
            to_addr=to_addr,
            subject_terms=[subject] if subject else [],
            after=after,
            before=before,
        )
        return await self._executor.execute(params, limit=limit, offset=0)

    async def close(self) -> None:
        """Close database connection."""
        await self._db_manager.close()

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()
