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
import mailbox
import sqlite3
import tempfile
import warnings
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

# Filter Python 3.14 stdlib deprecation warnings from the mailbox module
# The mailbox.mbox implementation uses text mode files internally, and this
# deprecation warning is not actionable in our codebase.
warnings.filterwarnings(
    "ignore",
    message="Use of text mode files is deprecated",
    category=DeprecationWarning,
)

from typer.testing import CliRunner  # noqa: E402

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

        # Schedules table (v1.3+)
        conn.execute(
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

        # Archive sessions table (v1.3.6+)
        conn.execute(
            """
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

            conn.execute(
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

            conn.execute(
                """
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

    Uses sync sqlite3 for setup to avoid event loop conflicts with pytest-asyncio.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path to created database file
    """
    db_path = temp_dir / "test.db"

    # Create database using sync sqlite3 to avoid asyncio.run() conflicts
    conn = sqlite3.connect(str(db_path))
    try:
        # Minimal schema for v1.1
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
                archived_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
        conn.execute(
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
        conn.execute(
            """
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

    yield db_path


@pytest.fixture
def populated_db(temp_dir: Path, sample_message: bytes) -> Generator[Path]:
    """Create temporary v1.1 database with test messages and archive files.

    Uses sync sqlite3 for setup to avoid event loop conflicts with pytest-asyncio.

    Args:
        temp_dir: Temporary directory fixture
        sample_message: Sample email message bytes

    Yields:
        Path to populated database file
    """
    from datetime import datetime

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

    # Create database using sync sqlite3 to avoid asyncio.run() conflicts
    conn = sqlite3.connect(str(db_path))
    try:
        # Create v1.1 schema
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

        # Insert test messages
        now = datetime.now().isoformat()
        test_messages = [
            (
                "msg001",
                "<test001@example.com>",
                str(mbox_path),
                0,
                len(msg1),
                "Test Message 1",
                "alice@example.com",
                "bob@example.com",
                now,
            ),
            (
                "msg002",
                "<test002@example.com>",
                str(mbox_path),
                len(msg1),
                len(msg2),
                "Test Message 2",
                "bob@example.com",
                "alice@example.com",
                now,
            ),
            (
                "msg003",
                "<test003@example.com>",
                str(gzip_path),
                0,
                len(msg3),
                "Test Message 3",
                "charlie@example.com",
                "alice@example.com",
                now,
            ),
        ]

        for msg in test_messages:
            conn.execute(
                """
                INSERT INTO messages (gmail_id, rfc_message_id, archive_file, mbox_offset,
                    mbox_length, subject, from_addr, to_addr, archived_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                msg,
            )

        conn.commit()
    finally:
        conn.close()

    yield db_path


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
async def db_manager(v11_db: str) -> AsyncGenerator[DBManager]:
    """Create a DBManager with proper async initialization and cleanup.

    This is the SINGLE source for async DBManager fixtures across all tests.
    Do NOT define local db_manager fixtures in individual test files.

    The fixture:
    - Creates DBManager pointed at a v1.1 schema database
    - Initializes the async connection
    - Yields the manager for test use
    - Closes the connection on teardown (prevents hanging tests)

    Args:
        v11_db: Path to v1.1 database from the v11_db fixture

    Yields:
        Initialized DBManager instance with active connection
    """
    manager = DBManager(v11_db)
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def hybrid_storage(db_manager: DBManager) -> AsyncGenerator:
    """Create a HybridStorage instance with proper cleanup.

    This is the SINGLE source for HybridStorage fixtures across all tests.
    Do NOT define local storage fixtures in individual test files.

    The fixture:
    - Uses the shared db_manager fixture (which handles connection cleanup)
    - Creates HybridStorage wrapping the DBManager
    - Yields the storage for test use

    Args:
        db_manager: Initialized DBManager from the db_manager fixture

    Yields:
        HybridStorage instance wrapping the DBManager
    """
    from gmailarchiver.data.hybrid_storage import HybridStorage

    storage = HybridStorage(db_manager)
    yield storage
    # db_manager cleanup is handled by its own fixture


@pytest.fixture
async def db_manager_with_messages(db_manager: DBManager) -> AsyncGenerator[DBManager]:
    """DBManager with pre-populated test messages for duplicate testing.

    This fixture extends db_manager with sample messages already in the database.
    Useful for testing deduplication, filtering, and import workflows.

    Args:
        db_manager: Base db_manager fixture

    Yields:
        DBManager with existing test messages
    """
    # Insert test messages directly via SQL
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, body_preview, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
        """,
        (
            "<existing1@example.com>",
            "existing1",
            "thread1",
            "Existing Message 1",
            "old@example.com",
            "recipient@example.com",
            "2024-01-01T00:00:00",
            "old.mbox",
            0,
            100,
            "Old message 1 body",
            "default",
        ),
    )
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, body_preview, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
        """,
        (
            "<existing2@example.com>",
            "existing2",
            "thread2",
            "Existing Message 2",
            "old@example.com",
            "recipient@example.com",
            "2024-01-02T00:00:00",
            "old.mbox",
            100,
            100,
            "Old message 2 body",
            "default",
        ),
    )
    await db_manager.commit()
    yield db_manager


@pytest.fixture
def db_connection(populated_db: Path) -> Generator[DBManager]:
    """Create managed database connection with automatic cleanup.

    NOTE: This fixture provides an uninitialized DBManager. Tests using this
    fixture should call `await db.initialize()` if they need a connection,
    and use async context manager (`async with DBManager(...) as db:`) for
    proper lifecycle management.

    Args:
        populated_db: Populated database fixture

    Yields:
        DBManager instance (not yet connected - call initialize() first)
    """
    # Note: DBManager.close() is async, so we can't call it from sync fixture.
    # Since we don't call initialize(), there's no connection to close.
    # Tests should use async context manager for proper cleanup.
    yield DBManager(str(populated_db))


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


# ============================================================================
# CLI Test Fixtures
# ============================================================================


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner.

    This is the SINGLE source for CliRunner across all CLI tests.
    Do NOT define local runner fixtures in individual test files.
    """
    return CliRunner()


@pytest.fixture
def v1_1_database(tmp_path: Path) -> Generator[Path]:
    """Create a v1.1 database for CLI testing.

    Uses sync sqlite3 to avoid asyncio.run() conflicts with pytest-asyncio.
    This is the SINGLE source for CLI database fixtures.
    Do NOT define local v1_1_database fixtures in individual test files.

    Yields:
        Path to a v1.1 database file
    """
    db_path = tmp_path / "archive_state.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create v1.1 schema (same as v11_db but for CLI tests)
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

        # FTS5 table
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

        # FTS triggers
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

        # archive_runs table
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

        # schema_version table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
            """
        )

        # accounts table (required for v1.1+)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                provider TEXT DEFAULT 'gmail',
                added_timestamp TEXT,
                last_sync_timestamp TEXT
            )
            """
        )

        # Insert default account
        conn.execute(
            "INSERT OR IGNORE INTO accounts (account_id, email, added_timestamp) "
            "VALUES ('default', 'default', '1970-01-01T00:00:00')"
        )

        # Set schema version
        conn.execute("PRAGMA user_version = 11")
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) "
            "VALUES ('1.1', '1970-01-01T00:00:00')"
        )

        conn.commit()
        yield db_path
    finally:
        conn.close()


