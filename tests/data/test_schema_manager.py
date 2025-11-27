"""Tests for centralized SchemaManager."""

import sqlite3

import pytest

from gmailarchiver.data.schema_manager import (
    SchemaCapability,
    SchemaManager,
    SchemaVersion,
    SchemaVersionError,
)


class TestSchemaVersion:
    """Test SchemaVersion enum."""

    def test_version_ordering(self):
        """Test that versions are properly ordered."""
        assert SchemaVersion.V1_0 < SchemaVersion.V1_1
        assert SchemaVersion.V1_1 < SchemaVersion.V1_2
        assert SchemaVersion.V1_0 < SchemaVersion.V1_2
        assert SchemaVersion.NONE < SchemaVersion.V1_0

    def test_version_comparison_operators(self):
        """Test all comparison operators."""
        assert SchemaVersion.V1_1 <= SchemaVersion.V1_1
        assert SchemaVersion.V1_1 <= SchemaVersion.V1_2
        assert SchemaVersion.V1_2 >= SchemaVersion.V1_1
        assert SchemaVersion.V1_2 >= SchemaVersion.V1_2
        assert SchemaVersion.V1_2 > SchemaVersion.V1_1
        assert not (SchemaVersion.V1_1 > SchemaVersion.V1_2)

    def test_from_string(self):
        """Test converting strings to SchemaVersion."""
        assert SchemaVersion.from_string("1.0") == SchemaVersion.V1_0
        assert SchemaVersion.from_string("1.1") == SchemaVersion.V1_1
        assert SchemaVersion.from_string("1.2") == SchemaVersion.V1_2
        assert SchemaVersion.from_string("2.0") == SchemaVersion.UNKNOWN
        assert SchemaVersion.from_string("invalid") == SchemaVersion.UNKNOWN

    def test_is_valid(self):
        """Test is_valid property."""
        assert SchemaVersion.V1_0.is_valid
        assert SchemaVersion.V1_1.is_valid
        assert SchemaVersion.V1_2.is_valid
        assert not SchemaVersion.NONE.is_valid
        assert not SchemaVersion.UNKNOWN.is_valid


