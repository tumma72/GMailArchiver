"""Deduplicator package - exports DeduplicatorFacade.

For backward compatibility, MessageDeduplicator is still available.
"""

from ..deduplicator_legacy import (
    DeduplicationError,
    DeduplicationReport,
    DeduplicationResult,
    MessageDeduplicator,
    MessageInfo,
)
from .facade import DeduplicatorFacade

__all__ = [
    "DeduplicatorFacade",
    "MessageDeduplicator",
    "DeduplicationError",
    "DeduplicationReport",
    "DeduplicationResult",
    "MessageInfo",
]
