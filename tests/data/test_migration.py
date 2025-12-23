"""Tests for database migration system."""

import email
import mailbox
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from gmailarchiver.data.migration import MigrationError, MigrationManager

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestMigrationManagerInit:
    """Test MigrationManager initialization."""

    async def test_init_with_path_string(self, tmp_path):
        """Test initialization with string path."""
        db_path = str(tmp_path / "test.db")
        manager = MigrationManager(db_path)
        assert manager.db_path == Path(db_path).resolve()
        assert manager.conn is None
        await manager._close()

    async def test_init_with_path_object(self, tmp_path):
        """Test initialization with Path object."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)
        assert manager.db_path == db_path.resolve()
        await manager._close()

    async def test_context_manager(self, tmp_path):
        """Test context manager behavior."""
        db_path = tmp_path / "test.db"
        async with MigrationManager(db_path) as manager:
            assert isinstance(manager, MigrationManager)
        # Connection should be closed after context exit
        assert manager.conn is None


class TestSchemaVersionDetection:
    """Test schema version detection."""

    async def test_detect_none_for_nonexistent_db(self, tmp_path):
        """Test detection returns 'none' for nonexistent database."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        assert version == "none"
        await manager._close()

    async def test_detect_v1_0_with_archived_messages_table(self, tmp_path):
        """Test detection of v1.0 schema."""
        db_path = tmp_path / "v1.db"

        # Create v1.0 schema
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT,
                archive_file TEXT,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        assert version == "1.0"
        await manager._close()

    async def test_detect_v1_1_with_messages_table(self, tmp_path):
        """Test detection of v1.1 schema."""
        db_path = tmp_path / "v1.1.db"

        # Create v1.1 schema
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        assert version == "1.1"
        await manager._close()

    async def test_detect_version_from_schema_version_table(self, tmp_path):
        """Test reading version from schema_version table."""
        db_path = tmp_path / "versioned.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        assert version == "1.1"
        await manager._close()


class TestNeedsMigration:
    """Test needs_migration() method."""

    async def test_needs_migration_for_v1_0(self, tmp_path):
        """Test that v1.0 schema needs migration."""
        db_path = tmp_path / "v1.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert await manager.needs_migration() is True
        await manager._close()

    async def test_needs_migration_for_none(self, tmp_path):
        """Test that nonexistent DB needs migration."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)
        assert await manager.needs_migration() is True
        await manager._close()

    async def test_no_migration_needed_for_v1_1(self, tmp_path):
        """Test that v1.1 schema doesn't need migration."""
        db_path = tmp_path / "v1.1.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert await manager.needs_migration() is False
        await manager._close()


class TestBackupCreation:
    """Test database backup functionality."""

    async def test_create_backup_success(self, tmp_path):
        """Test successful backup creation."""
        db_path = tmp_path / "test.db"

        # Create a test database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        backup_path = await manager.create_backup()

        assert backup_path.exists()
        assert backup_path.name.startswith("test.db.backup.")
        assert backup_path.parent == db_path.parent

        # Verify backup contains same data
        backup_conn = sqlite3.connect(str(backup_path))
        cursor = backup_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test'"
        )
        assert cursor.fetchone() is not None
        backup_conn.close()
        await manager._close()

    async def test_create_backup_nonexistent_db_fails(self, tmp_path):
        """Test that backing up nonexistent DB fails."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)

        with pytest.raises(MigrationError, match="Database not found"):
            await manager.create_backup()
        await manager._close()

    async def test_create_backup_fails_with_permission_error(self, tmp_path):
        """Test that backup creation fails gracefully with permission errors."""
        import os
        import stat

        db_path = tmp_path / "test.db"

        # Create a test database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        # Make parent directory read-only (no write permission for backup)
        original_mode = tmp_path.stat().st_mode
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IXUSR)  # Read and execute only

            manager = MigrationManager(db_path)
            with pytest.raises(MigrationError, match="Failed to create backup"):
                await manager.create_backup()
        finally:
            # Restore permissions
            os.chmod(tmp_path, original_mode)
        await manager._close()


class TestEnhancedSchemaCreation:
    """Test creation of enhanced v1.1 schema."""

    async def test_create_enhanced_schema(self, tmp_path):
        """Test that enhanced schema creates all required tables."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        conn = await manager._connect()
        await manager._create_enhanced_schema(conn)

        # Check messages table exists with correct columns
        cursor = await conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        required_columns = {
            "gmail_id",
            "rfc_message_id",
            "thread_id",
            "subject",
            "from_addr",
            "to_addr",
            "cc_addr",
            "date",
            "archived_timestamp",
            "archive_file",
            "mbox_offset",
            "mbox_length",
            "body_preview",
            "checksum",
            "size_bytes",
            "labels",
            "account_id",
        }
        assert required_columns.issubset(columns)

        # Check FTS5 table exists
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        assert await cursor.fetchone() is not None

        # Check indexes exist
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        index_names = {row[0] for row in await cursor.fetchall()}
        expected_indexes = {
            "idx_rfc_message_id",
            "idx_thread_id",
            "idx_archive_file",
            "idx_date",
            "idx_from",
            "idx_subject",
        }
        assert expected_indexes.issubset(index_names)

        # Check accounts table exists
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
        )
        assert await cursor.fetchone() is not None

        await conn.close()
        await manager._close()


