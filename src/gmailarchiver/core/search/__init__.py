"""Search package - exports SearchFacade."""

from ._types import MessageSearchResult, SearchResults
from .facade import SearchFacade

# Backward compatibility alias
SearchEngine = SearchFacade

__all__ = ["SearchFacade", "SearchEngine", "SearchResults", "MessageSearchResult"]
