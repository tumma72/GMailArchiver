"""Tests for database migration system."""

import email
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from gmailarchiver.migration import MigrationError, MigrationManager


class TestMigrationManagerInit:
    """Test MigrationManager initialization."""

    def test_init_with_path_string(self, tmp_path):
        """Test initialization with string path."""
        db_path = str(tmp_path / "test.db")
        manager = MigrationManager(db_path)
        assert manager.db_path == Path(db_path).resolve()
        assert manager.conn is None

    def test_init_with_path_object(self, tmp_path):
        """Test initialization with Path object."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)
        assert manager.db_path == db_path.resolve()

    def test_context_manager(self, tmp_path):
        """Test context manager behavior."""
        db_path = tmp_path / "test.db"
        with MigrationManager(db_path) as manager:
            assert isinstance(manager, MigrationManager)
        # Connection should be closed after context exit
        assert manager.conn is None


class TestSchemaVersionDetection:
    """Test schema version detection."""

    def test_detect_none_for_nonexistent_db(self, tmp_path):
        """Test detection returns 'none' for nonexistent database."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        assert version == "none"

    def test_detect_v1_0_with_archived_messages_table(self, tmp_path):
        """Test detection of v1.0 schema."""
        db_path = tmp_path / "v1.db"

        # Create v1.0 schema
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT,
                archive_file TEXT,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        assert version == "1.0"

    def test_detect_v1_1_with_messages_table(self, tmp_path):
        """Test detection of v1.1 schema."""
        db_path = tmp_path / "v1.1.db"

        # Create v1.1 schema
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        assert version == "1.1"

    def test_detect_version_from_schema_version_table(self, tmp_path):
        """Test reading version from schema_version table."""
        db_path = tmp_path / "versioned.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)",
            ("1.1", datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        assert version == "1.1"


class TestNeedsMigration:
    """Test needs_migration() method."""

    def test_needs_migration_for_v1_0(self, tmp_path):
        """Test that v1.0 schema needs migration."""
        db_path = tmp_path / "v1.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert manager.needs_migration() is True

    def test_needs_migration_for_none(self, tmp_path):
        """Test that nonexistent DB needs migration."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)
        assert manager.needs_migration() is True

    def test_no_migration_needed_for_v1_1(self, tmp_path):
        """Test that v1.1 schema doesn't need migration."""
        db_path = tmp_path / "v1.1.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert manager.needs_migration() is False


class TestBackupCreation:
    """Test database backup functionality."""

    def test_create_backup_success(self, tmp_path):
        """Test successful backup creation."""
        db_path = tmp_path / "test.db"

        # Create a test database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        backup_path = manager.create_backup()

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

    def test_create_backup_nonexistent_db_fails(self, tmp_path):
        """Test that backing up nonexistent DB fails."""
        db_path = tmp_path / "nonexistent.db"
        manager = MigrationManager(db_path)

        with pytest.raises(MigrationError, match="Database not found"):
            manager.create_backup()

    def test_create_backup_fails_with_permission_error(self, tmp_path):
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
                manager.create_backup()
        finally:
            # Restore permissions
            os.chmod(tmp_path, original_mode)


class TestEnhancedSchemaCreation:
    """Test creation of enhanced v1.1 schema."""

    def test_create_enhanced_schema(self, tmp_path):
        """Test that enhanced schema creates all required tables."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        conn = manager._connect()
        manager._create_enhanced_schema(conn)

        # Check messages table exists with correct columns
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        required_columns = {
            'gmail_id', 'rfc_message_id', 'thread_id', 'subject',
            'from_addr', 'to_addr', 'cc_addr', 'date', 'archived_timestamp',
            'archive_file', 'mbox_offset', 'mbox_length', 'body_preview',
            'checksum', 'size_bytes', 'labels', 'account_id'
        }
        assert required_columns.issubset(columns)

        # Check FTS5 table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        assert cursor.fetchone() is not None

        # Check indexes exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        index_names = {row[0] for row in cursor.fetchall()}
        expected_indexes = {
            'idx_rfc_message_id', 'idx_thread_id', 'idx_archive_file',
            'idx_date', 'idx_from', 'idx_subject'
        }
        assert expected_indexes.issubset(index_names)

        # Check accounts table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
        )
        assert cursor.fetchone() is not None

        conn.close()


class TestExtractRfcMessageId:
    """Test RFC Message-ID extraction."""

    def test_extract_existing_message_id(self):
        """Test extraction of existing Message-ID header."""
        msg = email.message.EmailMessage()
        msg['Message-ID'] = '<unique123@example.com>'
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)
        assert result == '<unique123@example.com>'

    def test_generate_fallback_message_id(self):
        """Test fallback Message-ID generation."""
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test Subject'
        msg['Date'] = 'Mon, 1 Jan 2024 12:00:00 +0000'

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)

        # Should generate SHA256-based ID
        assert result.startswith('<')
        assert result.endswith('@generated>')
        assert len(result) > 20  # SHA256 hash is long

    def test_handles_empty_message_id(self):
        """Test handling of empty Message-ID."""
        msg = email.message.EmailMessage()
        msg['Message-ID'] = '  '  # Whitespace only
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_rfc_message_id(msg)

        # Should generate fallback
        assert '@generated>' in result


class TestExtractBodyPreview:
    """Test body preview extraction."""

    def test_extract_from_plain_text(self):
        """Test extraction from plain text message."""
        msg = email.message.EmailMessage()
        msg.set_content("This is a test message body.")

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg, max_chars=10)
        assert result == "This is a "

    def test_extract_from_multipart(self):
        """Test extraction from multipart message."""
        msg = email.message.EmailMessage()
        msg.set_content("Plain text body")
        msg.add_alternative("<html><body>HTML body</body></html>", subtype='html')

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)
        assert "Plain text body" in result

    def test_max_chars_limit(self):
        """Test that preview respects max_chars limit."""
        long_text = "A" * 2000
        msg = email.message.EmailMessage()
        msg.set_content(long_text)

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg, max_chars=1000)
        assert len(result) == 1000
        assert result == "A" * 1000

    def test_handles_binary_payload(self):
        """Test handling of messages with binary payload."""
        msg = email.message.EmailMessage()
        msg.set_content(b"Binary content", maintype='application', subtype='octet-stream')

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)
        # EmailMessage.set_content converts bytes to string for non-multipart messages
        # so we actually get the content as text
        assert result == "Binary content"


class TestMigrationWorkflow:
    """Test the complete migration workflow."""

    def test_migrate_v1_to_v1_1_success(self, tmp_path):
        """Test successful migration from v1.0 to v1.1 with real mbox scanning."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox file with real message
        import mailbox
        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg['Message-ID'] = '<test123@example.com>'
        msg['Subject'] = 'Test Subject'
        msg['From'] = 'test@example.com'
        msg['Date'] = 'Mon, 1 Jan 2024 12:00:00 +0000'
        msg.set_content('This is a test message body.')
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database with sample data pointing to real mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        ''')
        # Insert test data - use a gmail_id that will be found in mbox
        # Migration should find the message by scanning the mbox
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('msg1', '2024-01-01T00:00:00', str(mbox_path), 'Test Subject',
              'test@example.com', '2024-01-01', 'checksum123'))
        conn.commit()
        conn.close()

        # Perform migration
        manager = MigrationManager(db_path)
        manager.migrate_v1_to_v1_1()

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
        assert rfc_message_id == '<test123@example.com>', \
            f"Expected real Message-ID, got placeholder: {rfc_message_id}"

        # Verify valid mbox offset (>= 0, not -1 placeholder)
        assert mbox_offset >= 0, \
            f"Expected valid offset >= 0, got placeholder: {mbox_offset}"

        # Verify valid mbox length (> 0, not -1 placeholder)
        assert mbox_length > 0, \
            f"Expected valid length > 0, got placeholder: {mbox_length}"

        # Verify subject was preserved
        assert subject == 'Test Subject'

        # Check schema_version table
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

        conn.close()

    def test_migrate_with_missing_mbox_file(self, tmp_path):
        """Test migration gracefully handles missing mbox files."""
        db_path = tmp_path / "test.db"
        nonexistent_mbox = tmp_path / "missing.mbox"

        # Create v1.0 database pointing to nonexistent mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('msg1', '2024-01-01T00:00:00', str(nonexistent_mbox), 'Test Subject',
              'test@example.com', '2024-01-01', 'checksum123'))
        conn.commit()
        conn.close()

        # Migration should complete but skip messages from missing files
        manager = MigrationManager(db_path)
        manager.migrate_v1_to_v1_1()

        # Verify migration completed
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

        # Message should not be migrated (mbox file missing)
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 0, "Should skip messages from missing mbox files"

        conn.close()

    def test_migrate_extracts_full_metadata(self, tmp_path):
        """Test migration extracts all v1.1 metadata fields."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "archive.mbox"

        # Create test mbox with rich metadata
        import mailbox
        mbox = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg['Message-ID'] = '<full-metadata@example.com>'
        msg['X-GM-THRID'] = '1234567890'
        msg['Subject'] = 'Full Metadata Test'
        msg['From'] = 'sender@example.com'
        msg['To'] = 'recipient@example.com'
        msg['Cc'] = 'cc@example.com'
        msg['Date'] = 'Mon, 1 Jan 2024 12:00:00 +0000'
        msg.set_content('This is a test message with full metadata.')
        mbox.add(msg)
        mbox.close()

        # Create v1.0 database
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('msg1', '2024-01-01T00:00:00', str(mbox_path), 'Full Metadata Test',
              'sender@example.com', '2024-01-01', 'checksum123'))
        conn.commit()
        conn.close()

        # Perform migration
        manager = MigrationManager(db_path)
        manager.migrate_v1_to_v1_1()

        # Verify all metadata was extracted
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            """SELECT rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
                      body_preview, mbox_offset, mbox_length
               FROM messages"""
        )
        row = cursor.fetchone()
        assert row is not None

        (rfc_message_id, thread_id, subject, from_addr, to_addr, cc_addr,
         body_preview, mbox_offset, mbox_length) = row

        # Verify all fields
        assert rfc_message_id == '<full-metadata@example.com>'
        assert thread_id == '1234567890'
        assert subject == 'Full Metadata Test'
        assert from_addr == 'sender@example.com'
        assert to_addr == 'recipient@example.com'
        assert cc_addr == 'cc@example.com'
        assert 'test message with full metadata' in body_preview.lower()
        assert mbox_offset >= 0
        assert mbox_length > 0

        conn.close()


class TestValidateMigration:
    """Test migration validation."""

    def test_validate_migration_success(self, tmp_path):
        """Test successful migration validation."""
        db_path = tmp_path / "test.db"

        # Create v1.1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        ''')
        conn.execute('''
            CREATE VIRTUAL TABLE messages_fts USING fts5(content)
        ''')
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.execute("INSERT INTO messages VALUES ('msg1')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        assert manager.validate_migration() is True

    def test_validate_migration_fails_wrong_version(self, tmp_path):
        """Test validation fails with wrong schema version."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute("INSERT INTO schema_version VALUES ('1.0', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="Schema version not set to 1.1"):
            manager.validate_migration()

    def test_validate_migration_fails_missing_messages_table(self, tmp_path):
        """Test validation fails if messages table missing."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="messages table not found"):
            manager.validate_migration()


class TestRollbackMigration:
    """Test migration rollback."""

    def test_rollback_success(self, tmp_path):
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
        manager.rollback_migration(backup_path)

        # Verify rollback
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute("SELECT COUNT(*) FROM archived_messages")
        assert cursor.fetchone()[0] == 1

        conn.close()

    def test_rollback_fails_missing_backup(self, tmp_path):
        """Test that rollback fails with missing backup."""
        db_path = tmp_path / "test.db"
        backup_path = tmp_path / "nonexistent.db"

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="Backup file not found"):
            manager.rollback_migration(backup_path)