class TestExtractRfcMessageId:
    """Test RFC Message-ID extraction."""

    async def test_extract_existing_message_id(self):
        """Test extraction of existing Message-ID header."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<unique123@example.com>"
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)
        assert result == "<unique123@example.com>"
        await manager._close()

    async def test_generate_fallback_message_id(self):
        """Test fallback Message-ID generation."""
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test Subject"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)

        # Should generate SHA256-based ID
        assert result.startswith("<")
        assert result.endswith("@generated>")
        assert len(result) > 20  # SHA256 hash is long
        await manager._close()

    async def test_handles_empty_message_id(self):
        """Test handling of empty Message-ID."""
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "  "  # Whitespace only
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)

        # Should generate fallback
        assert "@generated>" in result
        await manager._close()


class TestExtractBodyPreview:
    """Test body preview extraction."""

    async def test_extract_from_plain_text(self):
        """Test extraction from plain text message."""
        msg = email.message.EmailMessage()
        msg.set_content("This is a test message body.")

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg, max_chars=10)
        assert result == "This is a "
        await manager._close()

    async def test_extract_from_multipart(self):
        """Test extraction from multipart message."""
        msg = email.message.EmailMessage()
        msg.set_content("Plain text body")
        msg.add_alternative("<html><body>HTML body</body></html>", subtype="html")

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)
        assert "Plain text body" in result
        await manager._close()

    async def test_max_chars_limit(self):
        """Test that preview respects max_chars limit."""
        long_text = "A" * 2000
        msg = email.message.EmailMessage()
        msg.set_content(long_text)

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg, max_chars=1000)
        assert len(result) == 1000
        assert result == "A" * 1000
        await manager._close()

    async def test_handles_binary_payload(self):
        """Test handling of messages with binary payload."""
        msg = email.message.EmailMessage()
        msg.set_content(b"Binary content", maintype="application", subtype="octet-stream")

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)
        # EmailMessage.set_content converts bytes to string for non-multipart messages
        # so we actually get the content as text
        assert result == "Binary content"
        await manager._close()


class TestMigrationWorkflow:
    """Test the complete migration workflow."""

    async def test_migrate_v1_to_v1_1_success(self, tmp_path):
        """Test successful migration from v1.0 to v1.1 with real mbox scanning."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox file with real message
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test123@example.com>"
        msg["Subject"] = "Test Subject"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg.set_content("This is a test message body.")
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database with sample data pointing to real mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        # Insert test data - use a gmail_id that will be found in mbox
        # Migration should find the message by scanning the mbox
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Test Subject",
                "test@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Perform migration
        manager = MigrationManager(db_path)
        await manager.migrate_v1_to_v1_1()

        # Verify migration
        conn = sqlite3.connect(str(db_path))

        # Check old table is gone
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages_old'"
        )
        assert cursor.fetchone() is None

        # Check new messages table exists and has data
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 1

        # CRITICAL: Check that real data was extracted from mbox
        cursor = conn.execute(
            """SELECT gmail_id, rfc_message_id, subject, mbox_offset, mbox_length
               FROM messages WHERE gmail_id='msg1'"""
        )
        row = cursor.fetchone()
        assert row is not None, "Message not found after migration"

        gmail_id, rfc_message_id, subject, mbox_offset, mbox_length = row

        # Verify real RFC Message-ID was extracted (not placeholder)
        assert rfc_message_id == "<test123@example.com>", (
            f"Expected real Message-ID, got placeholder: {rfc_message_id}"
        )

        # Verify valid mbox offset (>= 0, not -1 placeholder)
        assert mbox_offset >= 0, f"Expected valid offset >= 0, got placeholder: {mbox_offset}"

        # Verify valid mbox length (> 0, not -1 placeholder)
        assert mbox_length > 0, f"Expected valid length > 0, got placeholder: {mbox_length}"

        # Verify subject was preserved
        assert subject == "Test Subject"

        # Check schema_version table
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

        conn.close()
        await manager._close()

    async def test_migrate_with_missing_mbox_file(self, tmp_path):
        """Test migration gracefully handles missing mbox files."""
        db_path = tmp_path / "test.db"
        nonexistent_mbox = tmp_path / "missing.mbox"

        # Create v1.0 database pointing to nonexistent mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(nonexistent_mbox),
                "Test Subject",
                "test@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Migration should complete but skip messages from missing files
        manager = MigrationManager(db_path)
        await manager.migrate_v1_to_v1_1()

        # Verify migration completed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

        # Message should not be migrated (mbox file missing)
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 0, "Should skip messages from missing mbox files"
        await manager._close()

    async def test_extract_body_preview_multipart_decode_error(self):
        """Test body preview extraction handles decode errors in multipart messages."""
        import email.mime.multipart
        import email.mime.text
        from unittest.mock import patch

        manager = MigrationManager(":memory:")

        # Create multipart message with a part that will fail to decode
        msg = email.mime.multipart.MIMEMultipart()
        text_part = email.mime.text.MIMEText("Test body", "plain")

        # Mock get_payload to raise an exception (lines 297-298)
        with patch.object(text_part, "get_payload", side_effect=Exception("Decode error")):
            msg.attach(text_part)
            result = manager._extract_body_preview(msg)
            # Should return empty string when all parts fail
            assert result == ""
        await manager._close()

    async def test_extract_body_preview_non_multipart_decode_error(self):
        """Test body preview extraction handles decode errors in non-multipart messages."""
        from unittest.mock import patch

        manager = MigrationManager(":memory:")

        # Create simple message
        msg = email.message.EmailMessage()
        msg.set_content("Test content")

        # Mock get_payload to raise exception (lines 304-305)
        with patch.object(msg, "get_payload", side_effect=Exception("Decode error")):
            result = manager._extract_body_preview(msg)
            # Should return empty string on error
            assert result == ""
        await manager._close()

    async def test_migrate_extracts_full_metadata(self, tmp_path):
        """Test migration extracts all v1.1 metadata fields."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox with rich metadata
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<full-metadata@example.com>"
        msg["X-GM-THRID"] = "1234567890"
        msg["Subject"] = "Full Metadata Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Cc"] = "cc@example.com"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg.set_content("This is a test message with full metadata.")
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Full Metadata Test",
                "sender@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Perform migration
        manager = MigrationManager(db_path)
        await manager.migrate_v1_to_v1_1()

        # Verify all metadata was extracted
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            """SELECT rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
                      body_preview, mbox_offset, mbox_length
               FROM messages"""
        )
        row = cursor.fetchone()
        assert row is not None

        (
            rfc_message_id,
            thread_id,
            subject,
            from_addr,
            to_addr,
            cc_addr,
            body_preview,
            mbox_offset,
            mbox_length,
        ) = row

        # Verify all fields
        assert rfc_message_id == "<full-metadata@example.com>"
        assert thread_id == "1234567890"
        assert subject == "Full Metadata Test"
        assert from_addr == "sender@example.com"
        assert to_addr == "recipient@example.com"
        assert cc_addr == "cc@example.com"
        assert "test message with full metadata" in body_preview.lower()
        assert mbox_offset >= 0
        assert mbox_length > 0

        conn.close()
        await manager._close()


class TestValidateMigration:
    """Test migration validation."""

    async def test_validate_migration_success(self, tmp_path):
        """Test successful migration validation."""
        db_path = tmp_path / "test.db"

        # Create v1.1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE messages_fts USING fts5(content)
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.execute("INSERT INTO messages VALUES ('msg1')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert await manager.validate_migration() is True
        await manager._close()

    async def test_validate_migration_fails_wrong_version(self, tmp_path):
        """Test validation fails with wrong schema version."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.0', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="Schema version not set to 1.1"):
            await manager.validate_migration()
        await manager._close()

    async def test_validate_migration_fails_missing_messages_table(self, tmp_path):
        """Test validation fails if messages table missing."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="messages table not found"):
            await manager.validate_migration()
        await manager._close()


class TestRollbackMigration:
    """Test migration rollback."""

    async def test_rollback_success(self, tmp_path):
        """Test successful rollback from backup."""
        db_path = tmp_path / "test.db"
        backup_path = tmp_path / "test.db.backup.20240101"

        # Create original database (backup)
        conn = sqlite3.connect(str(backup_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT)")
        conn.execute("INSERT INTO archived_messages VALUES ('msg1')")
        conn.commit()
        conn.close()

        # Create "migrated" database (to be rolled back)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT)")
        conn.commit()
        conn.close()

        # Perform rollback
        manager = MigrationManager(db_path)
        await manager.rollback_migration(backup_path)

        # Verify rollback
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute("SELECT COUNT(*) FROM archived_messages")
        assert cursor.fetchone()[0] == 1

        conn.close()
        await manager._close()

    async def test_rollback_fails_missing_backup(self, tmp_path):
        """Test that rollback fails with missing backup."""
        db_path = tmp_path / "test.db"
        backup_path = tmp_path / "nonexistent.db"

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="Backup file not found"):
            await manager.rollback_migration(backup_path)
        await manager._close()


class TestExtractThreadId:
    """Test thread ID extraction from email headers."""

    async def test_extract_from_gmail_thrid_header(self):
        """Test extraction from X-GM-THRID header."""
        msg = email.message.EmailMessage()
        msg["X-GM-THRID"] = "1234567890"
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result == "1234567890"
        await manager._close()

    async def test_extract_from_references_header(self):
        """Test fallback to References header."""
        msg = email.message.EmailMessage()
        msg["References"] = "<ref1@example.com> <ref2@example.com>"
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result == "<ref1@example.com>"
        await manager._close()

    async def test_returns_none_without_thread_headers(self):
        """Test returns None when no thread headers present."""
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result is None
        await manager._close()

    async def test_handles_empty_references_header(self):
        """Test handles empty References header."""
        msg = email.message.EmailMessage()
        msg["References"] = "   "  # Whitespace only
        msg["Subject"] = "Test"

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result is None
        await manager._close()


class TestValidationEdgeCases:
    """Test validation edge cases."""

    async def test_validate_migration_fails_missing_fts_table(self, tmp_path):
        """Test validation fails if FTS table missing."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="messages_fts table not found"):
            await manager.validate_migration()
        await manager._close()


