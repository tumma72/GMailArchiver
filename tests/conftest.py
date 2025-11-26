"""
Shared pytest fixtures for GMailArchiver tests.

This module provides centralized, properly-managed fixtures for:
- Temporary directories and files
- SQLite database connections with automatic cleanup
- Mock objects and patches with proper resource management
- Archive files (compressed and uncompressed)

All fixtures use proper context managers and cleanup to avoid ResourceWarnings.
"""

import gzip
import lzma
import sqlite3
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

# =============================================================================
# Test-only SQLite connection wrapper
# =============================================================================

# Preserve original connect function so we can delegate to it
_sqlite3_original_connect = sqlite3.connect


class ManagedConnection(sqlite3.Connection):
    """SQLite connection that auto-closes on garbage collection (tests only).

    This wrapper is used *only* in the test suite to eliminate
    ``ResourceWarning: unclosed database`` warnings that can occur when a
    test forgets to explicitly close a connection. In normal application
    code we prefer explicit close/with-context patterns; this safety net
    ensures the tests remain clean even if a connection escapes.
    """

    def __del__(self) -> None:  # pragma: no cover - defensive finalizer
        try:
            # If a transaction is still open, roll it back before closing.
            try:
                if getattr(self, "in_transaction", False):
                    self.rollback()
            except Exception:
                # Best-effort rollback; ignore errors in finalizer
                pass

            try:
                self.close()
            except Exception:
                # Avoid raising during interpreter shutdown
                pass
        except Exception:
            # Final guard against any unexpected errors in __del__
            pass


def _managed_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    """Factory that creates ManagedConnection instances for tests.

    We delegate to the original ``sqlite3.connect`` while injecting our
    ManagedConnection via the ``factory`` argument when the caller has
    not provided a custom factory.
    """
    if "factory" not in kwargs:
        kwargs["factory"] = ManagedConnection
    return _sqlite3_original_connect(*args, **kwargs)


# Install the managed connect function for the duration of the test suite.
# This ensures that any direct ``sqlite3.connect`` calls in tests or
# application code executed under pytest will use ManagedConnection and
# therefore be cleanly closed on garbage collection.
sqlite3.connect = _managed_connect  # type: ignore[assignment]

import pytest  # noqa: E402

from gmailarchiver.data.db_manager import DBManager  # noqa: E402

# ============================================================================
# Base Fixtures: Temporary Resources
# ============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create and cleanup temporary directory for testing.

    Yields:
        Path to a temporary directory that is automatically cleaned up.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# --------------------------------------------------------------------------
# Shared SQLite DB fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def temp_db_path(temp_dir: Path) -> str:
    """Common temporary database path used across tests.

    This returns a path without creating the database file. Tests and
    higher-level fixtures can create whatever schema they need at this
    location while still benefiting from the shared lifecycle of
    ``temp_dir``.
    """
    return str(temp_dir / "test_archive.db")


@pytest.fixture
def v11_db(temp_db_path: str) -> Generator[str]:
    """Create a minimal v1.1-style database used by multiple test modules.

    The schema matches the v1.1 expectations (messages + FTS +
    archive_runs + schema_version) and ensures the connection is always
    closed via a generator + ``finally`` block.
    """
    conn = sqlite3.connect(temp_db_path)
    try:
        # Messages table (v1.1 schema subset sufficient for tests)
        conn.execute(
            """
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
            """
        )

        # FTS5 table and basic triggers (sufficient for Doctor/Search tests)
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject,
                from_addr,
                to_addr,
                body_preview,
                content=messages,
                content_rowid=rowid,
                tokenize='porter unicode61 remove_diacritics 1'
            )
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_insert
            AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
            END
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_update
            AFTER UPDATE ON messages BEGIN
                UPDATE messages_fts
                SET subject = new.subject,
                    from_addr = new.from_addr,
                    to_addr = new.to_addr,
                    body_preview = new.body_preview
                WHERE rowid = new.rowid;
            END
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_delete
            AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE rowid = old.rowid;
            END
            """
        )

        # archive_runs and schema_version (used by multiple components)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
            """
        )

        # Ensure PRAGMA user_version reflects v1.1 for tools/tests that rely
        # on it (e.g. Doctor checks)
        conn.execute("PRAGMA user_version = 11")
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
            ("1.1", "1970-01-01T00:00:00"),
        )

        conn.commit()
        yield temp_db_path
    finally:
        conn.close()


