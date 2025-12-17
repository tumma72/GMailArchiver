"""Data layer - database and storage operations.

This layer manages all persistent state:
- SQLite database operations (DBManager)
- Schema version management (SchemaManager)
- Atomic mbox + database operations (HybridStorage)
- Database migrations (MigrationManager)
- Task scheduling (Scheduler)

Dependencies: shared layer only
"""

from .db_manager import DBManager, DBManagerError, SchemaValidationError
from .hybrid_storage import (
    ArchiveStats,
    ConsolidationResult,
    HybridStorage,
    HybridStorageError,
    IntegrityError,
)
from .migration import MigrationManager
from .scheduler import ScheduleEntry, Scheduler, ScheduleValidationError
from .schema_manager import (
    SchemaCapability,
    SchemaManager,
    SchemaVersion,
    SchemaVersionError,
)

__all__ = [
    # DBManager
    "DBManager",
    "DBManagerError",
    "SchemaValidationError",
    # SchemaManager
    "SchemaManager",
    "SchemaVersion",
    "SchemaCapability",
    "SchemaVersionError",
    # HybridStorage
    "HybridStorage",
    "HybridStorageError",
    "IntegrityError",
    "ConsolidationResult",
    "ArchiveStats",
    # MigrationManager
    "MigrationManager",
    # Scheduler
    "Scheduler",
    "ScheduleEntry",
    "ScheduleValidationError",
]