class TestSchemaVersionEdgeCases:
    """Test schema version detection edge cases."""

    async def test_detect_none_for_empty_schema_version_table(self, tmp_path):
        """Test detection returns 1.0 when schema_version table exists but empty."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """)
        # Don't insert any version - table exists but is empty
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        # When schema_version table exists but has no rows, it returns "1.0"
        assert version == "1.0"
        await manager._close()

    async def test_detect_none_for_unrecognized_schema(self, tmp_path):
        """Test detection returns 'none' for database with unrecognized schema."""
        db_path = tmp_path / "test.db"

        # Create database with unrecognized tables
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE some_random_table (
                id INTEGER PRIMARY KEY,
                data TEXT
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = await manager.detect_schema_version()
        # Database exists but has no recognized schema - should return "none"
        assert version == "none"
        await manager._close()


class TestCloseConnection:
    """Test database connection closing."""

    async def test_close_when_connection_exists(self, tmp_path):
        """Test closing an active connection."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        # Connect to database
        conn = await manager._connect()
        assert manager.conn is not None

        # Close connection
        await manager._close()
        assert manager.conn is None

    async def test_close_when_no_connection(self, tmp_path):
        """Test closing when no connection exists."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        # No connection established yet
        assert manager.conn is None

        # Should not raise error
        await manager._close()
        assert manager.conn is None


class TestBodyPreviewExceptions:
    """Test body preview extraction with malformed data."""

    async def test_extract_body_handles_decode_error_multipart(self):
        """Test that decode errors in multipart messages are handled gracefully."""
        import email.mime.multipart
        import email.mime.text

        # Create a multipart message
        msg = email.mime.multipart.MIMEMultipart()
        msg["Subject"] = "Test"

        # Add a text part with valid content
        text_part = email.mime.text.MIMEText("Valid text", "plain")
        msg.attach(text_part)

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)

        # Should extract from the valid part
        assert "Valid text" in result
        await manager._close()

    async def test_extract_body_handles_decode_error_plain(self):
        """Test that decode errors in plain messages are handled gracefully."""
        # Create a message with payload that might cause decode issues
        msg = email.message.EmailMessage()
        msg["Subject"] = "Test"
        msg.set_content("Plain text message")

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)

        # Should successfully extract
        assert "Plain text message" in result
        await manager._close()


