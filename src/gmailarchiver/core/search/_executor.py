"""Search execution engine for FTS5 and metadata queries.

Internal module - use SearchFacade instead.
"""

import sqlite3
import time

from ._parser import QueryParams
from ._types import MessageSearchResult, SearchResults


class SearchExecutor:
    """Execute search queries against database."""

    # Valid FTS5 field names (whitelist for security)
    VALID_FTS_FIELDS = {"subject", "from_addr", "to_addr", "body_preview"}

    def __init__(self, db_path: str) -> None:
        """
        Initialize executor with database connection.

        Args:
            db_path: Path to SQLite database

        Raises:
            ValueError: If database schema is missing required tables
        """
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

        # Validate database has required tables
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not cursor.fetchone():
            self.conn.close()
            raise ValueError(f"Database schema error: missing 'messages' table in {db_path}")

    def execute(self, params: QueryParams, limit: int = 100, offset: int = 0) -> SearchResults:
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
            results = self._search_hybrid(params, limit, offset)
        elif params.has_fulltext:
            # Pure FTS5 search
            results = self._search_fulltext(params.fts_query, limit)
        elif params.has_metadata:
            # Pure metadata search
            results = self._search_metadata(params, limit)
        else:
            # No filters - return all messages
            results = self._search_all(limit)

        # Update timing
        results.execution_time_ms = (time.perf_counter() - start_time) * 1000
        results.query = params.original_query

        return results

    def _search_fulltext(self, fts_query: str, limit: int) -> SearchResults:
        """
        Execute pure FTS5 search.

        Args:
            fts_query: FTS5 query string
            limit: Maximum results

        Returns:
            SearchResults with BM25 ranked results
        """
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

        try:
            cursor = self.conn.execute(sql, (fts_query, limit))
            rows = cursor.fetchall()
            return self._build_results(rows)
        except sqlite3.OperationalError:
            # Invalid FTS query - return empty results
            return SearchResults(total_results=0, results=[], query=fts_query, execution_time_ms=0)

    def _search_metadata(self, params: QueryParams, limit: int) -> SearchResults:
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

        cursor = self.conn.execute(sql, sql_params)
        rows = cursor.fetchall()
        return self._build_results(rows, include_relevance=False)

    def _search_hybrid(self, params: QueryParams, limit: int, offset: int) -> SearchResults:
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
        sql_params: list[str | int] = [params.fts_query]

        if params.from_addr:
            where_clauses.append("m.from_addr LIKE ?")
            sql_params.append(f"%{params.from_addr}%")

        if params.to_addr:
            where_clauses.append("m.to_addr LIKE ?")
            sql_params.append(f"%{params.to_addr}%")

        if params.after:
            where_clauses.append("m.date >= ?")
            sql_params.append(params.after)

        if params.before:
            where_clauses.append("m.date < ?")
            sql_params.append(params.before)

        additional_where = " AND " + " AND ".join(where_clauses) if where_clauses else ""

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

        sql_params.append(limit)

        try:
            cursor = self.conn.execute(sql, sql_params)
            rows = cursor.fetchall()
            return self._build_results(rows)
        except sqlite3.OperationalError:
            # Invalid FTS query - return empty results
            return SearchResults(
                total_results=0, results=[], query=params.original_query, execution_time_ms=0
            )

    def _search_all(self, limit: int) -> SearchResults:
        """
        Return all messages (no filters).

        Args:
            limit: Maximum results

        Returns:
            SearchResults ordered by date
        """
        sql = """
            SELECT
                gmail_id, rfc_message_id, subject, from_addr,
                to_addr, date, body_preview, archive_file, mbox_offset
            FROM messages
            ORDER BY date DESC
            LIMIT ?
        """

        cursor = self.conn.execute(sql, (limit,))
        rows = cursor.fetchall()
        return self._build_results(rows, include_relevance=False)

    def _build_results(
        self, rows: list[sqlite3.Row], include_relevance: bool = True
    ) -> SearchResults:
        """
        Build SearchResults from database rows.

        Args:
            rows: Database rows
            include_relevance: Whether to include relevance scores

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
            total_results=len(results), results=results, query="", execution_time_ms=0
        )

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
