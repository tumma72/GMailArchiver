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
from .consolidate import ConsolidateConfig, ConsolidateResult, ConsolidateWorkflow
from .dedupe import DedupeConfig, DedupeResult, DedupeWorkflow
from .doctor import DoctorConfig, DoctorResult, DoctorWorkflow
from .import_ import ImportConfig, ImportResult, ImportWorkflow
from .migrate import MigrateConfig, MigrateResult, MigrateWorkflow
from .repair import RepairConfig, RepairResult, RepairWorkflow
from .search import SearchConfig, SearchResult, SearchWorkflow
from .status import StatusConfig, StatusResult, StatusWorkflow
from .validate import ValidateConfig, ValidateResult, ValidateWorkflow
from .verify import VerifyConfig, VerifyResult, VerifyType, VerifyWorkflow

__all__ = [
    "ArchiveConfig",
    "ArchiveResult",
    "ArchiveWorkflow",
    "ConsolidateConfig",
    "ConsolidateResult",
    "ConsolidateWorkflow",
    "DedupeConfig",
    "DedupeResult",
    "DedupeWorkflow",
    "DoctorConfig",
    "DoctorResult",
    "DoctorWorkflow",
    "ImportConfig",
    "ImportResult",
    "ImportWorkflow",
    "MigrateConfig",
    "MigrateResult",
    "MigrateWorkflow",
    "RepairConfig",
    "RepairResult",
    "RepairWorkflow",
    "SearchConfig",
    "SearchResult",
    "SearchWorkflow",
    "StatusConfig",
    "StatusResult",
    "StatusWorkflow",
    "ValidateConfig",
    "ValidateResult",
    "ValidateWorkflow",
    "VerifyConfig",
    "VerifyResult",
    "VerifyType",
    "VerifyWorkflow",
]
