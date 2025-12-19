"""Centralized database operations manager for Gmail Archiver.

This module provides the DBManager class which serves as the single source of truth
for all database operations, addressing critical architectural issues:
- SQL queries scattered across 8+ modules
- No transaction coordination
- Missing audit trails (archive_runs not recording operations)
- Inconsistent error handling

ALL database operations MUST go through this class.
No direct SQL queries allowed in other modules.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from sqlite3 import IntegrityError
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class DBManagerError(Exception):
    """Raised when database operations fail."""

    pass


class SchemaValidationError(DBManagerError):
    """Raised when schema validation fails."""

    pass


class DBManager:
    """
    Centralized database operations manager.

    Provides transactional, parameterized, audited database access with
    automatic rollback on errors. All write operations are recorded in
    archive_runs for complete audit trail.
    """

    def __init__(
        self, db_path: str | Path, validate_schema: bool = True, auto_create: bool = True
    ) -> None:
        """
        Initialize database manager with automatic schema validation.

        NOTE: This constructor does NOT create the database or establish a connection.
        Call `await initialize()` or use the async context manager to complete setup.

        Args:
            db_path: Path to SQLite database file
            validate_schema: Whether to validate schema version on init
            auto_create: Whether to auto-create v1.2 database if it doesn't exist

        Raises:
            FileNotFoundError: If database file doesn't exist and auto_create=False
        """
        self.db_path = Path(db_path).resolve()
        self.validate_schema = validate_schema
        self.auto_create = auto_create
        self.conn: aiosqlite.Connection | None = None
        self.schema_version: str | None = None

        # Validate path exists or auto_create is enabled (actual creation happens in initialize)
        if not self.db_path.exists() and not auto_create:
            raise FileNotFoundError(f"Database file not found: {self.db_path}")

    async def initialize(self) -> None:
        """Establish async database connection and validate schema.

        If auto_create=True and database doesn't exist, creates a new v1.2 database.

        Raises:
            DBManagerError: If database connection or creation fails
            SchemaValidationError: If validate_schema=True and schema is invalid
        """
        try:
            # Auto-create database if it doesn't exist
            if not self.db_path.exists() and self.auto_create:
                logger.info(f"Database not found at {self.db_path}, creating new v1.2 database")
                await self._create_new_database()

            self.conn = await aiosqlite.connect(str(self.db_path))
            self.conn.row_factory = aiosqlite.Row
            # Enable foreign key support
            await self._conn.execute("PRAGMA foreign_keys = ON")
            if self.validate_schema:
                self.schema_version = await self._validate_schema_version()
        except Exception as e:
            if self.conn is not None:
                await self.conn.close()
            raise DBManagerError(f"Failed to initialize database: {e}") from e

    @property
    def _conn(self) -> aiosqlite.Connection:
        """Get connection with proper type assertion for mypy."""
        assert self.conn is not None, (
            "Database not initialized. Call initialize() or use async context manager."
        )
        return self.conn

    async def _create_new_database(self) -> None:
        """
        Create a new v1.3 database with complete schema.

        This is called automatically from initialize() when database doesn't exist.
        Creates all tables, indexes, triggers, and schema_version.

        v1.3 Schema Change (from v1.2):
        - Added schedules table for task scheduling

        v1.2 Schema Change (from v1.1):
        - PRIMARY KEY changed from gmail_id to rfc_message_id
        - gmail_id is now nullable (for imported messages not in Gmail)
        - Rationale: rfc_message_id is the universal email identifier (RFC 2822),
          while gmail_id is Gmail-specific and may not exist for imported messages
        """
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create database connection using aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")

            try:
                # Create messages table (v1.2 schema)
                # PRIMARY KEY is rfc_message_id (universal email identifier)
                # gmail_id is nullable (NULL for imported messages not in Gmail)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        rfc_message_id TEXT PRIMARY KEY,
                        gmail_id TEXT,
                        thread_id TEXT,
                        subject TEXT,
                        from_addr TEXT,
                        to_addr TEXT,
                        cc_addr TEXT,
                        date TIMESTAMP,
                        archived_timestamp TIMESTAMP NOT NULL,
                        archive_file TEXT NOT NULL,
                        mbox_offset INTEGER NOT NULL,
                        mbox_length INTEGER NOT NULL,
                        body_preview TEXT,
                        checksum TEXT,
                        size_bytes INTEGER,
                        labels TEXT,
                        account_id TEXT DEFAULT 'default'
                    )
                """)

                # Create performance indexes
                # Note: rfc_message_id is PRIMARY KEY so already indexed
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_gmail_id ON messages(gmail_id)",
                    "CREATE INDEX IF NOT EXISTS idx_thread_id ON messages(thread_id)",
                    "CREATE INDEX IF NOT EXISTS idx_archive_file ON messages(archive_file)",
                    "CREATE INDEX IF NOT EXISTS idx_date ON messages(date)",
                    "CREATE INDEX IF NOT EXISTS idx_from ON messages(from_addr)",
                    "CREATE INDEX IF NOT EXISTS idx_subject ON messages(subject)",
                ]
                for index_sql in indexes:
                    await conn.execute(index_sql)

                # Create FTS5 virtual table for full-text search
                await conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        subject,
                        from_addr,
                        to_addr,
                        body_preview,
                        content=messages,
                        content_rowid=rowid,
                        tokenize='porter unicode61 remove_diacritics 1'
                    )
                """)

                # Create auto-sync triggers for FTS5
                await conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
                        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                        VALUES (new.rowid, new.subject, new.from_addr, new.to_addr,
                                new.body_preview);
                    END
                """)

                await conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
                        UPDATE messages_fts
                        SET subject = new.subject,
                            from_addr = new.from_addr,
                            to_addr = new.to_addr,
                            body_preview = new.body_preview
                        WHERE rowid = new.rowid;
                    END
                """)

                await conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
                        DELETE FROM messages_fts WHERE rowid = old.rowid;
                    END
                """)

                # Create accounts table (for future multi-account support)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        account_id TEXT PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        display_name TEXT,
                        provider TEXT DEFAULT 'gmail',
                        added_timestamp TEXT,
                        last_sync_timestamp TEXT
                    )
                """)

                # Insert default account
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO accounts (account_id, email, added_timestamp)
                    VALUES ('default', 'default', ?)
                """,
                    (datetime.now().isoformat(),),
                )

                # Create archive_runs table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS archive_runs (
                        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_timestamp TEXT NOT NULL,
                        query TEXT NOT NULL,
                        messages_archived INTEGER NOT NULL,
                        archive_file TEXT NOT NULL,
                        account_id TEXT DEFAULT 'default',
                        operation_type TEXT DEFAULT 'archive'
                    )
                """)

                # Create archive_sessions table (for resumable operations, v1.3.6+)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS archive_sessions (
                        session_id TEXT PRIMARY KEY,
                        target_file TEXT NOT NULL,
                        query TEXT NOT NULL,
                        message_ids TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        updated_at TEXT,
                        status TEXT DEFAULT 'in_progress',
                        compression TEXT,
                        total_count INTEGER NOT NULL,
                        processed_count INTEGER DEFAULT 0,
                        account_id TEXT DEFAULT 'default'
                    )
                """)

                # Create index for session lookups
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_target_file
                    ON archive_sessions(target_file)
                """)

                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_status
                    ON archive_sessions(status)
                """)

                # Create schedules table (v1.3+)
                await conn.execute("""
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
                """)

                # Create schema_version table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version TEXT PRIMARY KEY,
                        migrated_timestamp TEXT NOT NULL
                    )
                """)

                # Set schema version to 1.3
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO schema_version (version, migrated_timestamp)
                    VALUES ('1.3', ?)
                """,
                    (datetime.now().isoformat(),),
                )

                await conn.commit()
                logger.info("Successfully created new v1.3 database")

            except Exception as e:
                await conn.rollback()
                raise DBManagerError(f"Failed to create database schema: {e}") from e

    async def _validate_schema_version(self) -> str:
        """
        Validate that database has v1.1+ schema (supports both v1.1 and v1.2).

        Returns:
            Schema version string ('1.1' or '1.2')

        Raises:
            SchemaValidationError: If schema is not v1.1+
        """
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not await cursor.fetchone():
            raise SchemaValidationError(
                "Database schema validation failed: 'messages' table not found. "
                "Expected v1.1+ schema. Run migration first."
            )

        # Check for required columns (gmail_id is optional in v1.2)
        cursor = await self._conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        required_columns = {
            "rfc_message_id",
            "archive_file",
            "mbox_offset",
            "mbox_length",
            "archived_timestamp",
        }

        missing = required_columns - columns
        if missing:
            raise SchemaValidationError(
                f"Database schema validation failed: missing columns {missing}"
            )

        # Detect schema version by checking PRIMARY KEY
        # v1.1: gmail_id is PRIMARY KEY, v1.2: rfc_message_id is PRIMARY KEY
        cursor = await self._conn.execute("PRAGMA table_info(messages)")
        for row in await cursor.fetchall():
            col_name, col_pk = row[1], row[5]
            if col_pk == 1:  # Primary key column
                if col_name == "rfc_message_id":
                    return "1.2"
                elif col_name == "gmail_id":
                    return "1.1"

        # Fallback: assume 1.1 if we can't determine
        return "1.1"

    async def close(self) -> None:
        """Close database connection."""
        if self.conn is not None:
            await self.conn.close()

    async def commit(self) -> None:
        """Explicitly commit current transaction."""
        await self._conn.commit()

    async def rollback(self) -> None:
        """Explicitly rollback current transaction."""
        await self._conn.rollback()

    # ==================== MESSAGE OPERATIONS ====================

    async def record_archived_message(
        self,
        rfc_message_id: str,
        archive_file: str,
        mbox_offset: int,
        mbox_length: int,
        gmail_id: str | None = None,
        thread_id: str | None = None,
        subject: str | None = None,
        from_addr: str | None = None,
        to_addr: str | None = None,
        cc_addr: str | None = None,
        date: str | None = None,
        body_preview: str | None = None,
        checksum: str | None = None,
        size_bytes: int | None = None,
        labels: str | None = None,
        account_id: str = "default",
        record_run: bool = True,
    ) -> None:
        """
        Record a newly archived message with optional audit trail.

        This is a transactional operation - commits or rolls back.
        Optionally records in archive_runs for complete audit trail.

        Args:
            rfc_message_id: RFC 2822 Message-ID header (primary key in v1.2)
            archive_file: Path to archive file
            mbox_offset: Byte offset in mbox file
            mbox_length: Message length in bytes
            gmail_id: Gmail message ID (optional - NULL for imported messages not in Gmail)
            thread_id: Gmail thread ID
            subject: Email subject
            from_addr: From address
            to_addr: To address
            cc_addr: CC address
            date: Message date (ISO 8601 timestamp)
            body_preview: First 1000 chars of body
            checksum: SHA256 checksum
            size_bytes: Total message size
            labels: JSON array of Gmail labels
            account_id: Account identifier (default: 'default')
            record_run: If True, record in archive_runs (default: True for single operations,
                       set False for bulk operations that will record a single run at the end)

        Raises:
            DBManagerError: If operation fails
        """
        try:
            await self._conn.execute(
                """
                INSERT INTO messages (
                    rfc_message_id, gmail_id, thread_id, subject, from_addr,
                    to_addr, cc_addr, date, archived_timestamp, archive_file,
                    mbox_offset, mbox_length, body_preview, checksum,
                    size_bytes, labels, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rfc_message_id,
                    gmail_id,
                    thread_id,
                    subject,
                    from_addr,
                    to_addr,
                    cc_addr,
                    date,
                    datetime.now().isoformat(),
                    archive_file,
                    mbox_offset,
                    mbox_length,
                    body_preview,
                    checksum,
                    size_bytes,
                    labels,
                    account_id,
                ),
            )

            # Record in audit trail (unless caller will do it in bulk)
            if record_run:
                await self._record_archive_run(
                    operation="archive",
                    messages_count=1,
                    archive_file=archive_file,
                    account_id=account_id,
                )
        except IntegrityError:
            # Re-raise IntegrityError for tests to catch
            raise
        except Exception as e:
            raise DBManagerError(f"Failed to record message {gmail_id}: {e}") from e

    async def get_message_by_gmail_id(self, gmail_id: str) -> dict[str, Any] | None:
        """
        Retrieve message metadata by Gmail ID.

        Args:
            gmail_id: Gmail message ID

        Returns:
            Dictionary with message metadata, or None if not found
        """
        cursor = await self._conn.execute(
            """
            SELECT gmail_id, rfc_message_id, thread_id, subject, from_addr,
                   to_addr, cc_addr, date, archived_timestamp, archive_file,
                   mbox_offset, mbox_length, body_preview, checksum,
                   size_bytes, labels, account_id
            FROM messages WHERE gmail_id = ?
            """,
            (gmail_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_message_by_rfc_message_id(self, rfc_message_id: str) -> dict[str, Any] | None:
        """
        Retrieve message metadata by RFC 2822 Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header value

        Returns:
            Dictionary with message metadata, or None if not found
        """
        cursor = await self._conn.execute(
            """
            SELECT gmail_id, rfc_message_id, thread_id, subject, from_addr,
                   to_addr, cc_addr, date, archived_timestamp, archive_file,
                   mbox_offset, mbox_length, body_preview, checksum,
                   size_bytes, labels, account_id
            FROM messages WHERE rfc_message_id = ?
            """,
            (rfc_message_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_rfc_message_ids(self) -> set[str]:
        """
        Get all RFC Message-IDs as a set for efficient duplicate detection.

        This enables O(1) duplicate lookup instead of per-message database queries.
        Useful when archiving large batches of messages.

        Returns:
            Set of all rfc_message_id values in the database
        """
        cursor = await self._conn.execute("SELECT rfc_message_id FROM messages")
        return {row[0] for row in await cursor.fetchall() if row[0]}

    async def get_message_location(self, rfc_message_id: str) -> tuple[str, int, int] | None:
        """
        Get mbox file location for O(1) message access.

        Args:
            rfc_message_id: RFC 2822 Message-ID (primary key in v1.2)

        Returns:
            Tuple of (archive_file, mbox_offset, mbox_length) or None if not found
        """
        cursor = await self._conn.execute(
            """
            SELECT archive_file, mbox_offset, mbox_length
            FROM messages WHERE rfc_message_id = ?
            """,
            (rfc_message_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2]) if row else None

    async def get_message_location_by_gmail_id(self, gmail_id: str) -> tuple[str, int, int] | None:
        """
        Get mbox file location by Gmail ID (for backward compatibility).

        Args:
            gmail_id: Gmail message ID

        Returns:
            Tuple of (archive_file, mbox_offset, mbox_length) or None if not found
        """
        cursor = await self._conn.execute(
            """
            SELECT archive_file, mbox_offset, mbox_length
            FROM messages WHERE gmail_id = ?
            """,
            (gmail_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2]) if row else None

    async def get_all_messages_for_archive(self, archive_file: str) -> list[dict[str, Any]]:
        """
        Get all messages in a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            List of message dictionaries
        """
        cursor = await self._conn.execute(
            """
            SELECT gmail_id, rfc_message_id, thread_id, subject, from_addr,
                   to_addr, cc_addr, date, archived_timestamp, archive_file,
                   mbox_offset, mbox_length, body_preview, checksum,
                   size_bytes, labels, account_id
            FROM messages
            WHERE archive_file = ?
            ORDER BY mbox_offset
            """,
            (archive_file,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_message_ids_for_archive(self, archive_file: str) -> list[str]:
        """
        Get all gmail IDs for messages in a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            List of gmail IDs
        """
        cursor = await self._conn.execute(
            """
            SELECT gmail_id
            FROM messages
            WHERE archive_file = ?
            ORDER BY mbox_offset
            """,
            (archive_file,),
        )
        return [row[0] for row in await cursor.fetchall()]

    # ==================== DEDUPLICATION ====================

    async def find_duplicates(self) -> list[tuple[str, list[str]]]:
        """
        Find all duplicate Message-IDs (rfc_message_id) across archives.

        Returns:
            List of tuples: [(rfc_message_id, [gmail_id1, gmail_id2, ...]), ...]
        """
        cursor = await self._conn.execute(
            """
            SELECT rfc_message_id, GROUP_CONCAT(gmail_id) as gmail_ids
            FROM messages
            GROUP BY rfc_message_id
            HAVING COUNT(*) > 1
            """
        )
        return [(row[0], row[1].split(",")) for row in await cursor.fetchall()]

    async def delete_message(self, gmail_id: str) -> None:
        """
        Delete a message record from database.

        CRITICAL: Only removes from database, doesn't modify mbox files.

        Args:
            gmail_id: Gmail message ID to delete

        Raises:
            DBManagerError: If operation fails
        """
        try:
            await self._conn.execute(
                "DELETE FROM messages WHERE gmail_id = ?",
                (gmail_id,),
            )
        except Exception as e:
            raise DBManagerError(f"Failed to delete message {gmail_id}: {e}") from e

    async def remove_duplicate_records(
        self, duplicates: list[tuple[str, list[str]]], reason: str = "deduplication"
    ) -> int:
        """
        Remove duplicate message records from database.

        CRITICAL: Only removes from database, doesn't modify mbox files.
        For each duplicate set, keeps the first message and removes the rest.

        Args:
            duplicates: List of (rfc_message_id, [gmail_id1, gmail_id2, ...]) tuples
            reason: Reason for removal (for audit trail)

        Returns:
            Number of records removed

        Raises:
            DBManagerError: If operation fails
        """
        if not duplicates:
            return 0

        try:
            total_removed = 0
            # For each duplicate set, keep first and remove rest
            for rfc_message_id, gmail_ids in duplicates:
                # Keep the first one, remove the rest
                to_remove = gmail_ids[1:]
                if to_remove:
                    placeholders = ",".join("?" * len(to_remove))
                    cursor = await self._conn.execute(
                        f"DELETE FROM messages WHERE gmail_id IN ({placeholders})",
                        to_remove,
                    )
                    total_removed += cursor.rowcount

            # Audit trail
            await self._record_archive_run(
                operation="deduplicate",
                messages_count=total_removed,
                notes=reason,
            )
            return total_removed
        except Exception as e:
            raise DBManagerError(f"Failed to remove duplicate records: {e}") from e

    # ==================== CONSOLIDATION ====================

    async def update_archive_location(
        self,
        gmail_id: str,
        new_archive_file: str,
        new_mbox_offset: int,
        new_mbox_length: int,
    ) -> None:
        """
        Update message location after consolidation.

        CRITICAL: Updates mbox_offset after messages are moved.

        Args:
            gmail_id: Gmail message ID
            new_archive_file: New archive file path
            new_mbox_offset: New byte offset
            new_mbox_length: New message length

        Raises:
            DBManagerError: If operation fails
        """
        try:
            await self._conn.execute(
                """
                UPDATE messages
                SET archive_file = ?,
                    mbox_offset = ?,
                    mbox_length = ?
                WHERE gmail_id = ?
                """,
                (new_archive_file, new_mbox_offset, new_mbox_length, gmail_id),
            )
        except Exception as e:
            raise DBManagerError(f"Failed to update location for {gmail_id}: {e}") from e

    async def bulk_update_archive_locations(self, updates: list[dict[str, Any]]) -> None:
        """
        Batch update for consolidation operations.

        Args:
            updates: List of dicts with keys: gmail_id, archive_file, mbox_offset, mbox_length

        Raises:
            DBManagerError: If operation fails
        """
        if not updates:
            return

        try:
            # Convert dicts to tuple format for executemany
            # SQL expects: (archive_file, offset, length, gmail_id)
            tuples = [
                (u["archive_file"], u["mbox_offset"], u["mbox_length"], u["gmail_id"])
                for u in updates
            ]

            await self._conn.executemany(
                """
                UPDATE messages
                SET archive_file = ?, mbox_offset = ?, mbox_length = ?
                WHERE gmail_id = ?
                """,
                tuples,
            )

            # Audit trail
            await self._record_archive_run(
                operation="consolidate",
                messages_count=len(updates),
                archive_file=updates[0]["archive_file"] if updates else None,
            )
        except Exception as e:
            raise DBManagerError(f"Failed to bulk update locations: {e}") from e

    # ==================== VALIDATION & INTEGRITY ====================

    async def verify_database_integrity(self, skip_missing_archives: bool = False) -> list[str]:
        """Comprehensive database integrity check.

        Args:
            skip_missing_archives: If True, do not report missing archive files as issues.

        Returns:
            List of issues found (empty list if all checks pass)
        """
        issues: list[str] = []

        try:
            # Detect whether FTS table exists before running FTS-specific checks
            cursor = await self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
            )
            has_fts = await cursor.fetchone() is not None

            if has_fts:
                # Check 1: Orphaned FTS records
                cursor = await self._conn.execute(
                    """
                    SELECT COUNT(*) FROM messages_fts
                    WHERE rowid NOT IN (SELECT rowid FROM messages)
                    """
                )
                orphaned_fts = (await cursor.fetchone())[0]  # type: ignore[index]
                if orphaned_fts > 0:
                    issues.append(f"{orphaned_fts} orphaned FTS records")

                # Check 2: Missing FTS records
                cursor = await self._conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                    """
                )
                missing_fts = (await cursor.fetchone())[0]  # type: ignore[index]
                if missing_fts > 0:
                    issues.append(f"{missing_fts} messages missing from FTS index")

            # Check 3: Invalid offsets
            cursor = await self._conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE mbox_offset < 0 OR mbox_length <= 0
                """
            )
            invalid_offsets = (await cursor.fetchone())[0]  # type: ignore[index]
            if invalid_offsets > 0:
                issues.append(f"{invalid_offsets} messages with invalid offsets")

            # Check 4: Duplicate Message-IDs (rfc_message_id should be unique)
            cursor = await self._conn.execute(
                """
                SELECT rfc_message_id, COUNT(*) as cnt
                FROM messages
                GROUP BY rfc_message_id
                HAVING cnt > 1
                """
            )
            duplicates = list(await cursor.fetchall())
            if duplicates:
                issues.append(f"{len(duplicates)} duplicate Message-IDs found")

            # Check 5: Missing archive files (only check distinct file paths)
            # Only run this check for v1.1-style databases with FTS enabled.
            if has_fts and not skip_missing_archives:
                cursor = await self._conn.execute("SELECT DISTINCT archive_file FROM messages")
                for row in await cursor.fetchall():
                    archive_file = Path(row[0])
                    if not archive_file.exists():
                        issues.append(f"Missing archive file: {archive_file}")

        except Exception as e:  # pragma: no cover - defensive guard
            logger.error(f"Error during integrity check: {e}")
            issues.append(f"Integrity check error: {e}")

        return issues

    async def repair_database(self, dry_run: bool = True) -> dict[str, int]:
        """
        Attempt to repair common database issues.

        Args:
            dry_run: If True, report repairs without executing them

        Returns:
            Dictionary of repair counts: {
                'orphaned_fts_removed': count,
                'missing_fts_added': count,
            }

        Raises:
            DBManagerError: If repair fails
        """
        repairs: dict[str, int] = {
            "orphaned_fts_removed": 0,
            "missing_fts_added": 0,
        }

        if dry_run:
            # Just count what would be repaired
            cursor = await self._conn.execute(
                """
                SELECT COUNT(*) FROM messages_fts
                WHERE rowid NOT IN (SELECT rowid FROM messages)
                """
            )
            repairs["orphaned_fts_removed"] = (await cursor.fetchone())[0]  # type: ignore[index]

            cursor = await self._conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                """
            )
            repairs["missing_fts_added"] = (await cursor.fetchone())[0]  # type: ignore[index]
        else:
            async with self._transaction():
                try:
                    # Detect FTS mode (content-based vs external content)
                    cursor = await self._conn.execute(
                        "SELECT sql FROM sqlite_master WHERE name='messages_fts'"
                    )
                    fts_sql = (await cursor.fetchone())[0]  # type: ignore[index]
                    is_external_content = 'content=""' in fts_sql or "content=''" in fts_sql

                    if is_external_content:
                        # For external content FTS, rebuild the entire FTS table
                        # Count what will be repaired first
                        cursor = await self._conn.execute(
                            """
                            SELECT COUNT(*) FROM messages_fts
                            WHERE rowid NOT IN (SELECT rowid FROM messages)
                            """
                        )
                        repairs["orphaned_fts_removed"] = (await cursor.fetchone())[0]  # type: ignore[index]

                        cursor = await self._conn.execute(
                            """
                            SELECT COUNT(*) FROM messages
                            WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                            """
                        )
                        repairs["missing_fts_added"] = (await cursor.fetchone())[0]  # type: ignore[index]

                        # Drop and recreate FTS with correct data
                        await self._conn.execute("DROP TABLE messages_fts")
                        await self._conn.execute(
                            """
                            CREATE VIRTUAL TABLE messages_fts USING fts5(
                                subject,
                                from_addr,
                                to_addr,
                                body_preview,
                                content=''
                            )
                            """
                        )
                        # Rebuild FTS from messages table
                        await self._conn.execute(
                            """
                            INSERT INTO messages_fts(
                                rowid, subject, from_addr, to_addr, body_preview
                            )
                            SELECT rowid, subject, from_addr, to_addr, body_preview
                            FROM messages
                            """
                        )
                    else:
                        # Content-based FTS: use DELETE and INSERT
                        # Repair 1: Remove orphaned FTS records
                        cursor = await self._conn.execute(
                            """
                            DELETE FROM messages_fts
                            WHERE rowid NOT IN (SELECT rowid FROM messages)
                            """
                        )
                        repairs["orphaned_fts_removed"] = cursor.rowcount

                        # Repair 2: Rebuild missing FTS records
                        cursor = await self._conn.execute(
                            """
                            INSERT INTO messages_fts(
                                rowid, subject, from_addr, to_addr, body_preview
                            )
                            SELECT rowid, subject, from_addr, to_addr, body_preview
                            FROM messages
                            WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                            """
                        )
                        repairs["missing_fts_added"] = cursor.rowcount

                    # Audit trail
                    await self._record_archive_run(
                        operation="repair",
                        messages_count=repairs["orphaned_fts_removed"]
                        + repairs["missing_fts_added"],
                        notes="Database repair: FTS sync",
                    )
                except Exception as e:
                    raise DBManagerError(f"Database repair failed: {e}") from e

        return repairs

    async def get_messages_with_invalid_offsets(self) -> list[dict[str, Any]]:
        """
        Find messages with invalid mbox offsets or lengths.

        Returns:
            List of message dictionaries with offset < 0 or length <= 0
        """
        cursor = await self._conn.execute(
            """
            SELECT gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length
            FROM messages
            WHERE mbox_offset < 0 OR mbox_length <= 0
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ==================== TRANSACTION SUPPORT ====================

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        """
        Transaction context manager with automatic commit/rollback.

        Usage:
            with db._transaction():
                db.conn.execute(...)
                db.conn.execute(...)
            # Commits here if no exception, rolls back otherwise

        Yields:
            None

        Raises:
            Exception: Re-raises any exception after rollback
        """
        try:
            yield
            await self._conn.commit()
        except Exception as e:
            await self._conn.rollback()
            logger.error(f"Transaction rolled back: {e}")
            raise

    async def record_archive_run(
        self,
        operation: str,
        messages_count: int,
        archive_file: str | None = None,
        notes: str | None = None,
        account_id: str = "default",
    ) -> None:
        """
        Record an operation in archive_runs for audit trail.

        Use this for bulk operations (import, consolidate, etc.) to record
        a single run entry instead of one per message.

        Args:
            operation: Operation type (archive, import, deduplicate, consolidate, repair)
            messages_count: Number of messages affected
            archive_file: Archive file path (if applicable)
            notes: Additional notes (stored in 'query' field for compatibility)
            account_id: Account identifier (default: 'default')
        """
        await self._record_archive_run(operation, messages_count, archive_file, notes, account_id)

    async def _record_archive_run(
        self,
        operation: str,
        messages_count: int,
        archive_file: str | None = None,
        notes: str | None = None,
        account_id: str = "default",
    ) -> None:
        """
        Internal: Record operation in archive_runs for audit trail.

        CRITICAL: This fixes the missing audit trail bug discovered in v1.1.0-beta.1.

        Args:
            operation: Operation type (archive, deduplicate, consolidate, repair)
            messages_count: Number of messages affected
            archive_file: Archive file path (if applicable)
            notes: Additional notes (stored in 'query' field for compatibility)
            account_id: Account identifier
        """
        # Repurpose 'query' field for operation notes
        query_value = notes if notes else operation

        await self._conn.execute(
            """
            INSERT INTO archive_runs (
                run_timestamp, query, messages_archived,
                archive_file, account_id, operation_type
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                query_value,
                messages_count,
                archive_file or "",
                account_id,
                operation,
            ),
        )

    # ==================== SESSION OPERATIONS (v1.3.6+) ====================

    async def ensure_sessions_table(self) -> None:
        """Ensure archive_sessions table exists (for existing databases).

        Call this before using session operations on databases created before v1.3.6.
        """
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_sessions (
                session_id TEXT PRIMARY KEY,
                target_file TEXT NOT NULL,
                query TEXT NOT NULL,
                message_ids TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT,
                status TEXT DEFAULT 'in_progress',
                compression TEXT,
                total_count INTEGER NOT NULL,
                processed_count INTEGER DEFAULT 0,
                account_id TEXT DEFAULT 'default'
            )
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_target_file
            ON archive_sessions(target_file)
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_status
            ON archive_sessions(status)
        """)
        await self._conn.commit()

    async def create_session(
        self,
        session_id: str,
        target_file: str,
        query: str,
        message_ids: list[str],
        compression: str | None = None,
        account_id: str = "default",
    ) -> None:
        """Create a new archive session for resumable operations.

        Args:
            session_id: Unique session identifier (UUID)
            target_file: Target archive file path (without .partial suffix)
            query: Gmail query used for this archive
            message_ids: List of Gmail message IDs to archive
            compression: Compression format (gzip, lzma, zstd, or None)
            account_id: Account ID for multi-account support
        """
        import json

        await self.ensure_sessions_table()
        await self._conn.execute(
            """
            INSERT INTO archive_sessions
            (session_id, target_file, query, message_ids, started_at, status,
             compression, total_count, processed_count, account_id)
            VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, 0, ?)
            """,
            (
                session_id,
                target_file,
                query,
                json.dumps(message_ids),
                datetime.now().isoformat(),
                compression,
                len(message_ids),
                account_id,
            ),
        )
        await self._conn.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session dict or None if not found
        """
        import json

        await self.ensure_sessions_table()
        cursor = await self._conn.execute(
            "SELECT * FROM archive_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result["message_ids"] = json.loads(result["message_ids"])
            return result
        return None

    async def get_session_by_file(self, target_file: str) -> dict[str, Any] | None:
        """Get in-progress session for a target file.

        Args:
            target_file: Target archive file path

        Returns:
            Session dict or None if not found
        """
        import json

        await self.ensure_sessions_table()
        cursor = await self._conn.execute(
            """
            SELECT * FROM archive_sessions
            WHERE target_file = ? AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
            """,
            (target_file,),
        )
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result["message_ids"] = json.loads(result["message_ids"])
            return result
        return None

    async def get_session_by_query(
        self, query: str, compression: str | None = None
    ) -> dict[str, Any] | None:
        """Get in-progress session for a Gmail query.

        Used to find existing partial archives that can be resumed.

        Args:
            query: Gmail query string (e.g., "before:2024/01/01")
            compression: Compression format to match (or None for uncompressed)

        Returns:
            Session dict or None if not found
        """
        import json

        await self.ensure_sessions_table()

        # Match query and compression (NULL-safe comparison for compression)
        if compression is None:
            cursor = await self._conn.execute(
                """
                SELECT * FROM archive_sessions
                WHERE query = ? AND compression IS NULL AND status = 'in_progress'
                ORDER BY started_at DESC LIMIT 1
                """,
                (query,),
            )
        else:
            cursor = await self._conn.execute(
                """
                SELECT * FROM archive_sessions
                WHERE query = ? AND compression = ? AND status = 'in_progress'
                ORDER BY started_at DESC LIMIT 1
                """,
                (query, compression),
            )

        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result["message_ids"] = json.loads(result["message_ids"])
            return result
        return None

    async def get_all_partial_sessions(self) -> list[dict[str, Any]]:
        """Get all in-progress sessions.

        Returns:
            List of session dicts
        """
        import json

        await self.ensure_sessions_table()
        cursor = await self._conn.execute(
            """
            SELECT * FROM archive_sessions
            WHERE status = 'in_progress'
            ORDER BY started_at DESC
            """
        )
        results = []
        for row in await cursor.fetchall():
            result = dict(row)
            result["message_ids"] = json.loads(result["message_ids"])
            results.append(result)
        return results

    async def update_session_progress(self, session_id: str, processed_count: int) -> None:
        """Update session progress.

        Args:
            session_id: Session identifier
            processed_count: Number of messages processed so far
        """
        await self._conn.execute(
            """
            UPDATE archive_sessions
            SET processed_count = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (processed_count, datetime.now().isoformat(), session_id),
        )
        await self._conn.commit()

    async def complete_session(self, session_id: str) -> None:
        """Mark session as completed.

        Args:
            session_id: Session identifier
        """
        await self._conn.execute(
            """
            UPDATE archive_sessions
            SET status = 'completed', updated_at = ?
            WHERE session_id = ?
            """,
            (datetime.now().isoformat(), session_id),
        )
        await self._conn.commit()

    async def abort_session(self, session_id: str) -> None:
        """Mark session as aborted.

        Args:
            session_id: Session identifier
        """
        await self._conn.execute(
            """
            UPDATE archive_sessions
            SET status = 'aborted', updated_at = ?
            WHERE session_id = ?
            """,
            (datetime.now().isoformat(), session_id),
        )
        await self._conn.commit()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session record.

        Args:
            session_id: Session identifier
        """
        await self._conn.execute(
            "DELETE FROM archive_sessions WHERE session_id = ?",
            (session_id,),
        )
        await self._conn.commit()

    async def delete_messages_for_file(self, archive_file: str) -> int:
        """Delete all messages associated with an archive file.

        Used for cleanup of partial archives.

        Args:
            archive_file: Archive file path

        Returns:
            Number of messages deleted
        """
        cursor = await self._conn.execute(
            "DELETE FROM messages WHERE archive_file = ?",
            (archive_file,),
        )
        await self._conn.commit()
        return cursor.rowcount

    # ==================== QUERY METHODS ====================

    async def search_messages(
        self,
        fulltext: str | None = None,
        from_addr: str | None = None,
        to_addr: str | None = None,
        subject: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Search messages using FTS5 fulltext search and metadata filters.

        Args:
            fulltext: Full-text search query (searches subject, from, to, body_preview)
            from_addr: Filter by from address (exact match)
            to_addr: Filter by to address (exact match)
            subject: Filter by subject (partial match using LIKE)
            date_start: Filter by date >= this value (ISO 8601 format)
            date_end: Filter by date <= this value (ISO 8601 format)
            limit: Maximum number of results to return (default: 100)

        Returns:
            List of message dictionaries matching the search criteria
        """
        # Build query based on whether we have fulltext search
        if fulltext:
            # Use FTS5 for fulltext search
            query = """
                SELECT m.gmail_id, m.rfc_message_id, m.thread_id, m.subject,
                       m.from_addr, m.to_addr, m.cc_addr, m.date,
                       m.archived_timestamp, m.archive_file, m.mbox_offset,
                       m.mbox_length, m.body_preview, m.checksum,
                       m.size_bytes, m.labels, m.account_id
                FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?
            """
            params: list[Any] = [fulltext]
        else:
            # Standard query without FTS
            query = """
                SELECT gmail_id, rfc_message_id, thread_id, subject,
                       from_addr, to_addr, cc_addr, date,
                       archived_timestamp, archive_file, mbox_offset,
                       mbox_length, body_preview, checksum,
                       size_bytes, labels, account_id
                FROM messages
                WHERE 1=1
            """
            params = []

        # Add metadata filters (use m. prefix when FTS is active)
        table_prefix = "m." if fulltext else ""

        if from_addr:
            # Use LIKE for partial matching if wildcards present, else exact match
            if "%" in from_addr:
                query += f" AND {table_prefix}from_addr LIKE ?"
            else:
                query += f" AND {table_prefix}from_addr = ?"
            params.append(from_addr)

        if to_addr:
            # Use LIKE for partial matching if wildcards present, else exact match
            if "%" in to_addr:
                query += f" AND {table_prefix}to_addr LIKE ?"
            else:
                query += f" AND {table_prefix}to_addr = ?"
            params.append(to_addr)

        if subject:
            query += f" AND {table_prefix}subject LIKE ?"
            params.append(f"%{subject}%")

        if date_start:
            query += f" AND {table_prefix}date >= ?"
            params.append(date_start)

        if date_end:
            query += f" AND {table_prefix}date <= ?"
            params.append(date_end)

        # Add limit
        query += " LIMIT ?"
        params.append(limit)

        cursor = await self._conn.execute(query, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def get_gmail_ids_for_archive(self, archive_file: str) -> set[str]:
        """
        Get all Gmail message IDs for a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            Set of gmail_id values for the archive file
        """
        cursor = await self._conn.execute(
            "SELECT gmail_id FROM messages WHERE archive_file = ?",
            (archive_file,),
        )
        return {row[0] for row in await cursor.fetchall() if row[0]}

    async def get_message_count(self) -> int:
        """
        Get total number of archived messages.

        Returns:
            Total count of messages in the database
        """
        cursor = await self._conn.execute("SELECT COUNT(*) FROM messages")
        result = await cursor.fetchone()
        return int(result[0]) if result else 0

    async def get_archive_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent archive run history.

        Args:
            limit: Maximum number of runs to return (default: 10)

        Returns:
            List of archive run dictionaries, ordered by timestamp descending
            (most recent first). Each dict contains: run_id, run_timestamp,
            query, messages_archived, archive_file
        """
        cursor = await self._conn.execute(
            """
            SELECT run_id, run_timestamp, query, messages_archived,
                   archive_file, account_id, operation_type
            FROM archive_runs
            ORDER BY run_timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def is_archived(self, gmail_id: str) -> bool:
        """
        Check if a message is already archived.

        Args:
            gmail_id: Gmail message ID to check

        Returns:
            True if message exists in database, False otherwise
        """
        cursor = await self._conn.execute(
            "SELECT 1 FROM messages WHERE gmail_id = ? LIMIT 1",
            (gmail_id,),
        )
        return await cursor.fetchone() is not None

    # ==================== SCHEDULE OPERATIONS ====================

    async def add_schedule(
        self,
        command: str,
        frequency: str,
        time: str,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
        created_at: str | None = None,
    ) -> int:
        """
        Add a new schedule to the database.

        Args:
            command: Command to execute (e.g., "check", "archive 3y")
            frequency: "daily", "weekly", or "monthly"
            time: Time in HH:MM format
            day_of_week: For weekly schedules (0=Sunday, 6=Saturday)
            day_of_month: For monthly schedules (1-31)
            created_at: ISO 8601 timestamp (defaults to now)

        Returns:
            Schedule ID of newly created schedule
        """
        if created_at is None:
            created_at = datetime.now().isoformat()

        cursor = await self._conn.execute(
            """
            INSERT INTO schedules
            (command, frequency, day_of_week, day_of_month, time, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (command, frequency, day_of_week, day_of_month, time, created_at),
        )
        await self._conn.commit()

        assert cursor.lastrowid is not None, "Failed to get lastrowid from database"
        return cursor.lastrowid

    async def list_schedules(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """
        List all schedules.

        Args:
            enabled_only: If True, only return enabled schedules

        Returns:
            List of schedule dictionaries
        """
        if enabled_only:
            cursor = await self._conn.execute(
                """
                SELECT id, command, frequency, day_of_week, day_of_month,
                       time, enabled, created_at, last_run
                FROM schedules
                WHERE enabled = 1
                ORDER BY id
                """
            )
        else:
            cursor = await self._conn.execute(
                """
                SELECT id, command, frequency, day_of_week, day_of_month,
                       time, enabled, created_at, last_run
                FROM schedules
                ORDER BY id
                """
            )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_schedule(self, schedule_id: int) -> dict[str, Any] | None:
        """
        Get a specific schedule by ID.

        Args:
            schedule_id: Schedule ID to retrieve

        Returns:
            Schedule dictionary if found, None otherwise
        """
        cursor = await self._conn.execute(
            """
            SELECT id, command, frequency, day_of_week, day_of_month,
                   time, enabled, created_at, last_run
            FROM schedules
            WHERE id = ?
            """,
            (schedule_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def remove_schedule(self, schedule_id: int) -> bool:
        """
        Remove a schedule.

        Args:
            schedule_id: Schedule ID to remove

        Returns:
            True if schedule was removed, False if not found
        """
        cursor = await self._conn.execute(
            "DELETE FROM schedules WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def enable_schedule(self, schedule_id: int) -> bool:
        """
        Enable a schedule.

        Args:
            schedule_id: Schedule ID to enable

        Returns:
            True if schedule was enabled, False if not found
        """
        cursor = await self._conn.execute(
            "UPDATE schedules SET enabled = 1 WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def disable_schedule(self, schedule_id: int) -> bool:
        """
        Disable a schedule.

        Args:
            schedule_id: Schedule ID to disable

        Returns:
            True if schedule was disabled, False if not found
        """
        cursor = await self._conn.execute(
            "UPDATE schedules SET enabled = 0 WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def update_schedule_last_run(self, schedule_id: int) -> None:
        """
        Update the last_run timestamp for a schedule.

        Args:
            schedule_id: Schedule ID to update
        """
        last_run = datetime.now().isoformat()
        await self._conn.execute(
            "UPDATE schedules SET last_run = ? WHERE id = ?",
            (last_run, schedule_id),
        )
        await self._conn.commit()

    # ==================== CONTEXT MANAGER ====================

    async def __aenter__(self) -> DBManager:
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - commits on success, rolls back on error, then closes."""
        try:
            if exc_type is None:
                await self._conn.commit()
            else:
                await self._conn.rollback()
        finally:
            await self.close()

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection."""
        # Note: Cannot use await in __del__, so cleanup must use async context manager
        pass
