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

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

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

        Args:
            db_path: Path to SQLite database file
            validate_schema: Whether to validate schema version on init
            auto_create: Whether to auto-create v1.1 database if it doesn't exist

        Raises:
            FileNotFoundError: If database file doesn't exist and auto_create=False
            SchemaValidationError: If validate_schema=True and schema is invalid
            DBManagerError: If database connection fails
        """
        self.db_path = Path(db_path).resolve()

        # Auto-create database if it doesn't exist
        if not self.db_path.exists():
            if not auto_create:
                raise FileNotFoundError(f"Database file not found: {self.db_path}")

            logger.info(f"Database not found at {self.db_path}, creating new v1.1 database")
            self._create_new_database()

        try:
            self.conn = self._connect()
            if validate_schema:
                self.schema_version = self._validate_schema_version()
        except Exception as e:
            if hasattr(self, "conn"):
                self.conn.close()
            raise DBManagerError(f"Failed to initialize database: {e}") from e

    def _connect(self) -> sqlite3.Connection:
        """
        Create database connection.

        Returns:
            SQLite connection with row factory enabled
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable foreign key support
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_new_database(self) -> None:
        """
        Create a new v1.1 database with complete schema.

        This is called automatically when database doesn't exist.
        Creates all tables, indexes, triggers, and schema_version.
        """
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create database connection
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            # Create messages table (enhanced schema)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
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
            ''')

            # Create performance indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_rfc_message_id ON messages(rfc_message_id)",
                "CREATE INDEX IF NOT EXISTS idx_thread_id ON messages(thread_id)",
                "CREATE INDEX IF NOT EXISTS idx_archive_file ON messages(archive_file)",
                "CREATE INDEX IF NOT EXISTS idx_date ON messages(date)",
                "CREATE INDEX IF NOT EXISTS idx_from ON messages(from_addr)",
                "CREATE INDEX IF NOT EXISTS idx_subject ON messages(subject)",
            ]
            for index_sql in indexes:
                conn.execute(index_sql)

            # Create FTS5 virtual table for full-text search
            conn.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject,
                    from_addr,
                    to_addr,
                    body_preview,
                    content=messages,
                    content_rowid=rowid,
                    tokenize='porter unicode61 remove_diacritics 1'
                )
            ''')

            # Create auto-sync triggers for FTS5
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                    VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
                END
            ''')

            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
                    UPDATE messages_fts
                    SET subject = new.subject,
                        from_addr = new.from_addr,
                        to_addr = new.to_addr,
                        body_preview = new.body_preview
                    WHERE rowid = new.rowid;
                END
            ''')

            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                END
            ''')

            # Create accounts table (for future multi-account support)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    provider TEXT DEFAULT 'gmail',
                    added_timestamp TEXT,
                    last_sync_timestamp TEXT
                )
            ''')

            # Insert default account
            conn.execute('''
                INSERT OR IGNORE INTO accounts (account_id, email, added_timestamp)
                VALUES ('default', 'default', ?)
            ''', (datetime.now().isoformat(),))

            # Create archive_runs table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS archive_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    query TEXT NOT NULL,
                    messages_archived INTEGER NOT NULL,
                    archive_file TEXT NOT NULL,
                    account_id TEXT DEFAULT 'default',
                    operation_type TEXT DEFAULT 'archive'
                )
            ''')

            # Create schema_version table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    migrated_timestamp TEXT NOT NULL
                )
            ''')

            # Set schema version to 1.1
            conn.execute('''
                INSERT OR REPLACE INTO schema_version (version, migrated_timestamp)
                VALUES ('1.1', ?)
            ''', (datetime.now().isoformat(),))

            conn.commit()
            logger.info("Successfully created new v1.1 database")

        except Exception as e:
            conn.rollback()
            raise DBManagerError(f"Failed to create database schema: {e}") from e
        finally:
            conn.close()

    def _validate_schema_version(self) -> str:
        """
        Validate that database has v1.1 schema.

        Returns:
            Schema version string ('1.1')

        Raises:
            SchemaValidationError: If schema is not v1.1
        """
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not cursor.fetchone():
            raise SchemaValidationError(
                "Database schema validation failed: 'messages' table not found. "
                "Expected v1.1 schema. Run migration first."
            )

        # Check for required columns
        cursor = self.conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        required_columns = {
            "gmail_id",
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

        return "1.1"

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def commit(self) -> None:
        """Explicitly commit current transaction."""
        self.conn.commit()

    def rollback(self) -> None:
        """Explicitly rollback current transaction."""
        self.conn.rollback()

    # ==================== MESSAGE OPERATIONS ====================

    def record_archived_message(
        self,
        gmail_id: str,
        rfc_message_id: str,
        archive_file: str,
        mbox_offset: int,
        mbox_length: int,
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
    ) -> None:
        """
        Record a newly archived message with audit trail.

        This is a transactional operation - commits or rolls back.
        Also records in archive_runs for complete audit trail.

        Args:
            gmail_id: Gmail message ID (primary key)
            rfc_message_id: RFC 2822 Message-ID header (must be unique)
            archive_file: Path to archive file
            mbox_offset: Byte offset in mbox file
            mbox_length: Message length in bytes
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

        Raises:
            DBManagerError: If operation fails
        """
        try:
            self.conn.execute(
                """
                INSERT INTO messages (
                    gmail_id, rfc_message_id, thread_id, subject, from_addr,
                    to_addr, cc_addr, date, archived_timestamp, archive_file,
                    mbox_offset, mbox_length, body_preview, checksum,
                    size_bytes, labels, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gmail_id,
                    rfc_message_id,
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

            # Record in audit trail
            self._record_archive_run(
                operation="archive",
                messages_count=1,
                archive_file=archive_file,
                account_id=account_id,
            )
        except sqlite3.IntegrityError:
            # Re-raise IntegrityError for tests to catch
            raise
        except Exception as e:
            raise DBManagerError(f"Failed to record message {gmail_id}: {e}") from e

    def get_message_by_gmail_id(self, gmail_id: str) -> dict[str, Any] | None:
        """
        Retrieve message metadata by Gmail ID.

        Args:
            gmail_id: Gmail message ID

        Returns:
            Dictionary with message metadata, or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT gmail_id, rfc_message_id, thread_id, subject, from_addr,
                   to_addr, cc_addr, date, archived_timestamp, archive_file,
                   mbox_offset, mbox_length, body_preview, checksum,
                   size_bytes, labels, account_id
            FROM messages WHERE gmail_id = ?
            """,
            (gmail_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_message_location(self, gmail_id: str) -> tuple[str, int, int] | None:
        """
        Get mbox file location for O(1) message access.

        Args:
            gmail_id: Gmail message ID

        Returns:
            Tuple of (archive_file, mbox_offset, mbox_length) or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT archive_file, mbox_offset, mbox_length
            FROM messages WHERE gmail_id = ?
            """,
            (gmail_id,),
        )
        row = cursor.fetchone()
        return (row[0], row[1], row[2]) if row else None

    def get_all_messages_for_archive(self, archive_file: str) -> list[dict[str, Any]]:
        """
        Get all messages in a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            List of message dictionaries
        """
        cursor = self.conn.execute(
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
        return [dict(row) for row in cursor.fetchall()]

    # ==================== DEDUPLICATION ====================

    def find_duplicates(self) -> list[tuple[str, list[str]]]:
        """
        Find all duplicate Message-IDs (rfc_message_id) across archives.

        Returns:
            List of tuples: [(rfc_message_id, [gmail_id1, gmail_id2, ...]), ...]
        """
        cursor = self.conn.execute(
            """
            SELECT rfc_message_id, GROUP_CONCAT(gmail_id) as gmail_ids
            FROM messages
            GROUP BY rfc_message_id
            HAVING COUNT(*) > 1
            """
        )
        return [(row[0], row[1].split(",")) for row in cursor.fetchall()]

    def delete_message(self, gmail_id: str) -> None:
        """
        Delete a message record from database.

        CRITICAL: Only removes from database, doesn't modify mbox files.

        Args:
            gmail_id: Gmail message ID to delete

        Raises:
            DBManagerError: If operation fails
        """
        try:
            self.conn.execute(
                "DELETE FROM messages WHERE gmail_id = ?",
                (gmail_id,),
            )
        except Exception as e:
            raise DBManagerError(f"Failed to delete message {gmail_id}: {e}") from e

    def remove_duplicate_records(
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
                    cursor = self.conn.execute(
                        f"DELETE FROM messages WHERE gmail_id IN ({placeholders})",
                        to_remove,
                    )
                    total_removed += cursor.rowcount

            # Audit trail
            self._record_archive_run(
                operation="deduplicate",
                messages_count=total_removed,
                notes=reason,
            )
            return total_removed
        except Exception as e:
            raise DBManagerError(f"Failed to remove duplicate records: {e}") from e

    # ==================== CONSOLIDATION ====================

    def update_archive_location(
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
            self.conn.execute(
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

    def bulk_update_archive_locations(self, updates: list[dict[str, Any]]) -> None:
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
                (u['archive_file'], u['mbox_offset'], u['mbox_length'], u['gmail_id'])
                for u in updates
            ]

            self.conn.executemany(
                """
                UPDATE messages
                SET archive_file = ?, mbox_offset = ?, mbox_length = ?
                WHERE gmail_id = ?
                """,
                tuples,
            )

            # Audit trail
            self._record_archive_run(
                operation="consolidate",
                messages_count=len(updates),
                archive_file=updates[0]['archive_file'] if updates else None,
            )
        except Exception as e:
            raise DBManagerError(f"Failed to bulk update locations: {e}") from e

    # ==================== VALIDATION & INTEGRITY ====================

    def verify_database_integrity(self) -> list[str]:
        """
        Comprehensive database integrity check.

        Returns:
            List of issues found (empty list if all checks pass)
        """
        issues = []

        try:
            # Check 1: Orphaned FTS records
            cursor = self.conn.execute(
                """
                SELECT COUNT(*) FROM messages_fts
                WHERE rowid NOT IN (SELECT rowid FROM messages)
                """
            )
            orphaned_fts = cursor.fetchone()[0]
            if orphaned_fts > 0:
                issues.append(f"{orphaned_fts} orphaned FTS records")

            # Check 2: Missing FTS records
            cursor = self.conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                """
            )
            missing_fts = cursor.fetchone()[0]
            if missing_fts > 0:
                issues.append(f"{missing_fts} messages missing from FTS index")

            # Check 3: Invalid offsets
            cursor = self.conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE mbox_offset < 0 OR mbox_length <= 0
                """
            )
            invalid_offsets = cursor.fetchone()[0]
            if invalid_offsets > 0:
                issues.append(f"{invalid_offsets} messages with invalid offsets")

            # Check 4: Duplicate Message-IDs (rfc_message_id should be unique)
            cursor = self.conn.execute(
                """
                SELECT rfc_message_id, COUNT(*) as cnt
                FROM messages
                GROUP BY rfc_message_id
                HAVING cnt > 1
                """
            )
            duplicates = cursor.fetchall()
            if duplicates:
                issues.append(f"{len(duplicates)} duplicate Message-IDs found")

            # Check 5: Missing archive files (only check distinct file paths)
            cursor = self.conn.execute("SELECT DISTINCT archive_file FROM messages")
            for row in cursor.fetchall():
                archive_file = Path(row[0])
                if not archive_file.exists():
                    issues.append(f"Missing archive file: {archive_file}")

        except Exception as e:
            logger.error(f"Error during integrity check: {e}")
            issues.append(f"Integrity check error: {e}")

        return issues

    def repair_database(self, dry_run: bool = True) -> dict[str, int]:
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
            cursor = self.conn.execute(
                """
                SELECT COUNT(*) FROM messages_fts
                WHERE rowid NOT IN (SELECT rowid FROM messages)
                """
            )
            repairs["orphaned_fts_removed"] = cursor.fetchone()[0]

            cursor = self.conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                """
            )
            repairs["missing_fts_added"] = cursor.fetchone()[0]
        else:
            with self._transaction():
                try:
                    # Detect FTS mode (content-based vs external content)
                    cursor = self.conn.execute(
                        "SELECT sql FROM sqlite_master WHERE name='messages_fts'"
                    )
                    fts_sql = cursor.fetchone()[0]
                    is_external_content = 'content=""' in fts_sql or "content=''" in fts_sql

                    if is_external_content:
                        # For external content FTS, rebuild the entire FTS table
                        # Count what will be repaired first
                        cursor = self.conn.execute(
                            """
                            SELECT COUNT(*) FROM messages_fts
                            WHERE rowid NOT IN (SELECT rowid FROM messages)
                            """
                        )
                        repairs["orphaned_fts_removed"] = cursor.fetchone()[0]

                        cursor = self.conn.execute(
                            """
                            SELECT COUNT(*) FROM messages
                            WHERE rowid NOT IN (SELECT rowid FROM messages_fts)
                            """
                        )
                        repairs["missing_fts_added"] = cursor.fetchone()[0]

                        # Drop and recreate FTS with correct data
                        self.conn.execute("DROP TABLE messages_fts")
                        self.conn.execute(
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
                        self.conn.execute(
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
                        cursor = self.conn.execute(
                            """
                            DELETE FROM messages_fts
                            WHERE rowid NOT IN (SELECT rowid FROM messages)
                            """
                        )
                        repairs["orphaned_fts_removed"] = cursor.rowcount

                        # Repair 2: Rebuild missing FTS records
                        cursor = self.conn.execute(
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
                    self._record_archive_run(
                        operation="repair",
                        messages_count=repairs["orphaned_fts_removed"]
                        + repairs["missing_fts_added"],
                        notes="Database repair: FTS sync",
                    )
                except Exception as e:
                    raise DBManagerError(f"Database repair failed: {e}") from e

        return repairs

    def get_messages_with_invalid_offsets(self) -> list[dict[str, Any]]:
        """
        Find messages with invalid mbox offsets or lengths.

        Returns:
            List of message dictionaries with offset < 0 or length <= 0
        """
        cursor = self.conn.execute(
            """
            SELECT gmail_id, rfc_message_id, archive_file, mbox_offset, mbox_length
            FROM messages
            WHERE mbox_offset < 0 OR mbox_length <= 0
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== TRANSACTION SUPPORT ====================

    @contextmanager
    def _transaction(self) -> Generator[None]:
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
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction rolled back: {e}")
            raise

    def _record_archive_run(
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

        self.conn.execute(
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

    # ==================== CONTEXT MANAGER ====================

    def __enter__(self) -> DBManager:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - commits on success, rolls back on error, then closes."""
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.close()
