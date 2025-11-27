"""Tests for DBManager class."""

import json
import sqlite3
from datetime import datetime
from typing import Any
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.data.db_manager import DBManager

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_message_data() -> dict[str, Any]:
    """Sample message data for testing."""
    return {
        "gmail_id": "msg123",
        "rfc_message_id": "<unique123@example.com>",
        "thread_id": "thread123",
        "subject": "Test Subject",
        "from_addr": "sender@example.com",
        "to_addr": "recipient@example.com",
        "cc_addr": "cc@example.com",
        "date": "2024-01-01T00:00:00",
        "archive_file": "archive.mbox",
        "mbox_offset": 0,
        "mbox_length": 1234,
        "body_preview": "This is a test message body",
        "checksum": "abc123",
        "size_bytes": 5000,
        "labels": json.dumps(["INBOX", "IMPORTANT"]),
        "account_id": "default",
    }


# ============================================================================
# Initialization Tests
# ============================================================================


class TestDBManagerInitialization:
    """Tests for DBManager initialization."""

    def test_connect_to_existing_database(self, v11_db: str) -> None:
        """Test connecting to an existing v1.1 database."""

        db = DBManager(v11_db)
        assert db.conn is not None
        assert db.schema_version == "1.1"
        db.close()

    def test_connect_to_missing_database(self, temp_db_path: str) -> None:
        """Test connecting to a non-existent database path."""
        # Should raise error when database doesn't exist
        with pytest.raises(FileNotFoundError):
            DBManager(temp_db_path, auto_create=False)

    def test_validate_schema_on_init(self, v11_db: str) -> None:
        """Test that schema is validated on initialization."""

        db = DBManager(v11_db)

        # Should detect all required tables
        cursor = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "messages" in tables
        assert "archive_runs" in tables
        assert "messages_fts" in tables
        assert "schema_version" in tables

        db.close()

    def test_invalid_database_path(self) -> None:
        """Test handling of invalid database path."""

        with pytest.raises((FileNotFoundError, ValueError)):
            DBManager("/invalid/path/to/database.db", auto_create=False)

    def test_context_manager_interface(self, v11_db: str) -> None:
        """Test using DBManager as a context manager."""

        with DBManager(v11_db) as db:
            assert db.conn is not None
            db.conn.execute("SELECT COUNT(*) FROM messages")

        # Connection should be closed after context
        # Verify by creating new connection
        conn = sqlite3.connect(v11_db)
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        assert count == 0
        conn.close()


# ============================================================================
# Message Operations Tests
# ============================================================================


