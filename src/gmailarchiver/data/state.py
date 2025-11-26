"""State tracking for incremental archiving using SQLite."""

import sqlite3
from datetime import datetime
from typing import Any

from gmailarchiver.shared.path_validator import validate_file_path


class ArchiveState:
    """Track archived messages in SQLite database."""

    def __init__(self, db_path: str = "archive_state.db", validate_path: bool = True) -> None:
        """
        Initialize state database.

        Args:
            db_path: Path to SQLite database file
            validate_path: Whether to validate path (set False for testing)

        Raises:
            PathTraversalError: If validate_path=True and path attempts to escape working directory
        """
        # Validate path to prevent path traversal attacks (unless disabled for testing)
        if validate_path:
            self.db_path = validate_file_path(db_path)
        else:
            from pathlib import Path

            self.db_path = Path(db_path).resolve()
        self.conn = sqlite3.connect(str(self.db_path))
        self._schema_version = self._detect_schema_version()
        self._create_tables()

    def _detect_schema_version(self) -> str:
        """
        Detect current database schema version.

        Returns:
            Schema version: "1.0", "1.1", or "none"
        """
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone():
            version_cursor = self.conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = version_cursor.fetchone()
            return row[0] if row else "1.0"

        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if cursor.fetchone():
            return "1.1"

        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        if cursor.fetchone():
            return "1.0"

        return "none"

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL
            )
        """)

        self.conn.commit()

    def is_archived(self, gmail_id: str) -> bool:
        """
        Check if a message has been archived.

        Args:
            gmail_id: Gmail message ID

        Returns:
            True if message is in archive database
        """
        table_name = "messages" if self._schema_version == "1.1" else "archived_messages"
        cursor = self.conn.execute(f"SELECT 1 FROM {table_name} WHERE gmail_id = ?", (gmail_id,))
        return cursor.fetchone() is not None

    def mark_archived(
        self,
        gmail_id: str,
        archive_file: str,
        subject: str | None = None,
        from_addr: str | None = None,
        message_date: str | None = None,
        checksum: str | None = None,
        # v1.1 enhanced fields
        rfc_message_id: str | None = None,
        mbox_offset: int | None = None,
        mbox_length: int | None = None,
        body_preview: str | None = None,
        to_addr: str | None = None,
        cc_addr: str | None = None,
        thread_id: str | None = None,
        size_bytes: int | None = None,
        labels: str | None = None,
        account_id: str = "default",
    ) -> None:
        """
        Mark a message as archived.

        Args:
            gmail_id: Gmail message ID
            archive_file: Path to archive file
            subject: Email subject
            from_addr: From address
            message_date: Message date
            checksum: SHA256 checksum of message
            rfc_message_id: RFC 2822 Message-ID header (v1.1+)
            mbox_offset: Byte offset in mbox file (v1.1+)
            mbox_length: Message length in bytes (v1.1+)
            body_preview: First 1000 chars of body (v1.1+)
            to_addr: To address (v1.1+)
            cc_addr: CC address (v1.1+)
            thread_id: Gmail thread ID (v1.1+)
            size_bytes: Total message size (v1.1+)
            labels: JSON array of Gmail labels (v1.1+)
            account_id: Account identifier (v1.1+, default: 'default')
        """
        if self._schema_version == "1.1":
            # Use enhanced schema
            # Default rfc_message_id if not provided
            if rfc_message_id is None:
                rfc_message_id = f"<{gmail_id}@gmail>"

            # Require mbox_offset and mbox_length for v1.1
            if mbox_offset is None or mbox_length is None:
                raise ValueError("mbox_offset and mbox_length required for v1.1 schema")

            self.conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
                 date, archived_timestamp, archive_file, mbox_offset, mbox_length,
                 body_preview, checksum, size_bytes, labels, account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    gmail_id,
                    rfc_message_id,
                    thread_id,
                    subject,
                    from_addr,
                    to_addr,
                    cc_addr,
                    message_date,
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
        else:
            # Use v1.0 schema (backward compatibility)
            self.conn.execute(
                """
                INSERT OR REPLACE INTO archived_messages
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    gmail_id,
                    datetime.now().isoformat(),
                    archive_file,
                    subject,
                    from_addr,
                    message_date,
                    checksum,
                ),
            )
        # Note: Commit is deferred to allow batch operations
        # Call commit() explicitly or use context manager to auto-commit

    def record_archive_run(self, query: str, messages_archived: int, archive_file: str) -> int:
        """
        Record an archive run.

        Args:
            query: Gmail query used
            messages_archived: Number of messages archived
            archive_file: Path to archive file

        Returns:
            Run ID
        """
        cursor = self.conn.execute(
            """
            INSERT INTO archive_runs (run_timestamp, query, messages_archived, archive_file)
            VALUES (?, ?, ?, ?)
        """,
            (datetime.now().isoformat(), query, messages_archived, archive_file),
        )
        # Note: Commit is deferred to allow batch operations
        # Call commit() explicitly or use context manager to auto-commit
        return cursor.lastrowid if cursor.lastrowid is not None else -1

    def get_archived_count(self) -> int:
        """
        Get total number of archived messages.

        Returns:
            Count of archived messages
        """
        table_name = "messages" if self._schema_version == "1.1" else "archived_messages"
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_archive_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent archive runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of archive run dictionaries
        """
        cursor = self.conn.execute(
            """
            SELECT run_id, run_timestamp, query, messages_archived, archive_file
            FROM archive_runs
            ORDER BY run_timestamp DESC
            LIMIT ?
        """,
            (limit,),
        )

        runs = []
        for row in cursor.fetchall():
            runs.append(
                {
                    "run_id": row[0],
                    "timestamp": row[1],
                    "query": row[2],
                    "messages_archived": row[3],
                    "archive_file": row[4],
                }
            )
        return runs

    def get_archived_message_ids(self) -> set[str]:
        """
        Get all archived message IDs.

        Returns:
            Set of Gmail message IDs
        """
        table_name = "messages" if self._schema_version == "1.1" else "archived_messages"
        cursor = self.conn.execute(f"SELECT gmail_id FROM {table_name}")
        return {row[0] for row in cursor.fetchall()}

    def get_archived_message_ids_for_file(self, archive_file: str) -> set[str]:
        """
        Get archived message IDs for a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            Set of Gmail message IDs in that specific archive
        """
        table_name = "messages" if self._schema_version == "1.1" else "archived_messages"
        cursor = self.conn.execute(
            f"SELECT gmail_id FROM {table_name} WHERE archive_file = ?", (archive_file,)
        )
        return {row[0] for row in cursor.fetchall()}

    @property
    def schema_version(self) -> str:
        """
        Get current schema version.

        Returns:
            Schema version string ("1.0", "1.1", or "none")
        """
        return self._schema_version

    def needs_migration(self) -> bool:
        """
        Check if database needs migration to v1.1.

        Returns:
            True if migration is needed
        """
        return self._schema_version in ("1.0", "none")

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def __enter__(self) -> ArchiveState:
        """Context manager entry - begins transaction."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - commits on success, rollbacks on exception.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        if exc_type is None:
            # No exception - commit the transaction
            self.conn.commit()
        else:
            # Exception occurred - rollback all changes
            self.conn.rollback()
        self.close()

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
