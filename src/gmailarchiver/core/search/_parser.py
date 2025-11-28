"""Gmail-style query parsing for search.

Internal module - use SearchFacade instead.
"""

import re
from dataclasses import dataclass, field


@dataclass
class QueryParams:
    """Parsed query parameters."""

    fulltext_terms: list[str] = field(default_factory=list)
    fts_query: str = ""
    original_query: str = ""
    from_addr: str | None = None
    to_addr: str | None = None
    subject_terms: list[str] = field(default_factory=list)
    after: str | None = None
    before: str | None = None

    @property
    def has_fulltext(self) -> bool:
        """Check if query has fulltext search terms."""
        return len(self.fulltext_terms) > 0

    @property
    def has_metadata(self) -> bool:
        """Check if query has metadata filters."""
        return any(
            [
                self.from_addr,
                self.to_addr,
                self.subject_terms,
                self.after,
                self.before,
            ]
        )


class QueryParser:
    """Parse Gmail-style query syntax into structured parameters."""

    # Regex patterns for special terms
    _FROM_PATTERN = r"from:(\S+)"
    _TO_PATTERN = r"to:(\S+)"
    _SUBJECT_PATTERN = r"subject:(\S+)"
    _AFTER_PATTERN = r"after:(\S+)"
    _BEFORE_PATTERN = r"before:(\S+)"

    def parse(self, query: str) -> QueryParams:
        """
        Parse Gmail-style query into structured parameters.

        Supported syntax:
        - from:alice@example.com
        - to:bob@example.com
        - subject:meeting
        - after:2024-01-01
        - before:2024-12-31
        - Bare words perform full-text search

        Args:
            query: Gmail-style search query

        Returns:
            QueryParams with parsed parameters
        """
        params = QueryParams(original_query=query)
        remaining_query = query

        # Extract from: filter
        from_match = re.search(self._FROM_PATTERN, query)
        if from_match:
            params.from_addr = from_match.group(1)
            remaining_query = re.sub(self._FROM_PATTERN, "", remaining_query)

        # Extract to: filter
        to_match = re.search(self._TO_PATTERN, query)
        if to_match:
            params.to_addr = to_match.group(1)
            remaining_query = re.sub(self._TO_PATTERN, "", remaining_query)

        # Extract subject: filter
        subject_match = re.search(self._SUBJECT_PATTERN, query)
        fts_subject_part = ""
        if subject_match:
            subject_term = subject_match.group(1)
            params.subject_terms = [subject_term]
            # Build FTS field constraint separately
            fts_subject_part = f"{{subject}}: {subject_term}"
            # Remove subject: from remaining query
            remaining_query = re.sub(self._SUBJECT_PATTERN, "", remaining_query)

        # Extract after: filter
        after_match = re.search(self._AFTER_PATTERN, query)
        if after_match:
            params.after = after_match.group(1)
            remaining_query = re.sub(self._AFTER_PATTERN, "", remaining_query)

        # Extract before: filter
        before_match = re.search(self._BEFORE_PATTERN, query)
        if before_match:
            params.before = before_match.group(1)
            remaining_query = re.sub(self._BEFORE_PATTERN, "", remaining_query)

        # Remaining words are fulltext search terms
        remaining_terms = remaining_query.strip().split()
        if remaining_terms:
            params.fulltext_terms = remaining_terms

        # Build FTS query combining subject constraint and remaining terms
        fts_parts = []
        if fts_subject_part:
            fts_parts.append(fts_subject_part)
        if remaining_terms:
            fts_parts.append(" ".join(remaining_terms))

        params.fts_query = " ".join(fts_parts)

        return params
