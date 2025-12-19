"""Search execution engine for FTS5 and metadata queries.

Internal module - use SearchFacade instead.
"""

import time
from typing import TYPE_CHECKING, Self

from aiosqlite import Row

if TYPE_CHECKING:
    from ...data.hybrid_storage import HybridStorage

from ._parser import QueryParams
from ._types import MessageSearchResult, SearchResults


class SearchExecutor:
    """Execute search queries against database."""

    # Valid FTS5 field names (whitelist for security)
    VALID_FTS_FIELDS = {"subject", "from_addr", "to_addr", "body_preview"}

    def __init__(self, storage: HybridStorage) -> None:
        """
        Initialize executor with HybridStorage (internal - use create() instead).

        Args:
            storage: HybridStorage instance (provides access to DBManager)
        """
        self.storage = storage
        self.db = storage.db  # DBManager instance for advanced queries

    @classmethod
    async def create(cls, storage: HybridStorage) -> Self:
        """
        Create and validate executor.

        Args:
            storage: HybridStorage instance (provides access to DBManager)

        Returns:
            Initialized SearchExecutor

        Raises:
            ValueError: If database schema is missing required tables
        """
        instance = cls(storage)

        # Validate database has required tables
        if instance.db.conn is None:
            raise ValueError("Database connection not initialized")
        cursor = await instance.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError("Database schema error: missing 'messages' table")

        return instance

    async def execute(
        self, params: QueryParams, limit: int = 100, offset: int = 0
    ) -> SearchResults:
        """
        Execute search query based on parsed parameters.

        Args:
            params: Parsed query parameters
            limit: Maximum results to return
            offset: Result offset for pagination

        Returns:
            SearchResults with matching messages
        """
        start_time = time.perf_counter()

        # Determine search strategy based on params
        if params.has_fulltext and params.has_metadata:
            # Hybrid: FTS5 + metadata filters
            results = await self._search_hybrid(params, limit, offset)
        elif params.has_fulltext:
            # Pure FTS5 search
            results = await self._search_fulltext(params.fts_query, limit)
        elif params.has_metadata:
            # Pure metadata search
            results = await self._search_metadata(params, limit)
        else:
            # No filters - return all messages
            results = await self._search_all(limit)

        # Update timing
        results.execution_time_ms = (time.perf_counter() - start_time) * 1000
        results.query = params.original_query

        return results

    async def _search_fulltext(self, fts_query: str, limit: int) -> SearchResults:
        """
        Execute pure FTS5 search.

        Args:
            fts_query: FTS5 query string
            limit: Maximum results

        Returns:
            SearchResults with BM25 ranked results
        """
        try:
            if self.db.conn is None:
                return SearchResults(
                    total_results=0, results=[], query=fts_query, execution_time_ms=0
                )

            # Get total count first (without LIMIT)
            count_sql = """
                SELECT COUNT(*) as cnt
                FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?
            """
            cursor = await self.db.conn.execute(count_sql, (fts_query,))
            count_row = await cursor.fetchone()
            total_count = count_row["cnt"] if count_row else 0

            # Get limited results
            sql = """
                SELECT
                    m.gmail_id, m.rfc_message_id, m.subject, m.from_addr,
                    m.to_addr, m.date, m.body_preview, m.archive_file,
                    m.mbox_offset, -fts.rank AS relevance_score
                FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY fts.rank
                LIMIT ?
            """
            cursor = await self.db.conn.execute(sql, (fts_query, limit))
            rows = list(await cursor.fetchall())
            return self._build_results(rows, total_count=total_count)
        except Exception:
            # Invalid FTS query - return empty results
            return SearchResults(total_results=0, results=[], query=fts_query, execution_time_ms=0)

    async def _search_metadata(self, params: QueryParams, limit: int) -> SearchResults:
        """
        Execute metadata-only search.

        Args:
            params: Query parameters with metadata filters
            limit: Maximum results

        Returns:
            SearchResults ordered by date
        """
        where_clauses = []
        sql_params: list[str | int] = []

        if params.from_addr:
            where_clauses.append("from_addr LIKE ?")
            sql_params.append(f"%{params.from_addr}%")

        if params.to_addr:
            where_clauses.append("to_addr LIKE ?")
            sql_params.append(f"%{params.to_addr}%")

        if params.subject_terms:
            where_clauses.append("subject LIKE ?")
            sql_params.append(f"%{params.subject_terms[0]}%")

        if params.after:
            where_clauses.append("date >= ?")
            sql_params.append(params.after)

        if params.before:
            where_clauses.append("date < ?")
            sql_params.append(params.before)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        if self.db.conn is None:
            return SearchResults(
                total_results=0, results=[], query=params.original_query, execution_time_ms=0
            )

        # Get total count first (without LIMIT)
        count_sql = f"SELECT COUNT(*) as cnt FROM messages WHERE {where_sql}"
        cursor = await self.db.conn.execute(count_sql, sql_params)
        count_row = await cursor.fetchone()
        total_count = count_row["cnt"] if count_row else 0

        # Get limited results
        sql = f"""
            SELECT
                gmail_id, rfc_message_id, subject, from_addr,
                to_addr, date, body_preview, archive_file, mbox_offset
            FROM messages
            WHERE {where_sql}
            ORDER BY date DESC
            LIMIT ?
        """
        sql_params.append(limit)

        cursor = await self.db.conn.execute(sql, sql_params)
        rows = list(await cursor.fetchall())
        return self._build_results(rows, include_relevance=False, total_count=total_count)

    async def _search_hybrid(self, params: QueryParams, limit: int, offset: int) -> SearchResults:
        """
        Execute hybrid FTS5 + metadata search.

        Args:
            params: Query parameters
            limit: Maximum results
            offset: Result offset

        Returns:
            SearchResults with combined filters
        """
        where_clauses = []
        filter_params: list[str | int] = []

        if params.from_addr:
            where_clauses.append("m.from_addr LIKE ?")
            filter_params.append(f"%{params.from_addr}%")

        if params.to_addr:
            where_clauses.append("m.to_addr LIKE ?")
            filter_params.append(f"%{params.to_addr}%")

        if params.after:
            where_clauses.append("m.date >= ?")
            filter_params.append(params.after)

        if params.before:
            where_clauses.append("m.date < ?")
            filter_params.append(params.before)

        additional_where = " AND " + " AND ".join(where_clauses) if where_clauses else ""

        try:
            if self.db.conn is None:
                return SearchResults(
                    total_results=0, results=[], query=params.original_query, execution_time_ms=0
                )

            # Get total count first (without LIMIT)
            count_sql = f"""
                SELECT COUNT(*) as cnt
                FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?{additional_where}
            """
            count_params: list[str | int] = [params.fts_query, *filter_params]
            cursor = await self.db.conn.execute(count_sql, count_params)
            count_row = await cursor.fetchone()
            total_count = count_row["cnt"] if count_row else 0

            # Get limited results
            sql = f"""
                SELECT
                    m.gmail_id, m.rfc_message_id, m.subject, m.from_addr,
                    m.to_addr, m.date, m.body_preview, m.archive_file,
                    m.mbox_offset, -fts.rank AS relevance_score
                FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?{additional_where}
                ORDER BY fts.rank
                LIMIT ?
            """
            sql_params: list[str | int] = [params.fts_query, *filter_params, limit]

            cursor = await self.db.conn.execute(sql, sql_params)
            rows = list(await cursor.fetchall())
            return self._build_results(rows, total_count=total_count)
        except Exception:
            # Invalid FTS query - return empty results
            return SearchResults(
                total_results=0, results=[], query=params.original_query, execution_time_ms=0
            )

    async def _search_all(self, limit: int) -> SearchResults:
        """
        Return all messages (no filters).

        Args:
            limit: Maximum results

        Returns:
            SearchResults ordered by date
        """
        if self.db.conn is None:
            return SearchResults(total_results=0, results=[], query="", execution_time_ms=0)

        # Get total count first (without LIMIT)
        count_sql = "SELECT COUNT(*) as cnt FROM messages"
        cursor = await self.db.conn.execute(count_sql)
        count_row = await cursor.fetchone()
        total_count = count_row["cnt"] if count_row else 0

        # Get limited results
        sql = """
            SELECT
                gmail_id, rfc_message_id, subject, from_addr,
                to_addr, date, body_preview, archive_file, mbox_offset
            FROM messages
            ORDER BY date DESC
            LIMIT ?
        """
        cursor = await self.db.conn.execute(sql, (limit,))
        rows = list(await cursor.fetchall())
        return self._build_results(rows, include_relevance=False, total_count=total_count)

    def _build_results(
        self, rows: list[Row], include_relevance: bool = True, total_count: int | None = None
    ) -> SearchResults:
        """
        Build SearchResults from database rows.

        Args:
            rows: Database rows
            include_relevance: Whether to include relevance scores
            total_count: Total matching results (before LIMIT). If None, uses len(rows).

        Returns:
            SearchResults object
        """
        results = [
            MessageSearchResult(
                gmail_id=row["gmail_id"],
                rfc_message_id=row["rfc_message_id"] or "",
                subject=row["subject"] or "",
                from_addr=row["from_addr"] or "",
                to_addr=row["to_addr"],
                date=row["date"] or "",
                body_preview=row["body_preview"],
                archive_file=row["archive_file"],
                mbox_offset=row["mbox_offset"],
                relevance_score=(
                    row["relevance_score"]
                    if include_relevance and "relevance_score" in row.keys()
                    else None
                ),
            )
            for row in rows
        ]

        return SearchResults(
            total_results=total_count if total_count is not None else len(results),
            results=results,
            query="",
            execution_time_ms=0,
        )