class TestSchemaManagerDetection:
    """Test schema version detection."""

    def test_detect_nonexistent_database(self):
        """Test detection on non-existent database."""
        manager = SchemaManager("/nonexistent/path/db.sqlite")
        assert manager.detect_version() == SchemaVersion.NONE

    def test_detect_empty_database(self, tmp_path):
        """Test detection on empty database."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.detect_version() == SchemaVersion.NONE

    def test_detect_v1_0_database(self, tmp_path):
        """Test detection of v1.0 schema (archived_messages table)."""
        db_path = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                thread_id TEXT,
                archive_file TEXT
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE archive_runs (
                run_id INTEGER PRIMARY KEY
            )
        """
        )
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.detect_version() == SchemaVersion.V1_0

    def test_detect_v1_1_database(self, tmp_path):
        """Test detection of v1.1 schema."""
        db_path = tmp_path / "v1_1.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE,
                mbox_offset INTEGER
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """
        )
        conn.execute("INSERT INTO schema_version VALUES ('1.1', datetime('now'))")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.detect_version() == SchemaVersion.V1_1

    def test_detect_v1_2_database(self, tmp_path):
        """Test detection of v1.2 schema."""
        db_path = tmp_path / "v1_2.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE messages (
                gmail_id TEXT,
                rfc_message_id TEXT PRIMARY KEY,
                mbox_offset INTEGER
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """
        )
        conn.execute("INSERT INTO schema_version VALUES ('1.2', datetime('now'))")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.detect_version() == SchemaVersion.V1_2

    def test_version_caching(self, tmp_path):
        """Test that version detection is cached."""
        db_path = tmp_path / "cached.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT
            )
        """
        )
        conn.execute("INSERT INTO schema_version VALUES ('1.1', datetime('now'))")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.detect_version() == SchemaVersion.V1_1

        # Modify database behind the scenes
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE schema_version SET version = '1.2'")
        conn.commit()
        conn.close()

        # Should still return cached value
        assert manager.detect_version() == SchemaVersion.V1_1

        # After invalidation, should detect new version
        manager.invalidate_cache()
        assert manager.detect_version() == SchemaVersion.V1_2


class TestSchemaManagerCapabilities:
    """Test capability checking."""

    def test_v1_0_capabilities(self, tmp_path):
        """Test v1.0 has only basic capabilities."""
        db_path = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.has_capability(SchemaCapability.BASIC_ARCHIVING)
        assert not manager.has_capability(SchemaCapability.FTS_SEARCH)
        assert not manager.has_capability(SchemaCapability.MBOX_OFFSETS)
        assert not manager.has_capability(SchemaCapability.NULLABLE_GMAIL_ID)

    def test_v1_1_capabilities(self, tmp_path):
        """Test v1.1 capabilities."""
        db_path = tmp_path / "v1_1.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.1')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.has_capability(SchemaCapability.BASIC_ARCHIVING)
        assert manager.has_capability(SchemaCapability.FTS_SEARCH)
        assert manager.has_capability(SchemaCapability.MBOX_OFFSETS)
        assert manager.has_capability(SchemaCapability.RFC_MESSAGE_ID)
        assert not manager.has_capability(SchemaCapability.NULLABLE_GMAIL_ID)

    def test_v1_2_capabilities(self, tmp_path):
        """Test v1.2 has all capabilities."""
        db_path = tmp_path / "v1_2.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.2')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.has_capability(SchemaCapability.BASIC_ARCHIVING)
        assert manager.has_capability(SchemaCapability.FTS_SEARCH)
        assert manager.has_capability(SchemaCapability.MBOX_OFFSETS)
        assert manager.has_capability(SchemaCapability.RFC_MESSAGE_ID)
        assert manager.has_capability(SchemaCapability.NULLABLE_GMAIL_ID)


class TestSchemaManagerVersionRequirements:
    """Test version requirement checking."""

    def test_require_version_success(self, tmp_path):
        """Test require_version passes when requirement met."""
        db_path = tmp_path / "v1_2.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.2')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        # Should not raise
        manager.require_version(SchemaVersion.V1_0)
        manager.require_version(SchemaVersion.V1_1)
        manager.require_version(SchemaVersion.V1_2)

    def test_require_version_failure(self, tmp_path):
        """Test require_version raises when requirement not met."""
        db_path = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        with pytest.raises(SchemaVersionError) as exc_info:
            manager.require_version(SchemaVersion.V1_1)

        assert exc_info.value.current_version == SchemaVersion.V1_0
        assert exc_info.value.required_version == SchemaVersion.V1_1
        assert "1.1" in str(exc_info.value)

    def test_require_capability_success(self, tmp_path):
        """Test require_capability passes when capability available."""
        db_path = tmp_path / "v1_1.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.1')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        # Should not raise
        manager.require_capability(SchemaCapability.FTS_SEARCH)

    def test_require_capability_failure(self, tmp_path):
        """Test require_capability raises when capability not available."""
        db_path = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        with pytest.raises(SchemaVersionError):
            manager.require_capability(SchemaCapability.FTS_SEARCH)


class TestSchemaManagerMigration:
    """Test migration checking."""

    def test_needs_migration_v1_0(self, tmp_path):
        """Test v1.0 needs migration."""
        db_path = tmp_path / "v1_0.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.needs_migration()
        assert manager.can_auto_migrate()

    def test_needs_migration_v1_1(self, tmp_path):
        """Test v1.1 needs migration to v1.2."""
        db_path = tmp_path / "v1_1.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.1')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.needs_migration()
        assert manager.can_auto_migrate()

    def test_no_migration_needed_current(self, tmp_path):
        """Test current version doesn't need migration."""
        db_path = tmp_path / "v1_2.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE messages (gmail_id TEXT)")
        conn.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES ('1.2')")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert not manager.needs_migration()

    def test_is_supported(self, tmp_path):
        """Test version support checking."""
        db_path = tmp_path / "test.db"

        # Create v1.0 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE archived_messages (gmail_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        manager = SchemaManager(db_path)
        assert manager.is_supported()
        assert manager.is_supported(SchemaVersion.V1_0)
        assert manager.is_supported(SchemaVersion.V1_1)
        assert manager.is_supported(SchemaVersion.V1_2)
        assert not manager.is_supported(SchemaVersion.NONE)
        assert not manager.is_supported(SchemaVersion.UNKNOWN)


