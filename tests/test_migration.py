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
        """Test successful migration from v1.0 to v1.1."""
        db_path = tmp_path / "test.db"

        # Create v1.0 database with sample data
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
        # Insert test data
        conn.execute('''
            INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('msg1', '2024-01-01T00:00:00', 'archive.mbox', 'Test Subject',
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

        # Check data was migrated
        cursor = conn.execute("SELECT gmail_id, subject FROM messages WHERE gmail_id='msg1'")
        row = cursor.fetchone()
        assert row[0] == 'msg1'
        assert row[1] == 'Test Subject'

        # Check schema_version table
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == "1.1"

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
