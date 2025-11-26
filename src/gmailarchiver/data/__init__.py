"""Data layer - database and storage operations.

This layer manages all persistent state:
- SQLite database operations (DBManager)
- Schema version management (SchemaManager)
- Atomic mbox + database operations (HybridStorage)
- Database migrations (MigrationManager)
- Legacy state tracking (ArchiveState)

Dependencies: shared layer only
"""

from .db_manager import DBManager, DBManagerError, SchemaValidationError
from .hybrid_storage import (
    ConsolidationResult,
    HybridStorage,
    HybridStorageError,
    IntegrityError,
)
from .migration import MigrationManager
from .schema_manager import (
    SchemaCapability,
    SchemaManager,
    SchemaVersion,
    SchemaVersionError,
)
from .state import ArchiveState

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
    # MigrationManager
    "MigrationManager",
    # ArchiveState (legacy)
    "ArchiveState",
]
