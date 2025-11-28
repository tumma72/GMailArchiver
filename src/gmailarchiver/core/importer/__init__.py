"""Gmail importer package with facade pattern.

This package provides clean architecture for mbox archive importing.
Public API is exposed through ImporterFacade.

Internal modules (prefixed with _) should not be imported directly.
"""

from .facade import ImporterFacade, ImportResult, MultiImportResult

__all__ = ["ImporterFacade", "ImportResult", "MultiImportResult"]