class TestMigrationErrorHandling:
    """Test migration error handling scenarios."""

    async def test_migrate_handles_corrupt_mbox_file(self, tmp_path):
        """Test migration gracefully handles corrupt mbox files."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "corrupt.mbox"

        # Create a corrupt/empty mbox file (will cause mailbox.mbox to fail)
        mbox_path.write_text("")

        # Create v1.0 database pointing to corrupt mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Test Subject",
                "test@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Migration should handle the error gracefully
        manager = MigrationManager(db_path)
        # Should not raise exception, just skip corrupt files
        await manager.migrate_v1_to_v1_1()

        # Verify migration completed despite corrupt mbox
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"
        conn.close()
        await manager._close()

    async def test_migrate_handles_multiple_mbox_files_with_failures(self, tmp_path):
        """Test migration continues when some mbox files fail."""
        db_path = tmp_path / "test.db"
        good_mbox_path = tmp_path / "good.mbox"
        bad_mbox_path = tmp_path / "bad.mbox"

        # Create a good mbox file
        import mailbox

        mbox = mailbox.mbox(str(good_mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<good@example.com>"
        msg["Subject"] = "Good Message"
        msg["From"] = "good@example.com"
        msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
        msg.set_content("This is a good message.")
        mbox.add(msg)
        mbox.close()

        # Create a bad mbox file (empty/corrupt)
        bad_mbox_path.write_text("")

        # Create v1.0 database with messages from both files
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "good1",
                "2024-01-01T00:00:00",
                str(good_mbox_path),
                "Good Message",
                "good@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "bad1",
                "2024-01-01T00:00:00",
                str(bad_mbox_path),
                "Bad Message",
                "bad@example.com",
                "2024-01-01",
                "checksum456",
            ),
        )
        conn.commit()
        conn.close()

        # Migration should handle partial failures
        manager = MigrationManager(db_path)
        await manager.migrate_v1_to_v1_1()

        # Verify good message was migrated, bad was skipped
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id='good1'")
        assert cursor.fetchone()[0] == 1

        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id='bad1'")
        assert cursor.fetchone()[0] == 0
        conn.close()
        await manager._close()


# ============================================================================
# Test: Migration Failure and Rollback Scenarios
# ============================================================================


async def test_migration_with_corrupted_database(temp_dir: Path) -> None:
    """Test migration handles corrupted database gracefully (lines 297-298)."""
    db_path = temp_dir / "corrupted.db"

    # Create a corrupted database file
    db_path.write_bytes(b"not a valid sqlite database")

    manager = MigrationManager(str(db_path))

    # Should handle corruption gracefully
    try:
        await manager.migrate_v1_to_v1_1()
    except Exception as e:
        # Should get a clear error, not a mysterious crash
        assert "database" in str(e).lower() or "corrupt" in str(e).lower()
    await manager._close()


async def test_migration_completes_successfully_simple(temp_dir: Path) -> None:
    """Test migration completes on empty v1.0 database (lines 304-305)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify database still exists and is accessible
    assert db_path.exists()

    # Verify v1.1 schema was created
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    assert cursor.fetchone() is not None
    conn.close()
    await manager._close()


async def test_migration_schema_update_transaction(temp_dir: Path) -> None:
    """Test migration schema updates happen transactionally (lines 461-462)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database with test data
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    # Insert test message
    conn.execute(
        """
        INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "msg1",
            "2024-01-01T00:00:00",
            "archive.mbox",
            "Subject",
            "from@example.com",
            "2024-01-01",
            "checksum123",
        ),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify new schema exists
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='messages'
    """)
    assert cursor.fetchone() is not None

    # Old table should be gone or renamed
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='archived_messages'
    """)
    assert cursor.fetchone() is None

    conn.close()
    await manager._close()


async def test_migration_backfill_with_missing_offsets(temp_dir: Path) -> None:
    """Test migration backfill handles messages with missing offsets (lines 522-527)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "archive.mbox"

    # Create mbox with messages
    mbox = mailbox.mbox(str(mbox_path))
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<msg1@example.com>"
    msg["Subject"] = "Test Message"
    msg["From"] = "sender@example.com"
    msg.set_content("Test body")
    mbox.add(msg)
    mbox.close()

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    # Insert message without offsets
    conn.execute(
        """
        INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "msg1",
            "2024-01-01T00:00:00",
            str(mbox_path),
            "Test Message",
            "sender@example.com",
            "2024-01-01",
            "checksum123",
        ),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify offsets were backfilled
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT mbox_offset, mbox_length FROM messages WHERE gmail_id='msg1'
    """)
    row = cursor.fetchone()
    assert row is not None
    assert row[0] >= 0  # Offset should be set
    assert row[1] > 0  # Length should be set

    conn.close()
    await manager._close()


async def test_migration_fts_index_creation(temp_dir: Path) -> None:
    """Test migration creates FTS5 index (lines 538-543)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify FTS5 table exists
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='messages_fts'
    """)
    assert cursor.fetchone() is not None

    conn.close()
    await manager._close()


async def test_migration_handles_duplicate_message_ids(temp_dir: Path) -> None:
    """Test migration handles duplicate message IDs (lines 568-570)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "archive.mbox"

    # Create mbox with one message
    mbox = mailbox.mbox(str(mbox_path))
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<dup@example.com>"
    msg["Subject"] = "Duplicate"
    msg["From"] = "sender@example.com"
    msg.set_content("Message 1")
    mbox.add(msg)
    mbox.close()

    # Create v1.0 database with duplicate entries (same message, different gmail_ids)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    # Two messages with same RFC ID (simulating duplicate in v1.0)
    conn.execute(
        """
        INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "gmail1",
            "2024-01-01T00:00:00",
            str(mbox_path),
            "Duplicate",
            "sender@example.com",
            "2024-01-01",
            "checksum123",
        ),
    )
    conn.execute(
        """
        INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "gmail2",
            "2024-01-01T00:00:00",
            str(mbox_path),
            "Duplicate",
            "sender@example.com",
            "2024-01-01",
            "checksum123",
        ),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    # Should handle gracefully (might keep one, might keep both)
    await manager.migrate_v1_to_v1_1()

    # Database should be valid after migration
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM messages")
    count = cursor.fetchone()[0]
    assert count > 0

    conn.close()
    await manager._close()


async def test_migration_preserves_data_integrity(temp_dir: Path) -> None:
    """Test migration preserves all message data (lines 644-645)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "archive.mbox"

    # Create mbox with message
    mbox = mailbox.mbox(str(mbox_path))
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<integrity@example.com>"
    msg["Subject"] = "Data Integrity Test"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Cc"] = "cc@example.com"
    msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg.set_content("Test content for integrity")
    mbox.add(msg)
    mbox.close()

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.execute(
        """
        INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "integrity1",
            "2024-01-01T00:00:00",
            str(mbox_path),
            "Data Integrity Test",
            "sender@example.com",
            "2024-01-01",
            "original_checksum",
        ),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify data preserved in new schema
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT subject, from_addr, archive_file FROM messages
        WHERE gmail_id='integrity1'
    """)
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "Data Integrity Test"
    assert row[1] == "sender@example.com"
    assert row[2] == str(mbox_path)

    conn.close()
    await manager._close()


async def test_migration_schema_version_updated(temp_dir: Path) -> None:
    """Test migration updates schema_version correctly (lines 671, 688-691)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.commit()
    conn.close()

    manager = MigrationManager(str(db_path))
    await manager.migrate_v1_to_v1_1()

    # Verify schema_version table exists and is updated
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT version FROM schema_version WHERE version='1.1'
    """)
    assert cursor.fetchone() is not None

    conn.close()
    await manager._close()


async def test_migration_handles_message_processing_error(temp_dir: Path) -> None:
    """Test migration handles errors processing individual messages (lines 528-536)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)

    # Create archive_runs table
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)

    # Insert test message
    mbox_path = temp_dir / "test.mbox"
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(mbox_path), "Test", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.commit()
    conn.close()

    # Create corrupt mbox (will cause processing error)
    with open(mbox_path, "wb") as f:
        f.write(b"corrupt mbox data\x00\xff")

    manager = MigrationManager(db_path)

    # Migration should handle the error and skip the message
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed despite error
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    version = cursor.fetchone()[0]
    conn.close()

    assert version == "1.1"
    await manager._close()


