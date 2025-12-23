"""Centralized schema version management for Gmail Archiver.

This module provides a single source of truth for:
- Schema version constants
- Version detection
- Version comparison
- Capability checks
- Automatic migration coordination

All database access should go through SchemaManager for version-related operations.
"""

import logging
import sqlite3
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class SchemaVersion(Enum):
    """Known schema versions with comparison support."""

    V1_0 = "1.0"
    V1_1 = "1.1"
    V1_2 = "1.2"
    V1_3 = "1.3"
    NONE = "none"  # Empty or missing database
    UNKNOWN = "unknown"  # Unrecognized schema

    def __lt__(self, other: SchemaVersion) -> bool:
        if not isinstance(other, SchemaVersion):
            return NotImplemented
        order = [self.NONE, self.V1_0, self.V1_1, self.V1_2, self.V1_3, self.UNKNOWN]
        return order.index(self) < order.index(other)

    def __le__(self, other: SchemaVersion) -> bool:
        return self == other or self < other

    def __gt__(self, other: SchemaVersion) -> bool:
        if not isinstance(other, SchemaVersion):
            return NotImplemented
        return not self <= other

    def __ge__(self, other: SchemaVersion) -> bool:
        return self == other or self > other

    @classmethod
    def from_string(cls, version_str: str) -> SchemaVersion:
        """Convert a version string to SchemaVersion enum."""
        for v in cls:
            if v.value == version_str:
                return v
        return cls.UNKNOWN

    @property
    def is_valid(self) -> bool:
        """Check if this is a valid, known version."""
        return self not in (SchemaVersion.NONE, SchemaVersion.UNKNOWN)


class SchemaCapability(Enum):
    """Capabilities available in different schema versions.

    Use these instead of version string comparisons to check
    what features are available.
    """

    BASIC_ARCHIVING = auto()  # v1.0+: Basic message archiving
    MBOX_OFFSETS = auto()  # v1.1+: O(1) message retrieval via offsets
    FTS_SEARCH = auto()  # v1.1+: Full-text search
    RFC_MESSAGE_ID = auto()  # v1.1+: RFC 2822 Message-ID tracking
    NULLABLE_GMAIL_ID = auto()  # v1.2+: gmail_id can be NULL
    SCHEDULING = auto()  # v1.3+: Scheduled task management


# Capabilities per version - SINGLE SOURCE OF TRUTH
_VERSION_CAPABILITIES: dict[SchemaVersion, set[SchemaCapability]] = {
    SchemaVersion.V1_0: {
        SchemaCapability.BASIC_ARCHIVING,
    },
    SchemaVersion.V1_1: {
        SchemaCapability.BASIC_ARCHIVING,
        SchemaCapability.MBOX_OFFSETS,
        SchemaCapability.FTS_SEARCH,
        SchemaCapability.RFC_MESSAGE_ID,
    },
    SchemaVersion.V1_2: {
        SchemaCapability.BASIC_ARCHIVING,
        SchemaCapability.MBOX_OFFSETS,
        SchemaCapability.FTS_SEARCH,
        SchemaCapability.RFC_MESSAGE_ID,
        SchemaCapability.NULLABLE_GMAIL_ID,
    },
    SchemaVersion.V1_3: {
        SchemaCapability.BASIC_ARCHIVING,
        SchemaCapability.MBOX_OFFSETS,
        SchemaCapability.FTS_SEARCH,
        SchemaCapability.RFC_MESSAGE_ID,
        SchemaCapability.NULLABLE_GMAIL_ID,
        SchemaCapability.SCHEDULING,
    },
}