@pytest.fixture
def sample_mbox(tmp_path: Path) -> Path:
    """Create a sample mbox file with test messages.

    This is the SINGLE source for sample mbox fixtures.
    Do NOT define local sample_mbox fixtures in individual test files.

    Returns:
        Path to mbox file with 3 test messages
    """
    mbox_path = tmp_path / "test_archive.mbox"
    mbox_obj = mailbox.mbox(str(mbox_path))

    # Add 3 test messages
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg.set_payload(f"This is test message {i}")
        mbox_obj.add(msg)

    mbox_obj.close()
    return mbox_path


# ============================================================================
# Doctor Test Fixtures
# ============================================================================


@pytest.fixture
async def doctor(v11_db: str) -> AsyncGenerator:
    """Create a Doctor instance for a v1.1 database with automatic cleanup.

    This is the primary fixture for simple doctor tests that need a Doctor
    instance for a valid v1.1 database.

    Yields:
        Doctor instance (properly closed on teardown)
    """
    from gmailarchiver.core.doctor import Doctor

    doc = await Doctor.create(v11_db)
    try:
        yield doc
    finally:
        await doc.close()


@pytest.fixture
async def memory_doctor() -> AsyncGenerator:
    """Create a Doctor instance for an in-memory database with automatic cleanup.

    Use this for tests that need a Doctor but don't need persistent data.

    Yields:
        Doctor instance with :memory: database (properly closed on teardown)
    """
    from gmailarchiver.core.doctor import Doctor

    doc = await Doctor.create(":memory:")
    try:
        yield doc
    finally:
        await doc.close()


@pytest.fixture
def sample_mbox_with_duplicates(tmp_path: Path) -> Path:
    """Create mbox file with duplicate Message-IDs.

    This is the SINGLE source for duplicate mbox fixtures.
    Do NOT define local sample_mbox_with_duplicates fixtures in individual test files.

    Returns:
        Path to mbox file with duplicate messages
    """
    mbox_path = tmp_path / "duplicates.mbox"
    mbox_obj = mailbox.mbox(str(mbox_path))

    # Add 2 messages with same Message-ID
    for i in range(1, 3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Duplicate Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = "<duplicate@example.com>"
        msg.set_payload(f"Duplicate message {i}")
        mbox_obj.add(msg)

    mbox_obj.close()
    return mbox_path
