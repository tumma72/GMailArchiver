"""Deduplicator package - exports DeduplicatorFacade."""

from ._scanner import MessageInfo
from .facade import DeduplicationReport, DeduplicationResult, DeduplicatorFacade


class DeduplicationError(Exception):
    """Error during deduplication operation."""

    pass


# Backward compatibility alias
MessageDeduplicator = DeduplicatorFacade

__all__ = [
    "DeduplicatorFacade",
    "MessageDeduplicator",
    "DeduplicationError",
    "DeduplicationReport",
    "DeduplicationResult",
    "MessageInfo",
]
