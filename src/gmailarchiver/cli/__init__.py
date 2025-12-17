"""CLI layer - user interface and output formatting."""

from .adapters import CLIProgressAdapter
from .command_context import CommandContext
from .output import (
    OperationHandle,
    OutputManager,
    SearchResultEntry,
)

__all__ = [
    "CLIProgressAdapter",
    "CommandContext",
    "OperationHandle",
    "OutputManager",
    "SearchResultEntry",
]