class TestMessageOperations:
    """Tests for message CRUD operations."""

    def test_record_archived_message_success(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test recording a new archived message."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            # Verify message was stored
            cursor = db.conn.execute(
                "SELECT * FROM messages WHERE gmail_id = ?", (sample_message_data["gmail_id"],)
            )
            row = cursor.fetchone()

            assert row is not None
            # Verify key fields
            assert row[0] == sample_message_data["gmail_id"]
            assert row[1] == sample_message_data["rfc_message_id"]
            assert row[3] == sample_message_data["subject"]

    def test_record_duplicate_gmail_id_fails(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that duplicate gmail_id raises error."""

        with DBManager(v11_db) as db:
            # Insert first message
            db.record_archived_message(**sample_message_data)

            # Try to insert duplicate gmail_id with different rfc_message_id
            duplicate_data = sample_message_data.copy()
            duplicate_data["rfc_message_id"] = "<different@example.com>"

            with pytest.raises(sqlite3.IntegrityError):
                db.record_archived_message(**duplicate_data)

    def test_record_duplicate_rfc_message_id_fails(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that duplicate rfc_message_id raises error."""

        with DBManager(v11_db) as db:
            # Insert first message
            db.record_archived_message(**sample_message_data)

            # Try to insert duplicate rfc_message_id with different gmail_id
            duplicate_data = sample_message_data.copy()
            duplicate_data["gmail_id"] = "msg456"

            with pytest.raises(sqlite3.IntegrityError):
                db.record_archived_message(**duplicate_data)

    def test_record_message_creates_archive_run(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that recording a message also creates an archive_run entry."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            # Verify archive_run was created
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM archive_runs WHERE archive_file = ?",
                (sample_message_data["archive_file"],),
            )
            count = cursor.fetchone()[0]
            assert count > 0

    def test_get_message_by_gmail_id_found(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test retrieving a message by gmail_id."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            message = db.get_message_by_gmail_id(sample_message_data["gmail_id"])

            assert message is not None
            assert message["gmail_id"] == sample_message_data["gmail_id"]
            assert message["subject"] == sample_message_data["subject"]
            assert message["archive_file"] == sample_message_data["archive_file"]

    def test_get_message_by_gmail_id_not_found(self, v11_db: str) -> None:
        """Test retrieving a non-existent message."""

        with DBManager(v11_db) as db:
            message = db.get_message_by_gmail_id("nonexistent123")
            assert message is None

    def test_get_message_location(self, v11_db: str, sample_message_data: dict[str, Any]) -> None:
        """Test getting message location (file, offset, length)."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            # v1.2: get_message_location uses rfc_message_id (primary key)
            location = db.get_message_location(sample_message_data["rfc_message_id"])

            assert location is not None
            assert location[0] == sample_message_data["archive_file"]
            assert location[1] == sample_message_data["mbox_offset"]
            assert location[2] == sample_message_data["mbox_length"]

    def test_get_all_messages_for_archive(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test retrieving all messages for a specific archive file."""

        with DBManager(v11_db) as db:
            # Insert multiple messages to same archive
            for i in range(3):
                data = sample_message_data.copy()
                data["gmail_id"] = f"msg{i}"
                data["rfc_message_id"] = f"<unique{i}@example.com>"
                data["mbox_offset"] = i * 1000
                db.record_archived_message(**data)

            # Insert message to different archive
            other_data = sample_message_data.copy()
            other_data["gmail_id"] = "msg999"
            other_data["rfc_message_id"] = "<unique999@example.com>"
            other_data["archive_file"] = "other.mbox"
            db.record_archived_message(**other_data)

            messages = db.get_all_messages_for_archive(sample_message_data["archive_file"])

            assert len(messages) == 3
            assert all(
                msg["archive_file"] == sample_message_data["archive_file"] for msg in messages
            )


# ============================================================================
# Deduplication Tests
# ============================================================================


class TestDeduplication:
    """Tests for duplicate detection and removal."""

    def test_find_duplicates_none(self, v11_db: str) -> None:
        """Test finding duplicates when there are none."""

        with DBManager(v11_db) as db:
            duplicates = db.find_duplicates()
            assert len(duplicates) == 0

    def test_find_duplicates_by_rfc_message_id(self, v11_db: str) -> None:
        """Test finding duplicates by RFC Message-ID (migration scenario)."""

        # Simulate legacy database by recreating schema without UNIQUE constraint
        conn = sqlite3.connect(v11_db)
        timestamp = datetime.now().isoformat()

        # Recreate messages table without UNIQUE constraint
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                body_preview TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        # Insert duplicates
        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, thread_id, subject, from_addr,
             to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "<same@example.com>",
                "thread1",
                "Test",
                "from@example.com",
                "to@example.com",
                timestamp,
                timestamp,
                "archive1.mbox",
                0,
                1000,
            ),
        )

        conn.execute(
            """
            INSERT INTO messages
            (gmail_id, rfc_message_id, thread_id, subject, from_addr,
             to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg2",
                "<same@example.com>",
                "thread1",
                "Test",
                "from@example.com",
                "to@example.com",
                timestamp,
                timestamp,
                "archive2.mbox",
                0,
                1000,
            ),
        )

        conn.commit()
        conn.close()

        with DBManager(v11_db, validate_schema=False) as db:
            duplicates = db.find_duplicates()
            assert len(duplicates) > 0
            # Should find the duplicate RFC Message-ID
            # duplicates is list[tuple[rfc_message_id, list[gmail_ids]]]
            assert any(dup[0] == "<same@example.com>" for dup in duplicates)

    def test_remove_duplicate_records(self, v11_db: str) -> None:
        """Test removing duplicate records (migration scenario)."""

        # Recreate schema without UNIQUE constraint
        conn = sqlite3.connect(v11_db)
        timestamp = datetime.now().isoformat()

        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                body_preview TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        # Insert duplicates
        for i in range(2):
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr,
                 to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"msg{i}",
                    "<dup@example.com>",
                    "thread1",
                    "Test",
                    "from@example.com",
                    "to@example.com",
                    timestamp,
                    timestamp,
                    f"archive{i}.mbox",
                    0,
                    1000,
                ),
            )

        conn.commit()
        conn.close()

        with DBManager(v11_db, validate_schema=False) as db:
            # Find and remove duplicates
            duplicates = db.find_duplicates()
            removed = db.remove_duplicate_records(duplicates)

            assert removed > 0

            # Verify only one record remains
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE rfc_message_id = ?", ("<dup@example.com>",)
            )
            count = cursor.fetchone()[0]
            assert count == 1

    def test_remove_duplicates_creates_archive_run(self, v11_db: str) -> None:
        """Test that removing duplicates records in archive_runs (migration scenario)."""

        # Recreate schema without UNIQUE constraint
        conn = sqlite3.connect(v11_db)
        timestamp = datetime.now().isoformat()

        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                body_preview TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        for i in range(2):
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr,
                 to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"msg{i}",
                    "<dup@example.com>",
                    "thread1",
                    "Test",
                    "from@example.com",
                    "to@example.com",
                    timestamp,
                    timestamp,
                    "archive.mbox",
                    0,
                    1000,
                ),
            )

        conn.commit()
        conn.close()

        with DBManager(v11_db, validate_schema=False) as db:
            duplicates = db.find_duplicates()
            db.remove_duplicate_records(duplicates)

            # Verify archive_run entry
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM archive_runs WHERE operation_type = ?", ("deduplicate",)
            )
            count = cursor.fetchone()[0]
            assert count > 0


# ============================================================================
# Consolidation Tests
# ============================================================================


class TestConsolidation:
    """Tests for archive file consolidation operations."""

    def test_update_archive_location_single(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test updating archive location for a single message."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            # Update location
            db.update_archive_location(
                gmail_id=sample_message_data["gmail_id"],
                new_archive_file="new_archive.mbox",
                new_mbox_offset=5000,
                new_mbox_length=2000,
            )

            # Verify update
            message = db.get_message_by_gmail_id(sample_message_data["gmail_id"])
            assert message["archive_file"] == "new_archive.mbox"
            assert message["mbox_offset"] == 5000
            assert message["mbox_length"] == 2000

    def test_bulk_update_archive_locations(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test bulk updating archive locations for multiple messages."""

        with DBManager(v11_db) as db:
            # Insert multiple messages
            message_ids = []
            for i in range(5):
                data = sample_message_data.copy()
                data["gmail_id"] = f"msg{i}"
                data["rfc_message_id"] = f"<unique{i}@example.com>"
                data["mbox_offset"] = i * 1000
                db.record_archived_message(**data)
                message_ids.append(data["gmail_id"])

            # Bulk update
            updates = [
                {
                    "gmail_id": f"msg{i}",
                    "archive_file": "consolidated.mbox",
                    "mbox_offset": i * 2000,
                    "mbox_length": 1500,
                }
                for i in range(5)
            ]
            db.bulk_update_archive_locations(updates)

            # Verify all updates
            for i in range(5):
                message = db.get_message_by_gmail_id(f"msg{i}")
                assert message["archive_file"] == "consolidated.mbox"
                assert message["mbox_offset"] == i * 2000
                assert message["mbox_length"] == 1500

    def test_bulk_update_creates_archive_run(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that bulk update records in archive_runs."""

        with DBManager(v11_db) as db:
            # Insert messages
            for i in range(3):
                data = sample_message_data.copy()
                data["gmail_id"] = f"msg{i}"
                data["rfc_message_id"] = f"<unique{i}@example.com>"
                db.record_archived_message(**data)

            # Bulk update
            updates = [
                {
                    "gmail_id": f"msg{i}",
                    "archive_file": "new.mbox",
                    "mbox_offset": i * 1000,
                    "mbox_length": 1000,
                }
                for i in range(3)
            ]
            db.bulk_update_archive_locations(updates)

            # Verify archive_run entry
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM archive_runs WHERE operation_type = ?", ("consolidate",)
            )
            count = cursor.fetchone()[0]
            assert count > 0


# ============================================================================
# Integrity Tests
# ============================================================================


class TestDatabaseIntegrity:
    """Tests for database integrity verification and repair."""

    def test_verify_integrity_clean_database(self, v11_db: str) -> None:
        """Test integrity verification on a clean database."""

        with DBManager(v11_db) as db:
            issues = db.verify_database_integrity()
            assert len(issues) == 0

    def test_verify_integrity_invalid_offsets(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test detection of invalid mbox offsets."""

        with DBManager(v11_db) as db:
            # Insert message with negative offset
            data = sample_message_data.copy()
            data["mbox_offset"] = -100
            db.record_archived_message(**data)

            issues = db.verify_database_integrity()
            # Should detect invalid offset
            assert any("invalid" in issue.lower() and "offset" in issue.lower() for issue in issues)

    def test_verify_integrity_duplicate_message_ids(self, v11_db: str) -> None:
        """Test detection of duplicate RFC Message-IDs (migration scenario)."""

        # Recreate schema without UNIQUE constraint
        conn = sqlite3.connect(v11_db)
        timestamp = datetime.now().isoformat()

        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TEXT,
                body_preview TEXT,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        for i in range(2):
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr,
                 to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"msg{i}",
                    "<dup@example.com>",
                    "thread1",
                    "Test",
                    "from@example.com",
                    "to@example.com",
                    timestamp,
                    timestamp,
                    "archive.mbox",
                    0,
                    1000,
                ),
            )

        conn.commit()
        conn.close()

        with DBManager(v11_db, validate_schema=False) as db:
            issues = db.verify_database_integrity()
            # Should detect duplicate RFC Message-IDs
            assert any("duplicate" in issue.lower() for issue in issues)

    @patch("pathlib.Path.exists")
    def test_verify_integrity_missing_archive_files(
        self, mock_exists: Mock, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test detection of missing archive files."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)

            # Mock file system to report file doesn't exist
            mock_exists.return_value = False

            issues = db.verify_database_integrity()
            # Should detect missing archive file
            assert any("missing" in issue.lower() and "file" in issue.lower() for issue in issues)

    def test_get_messages_with_invalid_offsets(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test finding messages with invalid mbox offsets."""

        with DBManager(v11_db) as db:
            # Insert valid message
            data1 = sample_message_data.copy()
            data1["gmail_id"] = "msg1"
            data1["rfc_message_id"] = "<msg1@example.com>"
            data1["mbox_offset"] = 0
            db.record_archived_message(**data1)

            # Insert message with negative offset
            data2 = sample_message_data.copy()
            data2["gmail_id"] = "msg2"
            data2["rfc_message_id"] = "<msg2@example.com>"
            data2["mbox_offset"] = -100
            db.record_archived_message(**data2)

            # Insert message with negative length
            data3 = sample_message_data.copy()
            data3["gmail_id"] = "msg3"
            data3["rfc_message_id"] = "<msg3@example.com>"
            data3["mbox_length"] = -50
            db.record_archived_message(**data3)

            invalid = db.get_messages_with_invalid_offsets()

            # Should find msg2 and msg3
            assert len(invalid) == 2
            invalid_ids = {msg["gmail_id"] for msg in invalid}
            assert "msg2" in invalid_ids
            assert "msg3" in invalid_ids
            assert "msg1" not in invalid_ids


# ============================================================================
# Transaction Tests
# ============================================================================


class TestTransactions:
    """Tests for transaction handling."""

    def test_transaction_commit_on_success(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that transactions commit on success."""

        with DBManager(v11_db) as db:
            db.record_archived_message(**sample_message_data)
            # Context manager should auto-commit

        # Verify commit by opening new connection
        conn = sqlite3.connect(v11_db)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id = ?", (sample_message_data["gmail_id"],)
        )
        count = cursor.fetchone()[0]
        assert count == 1
        conn.close()

    def test_transaction_rollback_on_error(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test that transactions rollback on error."""

        try:
            with DBManager(v11_db) as db:
                db.record_archived_message(**sample_message_data)
                # Force an error
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback by opening new connection
        conn = sqlite3.connect(v11_db)
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        assert count == 0
        conn.close()

    def test_explicit_commit(self, v11_db: str, sample_message_data: dict[str, Any]) -> None:
        """Test explicit commit functionality."""

        db = DBManager(v11_db)
        db.record_archived_message(**sample_message_data)

        # Explicit commit
        db.commit()

        # Verify
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE gmail_id = ?", (sample_message_data["gmail_id"],)
        )
        count = cursor.fetchone()[0]
        assert count == 1

        db.close()

    def test_explicit_rollback(self, v11_db: str, sample_message_data: dict[str, Any]) -> None:
        """Test explicit rollback functionality."""

        db = DBManager(v11_db)
        db.record_archived_message(**sample_message_data)

        # Explicit rollback
        db.rollback()

        # Verify rollback
        cursor = db.conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        assert count == 0

        db.close()


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_record_message_with_null_optional_fields(self, v11_db: str) -> None:
        """Test recording message with minimal required fields."""

        with DBManager(v11_db) as db:
            # Only provide required fields
            db.record_archived_message(
                gmail_id="msg123",
                rfc_message_id="<msg123@example.com>",
                archive_file="archive.mbox",
                mbox_offset=0,
                mbox_length=1000,
            )

            # Verify record was created
            message = db.get_message_by_gmail_id("msg123")
            assert message is not None
            assert message["gmail_id"] == "msg123"

    def test_bulk_update_empty_list(self, v11_db: str) -> None:
        """Test bulk update with empty list."""

        with DBManager(v11_db) as db:
            # Should handle empty list gracefully
            db.bulk_update_archive_locations([])

    def test_bulk_update_partial_failure(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test bulk update with some invalid IDs."""

        with DBManager(v11_db) as db:
            # Insert one valid message
            db.record_archived_message(**sample_message_data)

            # Try to update valid and invalid IDs
            updates = [
                {
                    "gmail_id": sample_message_data["gmail_id"],
                    "archive_file": "new.mbox",
                    "mbox_offset": 0,
                    "mbox_length": 1000,
                },
                {
                    "gmail_id": "nonexistent",
                    "archive_file": "new.mbox",
                    "mbox_offset": 1000,
                    "mbox_length": 1000,
                },
            ]

            # Should handle partial failure gracefully
            # (either skip invalid or raise informative error)
            try:
                db.bulk_update_archive_locations(updates)
            except ValueError as e:
                # Acceptable to raise error for invalid IDs
                assert "nonexistent" in str(e)

    def test_find_duplicates_large_dataset(self, v11_db: str) -> None:
        """Test duplicate finding with large number of records."""

        # Insert many records
        conn = sqlite3.connect(v11_db)
        timestamp = datetime.now().isoformat()

        for i in range(1000):
            conn.execute(
                """
                INSERT INTO messages
                (gmail_id, rfc_message_id, thread_id, subject, from_addr,
                 to_addr, date, archived_timestamp, archive_file, mbox_offset, mbox_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    f"msg{i}",
                    f"<msg{i}@example.com>",
                    f"thread{i}",
                    f"Subject {i}",
                    "from@example.com",
                    "to@example.com",
                    timestamp,
                    timestamp,
                    "archive.mbox",
                    i * 1000,
                    1000,
                ),
            )

        conn.commit()
        conn.close()

        with DBManager(v11_db) as db:
            # Should handle large dataset efficiently
            duplicates = db.find_duplicates()
            assert len(duplicates) == 0

    def test_unicode_handling(self, v11_db: str, sample_message_data: dict[str, Any]) -> None:
        """Test handling of Unicode characters in message data."""

        with DBManager(v11_db) as db:
            # Use Unicode characters
            data = sample_message_data.copy()
            data["subject"] = "测试 Test こんにちは 🎉"
            data["from_addr"] = "user@例え.jp"
            data["body_preview"] = "Тест текст with émojis 🚀"

            db.record_archived_message(**data)

            # Verify Unicode is preserved
            message = db.get_message_by_gmail_id(data["gmail_id"])
            assert message["subject"] == data["subject"]
            assert message["from_addr"] == data["from_addr"]
            assert message["body_preview"] == data["body_preview"]

    def test_very_long_field_values(self, v11_db: str, sample_message_data: dict[str, Any]) -> None:
        """Test handling of very long field values."""

        with DBManager(v11_db) as db:
            # Use very long values
            data = sample_message_data.copy()
            data["subject"] = "A" * 10000
            data["body_preview"] = "B" * 50000

            db.record_archived_message(**data)

            # Verify long values are stored
            message = db.get_message_by_gmail_id(data["gmail_id"])
            assert len(message["subject"]) == 10000
            assert len(message["body_preview"]) == 50000

    def test_concurrent_access(self, v11_db: str) -> None:
        """Test handling of concurrent database access."""

        # Open two connections
        db1 = DBManager(v11_db)
        db2 = DBManager(v11_db)

        try:
            # Both should be able to read
            count1 = db1.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            count2 = db2.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            assert count1 == count2 == 0

        finally:
            db1.close()
            db2.close()


# ============================================================================
# Coverage Improvement Tests (TDD - Target 90%+)
# ============================================================================


class TestSchemaValidation:
    """Tests for schema validation error paths."""

    def test_missing_messages_table(self, temp_db_path: str) -> None:
        """Test schema validation when messages table is missing."""
        # Create database without messages table
        conn = sqlite3.connect(temp_db_path)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        # Should raise SchemaValidationError
        with pytest.raises(Exception) as exc_info:
            DBManager(temp_db_path, validate_schema=True)
        assert "messages" in str(exc_info.value).lower()

    def test_missing_required_columns(self, temp_db_path: str) -> None:
        """Test schema validation when required columns are missing."""
        # Create messages table without required columns
        conn = sqlite3.connect(temp_db_path)
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        # Should raise SchemaValidationError
        with pytest.raises(Exception) as exc_info:
            DBManager(temp_db_path, validate_schema=True)
        assert "missing columns" in str(exc_info.value).lower()


class TestExceptionHandling:
    """Tests for exception handling and error paths."""

    def test_init_with_nonexistent_file(self, temp_db_path: str) -> None:
        """Test handling of nonexistent database file."""
        import os

        # Make sure file doesn't exist
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

        # Should raise FileNotFoundError when auto_create=False
        with pytest.raises(FileNotFoundError):
            DBManager(temp_db_path, validate_schema=False, auto_create=False)


class TestRepairDatabaseCoverage:
    """Tests for repair_database method coverage."""

    def test_repair_database_with_no_issues(self, v11_db: str) -> None:
        """Test repair_database when there are no issues to fix."""
        with DBManager(v11_db, validate_schema=False) as db:
            # Dry run on clean database
            repairs = db.repair_database(dry_run=True)
            assert repairs["orphaned_fts_removed"] == 0
            assert repairs["missing_fts_added"] == 0

            # Actual run on clean database
            repairs = db.repair_database(dry_run=False)
            assert repairs["orphaned_fts_removed"] == 0
            assert repairs["missing_fts_added"] == 0


class TestGetMessageLocation:
    """Test get_message_location error paths."""

    def test_get_message_location_not_found(self, v11_db: str) -> None:
        """Test get_message_location with nonexistent rfc_message_id."""
        with DBManager(v11_db) as db:
            result = db.get_message_location("nonexistent")
            assert result is None


class TestUpdateArchiveLocation:
    """Test update_archive_location error paths."""

    def test_update_archive_location_not_found(self, v11_db: str) -> None:
        """Test update_archive_location with nonexistent gmail_id."""
        with DBManager(v11_db) as db:
            # Should not raise exception, just update nothing
            db.update_archive_location(
                gmail_id="nonexistent",
                new_archive_file="new.mbox",
                new_mbox_offset=0,
                new_mbox_length=1000,
            )


class TestRemoveDuplicateRecords:
    """Test remove_duplicate_records error paths."""

    def test_remove_duplicates_empty_list(self, v11_db: str) -> None:
        """Test remove_duplicate_records with empty list."""
        with DBManager(v11_db) as db:
            # Should handle empty list gracefully
            removed = db.remove_duplicate_records([])
            assert removed == 0


class TestTransactionContextManager:
    """Test transaction context manager error handling."""

    def test_transaction_exception_handling(self, v11_db: str) -> None:
        """Test transaction rollback on exception."""
        with DBManager(v11_db) as db:
            try:
                with db._transaction():
                    # Insert a record
                    db.conn.execute(
                        """INSERT INTO messages
                        (gmail_id, rfc_message_id, archived_timestamp, archive_file,
                         mbox_offset, mbox_length)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            "test_exc",
                            "<test_exc@example.com>",
                            "2024-01-01T00:00:00",
                            "test.mbox",
                            0,
                            1000,
                        ),
                    )
                    # Force an exception
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Expected

            # Verify the record was rolled back
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE gmail_id = ?", ("test_exc",)
            )
            assert cursor.fetchone()[0] == 0


# ============================================================================
# Session Management Tests (Coverage for lines 1120-1182)
# ============================================================================


class TestSessionManagement:
    """Tests for archive session management methods."""

    def test_get_session_returns_session_when_found(self, v11_db: str) -> None:
        """Test get_session returns session dict when session exists."""
        with DBManager(v11_db) as db:
            # Create a session first
            session_id = "test-session-123"
            target_file = "archive.mbox"
            query = "before:2024/01/01"
            message_ids = ["msg1", "msg2", "msg3"]

            db.create_session(
                session_id=session_id,
                target_file=target_file,
                query=query,
                message_ids=message_ids,
                compression="gzip",
                account_id="default",
            )

            # Get the session
            session = db.get_session(session_id)

            assert session is not None
            assert session["session_id"] == session_id
            assert session["target_file"] == target_file
            assert session["query"] == query
            assert session["message_ids"] == message_ids  # Should be deserialized from JSON
            assert session["status"] == "in_progress"
            assert session["total_count"] == 3
            assert session["processed_count"] == 0

    def test_get_session_returns_none_when_not_found(self, v11_db: str) -> None:
        """Test get_session returns None when session doesn't exist."""
        with DBManager(v11_db) as db:
            session = db.get_session("nonexistent-session-id")
            assert session is None

    def test_get_session_by_file_returns_in_progress_session(self, v11_db: str) -> None:
        """Test get_session_by_file returns the most recent in_progress session."""
        with DBManager(v11_db) as db:
            target_file = "archive.mbox"

            # Create an in_progress session
            db.create_session(
                session_id="session-1",
                target_file=target_file,
                query="query1",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )

            # Get the session by file
            session = db.get_session_by_file(target_file)

            assert session is not None
            assert session["session_id"] == "session-1"
            assert session["target_file"] == target_file
            assert session["message_ids"] == ["msg1"]

    def test_get_session_by_file_returns_none_when_no_in_progress(self, v11_db: str) -> None:
        """Test get_session_by_file returns None when no in_progress session exists."""
        with DBManager(v11_db) as db:
            # Create and complete a session
            db.create_session(
                session_id="session-1",
                target_file="archive.mbox",
                query="query1",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )
            db.complete_session("session-1")

            # Now there's no in_progress session for this file
            session = db.get_session_by_file("archive.mbox")
            assert session is None

    def test_get_session_by_file_returns_none_for_different_file(self, v11_db: str) -> None:
        """Test get_session_by_file returns None for different target file."""
        with DBManager(v11_db) as db:
            # Create session for one file
            db.create_session(
                session_id="session-1",
                target_file="archive1.mbox",
                query="query1",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )

            # Query for different file
            session = db.get_session_by_file("archive2.mbox")
            assert session is None

    def test_get_all_partial_sessions_returns_all_in_progress(self, v11_db: str) -> None:
        """Test get_all_partial_sessions returns all in_progress sessions."""
        with DBManager(v11_db) as db:
            # Create multiple in_progress sessions
            for i in range(3):
                db.create_session(
                    session_id=f"session-{i}",
                    target_file=f"archive{i}.mbox",
                    query=f"query{i}",
                    message_ids=[f"msg{i}a", f"msg{i}b"],
                    compression="gzip",
                    account_id="default",
                )

            # Get all partial sessions
            sessions = db.get_all_partial_sessions()

            assert len(sessions) == 3
            session_ids = {s["session_id"] for s in sessions}
            assert session_ids == {"session-0", "session-1", "session-2"}

            # Verify message_ids are deserialized
            for session in sessions:
                assert isinstance(session["message_ids"], list)
                assert len(session["message_ids"]) == 2

    def test_get_all_partial_sessions_excludes_completed(self, v11_db: str) -> None:
        """Test get_all_partial_sessions excludes completed sessions."""
        with DBManager(v11_db) as db:
            # Create sessions with different statuses
            db.create_session(
                session_id="session-in-progress",
                target_file="archive1.mbox",
                query="query1",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )
            db.create_session(
                session_id="session-completed",
                target_file="archive2.mbox",
                query="query2",
                message_ids=["msg2"],
                compression=None,
                account_id="default",
            )
            db.complete_session("session-completed")

            # Get all partial sessions
            sessions = db.get_all_partial_sessions()

            assert len(sessions) == 1
            assert sessions[0]["session_id"] == "session-in-progress"

    def test_get_all_partial_sessions_returns_empty_when_none(self, v11_db: str) -> None:
        """Test get_all_partial_sessions returns empty list when no sessions exist."""
        with DBManager(v11_db) as db:
            sessions = db.get_all_partial_sessions()
            assert sessions == []

    def test_get_all_partial_sessions_ordered_by_started_at_desc(self, v11_db: str) -> None:
        """Test get_all_partial_sessions returns sessions ordered by started_at DESC."""
        import time

        with DBManager(v11_db) as db:
            # Create sessions with slight delay to ensure different timestamps
            for i in range(3):
                db.create_session(
                    session_id=f"session-{i}",
                    target_file=f"archive{i}.mbox",
                    query=f"query{i}",
                    message_ids=[f"msg{i}"],
                    compression=None,
                    account_id="default",
                )
                time.sleep(0.01)  # Small delay to ensure different timestamps

            sessions = db.get_all_partial_sessions()

            # Most recent should be first (session-2)
            assert sessions[0]["session_id"] == "session-2"
            assert sessions[-1]["session_id"] == "session-0"

    def test_abort_session_changes_status_to_aborted(self, v11_db: str) -> None:
        """Test abort_session marks session as aborted."""
        with DBManager(v11_db) as db:
            # Create a session
            db.create_session(
                session_id="session-to-abort",
                target_file="archive.mbox",
                query="query",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )

            # Abort the session
            db.abort_session("session-to-abort")

            # Verify status changed
            session = db.get_session("session-to-abort")
            assert session is not None
            assert session["status"] == "aborted"

    def test_delete_session_removes_session(self, v11_db: str) -> None:
        """Test delete_session removes session from database."""
        with DBManager(v11_db) as db:
            # Create a session
            db.create_session(
                session_id="session-to-delete",
                target_file="archive.mbox",
                query="query",
                message_ids=["msg1"],
                compression=None,
                account_id="default",
            )

            # Delete the session
            db.delete_session("session-to-delete")

            # Verify session is gone
            session = db.get_session("session-to-delete")
            assert session is None

    def test_delete_messages_for_file_removes_all_messages(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test delete_messages_for_file removes all messages for a file."""
        with DBManager(v11_db) as db:
            # Insert messages for target file
            for i in range(3):
                data = sample_message_data.copy()
                data["gmail_id"] = f"msg{i}"
                data["rfc_message_id"] = f"<msg{i}@example.com>"
                data["archive_file"] = "target.mbox"
                db.record_archived_message(**data)

            # Insert message for different file
            other_data = sample_message_data.copy()
            other_data["gmail_id"] = "msg_other"
            other_data["rfc_message_id"] = "<msg_other@example.com>"
            other_data["archive_file"] = "other.mbox"
            db.record_archived_message(**other_data)

            # Delete messages for target file
            deleted = db.delete_messages_for_file("target.mbox")

            assert deleted == 3

            # Verify messages are gone from target file
            messages = db.get_all_messages_for_archive("target.mbox")
            assert len(messages) == 0

            # Verify other file's messages still exist
            messages = db.get_all_messages_for_archive("other.mbox")
            assert len(messages) == 1

    def test_delete_messages_for_file_returns_zero_when_none(self, v11_db: str) -> None:
        """Test delete_messages_for_file returns 0 when no messages exist."""
        with DBManager(v11_db) as db:
            deleted = db.delete_messages_for_file("nonexistent.mbox")
            assert deleted == 0


# ============================================================================
# Exception Handling Tests
# ============================================================================


class TestDBManagerExceptionHandling:
    """Tests for exception handling in DBManager methods.

    These tests cover the exception wrapping paths that convert
    low-level SQLite errors into DBManagerError.
    """

    def test_delete_message_raises_db_manager_error_on_failure(self, v11_db: str) -> None:
        """Test delete_message wraps exceptions in DBManagerError.

        Covers lines 598-599: Exception handler in delete_message.
        """
        from gmailarchiver.data.db_manager import DBManagerError

        with DBManager(v11_db) as db:
            # Mock conn.execute to raise an error
            with patch.object(db, "conn") as mock_conn:
                mock_conn.execute.side_effect = sqlite3.OperationalError("database is locked")

                with pytest.raises(DBManagerError) as exc_info:
                    db.delete_message("msg123")

                assert "Failed to delete message msg123" in str(exc_info.value)
                assert "database is locked" in str(exc_info.value)

    def test_remove_duplicate_records_raises_db_manager_error_on_failure(self, v11_db: str) -> None:
        """Test remove_duplicate_records wraps exceptions in DBManagerError.

        Covers lines 644-645: Exception handler in remove_duplicate_records.
        """
        from gmailarchiver.data.db_manager import DBManagerError

        with DBManager(v11_db) as db:
            # Mock conn.execute to raise an error during deletion
            with patch.object(db, "conn") as mock_conn:
                mock_conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")

                duplicates = [("rfc123", ["msg1", "msg2"])]
                with pytest.raises(DBManagerError) as exc_info:
                    db.remove_duplicate_records(duplicates)

                assert "Failed to remove duplicate records" in str(exc_info.value)

    def test_update_archive_location_raises_db_manager_error_on_failure(self, v11_db: str) -> None:
        """Test update_archive_location wraps exceptions in DBManagerError.

        Covers lines 681-682: Exception handler in update_archive_location.
        """
        from gmailarchiver.data.db_manager import DBManagerError

        with DBManager(v11_db) as db:
            # Mock conn.execute to raise an error
            with patch.object(db, "conn") as mock_conn:
                mock_conn.execute.side_effect = sqlite3.IntegrityError("constraint violation")

                with pytest.raises(DBManagerError) as exc_info:
                    db.update_archive_location("msg123", "new.mbox", 1000, 500)

                assert "Failed to update location for msg123" in str(exc_info.value)

    def test_bulk_update_archive_locations_raises_db_manager_error_on_failure(
        self, v11_db: str
    ) -> None:
        """Test bulk_update_archive_locations wraps exceptions in DBManagerError.

        Covers lines 720-721: Exception handler in bulk_update_archive_locations.
        """
        from gmailarchiver.data.db_manager import DBManagerError

        with DBManager(v11_db) as db:
            # Mock conn.executemany to raise an error
            with patch.object(db, "conn") as mock_conn:
                mock_conn.executemany.side_effect = sqlite3.DatabaseError("no such table: messages")

                updates = [
                    {
                        "gmail_id": "msg1",
                        "archive_file": "new.mbox",
                        "mbox_offset": 0,
                        "mbox_length": 100,
                    }
                ]
                with pytest.raises(DBManagerError) as exc_info:
                    db.bulk_update_archive_locations(updates)

                assert "Failed to bulk update locations" in str(exc_info.value)

    def test_record_archived_message_wraps_non_integrity_exceptions(
        self, v11_db: str, sample_message_data: dict[str, Any]
    ) -> None:
        """Test record_archived_message wraps non-IntegrityError exceptions.

        Covers lines 436-437: Exception handler for non-IntegrityError.
        IntegrityError is re-raised directly, other exceptions are wrapped.
        """
        from gmailarchiver.data.db_manager import DBManagerError

        with DBManager(v11_db) as db:
            # Mock conn.execute to raise a non-IntegrityError
            with patch.object(db, "conn") as mock_conn:
                mock_conn.execute.side_effect = sqlite3.OperationalError(
                    "database disk image is malformed"
                )

                with pytest.raises(DBManagerError) as exc_info:
                    db.record_archived_message(**sample_message_data)

                assert "Failed to record message" in str(exc_info.value)
                assert "malformed" in str(exc_info.value)
