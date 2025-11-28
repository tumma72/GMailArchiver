"""Search package - exports SearchFacade.

For backward compatibility, SearchEngine is still available.
"""

from ..search_legacy import MessageSearchResult, SearchEngine, SearchResults
from .facade import SearchFacade

__all__ = ["SearchFacade", "SearchEngine", "SearchResults", "MessageSearchResult"]