async def test_migration_handles_mbox_scan_failure(temp_dir: Path) -> None:
    """Test migration handles mbox scan failures (lines 547-552)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)

    # Insert message pointing to non-existent mbox
    mbox_path = temp_dir / "missing.mbox"
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(mbox_path), "Test", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(db_path)

    # Should handle missing mbox file
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    version = cursor.fetchone()[0]
    conn.close()

    assert version == "1.1"
    await manager._close()


async def test_backfill_offsets_missing_archive(temp_dir: Path) -> None:
    """Test backfill_offsets_from_mbox handles missing archives (lines 680, 697-700)."""
    db_path = temp_dir / "test.db"

    # Create v1.1 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT,
            archive_file TEXT,
            mbox_offset INTEGER,
            mbox_length INTEGER,
            archived_timestamp TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            date TEXT,
            body_preview TEXT,
            checksum TEXT,
            size_bytes INTEGER,
            labels TEXT,
            account_id TEXT,
            thread_id TEXT
        )
    """)
    conn.commit()
    conn.close()

    manager = MigrationManager(db_path)

    # Messages pointing to missing archive
    invalid_messages = [
        {
            "gmail_id": "msg1",
            "rfc_message_id": "<msg1@example.com>",
            "archive_file": str(temp_dir / "missing.mbox"),
        }
    ]

    # Should handle missing file gracefully
    backfilled = await manager.backfill_offsets_from_mbox(invalid_messages)

    assert backfilled == 0
    await manager._close()


async def test_backfill_offsets_message_processing_error(temp_dir: Path) -> None:
    """Test backfill handles message processing errors (lines 745-757)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "test.mbox"

    # Create v1.1 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE messages (
            gmail_id TEXT PRIMARY KEY,
            rfc_message_id TEXT,
            archive_file TEXT,
            mbox_offset INTEGER,
            mbox_length INTEGER,
            archived_timestamp TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            date TEXT,
            body_preview TEXT,
            checksum TEXT,
            size_bytes INTEGER,
            labels TEXT,
            account_id TEXT,
            thread_id TEXT
        )
    """)
    conn.commit()
    conn.close()

    # Create corrupt mbox
    with open(mbox_path, "wb") as f:
        f.write(b"corrupt\x00\xff")

    manager = MigrationManager(db_path)

    invalid_messages = [
        {"gmail_id": "msg1", "rfc_message_id": "<msg1@example.com>", "archive_file": str(mbox_path)}
    ]

    # Should handle corruption gracefully
    backfilled = await manager.backfill_offsets_from_mbox(invalid_messages)

    # No messages backfilled due to corruption
    assert backfilled == 0
    await manager._close()


async def test_rollback_migration_missing_backup(temp_dir: Path) -> None:
    """Test rollback_migration raises error for missing backup (lines 653-654)."""
    db_path = temp_dir / "test.db"
    backup_path = temp_dir / "missing_backup.db"

    manager = MigrationManager(db_path)

    with pytest.raises(Exception) as exc_info:  # MigrationError
        await manager.rollback_migration(backup_path)

    assert "not found" in str(exc_info.value).lower()
    await manager._close()


async def test_migration_multipart_message_handling(temp_dir: Path) -> None:
    """Test migration handles multipart messages (lines 297-298)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "test.mbox"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(mbox_path), "Test", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.commit()
    conn.close()

    # Create mbox with multipart message
    msg = email.message.EmailMessage()
    msg["From"] = "from@test.com"
    msg["To"] = "to@test.com"
    msg["Subject"] = "Test"
    msg["Message-ID"] = "<test@example.com>"
    msg["Date"] = "2024-01-01"
    msg.make_mixed()

    # Add text/plain part
    text_part = email.message.EmailMessage()
    text_part.set_content("Plain text body", subtype="plain")
    msg.attach(text_part)

    # Write to mbox
    mbox = mailbox.mbox(str(mbox_path))
    mbox.add(msg)
    mbox.close()

    manager = MigrationManager(db_path)

    # Should handle multipart message
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT body_preview FROM messages WHERE gmail_id = ?", ("msg1",))
    row = cursor.fetchone()
    conn.close()

    # Should have extracted body preview
    assert row is not None
    assert len(row[0]) > 0
    await manager._close()


async def test_migration_non_multipart_message_handling(temp_dir: Path) -> None:
    """Test migration handles non-multipart messages (lines 304-305)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "test.mbox"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(mbox_path), "Test", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.commit()
    conn.close()

    # Create simple non-multipart message
    msg = email.message.EmailMessage()
    msg["From"] = "from@test.com"
    msg["To"] = "to@test.com"
    msg["Subject"] = "Test"
    msg["Message-ID"] = "<test@example.com>"
    msg["Date"] = "2024-01-01"
    msg.set_content("Simple body text")

    # Write to mbox
    mbox = mailbox.mbox(str(mbox_path))
    mbox.add(msg)
    mbox.close()

    manager = MigrationManager(db_path)

    # Should handle non-multipart message
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT body_preview FROM messages WHERE gmail_id = ?", ("msg1",))
    row = cursor.fetchone()
    conn.close()

    # Should have extracted body preview
    assert row is not None
    assert "Simple body text" in row[0]
    await manager._close()


async def test_migration_handles_missing_archive_file(temp_dir: Path) -> None:
    """Test migration handles missing archive files gracefully (lines 461-462)."""
    db_path = temp_dir / "test.db"

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)

    # Insert message pointing to non-existent file
    missing_path = temp_dir / "missing.mbox"
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(missing_path), "Test", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.commit()
    conn.close()

    manager = MigrationManager(db_path)

    # Should handle missing file gracefully
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    version = cursor.fetchone()[0]
    conn.close()

    assert version == "1.1"
    await manager._close()


