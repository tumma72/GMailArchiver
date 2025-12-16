"""Async workflows for Gmail Archiver commands.

This module contains the async implementation of all CLI commands.
Each command has a corresponding async workflow class that contains
the business logic, called via asyncio.run() from the CLI layer.

Workflow Pattern:
- CLI commands are sync (Typer limitation)
- Workflows are async (business logic)
- Single asyncio.run() call per command
- Workflows use core facades and data layer

Dependencies: core layer only (not CLI layer)
"""

# Import workflows for CLI commands to use
from .archive import ArchiveConfig, ArchiveResult, ArchiveWorkflow
from .status import StatusConfig, StatusResult, StatusWorkflow

__all__ = [
    "ArchiveConfig",
    "ArchiveResult",
    "ArchiveWorkflow",
    "StatusConfig",
    "StatusResult",
    "StatusWorkflow",
]
