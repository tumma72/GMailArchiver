"""Gmail archiver package with facade pattern.

This package provides clean architecture for Gmail message archiving.
Public API is exposed through ArchiverFacade.

Internal modules (prefixed with _) should not be imported directly.
"""

from .facade import ArchiverFacade

__all__ = ["ArchiverFacade"]