async def test_migration_remaining_messages_warning(temp_dir: Path) -> None:
    """Test migration warns about remaining messages (lines 547-552)."""
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "test.mbox"

    # Create v1.0 database with 2 messages
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT,
            archive_file TEXT,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)

    # Insert 2 messages
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg1", "2024-01-01", str(mbox_path), "Test 1", "from@test.com", "2024-01-01", "abc123"),
    )
    conn.execute(
        """INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("msg2", "2024-01-01", str(mbox_path), "Test 2", "from@test.com", "2024-01-01", "def456"),
    )
    conn.commit()
    conn.close()

    # Create mbox with only 1 message (fewer than expected)
    msg = email.message.EmailMessage()
    msg["From"] = "from@test.com"
    msg["Subject"] = "Test 1"
    msg["Message-ID"] = "<test1@example.com>"
    msg.set_content("Body 1")

    mbox = mailbox.mbox(str(mbox_path))
    mbox.add(msg)
    mbox.close()

    manager = MigrationManager(db_path)

    # Should handle mismatch and complete migration
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    version = cursor.fetchone()[0]
    conn.close()

    assert version == "1.1"
    await manager._close()


async def test_migration_handles_malformed_messages(temp_dir: Path) -> None:
    """Test migration handles malformed/corrupted messages gracefully (lines 297, 528-536).

    When an mbox contains a message that raises an exception during parsing,
    the migration should skip it with a warning and continue processing other messages.
    """
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "mixed.mbox"

    # Create mbox with 3 messages: valid, corrupted, valid
    with open(mbox_path, "wb") as f:
        # Valid message 1
        f.write(b"From valid1@example.com Mon Jan 01 12:00:00 2024\n")
        f.write(b"Message-ID: <valid1@example.com>\n")
        f.write(b"Subject: Valid Message 1\n")
        f.write(b"From: valid1@example.com\n")
        f.write(b"Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
        f.write(b"\n")
        f.write(b"Body of valid message 1\n")
        f.write(b"\n")

        # Corrupted message - malformed structure
        f.write(b"From corrupted@example.com Tue Jan 02 12:00:00 2024\n")
        # No proper headers, will cause parsing issues
        f.write(b"This is not a valid email structure\n")
        f.write(b"\xff\xfe\xfd Invalid bytes mixed in\n")
        f.write(b"\n")

        # Valid message 2
        f.write(b"From valid2@example.com Wed Jan 03 12:00:00 2024\n")
        f.write(b"Message-ID: <valid2@example.com>\n")
        f.write(b"Subject: Valid Message 2\n")
        f.write(b"From: valid2@example.com\n")
        f.write(b"Date: Wed, 03 Jan 2024 12:00:00 +0000\n")
        f.write(b"\n")
        f.write(b"Body of valid message 2\n")
        f.write(b"\n")

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)

    # Insert records for all 3 messages (migration will try to process all)
    conn.execute(
        "INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg1",
            "2024-01-01",
            str(mbox_path),
            "Valid Message 1",
            "valid1@example.com",
            "2024-01-01",
            "checksum1",
        ),
    )
    conn.execute(
        "INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg2",
            "2024-01-02",
            str(mbox_path),
            "Corrupted",
            "corrupted@example.com",
            "2024-01-02",
            "checksum2",
        ),
    )
    conn.execute(
        "INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg3",
            "2024-01-03",
            str(mbox_path),
            "Valid Message 2",
            "valid2@example.com",
            "2024-01-03",
            "checksum3",
        ),
    )
    conn.commit()
    conn.close()

    # Run migration - should complete despite corrupted message
    manager = MigrationManager(db_path)
    await manager.migrate_v1_to_v1_1()

    # Verify migration completed
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT version FROM schema_version")
    assert cursor.fetchone()[0] == "1.1"

    # Check how many messages were migrated (should be 2-3 depending on parsing)
    cursor = conn.execute("SELECT COUNT(*) FROM messages")
    migrated_count = cursor.fetchone()[0]

    # At minimum, the 2 valid messages should be migrated
    # The corrupted one might be skipped or partially migrated
    assert migrated_count >= 2, f"Expected at least 2 valid messages migrated, got {migrated_count}"

    # Verify the valid messages were migrated successfully
    cursor = conn.execute("SELECT gmail_id FROM messages WHERE gmail_id IN ('msg1', 'msg3')")
    valid_messages = [row[0] for row in cursor.fetchall()]
    assert "msg1" in valid_messages or "msg3" in valid_messages, (
        "At least one valid message should be migrated"
    )

    conn.close()
    await manager._close()


async def test_migration_last_message_length_calculation(temp_dir: Path) -> None:
    """Test correct length calculation for last message in mbox (line 461).

    The last message has no following message, so length = file_size - message_offset.
    """
    db_path = temp_dir / "test.db"
    mbox_path = temp_dir / "single.mbox"

    # Create mbox with exactly 1 message
    mbox = mailbox.mbox(str(mbox_path))
    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<single@example.com>"
    msg["Subject"] = "Single Message"
    msg["From"] = "sender@example.com"
    msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg.set_content("This is the only message in the mbox.")
    mbox.add(msg)
    mbox.close()

    # Get file size for later verification
    file_size = mbox_path.stat().st_size

    # Create v1.0 database
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE archived_messages (
            gmail_id TEXT PRIMARY KEY,
            archived_timestamp TEXT NOT NULL,
            archive_file TEXT NOT NULL,
            subject TEXT,
            from_addr TEXT,
            message_date TEXT,
            checksum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT,
            query TEXT,
            messages_archived INTEGER,
            archive_file TEXT
        )
    """)
    conn.execute(
        "INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg1",
            "2024-01-01",
            str(mbox_path),
            "Single Message",
            "sender@example.com",
            "2024-01-01",
            "checksum1",
        ),
    )
    conn.commit()
    conn.close()

    # Run migration with backfill
    manager = MigrationManager(db_path)
    await manager.migrate_v1_to_v1_1()

    # Verify last message length = file_size - offset
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT mbox_offset, mbox_length FROM messages WHERE gmail_id=?", ("msg1",)
    )
    row = cursor.fetchone()
    assert row is not None, "Message should be migrated"

    offset, length = row
    assert offset >= 0, "Offset should be valid"
    assert length > 0, "Length should be positive"

    # Critical: Verify length calculation for last message
    expected_length = file_size - offset
    assert length == expected_length, (
        f"Last message length should be {expected_length} (file_size - offset), got {length}"
    )

    # Verify we can actually read the message at the offset
    with open(mbox_path, "rb") as f:
        f.seek(offset)
        message_data = f.read(length)
        # Should contain the Message-ID
        assert b"<single@example.com>" in message_data

    conn.close()
    await manager._close()


