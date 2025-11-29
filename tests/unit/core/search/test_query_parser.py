"""Tests for query parser module (TDD)."""

from gmailarchiver.core.search._parser import QueryParams, QueryParser


class TestQueryParser:
    """Test Gmail-style query parsing."""

    def test_parse_empty_query(self) -> None:
        """Test parsing empty query."""
        parser = QueryParser()
        params = parser.parse("")

        assert params.fulltext_terms == []
        assert params.from_addr is None
        assert params.to_addr is None
        assert params.subject_terms == []
        assert params.after is None
        assert params.before is None

    def test_parse_fulltext_only(self) -> None:
        """Test parsing fulltext search terms."""
        parser = QueryParser()
        params = parser.parse("meeting project urgent")

        assert params.fulltext_terms == ["meeting", "project", "urgent"]
        assert params.from_addr is None
        assert params.to_addr is None

    def test_parse_from_filter(self) -> None:
        """Test parsing from: filter."""
        parser = QueryParser()
        params = parser.parse("from:alice@example.com")

        assert params.from_addr == "alice@example.com"
        assert params.fulltext_terms == []

    def test_parse_to_filter(self) -> None:
        """Test parsing to: filter."""
        parser = QueryParser()
        params = parser.parse("to:bob@example.com")

        assert params.to_addr == "bob@example.com"
        assert params.fulltext_terms == []

    def test_parse_subject_filter(self) -> None:
        """Test parsing subject: filter."""
        parser = QueryParser()
        params = parser.parse("subject:invoice")

        assert params.subject_terms == ["invoice"]
        # Subject term should be added to fulltext with field constraint
        assert "{subject}:" in params.fts_query

    def test_parse_date_filters(self) -> None:
        """Test parsing after: and before: filters."""
        parser = QueryParser()
        params = parser.parse("after:2024-01-01 before:2024-12-31")

        assert params.after == "2024-01-01"
        assert params.before == "2024-12-31"
        assert params.fulltext_terms == []

    def test_parse_combined_filters(self) -> None:
        """Test parsing combination of filters."""
        parser = QueryParser()
        params = parser.parse("from:alice subject:meeting project after:2024-01-01")

        assert params.from_addr == "alice"
        assert params.subject_terms == ["meeting"]
        assert params.fulltext_terms == ["project"]
        assert params.after == "2024-01-01"

    def test_parse_preserves_original_query(self) -> None:
        """Test that original query is preserved."""
        parser = QueryParser()
        original = "from:alice subject:meeting project"
        params = parser.parse(original)

        assert params.original_query == original

    def test_parse_builds_fts_query(self) -> None:
        """Test that FTS query is built correctly."""
        parser = QueryParser()
        params = parser.parse("meeting project")

        assert params.fts_query == "meeting project"

    def test_parse_builds_fts_query_with_subject(self) -> None:
        """Test FTS query with subject field constraint."""
        parser = QueryParser()
        params = parser.parse("subject:invoice payment")

        assert "{subject}: invoice" in params.fts_query
        assert "payment" in params.fts_query


class TestQueryParams:
    """Test QueryParams dataclass."""

    def test_has_fulltext_terms(self) -> None:
        """Test detecting fulltext terms."""
        params = QueryParams(fulltext_terms=["test"], fts_query="test", original_query="test")
        assert params.has_fulltext

        params_empty = QueryParams(fulltext_terms=[], fts_query="", original_query="")
        assert not params_empty.has_fulltext

    def test_has_metadata_filters(self) -> None:
        """Test detecting metadata filters."""
        params = QueryParams(
            fulltext_terms=[],
            fts_query="",
            original_query="from:alice",
            from_addr="alice",
        )
        assert params.has_metadata

        params_no_meta = QueryParams(fulltext_terms=[], fts_query="", original_query="")
        assert not params_no_meta.has_metadata
