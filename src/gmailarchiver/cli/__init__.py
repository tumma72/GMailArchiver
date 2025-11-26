"""CLI layer - user interface and output formatting."""

from .command_context import CommandContext
from .output import (
    OperationHandle,
    OutputManager,
    SearchResultEntry,
)

__all__ = [
    "CommandContext",
    "OperationHandle",
    "OutputManager",
    "SearchResultEntry",
]
