"""Search facade - simplified interface for message search.

Coordinates query parsing and execution for Gmail-style searches.
"""

from pathlib import Path

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
        >>> with SearchFacade("state.db") as search:
        ...     results = search.search("from:alice meeting after:2024-01-01")
        ...     print(f"Found {results.total_results} messages")
    """

    def __init__(self, state_db_path: str) -> None:
        """
        Initialize search facade.

        Args:
            state_db_path: Path to SQLite state database

        Raises:
            FileNotFoundError: If database doesn't exist
        """
        db_path = Path(state_db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {state_db_path}")

        self.db_path = state_db_path
        self._parser = QueryParser()
        self._executor = SearchExecutor(state_db_path)

    def search(self, query: str, limit: int = 100, offset: int = 0) -> SearchResults:
        """
        Execute Gmail-style search query.

        Args:
            query: Gmail-style search query
            limit: Maximum results to return
            offset: Result offset for pagination

        Returns:
            SearchResults with matching messages

        Example:
            >>> results = facade.search("from:alice subject:meeting project")
            >>> for msg in results.results:
            ...     print(f"{msg.subject} - {msg.from_addr}")
        """
        # Parse query
        params = self._parser.parse(query)

        # Execute search
        results = self._executor.execute(params, limit=limit, offset=offset)

        return results

    def search_fulltext(
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
            >>> results = facade.search_fulltext("invoice payment")
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
        return self._executor.execute(params, limit=limit, offset=0)

    def search_metadata(
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
            >>> results = facade.search_metadata(
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
        return self._executor.execute(params, limit=limit, offset=0)

    def close(self) -> None:
        """Close database connection."""
        self._executor.close()

    def __enter__(self) -> SearchFacade:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()