class TestSchemaVersionError:
    """Test SchemaVersionError exception."""

    def test_error_with_versions(self):
        """Test error includes version info."""
        error = SchemaVersionError(
            "Test error",
            current_version=SchemaVersion.V1_0,
            required_version=SchemaVersion.V1_1,
        )
        assert error.current_version == SchemaVersion.V1_0
        assert error.required_version == SchemaVersion.V1_1
        assert "migrate" in error.suggestion.lower()

    def test_error_suggestion_for_none(self):
        """Test suggestion for empty database."""
        error = SchemaVersionError(
            "No database",
            current_version=SchemaVersion.NONE,
            required_version=SchemaVersion.V1_1,
        )
        assert "create" in error.suggestion.lower()


class TestSchemaManagerClassMethods:
    """Test class-level methods."""

    def test_get_current_version_string(self):
        """Test getting current version as string."""
        version_str = SchemaManager.get_current_version_string()
        assert version_str == "1.2"

    def test_version_from_string(self):
        """Test version string conversion."""
        assert SchemaManager.version_from_string("1.0") == SchemaVersion.V1_0
        assert SchemaManager.version_from_string("1.1") == SchemaVersion.V1_1
        assert SchemaManager.version_from_string("1.2") == SchemaVersion.V1_2


class TestSchemaVersionComparisons:
    """Test SchemaVersion comparison operators with non-SchemaVersion types."""

    def test_lt_with_non_schema_version_returns_not_implemented(self):
        """Test __lt__ returns NotImplemented when compared with non-SchemaVersion."""
        version = SchemaVersion.V1_1
        # Comparing with a string should return NotImplemented
        result = version.__lt__("1.1")
        assert result is NotImplemented

    def test_gt_with_non_schema_version_returns_not_implemented(self):
        """Test __gt__ returns NotImplemented when compared with non-SchemaVersion."""
        version = SchemaVersion.V1_1
        # Comparing with an int should return NotImplemented
        result = version.__gt__(1)
        assert result is NotImplemented

    def test_le_with_schema_versions(self):
        """Test __le__ works correctly with SchemaVersion types."""
        assert SchemaVersion.V1_0 <= SchemaVersion.V1_1
        assert SchemaVersion.V1_1 <= SchemaVersion.V1_1
        assert not SchemaVersion.V1_2 <= SchemaVersion.V1_0

    def test_ge_with_schema_versions(self):
        """Test __ge__ works correctly with SchemaVersion types."""
        assert SchemaVersion.V1_1 >= SchemaVersion.V1_0
        assert SchemaVersion.V1_1 >= SchemaVersion.V1_1
        assert not SchemaVersion.V1_0 >= SchemaVersion.V1_2


class TestSchemaManagerEdgeCases:
    """Test edge cases and error handling in SchemaManager."""

    def test_detect_version_sqlite_error_returns_unknown(self, tmp_path):
        """Test that sqlite3.Error during detection returns UNKNOWN.

        This covers lines 194-197: sqlite3.Error handling
        """
        # Create a file that's not a valid SQLite database
        bad_db = tmp_path / "corrupt.db"
        bad_db.write_bytes(b"\x00\x01\x02\x03\x04corrupted")

        manager = SchemaManager(bad_db)
        version = manager.detect_version()

        # Should return UNKNOWN due to error (not NONE)
        assert version == SchemaVersion.UNKNOWN

    def test_has_capability_returns_false_for_invalid_version(self, tmp_path):
        """Test has_capability returns False when version is invalid.

        This covers line 250: return False when not version.is_valid
        """
        # Non-existent database returns NONE (invalid)
        manager = SchemaManager(tmp_path / "nonexistent.db")

        # Should return False for any capability check
        assert manager.has_capability(SchemaCapability.BASIC_ARCHIVING) is False
        assert manager.has_capability(SchemaCapability.FTS_SEARCH) is False

    def test_require_version_raises_for_invalid_version(self, tmp_path):
        """Test require_version raises for invalid schema version.

        This covers lines 266-271: SchemaVersionError for invalid version
        """
        # Non-existent database has NONE version (invalid)
        manager = SchemaManager(tmp_path / "nonexistent.db")

        with pytest.raises(SchemaVersionError) as exc_info:
            manager.require_version(SchemaVersion.V1_0)

        assert exc_info.value.current_version == SchemaVersion.NONE
        assert "Invalid database schema" in str(exc_info.value)