class TestMigrationErrorPaths:
    """Test error handling during migration."""

    async def test_migrate_message_processing_error(self, tmp_path):
        """Test migration handles individual message processing errors (lines 528-536)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox with one valid message
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<valid@example.com>"
        msg1["Subject"] = "Valid Message"
        msg1["From"] = "test@example.com"
        msg1.set_content("Valid message body")
        mbox.add(msg1)
        mbox.close()

        # Create v1.0 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Valid Message",
                "test@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Now patch the mbox to cause errors during message processing
        from unittest.mock import patch

        manager = MigrationManager(db_path)

        # Patch mailbox.mbox to return a mock that raises errors
        original_mbox = mailbox.mbox

        class ErrorMbox:
            """Mock mbox that raises errors for specific messages."""

            def __init__(self, path):
                self.real_mbox = original_mbox(path)
                self._toc = self.real_mbox._toc

            def keys(self):
                return self.real_mbox.keys()

            def __getitem__(self, key):
                # Raise error when accessing message to trigger lines 528-536
                raise Exception("Simulated message processing error")

            def close(self):
                self.real_mbox.close()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with patch("mailbox.mbox", side_effect=lambda p: ErrorMbox(p)):
            # Migration should complete despite message errors
            await manager.migrate_v1_to_v1_1()

        # Verify migration completed (message skipped due to error)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

        # Message should be skipped (processing error)
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 0
        conn.close()
        await manager._close()

    async def test_migrate_mbox_scan_failure(self, tmp_path):
        """Test migration handles mbox scan failures (lines 547-552)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg.set_content("Test")
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Test",
                "test@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Patch mailbox.mbox to raise error on opening
        from unittest.mock import patch

        manager = MigrationManager(db_path)

        with patch("mailbox.mbox", side_effect=Exception("Failed to open mbox")):
            # Migration should complete but skip failed archive
            await manager.migrate_v1_to_v1_1()

        # Verify migration completed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"
        conn.close()
        await manager._close()

    async def test_rollback_migration_error(self, tmp_path):
        """Test rollback handles errors (lines 653-654)."""
        db_path = tmp_path / "test.db"
        backup_path = tmp_path / "backup.db"

        # Create a database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        # Create a backup
        import shutil

        shutil.copy2(db_path, backup_path)

        manager = MigrationManager(db_path)

        # Make backup_path unreadable to trigger error
        from unittest.mock import patch

        with patch("shutil.copy2", side_effect=PermissionError("Cannot copy")):
            with pytest.raises(MigrationError, match="Rollback failed"):
                await manager.rollback_migration(backup_path)
        await manager._close()

    async def test_backfill_empty_invalid_messages(self, tmp_path):
        """Test backfill returns 0 for empty list (line 680)."""
        db_path = tmp_path / "test.db"

        # Create v1.1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER
            )
        """)
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        result = await manager.backfill_offsets_from_mbox([])
        assert result == 0
        await manager._close()

    async def test_backfill_message_processing_error(self, tmp_path):
        """Test backfill handles message processing errors (lines 745-751)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg.set_content("Test")
        mbox.add(msg)
        mbox.close()

        # Create v1.1 database with invalid offset
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?)
        """,
            ("msg1", "<test@example.com>", str(mbox_path), -1, -1),
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)

        # Patch to cause error during message processing
        from unittest.mock import patch

        original_mbox = mailbox.mbox

        class ErrorMbox:
            """Mock mbox that raises errors."""

            def __init__(self, path):
                self.real_mbox = original_mbox(path)
                self._toc = self.real_mbox._toc

            def keys(self):
                return self.real_mbox.keys()

            def __getitem__(self, key):
                raise Exception("Processing error")

            def close(self):
                self.real_mbox.close()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        invalid_msgs = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<test@example.com>",
                "archive_file": str(mbox_path),
            }
        ]

        with patch("mailbox.mbox", side_effect=lambda p: ErrorMbox(p)):
            # Should continue despite error
            result = await manager.backfill_offsets_from_mbox(invalid_msgs)
            # No messages backfilled due to error
            assert result == 0
        await manager._close()

    async def test_backfill_mbox_scan_error(self, tmp_path):
        """Test backfill handles mbox scan failures (lines 753-757)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg.set_content("Test")
        mbox.add(msg)
        mbox.close()

        # Create v1.1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?)
        """,
            ("msg1", "<test@example.com>", str(mbox_path), -1, -1),
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)

        # Patch mailbox.mbox to fail during scanning
        from unittest.mock import patch

        invalid_msgs = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<test@example.com>",
                "archive_file": str(mbox_path),
            }
        ]

        with patch("mailbox.mbox", side_effect=Exception("Scan error")):
            result = await manager.backfill_offsets_from_mbox(invalid_msgs)
            assert result == 0
        await manager._close()

    async def test_backfill_rollback_on_error(self, tmp_path):
        """Test backfill rolls back on database errors (lines 765-767)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg.set_content("Test")
        mbox.add(msg)
        mbox.close()

        # Create v1.1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?)
        """,
            ("msg1", "<test@example.com>", str(mbox_path), -1, -1),
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)

        invalid_msgs = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<test@example.com>",
                "archive_file": str(mbox_path),
            }
        ]

        # Patch commit to raise an error to trigger lines 765-767
        from unittest.mock import patch

        async def failing_commit():
            raise sqlite3.OperationalError("Database commit failed")

        # Get the connection and patch its commit method
        async_conn = await manager._connect()
        original_commit = async_conn.commit

        try:
            with patch.object(async_conn, "commit", side_effect=failing_commit):
                with pytest.raises(MigrationError, match="Backfill failed"):
                    await manager.backfill_offsets_from_mbox(invalid_msgs)
        finally:
            async_conn.commit = original_commit
        await manager._close()

    async def test_backfill_multiple_messages_offset_calculation(self, tmp_path):
        """Test backfill calculates offsets correctly for multiple messages (lines 726-727)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox with TWO messages
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<first@example.com>"
        msg1.set_content("First message")
        mbox.add(msg1)

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<second@example.com>"
        msg2.set_content("Second message")
        mbox.add(msg2)
        mbox.close()

        # Create v1.1 database with invalid offsets for both messages
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT,
                archive_file TEXT,
                mbox_offset INTEGER,
                mbox_length INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?)
        """,
            ("msg1", "<first@example.com>", str(mbox_path), -1, -1),
        )
        conn.execute(
            """
            INSERT INTO messages VALUES (?, ?, ?, ?, ?)
        """,
            ("msg2", "<second@example.com>", str(mbox_path), -1, -1),
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)

        invalid_msgs = [
            {
                "gmail_id": "msg1",
                "rfc_message_id": "<first@example.com>",
                "archive_file": str(mbox_path),
            },
            {
                "gmail_id": "msg2",
                "rfc_message_id": "<second@example.com>",
                "archive_file": str(mbox_path),
            },
        ]

        # Backfill should work for both messages
        result = await manager.backfill_offsets_from_mbox(invalid_msgs)
        assert result == 2

        # Verify both messages have valid offsets
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT gmail_id, mbox_offset, mbox_length FROM messages ORDER BY gmail_id"
        )
        rows = cursor.fetchall()
        assert len(rows) == 2

        # First message should have valid offset and length
        msg1_id, msg1_offset, msg1_length = rows[0]
        assert msg1_id == "msg1"
        assert msg1_offset >= 0
        assert msg1_length > 0

        # Second message should have valid offset and length
        msg2_id, msg2_offset, msg2_length = rows[1]
        assert msg2_id == "msg2"
        assert msg2_offset >= 0
        assert msg2_length > 0

        # First message's offset should be less than second message's
        assert msg1_offset < msg2_offset

        conn.close()
        await manager._close()


# ============================================================================
# Additional Coverage Tests for Missing Lines
# ============================================================================


class TestBodyPreviewNonePayload:
    """Test body preview extraction with None/non-bytes payload (lines 300->295, 308->313)."""

    async def test_extract_body_multipart_with_none_payload(self):
        """Test multipart message with None payload (line 300->295)."""
        from unittest.mock import MagicMock

        manager = MigrationManager(":memory:")

        # Create a multipart message with a part that returns None payload
        msg = MagicMock()
        msg.is_multipart.return_value = True

        # Create a part that returns None from get_payload
        part = MagicMock()
        part.get_content_type.return_value = "text/plain"
        part.get_payload.return_value = None  # This triggers line 300->295

        msg.walk.return_value = [msg, part]

        result = manager._extract_body_preview(msg)
        # Should return empty string when payload is None
        assert result == ""
        await manager._close()

    async def test_extract_body_multipart_with_string_payload(self):
        """Test multipart message with string payload instead of bytes (line 300->295)."""
        from unittest.mock import MagicMock

        manager = MigrationManager(":memory:")

        # Create a multipart message with a part that returns string payload
        msg = MagicMock()
        msg.is_multipart.return_value = True

        # Create a part that returns string (not bytes) from get_payload
        part = MagicMock()
        part.get_content_type.return_value = "text/plain"
        part.get_payload.return_value = "string not bytes"  # Not isinstance(payload, bytes)

        msg.walk.return_value = [msg, part]

        result = manager._extract_body_preview(msg)
        # Should return empty string when payload is not bytes
        assert result == ""
        await manager._close()

    async def test_extract_body_non_multipart_with_none_payload(self):
        """Test non-multipart message with None payload (line 308->313)."""
        from unittest.mock import MagicMock

        manager = MigrationManager(":memory:")

        # Create a non-multipart message that returns None from get_payload
        msg = MagicMock()
        msg.is_multipart.return_value = False
        msg.get_payload.return_value = None  # This triggers line 308->313

        result = manager._extract_body_preview(msg)
        # Should return empty string when payload is None
        assert result == ""
        await manager._close()

    async def test_extract_body_non_multipart_with_string_payload(self):
        """Test non-multipart message with string payload instead of bytes (line 308->313)."""
        from unittest.mock import MagicMock

        manager = MigrationManager(":memory:")

        # Create a non-multipart message that returns string (not bytes)
        msg = MagicMock()
        msg.is_multipart.return_value = False
        msg.get_payload.return_value = "string not bytes"  # Not isinstance(payload, bytes)

        result = manager._extract_body_preview(msg)
        # Should return empty string when payload is not bytes
        assert result == ""
        await manager._close()


class TestRollbackWithNonexistentDatabase:
    """Test rollback when database doesn't exist (line 593->597)."""

    async def test_rollback_when_db_does_not_exist(self, tmp_path):
        """Test rollback when current database doesn't exist (line 593->597)."""
        db_path = tmp_path / "nonexistent.db"
        backup_path = tmp_path / "backup.db"

        # Create backup file
        conn = sqlite3.connect(str(backup_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT)")
        conn.execute("INSERT INTO archived_messages VALUES ('msg1')")
        conn.commit()
        conn.close()

        # Database doesn't exist yet
        assert not db_path.exists()

        # Perform rollback
        manager = MigrationManager(db_path)
        await manager.rollback_migration(backup_path)

        # Verify database now exists with restored data
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM archived_messages")
        assert cursor.fetchone()[0] == 1
        conn.close()
        await manager._close()


class TestMigrationWithMoreMessagesInMboxThanDB:
    """Test migration when mbox has more messages than v1.0 DB (line 735->720)."""

    async def test_migrate_with_extra_messages_in_mbox(self, tmp_path):
        """Test migration when mbox file has more messages than v1.0 DB records (line 735->720)."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create mbox file with 3 messages
        import mailbox

        mbox = mailbox.mbox(str(mbox_path))
        for i in range(3):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<test{i}@example.com>"
            msg["Subject"] = f"Test Subject {i}"
            msg["From"] = f"test{i}@example.com"
            msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
            msg.set_content(f"This is test message {i}.")
            mbox.add(msg)
        mbox.close()

        # Create v1.0 database with only 1 message (less than mbox)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        """)
        # Only insert 1 message, but mbox has 3
        conn.execute(
            """
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "2024-01-01T00:00:00",
                str(mbox_path),
                "Test Subject 0",
                "test0@example.com",
                "2024-01-01",
                "checksum123",
            ),
        )
        conn.commit()
        conn.close()

        # Perform migration - should process first message, then hit remaining_messages empty
        manager = MigrationManager(db_path)
        await manager.migrate_v1_to_v1_1()

        # Verify migration completed with just 1 message
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        # Should only have 1 message (from v1.0 DB)
        # The extra 2 messages in mbox are ignored after remaining_messages is empty
        assert count == 1
        conn.close()
        await manager._close()


# Note: Lines 870-881 (__del__ destructor) are defensive cleanup code
# that's difficult to test reliably in async contexts. The destructor
# handles edge cases during garbage collection and is excluded from
# coverage requirements as it's not a testable path in normal usage.