class SchemaManager:
    """Centralized schema version management.

    This class is the SINGLE SOURCE OF TRUTH for:
    - Current schema version
    - Minimum supported version
    - Version detection and comparison
    - Capability checks
    - Migration coordination

    Usage:
        manager = SchemaManager(db_path)
        version = manager.detect_version()

        if manager.needs_migration():
            manager.auto_migrate_if_needed()

        if manager.has_capability(SchemaCapability.FTS_SEARCH):
            # Use full-text search

        manager.require_version(SchemaVersion.V1_1)  # Raises if not met
    """

    # SINGLE SOURCE OF TRUTH: Current schema version
    CURRENT_VERSION = SchemaVersion.V1_3

    # Minimum version for any operation
    MIN_SUPPORTED_VERSION = SchemaVersion.V1_0

    # Versions that can be automatically migrated to CURRENT_VERSION
    AUTO_MIGRATE_FROM = frozenset({SchemaVersion.V1_0, SchemaVersion.V1_1, SchemaVersion.V1_2})

    def __init__(self, db_path: Path | str):
        """Initialize schema manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self._cached_version: SchemaVersion | None = None
        self._conn: sqlite3.Connection | None = None

    async def detect_version(self) -> SchemaVersion:
        """Detect the current schema version of the database.

        Returns:
            SchemaVersion enum value

        This method caches the result. Call invalidate_cache() to re-detect.
        """
        if self._cached_version is not None:
            return self._cached_version

        if not self.db_path.exists():
            self._cached_version = SchemaVersion.NONE
            return self._cached_version

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                cursor = await conn.cursor()

                # Check for schema_version table (v1.1+)
                await cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                )
                if await cursor.fetchone():
                    await cursor.execute("SELECT version FROM schema_version LIMIT 1")
                    row = await cursor.fetchone()
                    if row:
                        self._cached_version = SchemaVersion.from_string(row[0])
                        return self._cached_version

                # Check for messages table (v1.1+) vs archived_messages (v1.0)
                await cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
                )
                if await cursor.fetchone():
                    # Has messages table but no schema_version - assume 1.1
                    self._cached_version = SchemaVersion.V1_1
                    return self._cached_version

                # Check for archived_messages table (v1.0)
                await cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
                )
                if await cursor.fetchone():
                    self._cached_version = SchemaVersion.V1_0
                    return self._cached_version

                # Empty database
                self._cached_version = SchemaVersion.NONE
                return self._cached_version

        except sqlite3.Error as e:
            logger.warning(f"Error detecting schema version: {e}")
            self._cached_version = SchemaVersion.UNKNOWN
            return self._cached_version

    def invalidate_cache(self) -> None:
        """Clear the cached version to force re-detection."""
        self._cached_version = None

    async def is_supported(self, version: SchemaVersion | None = None) -> bool:
        """Check if a version is supported.

        Args:
            version: Version to check (defaults to detected version)

        Returns:
            True if version is supported for operations
        """
        if version is None:
            version = await self.detect_version()

        return version.is_valid and version >= self.MIN_SUPPORTED_VERSION

    async def needs_migration(self) -> bool:
        """Check if database needs migration to current version.

        Returns:
            True if migration is needed and possible
        """
        version = await self.detect_version()
        return version.is_valid and version < self.CURRENT_VERSION

    async def can_auto_migrate(self) -> bool:
        """Check if automatic migration is possible.

        Returns:
            True if database can be automatically migrated
        """
        version = await self.detect_version()
        return version in self.AUTO_MIGRATE_FROM

    async def has_capability(self, capability: SchemaCapability) -> bool:
        """Check if the database has a specific capability.

        Args:
            capability: The capability to check for

        Returns:
            True if the capability is available

        Example:
            if manager.has_capability(SchemaCapability.FTS_SEARCH):
                results = search_engine.search(query)
        """
        version = await self.detect_version()
        if not version.is_valid:
            return False

        capabilities = _VERSION_CAPABILITIES.get(version, set())
        return capability in capabilities

    async def require_version(self, min_version: SchemaVersion) -> None:
        """Require a minimum schema version.

        Args:
            min_version: Minimum required version

        Raises:
            SchemaVersionError: If version requirement not met
        """
        version = await self.detect_version()

        if not version.is_valid:
            raise SchemaVersionError(
                f"Invalid database schema: {version.value}",
                current_version=version,
                required_version=min_version,
            )

        if version < min_version:
            raise SchemaVersionError(
                f"Schema version {min_version.value}+ required, got {version.value}",
                current_version=version,
                required_version=min_version,
            )

    async def require_capability(self, capability: SchemaCapability) -> None:
        """Require a specific capability.

        Args:
            capability: Required capability

        Raises:
            SchemaVersionError: If capability not available
        """
        if not await self.has_capability(capability):
            version = await self.detect_version()
            # Find minimum version with this capability
            min_version = None
            for v, caps in _VERSION_CAPABILITIES.items():
                if capability in caps:
                    if min_version is None or v < min_version:
                        min_version = v

            version_str = min_version.value if min_version else "unknown"
            raise SchemaVersionError(
                f"Capability {capability.name} requires schema {version_str}+",
                current_version=version,
                required_version=min_version,
            )

    async def auto_migrate_if_needed(
        self,
        confirm_callback: Callable[[str], bool] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """Automatically migrate database if needed and possible.

        Args:
            confirm_callback: Optional callback to confirm migration.
                              Called with message, returns True to proceed.
            progress_callback: Optional callback for progress updates.

        Returns:
            True if migration was performed, False if not needed/possible

        Raises:
            SchemaVersionError: If migration fails
        """
        version = await self.detect_version()

        if not await self.needs_migration():
            return False

        if not await self.can_auto_migrate():
            raise SchemaVersionError(
                f"Cannot auto-migrate from version {version.value}",
                current_version=version,
                required_version=self.CURRENT_VERSION,
            )

        # Confirm with user if callback provided
        if confirm_callback:
            msg = f"Database needs migration from {version.value} to {self.CURRENT_VERSION.value}"
            if not confirm_callback(msg):
                return False

        # Perform migration
        from .migration import MigrationManager

        migrator = MigrationManager(self.db_path)
        try:
            if version == SchemaVersion.V1_0:
                if progress_callback:
                    progress_callback("Migrating v1.0 to v1.1...")
                await migrator.migrate_v1_to_v1_1()

                # After v1.0 -> v1.1, check if we need to go to v1.2
                self.invalidate_cache()
                version = await self.detect_version()

            if version == SchemaVersion.V1_1:
                if progress_callback:
                    progress_callback("Upgrading v1.1 to v1.2...")
                # v1.1 to v1.2 is just a schema_version update
                # (nullable gmail_id is already supported structurally)
                await self._upgrade_v1_1_to_v1_2()

                # After v1.1 -> v1.2, check if we need to go to v1.3
                self.invalidate_cache()
                version = await self.detect_version()

            if version == SchemaVersion.V1_2:
                if progress_callback:
                    progress_callback("Upgrading v1.2 to v1.3...")
                # v1.2 to v1.3 adds the schedules table
                await self._upgrade_v1_2_to_v1_3()

            self.invalidate_cache()

            if progress_callback:
                progress_callback(f"Migration complete: now at v{self.CURRENT_VERSION.value}")

            return True

        except Exception as e:
            raise SchemaVersionError(
                f"Migration failed: {e}",
                current_version=version,
                required_version=self.CURRENT_VERSION,
            ) from e
        finally:
            await migrator._close()

    async def _upgrade_v1_1_to_v1_2(self) -> None:
        """Upgrade from v1.1 to v1.2 (schema version table update only)."""
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.cursor()
            # Delete all existing versions and insert new one
            await cursor.execute("DELETE FROM schema_version")
            await cursor.execute(
                """
                INSERT INTO schema_version (version, migrated_timestamp)
                VALUES ('1.2', datetime('now'))
            """
            )
            await conn.commit()
            logger.info("Upgraded schema version from 1.1 to 1.2")

    async def _upgrade_v1_2_to_v1_3(self) -> None:
        """Upgrade from v1.2 to v1.3 (adds schedules table)."""
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.cursor()

            # Create schedules table for task scheduling
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    day_of_week INTEGER,
                    day_of_month INTEGER,
                    time TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_run TEXT
                )
            """
            )

            # Update schema version
            await cursor.execute("DELETE FROM schema_version")
            await cursor.execute(
                """
                INSERT INTO schema_version (version, migrated_timestamp)
                VALUES ('1.3', datetime('now'))
            """
            )
            await conn.commit()
            logger.info("Upgraded schema version from 1.2 to 1.3 (added schedules table)")

    @classmethod
    def version_from_string(cls, version_str: str) -> SchemaVersion:
        """Convert version string to SchemaVersion enum.

        Args:
            version_str: Version string like "1.1" or "1.2"

        Returns:
            SchemaVersion enum value
        """
        return SchemaVersion.from_string(version_str)

    @classmethod
    def get_current_version_string(cls) -> str:
        """Get the current schema version as a string.

        Returns:
            Current version string (e.g., "1.3")
        """
        return cls.CURRENT_VERSION.value


class SchemaVersionError(Exception):
    """Error related to schema version mismatch or migration failure."""

    def __init__(
        self,
        message: str,
        current_version: SchemaVersion | None = None,
        required_version: SchemaVersion | None = None,
    ):
        super().__init__(message)
        self.current_version = current_version
        self.required_version = required_version

    @property
    def suggestion(self) -> str:
        """Get a user-friendly suggestion for resolving the error."""
        if self.current_version == SchemaVersion.NONE:
            return "Create a database with 'gmailarchiver archive' or 'gmailarchiver import'"

        if self.current_version and self.required_version:
            if self.current_version < self.required_version:
                return "Run 'gmailarchiver migrate' to upgrade the database"

        return "Check database integrity with 'gmailarchiver check'"