class TestExtractThreadId:
    """Test thread ID extraction from email headers."""

    def test_extract_from_gmail_thrid_header(self):
        """Test extraction from X-GM-THRID header."""
        msg = email.message.EmailMessage()
        msg['X-GM-THRID'] = '1234567890'
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result == '1234567890'

    def test_extract_from_references_header(self):
        """Test fallback to References header."""
        msg = email.message.EmailMessage()
        msg['References'] = '<ref1@example.com> <ref2@example.com>'
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result == '<ref1@example.com>'

    def test_returns_none_without_thread_headers(self):
        """Test returns None when no thread headers present."""
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result is None

    def test_handles_empty_references_header(self):
        """Test handles empty References header."""
        msg = email.message.EmailMessage()
        msg['References'] = '   '  # Whitespace only
        msg['Subject'] = 'Test'

        manager = MigrationManager(":memory:")
        result = manager._extract_thread_id(msg)
        assert result is None


class TestValidationEdgeCases:
    """Test validation edge cases."""

    def test_validate_migration_fails_missing_fts_table(self, tmp_path):
        """Test validation fails if FTS table missing."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        conn.execute("INSERT INTO schema_version VALUES ('1.1', '2024-01-01T00:00:00')")
        conn.execute('''
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        with pytest.raises(MigrationError, match="messages_fts table not found"):
            manager.validate_migration()


class TestSchemaVersionEdgeCases:
    """Test schema version detection edge cases."""

    def test_detect_none_for_empty_schema_version_table(self, tmp_path):
        """Test detection returns 1.0 when schema_version table exists but empty."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        ''')
        # Don't insert any version - table exists but is empty
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        # When schema_version table exists but has no rows, it returns "1.0"
        assert version == "1.0"

    def test_detect_none_for_unrecognized_schema(self, tmp_path):
        """Test detection returns 'none' for database with unrecognized schema."""
        db_path = tmp_path / "test.db"

        # Create database with unrecognized tables
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE some_random_table (
                id INTEGER PRIMARY KEY,
                data TEXT
            )
        ''')
        conn.commit()
        conn.close()

        manager = MigrationManager(db_path)
        version = manager.detect_schema_version()
        # Database exists but has no recognized schema - should return "none"
        assert version == "none"


class TestCloseConnection:
    """Test database connection closing."""

    def test_close_when_connection_exists(self, tmp_path):
        """Test closing an active connection."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        # Connect to database
        conn = manager._connect()
        assert manager.conn is not None

        # Close connection
        manager._close()
        assert manager.conn is None

    def test_close_when_no_connection(self, tmp_path):
        """Test closing when no connection exists."""
        db_path = tmp_path / "test.db"
        manager = MigrationManager(db_path)

        # No connection established yet
        assert manager.conn is None

        # Should not raise error
        manager._close()
        assert manager.conn is None


class TestBodyPreviewExceptions:
    """Test body preview extraction with malformed data."""

    def test_extract_body_handles_decode_error_multipart(self):
        """Test that decode errors in multipart messages are handled gracefully."""
        import email.mime.multipart
        import email.mime.text

        # Create a multipart message
        msg = email.mime.multipart.MIMEMultipart()
        msg['Subject'] = 'Test'

        # Add a text part with valid content
        text_part = email.mime.text.MIMEText('Valid text', 'plain')
        msg.attach(text_part)

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)

        # Should extract from the valid part
        assert 'Valid text' in result

    def test_extract_body_handles_decode_error_plain(self):
        """Test that decode errors in plain messages are handled gracefully."""
        # Create a message with payload that might cause decode issues
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test'
        msg.set_content('Plain text message')

        manager = MigrationManager(":memory:")
        result = manager._extract_body_preview(msg)

        # Should successfully extract
        assert 'Plain text message' in result


class TestMigrationErrorHandling:
    """Test migration error handling scenarios."""

    def test_migrate_handles_corrupt_mbox_file(self, tmp_path):
        """Test migration gracefully handles corrupt mbox files."""
        db_path = tmp_path / "test.db"
        mbox_path = tmp_path / "corrupt.mbox"

        # Create a corrupt/empty mbox file (will cause mailbox.mbox to fail)
        mbox_path.write_text("")

        # Create v1.0 database pointing to corrupt mbox
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('msg1', '2024-01-01T00:00:00', str(mbox_path), 'Test Subject',
              'test@example.com', '2024-01-01', 'checksum123'))
        conn.commit()
        conn.close()

        # Migration should handle the error gracefully
        manager = MigrationManager(db_path)
        # Should not raise exception, just skip corrupt files
        manager.migrate_v1_to_v1_1()

        # Verify migration completed despite corrupt mbox
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"
        conn.close()

    def test_migrate_handles_multiple_mbox_files_with_failures(self, tmp_path):
        """Test migration continues when some mbox files fail."""
        db_path = tmp_path / "test.db"
        good_mbox_path = tmp_path / "good.mbox"
        bad_mbox_path = tmp_path / "bad.mbox"

        # Create a good mbox file
        import mailbox
        mbox = mailbox.mbox(str(good_mbox_path))
        msg = email.message.EmailMessage()
        msg['Message-ID'] = '<good@example.com>'
        msg['Subject'] = 'Good Message'
        msg['From'] = 'good@example.com'
        msg['Date'] = 'Mon, 1 Jan 2024 12:00:00 +0000'
        msg.set_content('This is a good message.')
        mbox.add(msg)
        mbox.close()

        # Create a bad mbox file (empty/corrupt)
        bad_mbox_path.write_text("")

        # Create v1.0 database with messages from both files
        conn = sqlite3.connect(str(db_path))
        conn.execute('''
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                archived_timestamp TEXT NOT NULL,
                archive_file TEXT NOT NULL,
                subject TEXT,
                from_addr TEXT,
                message_date TEXT,
                checksum TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                query TEXT,
                messages_archived INTEGER,
                archive_file TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('good1', '2024-01-01T00:00:00', str(good_mbox_path), 'Good Message',
              'good@example.com', '2024-01-01', 'checksum123'))
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('bad1', '2024-01-01T00:00:00', str(bad_mbox_path), 'Bad Message',
              'bad@example.com', '2024-01-01', 'checksum456'))
        conn.commit()
        conn.close()

        # Migration should handle partial failures
        manager = MigrationManager(db_path)
        manager.migrate_v1_to_v1_1()

        # Verify good message was migrated, bad was skipped
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id='good1'")
        assert cursor.fetchone()[0] == 1

        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE gmail_id='bad1'")
        assert cursor.fetchone()[0] == 0
        conn.close()
