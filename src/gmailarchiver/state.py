"""State tracking for incremental archiving using SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class ArchiveState:
    """Track archived messages in SQLite database."""

    def __init__(self, db_path: str = 'archive_state.db') -> None:
        """
        Initialize state database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL
            )
        ''')

        self.conn.commit()

    def is_archived(self, gmail_id: str) -> bool:
        """
        Check if a message has been archived.

        Args:
            gmail_id: Gmail message ID

        Returns:
            True if message is in archive database
        """
        cursor = self.conn.execute(
            'SELECT 1 FROM archived_messages WHERE gmail_id = ?',
            (gmail_id,)
        )
        return cursor.fetchone() is not None

    def mark_archived(
        self,
        gmail_id: str,
        archive_file: str,
        subject: str | None = None,
        from_addr: str | None = None,
        message_date: str | None = None,
        checksum: str | None = None
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
        """
        self.conn.execute('''
            INSERT OR REPLACE INTO archived_messages
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            gmail_id,
            datetime.now().isoformat(),
            archive_file,
            subject,
            from_addr,
            message_date,
            checksum
        ))
        self.conn.commit()

    def record_archive_run(
        self,
        query: str,
        messages_archived: int,
        archive_file: str
    ) -> int:
        """
        Record an archive run.

        Args:
            query: Gmail query used
            messages_archived: Number of messages archived
            archive_file: Path to archive file

        Returns:
            Run ID
        """
        cursor = self.conn.execute('''
            INSERT INTO archive_runs (run_timestamp, query, messages_archived, archive_file)
            VALUES (?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            query,
            messages_archived,
            archive_file
        ))
        self.conn.commit()
        return cursor.lastrowid if cursor.lastrowid is not None else -1

    def get_archived_count(self) -> int:
        """
        Get total number of archived messages.

        Returns:
            Count of archived messages
        """
        cursor = self.conn.execute('SELECT COUNT(*) FROM archived_messages')
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
        cursor = self.conn.execute('''
            SELECT run_id, run_timestamp, query, messages_archived, archive_file
            FROM archive_runs
            ORDER BY run_timestamp DESC
            LIMIT ?
        ''', (limit,))

        runs = []
        for row in cursor.fetchall():
            runs.append({
                'run_id': row[0],
                'timestamp': row[1],
                'query': row[2],
                'messages_archived': row[3],
                'archive_file': row[4]
            })
        return runs

    def get_archived_message_ids(self) -> set[str]:
        """
        Get all archived message IDs.

        Returns:
            Set of Gmail message IDs
        """
        cursor = self.conn.execute('SELECT gmail_id FROM archived_messages')
        return {row[0] for row in cursor.fetchall()}

    def get_archived_message_ids_for_file(self, archive_file: str) -> set[str]:
        """
        Get archived message IDs for a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            Set of Gmail message IDs in that specific archive
        """
        cursor = self.conn.execute(
            'SELECT gmail_id FROM archived_messages WHERE archive_file = ?',
            (archive_file,)
        )
        return {row[0] for row in cursor.fetchall()}

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def __enter__(self) -> ArchiveState:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()