@pytest.fixture
def v11_db_factory(temp_dir: Path):
    """Factory to create additional v1.1-style databases in tests.

    This allows tests to create one or more separate v1.1 databases
    sharing the same temporary directory without duplicating schema
    setup code. Each call returns a database path with the standard
    v1.1 schema already created.
    """

    def _factory(name: str = "test_archive.db") -> str:
        db_path = temp_dir / name
        conn = sqlite3.connect(str(db_path))
        try:
            # Reuse the same schema as v11_db
            conn.execute(
                """
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
                """
            )

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject,
                    from_addr,
                    to_addr,
                    body_preview,
                    content=messages,
                    content_rowid=rowid,
                    tokenize='porter unicode61 remove_diacritics 1'
                )
                """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_fts_insert
                AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                    VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
                END
                """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_fts_update
                AFTER UPDATE ON messages BEGIN
                    UPDATE messages_fts
                    SET subject = new.subject,
                        from_addr = new.from_addr,
                        to_addr = new.to_addr,
                        body_preview = new.body_preview
                    WHERE rowid = new.rowid;
                END
                """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_fts_delete
                AFTER DELETE ON messages BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                END
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    query TEXT,
                    messages_archived INTEGER NOT NULL,
                    archive_file TEXT NOT NULL,
                    account_id TEXT DEFAULT 'default',
                    operation_type TEXT DEFAULT 'archive'
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    migrated_timestamp TEXT NOT NULL
                )
                """
            )

            conn.execute("PRAGMA user_version = 11")
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
                ("1.1", "1970-01-01T00:00:00"),
            )

            conn.commit()
        finally:
            conn.close()

        return str(db_path)

    return _factory


@pytest.fixture
def temp_db(temp_dir: Path) -> Generator[Path]:
    """Create temporary v1.1 database with automatic cleanup.

    Ensures DBManager connections are properly closed to avoid ResourceWarnings.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path to created database file
    """
    db_path = temp_dir / "test.db"

    # Create database and immediately close to ensure proper initialization
    db = DBManager(str(db_path))
    db.close()

    yield db_path

    # Cleanup: ensure no dangling connections
    # The database file will be deleted with temp_dir


@pytest.fixture
def populated_db(temp_dir: Path, sample_message: bytes) -> Generator[Path]:
    """Create temporary v1.1 database with test messages and archive files.

    This fixture populates the database with test messages and creates the
    corresponding archive files (both compressed and uncompressed) that the
    database records reference. All connections are properly closed.

    Args:
        temp_dir: Temporary directory fixture
        sample_message: Sample email message bytes

    Yields:
        Path to populated database file
    """
    db_path = temp_dir / "test.db"

    # Create archive files first
    # Uncompressed mbox with msg001 and msg002
    mbox_path = temp_dir / "archive.mbox"
    msg1 = sample_message
    msg2 = (
        sample_message.replace(b"test001", b"test002")
        .replace(b"alice@example.com", b"bob@example.com")
        .replace(b"bob@example.com", b"alice@example.com")
    )

    with open(mbox_path, "wb") as f:
        f.write(msg1)
        f.write(msg2)

    # Gzip compressed mbox with msg003
    gzip_path = temp_dir / "archive.mbox.gz"
    msg3 = (
        sample_message.replace(b"test001", b"test003")
        .replace(b"alice@example.com", b"charlie@example.com")
        .replace(b"bob@example.com", b"alice@example.com")
    )

    with gzip.open(gzip_path, "wb") as f:
        f.write(msg3)

    # Create database with v1.1 schema and insert records within a
    # context manager so changes are committed on success.
    with DBManager(str(db_path)) as db:
        # Add test messages that reference the created archive files
        test_messages = [
            {
                "gmail_id": "msg001",
                "rfc_message_id": "<test001@example.com>",
                "archive_file": str(mbox_path),
                "mbox_offset": 0,
                "mbox_length": len(msg1),
                "subject": "Test Message 1",
                "from_addr": "alice@example.com",
                "to_addr": "bob@example.com",
            },
            {
                "gmail_id": "msg002",
                "rfc_message_id": "<test002@example.com>",
                "archive_file": str(mbox_path),
                "mbox_offset": len(msg1),
                "mbox_length": len(msg2),
                "subject": "Test Message 2",
                "from_addr": "bob@example.com",
                "to_addr": "alice@example.com",
            },
            {
                "gmail_id": "msg003",
                "rfc_message_id": "<test003@example.com>",
                "archive_file": str(gzip_path),
                "mbox_offset": 0,
                "mbox_length": len(msg3),
                "subject": "Test Message 3",
                "from_addr": "charlie@example.com",
                "to_addr": "alice@example.com",
            },
        ]

        for msg in test_messages:
            db.record_archived_message(
                gmail_id=msg["gmail_id"],
                rfc_message_id=msg["rfc_message_id"],
                archive_file=msg["archive_file"],
                mbox_offset=msg["mbox_offset"],
                mbox_length=msg["mbox_length"],
                subject=msg["subject"],
                from_addr=msg["from_addr"],
                to_addr=msg["to_addr"],
                record_run=False,
            )

    yield db_path

    # Cleanup: ensure no dangling connections
    # The database file and archive files will be deleted with temp_dir


