"""Full-text and metadata search for archived Gmail messages.

This module provides a SearchEngine for querying archived Gmail messages using
SQLite FTS5 full-text search and metadata filters. It supports Gmail-style query
syntax for intuitive searching.

Query Syntax Examples:
    - from:alice@example.com
    - to:bob@example.com
    - subject:meeting
    - after:2024-01-01
    - before:2024-12-31
    - meeting project (bare words search all fields)
    - from:alice subject:invoice after:2024-01-01 (combined filters)

Security:
    All query parameters are passed through parameterized SQL to prevent injection.
    Field names for FTS5 are validated against a whitelist.
"""

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MessageSearchResult:
    """Single message search result."""

    gmail_id: str
    rfc_message_id: str
    subject: str
    from_addr: str
    to_addr: str | None
    date: str
    body_preview: str | None
    archive_file: str
    mbox_offset: int
    relevance_score: float | None


@dataclass
class SearchResults:
    """Search results container."""

    total_results: int
    results: list[MessageSearchResult]
    query: str
    execution_time_ms: float


class SearchEngine:
    """Full-text and metadata search for archived messages."""

    # Valid FTS5 field names (whitelist for security)
    VALID_FTS_FIELDS = {'subject', 'from_addr', 'to_addr', 'body_preview'}

    def __init__(self, state_db_path: str) -> None:
        """
        Initialize search engine.

        Args:
            state_db_path: Path to SQLite state database

        Raises:
            Exception: If database doesn't exist or can't be opened
        """
        db_path = Path(state_db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {state_db_path}")

        self.db_path = state_db_path
        self.conn = sqlite3.connect(state_db_path)
        self.conn.row_factory = sqlite3.Row

        # Verify schema has required tables
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not cursor.fetchone():
            raise ValueError("Database missing 'messages' table (v1.1 schema required)")

    def search(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0
    ) -> SearchResults:
        """
        Execute Gmail-style search query and return results.

        Supports Gmail query syntax:
        - from:alice@example.com
        - to:bob@example.com
        - subject:meeting
        - after:2024-01-01
        - before:2024-12-31
        - Bare words perform full-text search

        Args:
            query: Gmail-style search query
            limit: Maximum results to return
            offset: Result offset for pagination

        Returns:
            SearchResults with matching messages
        """
        start_time = time.perf_counter()

        # Parse Gmail-style query
        params = self._parse_gmail_query(query)

        # Extract typed values from params
        fulltext_terms = params['fulltext_terms']
        from_addr = params['from_addr']
        to_addr = params['to_addr']
        subject_terms = params['subject_terms']
        after = params['after']
        before = params['before']

        # Type assertions for mypy
        assert isinstance(fulltext_terms, list)
        assert isinstance(from_addr, (str, type(None)))
        assert isinstance(to_addr, (str, type(None)))
        assert isinstance(subject_terms, list)
        assert isinstance(after, (str, type(None)))
        assert isinstance(before, (str, type(None)))

        # Determine search strategy
        if fulltext_terms:
            # Has free-text terms - use FTS5
            fulltext_query = ' '.join(fulltext_terms)

            # If we also have metadata filters, combine them
            if any([from_addr, to_addr, subject_terms, after, before]):
                # Hybrid: FTS5 + metadata filters
                results = self._search_hybrid(
                    fulltext_query=fulltext_query,
                    from_addr=from_addr,
                    to_addr=to_addr,
                    subject_terms=subject_terms,
                    after=after,
                    before=before,
                    limit=limit,
                    offset=offset
                )
            else:
                # Pure FTS5 search
                results = self.search_fulltext(fulltext_query, limit=limit)
        else:
            # Pure metadata search
            results = self.search_metadata(
                from_addr=from_addr,
                to_addr=to_addr,
                subject=subject_terms[0] if subject_terms else None,
                after=after,
                before=before,
                limit=limit
            )

        # Update query in results
        results.query = query
        results.execution_time_ms = (time.perf_counter() - start_time) * 1000

        return results

    def search_fulltext(
        self,
        text: str,
        fields: list[str] | None = None,
        limit: int = 100
    ) -> SearchResults:
        """
        Direct FTS5 full-text search.

        Args:
            text: Search text
            fields: Specific fields to search (subject, from_addr, to_addr, body_preview)
            limit: Maximum results to return

        Returns:
            SearchResults with ranked results (BM25 scoring)

        Raises:
            ValueError: If invalid field names are provided
        """
        start_time = time.perf_counter()

        # Validate fields against whitelist
        if fields:
            invalid_fields = set(fields) - self.VALID_FTS_FIELDS
            if invalid_fields:
                raise ValueError(f"Invalid FTS5 field names: {invalid_fields}")

        # Build FTS5 query
        if fields:
            # Search specific fields: {field1 field2}: "text"
            fts_query = f"{{{' '.join(fields)}}}: {text}"
        else:
            # Search all fields
            fts_query = text

        # Execute FTS5 search
        # Note: FTS5 rank is negative (lower = better match), so sort ascending
        sql = '''
            SELECT
                m.gmail_id, m.rfc_message_id, m.subject, m.from_addr,
                m.to_addr, m.date, m.body_preview, m.archive_file,
                m.mbox_offset, -fts.rank AS relevance_score
            FROM messages m
            JOIN messages_fts fts ON m.rowid = fts.rowid
            WHERE messages_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
        '''

        try:
            cursor = self.conn.execute(sql, (fts_query, limit))
            rows = cursor.fetchall()

            results = [
                MessageSearchResult(
                    gmail_id=row['gmail_id'],
                    rfc_message_id=row['rfc_message_id'],
                    subject=row['subject'] or '',
                    from_addr=row['from_addr'] or '',
                    to_addr=row['to_addr'],
                    date=row['date'] or '',
                    body_preview=row['body_preview'],
                    archive_file=row['archive_file'],
                    mbox_offset=row['mbox_offset'],
                    relevance_score=row['relevance_score']
                )
                for row in rows
            ]

            execution_time = (time.perf_counter() - start_time) * 1000

            return SearchResults(
                total_results=len(results),
                results=results,
                query=text,
                execution_time_ms=execution_time
            )
        except sqlite3.OperationalError:
            # FTS5 query syntax error - return empty results
            execution_time = (time.perf_counter() - start_time) * 1000
            return SearchResults(
                total_results=0,
                results=[],
                query=text,
                execution_time_ms=execution_time
            )

    def search_metadata(
        self,
        from_addr: str | None = None,
        to_addr: str | None = None,
        subject: str | None = None,
        after: str | None = None,
        before: str | None = None,
        has_label: str | None = None,
        limit: int = 100
    ) -> SearchResults:
        """
        Structured metadata search.

        Args:
            from_addr: Filter by from address (partial match)
            to_addr: Filter by to address (partial match)
            subject: Filter by subject (partial match)
            after: Filter by date >= (ISO format)
            before: Filter by date < (ISO format)
            has_label: Filter by label (unused for now)
            limit: Maximum results to return

        Returns:
            SearchResults ordered by date
        """
        start_time = time.perf_counter()

        # Build WHERE clause
        where_clauses = []
        params: list[str | int] = []

        if from_addr:
            where_clauses.append('from_addr LIKE ?')
            params.append(f'%{from_addr}%')

        if to_addr:
            where_clauses.append('to_addr LIKE ?')
            params.append(f'%{to_addr}%')

        if subject:
            where_clauses.append('subject LIKE ?')
            params.append(f'%{subject}%')

        if after:
            where_clauses.append('date >= ?')
            params.append(after)

        if before:
            where_clauses.append('date < ?')
            params.append(before)

        # Build SQL
        where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'

        sql = f'''
            SELECT
                gmail_id, rfc_message_id, subject, from_addr,
                to_addr, date, body_preview, archive_file, mbox_offset
            FROM messages
            WHERE {where_sql}
            ORDER BY date DESC
            LIMIT ?
        '''

        params.append(limit)

        cursor = self.conn.execute(sql, params)
        rows = cursor.fetchall()

        results = [
            MessageSearchResult(
                gmail_id=row['gmail_id'],
                rfc_message_id=row['rfc_message_id'],
                subject=row['subject'] or '',
                from_addr=row['from_addr'] or '',
                to_addr=row['to_addr'],
                date=row['date'] or '',
                body_preview=row['body_preview'],
                archive_file=row['archive_file'],
                mbox_offset=row['mbox_offset'],
                relevance_score=None  # No ranking for metadata search
            )
            for row in rows
        ]

        execution_time = (time.perf_counter() - start_time) * 1000

        return SearchResults(
            total_results=len(results),
            results=results,
            query='metadata search',
            execution_time_ms=execution_time
        )

    def _search_hybrid(
        self,
        fulltext_query: str,
        from_addr: str | None,
        to_addr: str | None,
        subject_terms: list[str],
        after: str | None,
        before: str | None,
        limit: int,
        offset: int
    ) -> SearchResults:
        """
        Hybrid search combining FTS5 and metadata filters.

        Args:
            fulltext_query: Full-text search terms
            from_addr: From address filter
            to_addr: To address filter
            subject_terms: Subject search terms
            after: Date >= filter
            before: Date < filter
            limit: Maximum results
            offset: Result offset

        Returns:
            SearchResults with combined filters
        """
        start_time = time.perf_counter()

        # Build WHERE clause for metadata filters
        where_clauses = []
        params: list[str | int] = [fulltext_query]

        if from_addr:
            where_clauses.append('m.from_addr LIKE ?')
            params.append(f'%{from_addr}%')

        if to_addr:
            where_clauses.append('m.to_addr LIKE ?')
            params.append(f'%{to_addr}%')

        if subject_terms:
            # Subject terms are already in FTS query
            pass

        if after:
            where_clauses.append('m.date >= ?')
            params.append(after)

        if before:
            where_clauses.append('m.date < ?')
            params.append(before)

        # Build SQL
        additional_where = ' AND ' + ' AND '.join(where_clauses) if where_clauses else ''

        sql = f'''
            SELECT
                m.gmail_id, m.rfc_message_id, m.subject, m.from_addr,
                m.to_addr, m.date, m.body_preview, m.archive_file,
                m.mbox_offset, -fts.rank AS relevance_score
            FROM messages m
            JOIN messages_fts fts ON m.rowid = fts.rowid
            WHERE messages_fts MATCH ?{additional_where}
            ORDER BY fts.rank
            LIMIT ?
        '''

        params.append(limit)

        cursor = self.conn.execute(sql, params)
        rows = cursor.fetchall()

        results = [
            MessageSearchResult(
                gmail_id=row['gmail_id'],
                rfc_message_id=row['rfc_message_id'],
                subject=row['subject'] or '',
                from_addr=row['from_addr'] or '',
                to_addr=row['to_addr'],
                date=row['date'] or '',
                body_preview=row['body_preview'],
                archive_file=row['archive_file'],
                mbox_offset=row['mbox_offset'],
                relevance_score=row['relevance_score']
            )
            for row in rows
        ]

        execution_time = (time.perf_counter() - start_time) * 1000

        return SearchResults(
            total_results=len(results),
            results=results,
            query=fulltext_query,
            execution_time_ms=execution_time
        )

    def _parse_gmail_query(self, query: str) -> dict[str, object]:
        """
        Parse Gmail-style query into search parameters.

        Args:
            query: Gmail-style query string

        Returns:
            Dictionary with parsed parameters
        """
        params: dict[str, object] = {
            'fulltext_terms': [],
            'from_addr': None,
            'to_addr': None,
            'subject_terms': [],
            'after': None,
            'before': None,
        }

        # Regex patterns for special terms
        from_pattern = r'from:(\S+)'
        to_pattern = r'to:(\S+)'
        subject_pattern = r'subject:(\S+)'
        after_pattern = r'after:(\S+)'
        before_pattern = r'before:(\S+)'

        # Extract special terms
        from_match = re.search(from_pattern, query)
        if from_match:
            params['from_addr'] = from_match.group(1)
            query = re.sub(from_pattern, '', query)

        to_match = re.search(to_pattern, query)
        if to_match:
            params['to_addr'] = to_match.group(1)
            query = re.sub(to_pattern, '', query)

        subject_match = re.search(subject_pattern, query)
        if subject_match:
            subject_term = subject_match.group(1)
            params['subject_terms'] = [subject_term]
            # Add subject term to fulltext query with field constraint
            query = re.sub(subject_pattern, f'{{subject}}: {subject_term}', query)

        after_match = re.search(after_pattern, query)
        if after_match:
            params['after'] = after_match.group(1)
            query = re.sub(after_pattern, '', query)

        before_match = re.search(before_pattern, query)
        if before_match:
            params['before'] = before_match.group(1)
            query = re.sub(before_pattern, '', query)

        # Remaining words are fulltext search terms
        remaining_terms = query.strip().split()
        if remaining_terms:
            params['fulltext_terms'] = remaining_terms

        return params

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def __enter__(self) -> SearchEngine:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()