# ============================================================================
# Archive File Fixtures
# ============================================================================


@pytest.fixture
def sample_message() -> bytes:
    """Sample email message for testing.

    Returns:
        Raw email message bytes in mbox format
    """
    return b"""From alice@example.com Mon Jan 01 00:00:00 2024
From: alice@example.com
To: bob@example.com
Subject: Test Message
Message-ID: <test001@example.com>
Date: Mon, 01 Jan 2024 00:00:00 +0000

This is a test message body.
"""


@pytest.fixture
def uncompressed_mbox(temp_dir: Path, sample_message: bytes) -> Path:
    """Create uncompressed mbox archive file.

    Args:
        temp_dir: Temporary directory fixture
        sample_message: Sample email message bytes

    Returns:
        Path to created mbox file
    """
    mbox_path = temp_dir / "archive.mbox"

    # Write sample messages
    msg1 = sample_message
    msg2 = sample_message.replace(b"test001", b"test002").replace(
        b"Test Message", b"Test Message 2"
    )

    with open(mbox_path, "wb") as f:
        f.write(msg1)
        f.write(msg2)

    return mbox_path


@pytest.fixture
def compressed_mbox_gzip(temp_dir: Path, sample_message: bytes) -> Path:
    """Create gzip-compressed mbox archive file.

    Args:
        temp_dir: Temporary directory fixture
        sample_message: Sample email message bytes

    Returns:
        Path to created gzip mbox file
    """
    mbox_path = temp_dir / "archive.mbox.gz"

    msg1 = sample_message.replace(b"test001", b"test003").replace(b"alice", b"charlie")

    with gzip.open(mbox_path, "wb") as f:
        f.write(msg1)

    return mbox_path


@pytest.fixture
def compressed_mbox_lzma(temp_dir: Path, sample_message: bytes) -> Path:
    """Create lzma-compressed mbox archive file.

    Args:
        temp_dir: Temporary directory fixture
        sample_message: Sample email message bytes

    Returns:
        Path to created lzma mbox file
    """
    mbox_path = temp_dir / "archive.mbox.xz"

    msg1 = sample_message.replace(b"test001", b"test004").replace(b"alice", b"dave")

    with lzma.open(mbox_path, "wb") as f:
        f.write(msg1)

    return mbox_path


# ============================================================================
# Database Management Fixtures with Context Managers
# ============================================================================


@pytest.fixture
def db_connection(populated_db: Path) -> Generator[DBManager]:
    """Create managed database connection with automatic cleanup.

    This fixture provides a DBManager instance that is properly closed
    at the end of the test to avoid ResourceWarnings.

    Args:
        populated_db: Populated database fixture

    Yields:
        DBManager instance connected to the test database
    """
    db = DBManager(str(populated_db))
    try:
        yield db
    finally:
        # Always close to avoid ResourceWarnings
        db.close()


@pytest.fixture
def raw_db_connection(temp_db: Path) -> Generator[sqlite3.Connection]:
    """Create managed raw SQLite connection with automatic cleanup.

    For tests that need direct SQLite access rather than DBManager.

    Args:
        temp_db: Temporary database fixture

    Yields:
        sqlite3.Connection instance
    """
    conn = sqlite3.connect(str(temp_db))
    try:
        yield conn
    finally:
        # Always close to avoid ResourceWarnings
        conn.close()


# ============================================================================
# Mock and Patch Fixtures
# ============================================================================


@pytest.fixture
def mock_db_path(temp_dir: Path) -> Path:
    """Provide a path for a mock database that will be cleaned up.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to a database file (not created, just the path)
    """
    return temp_dir / "mock_test.db"
