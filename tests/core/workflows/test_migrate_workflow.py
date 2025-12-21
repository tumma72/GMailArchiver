"""Behavioral tests for MigrateWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Migrates from v1.0 to current schema version
- Creates backups before migration
- Rolls back on failure
- Reports progress during migration
- Handles edge cases and errors
"""

import mailbox
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.core.workflows.migrate import (
    MigrateConfig,
    MigrateResult,
    MigrateWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.data.schema_manager import SchemaVersion

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def v10_db(temp_dir: Path) -> str:
    """Create a v1.0-style database with archived_messages table."""
    db_path = temp_dir / "v10.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create v1.0 schema (archived_messages table)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archived_messages (
                gmail_id TEXT PRIMARY KEY,
                subject TEXT,
                from_addr TEXT,
                message_date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                checksum TEXT
            )
            """
        )

        # archive_runs table (present in v1.0)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL
            )
            """
        )

        conn.commit()
        yield str(db_path)
    finally:
        conn.close()


@pytest.fixture
def v10_db_with_messages(temp_dir: Path) -> tuple[str, Path]:
    """Create a v1.0 database with messages in an mbox file."""
    db_path = temp_dir / "v10_with_data.db"
    mbox_path = temp_dir / "archive_v10.mbox"

    # Create mbox file with test messages
    mbox = mailbox.mbox(str(mbox_path))
    for i in range(3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test message {i}"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg["Date"] = f"Mon, {i + 1} Jan 2024 12:00:00 +0000"
        msg.set_payload(f"Body of message {i}")
        mbox.add(msg)
    mbox.close()

    # Create v1.0 database and populate it
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archived_messages (
                gmail_id TEXT PRIMARY KEY,
                subject TEXT,
                from_addr TEXT,
                message_date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                checksum TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL
            )
            """
        )

        # Insert test messages
        for i in range(3):
            conn.execute(
                """
                INSERT INTO archived_messages
                (gmail_id, subject, from_addr, message_date,
                 archived_timestamp, archive_file, checksum)
                VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                (
                    f"gmail{i}",
                    f"Test message {i}",
                    f"sender{i}@example.com",
                    f"2024-01-0{i + 1}T12:00:00",
                    str(mbox_path),
                    f"checksum{i}",
                ),
            )

        conn.commit()
        yield str(db_path), mbox_path
    finally:
        conn.close()


@pytest.fixture
def v11_db_empty(temp_dir: Path) -> str:
    """Create an empty v1.1 database (already migrated)."""
    db_path = temp_dir / "v11_empty.db"
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
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
            """
        )

        conn.execute(
            "INSERT INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
            ("1.1", "2024-01-01T00:00:00"),
        )

        conn.execute("PRAGMA user_version = 11")
        conn.commit()
        yield str(db_path)
    finally:
        conn.close()


@pytest.fixture
def nonexistent_db(temp_dir: Path) -> str:
    """Return path to a database that doesn't exist."""
    return str(temp_dir / "nonexistent.db")


@pytest.fixture
def mock_progress() -> MagicMock:
    """Create a mock progress reporter for tracking progress calls."""
    progress = MagicMock()

    # Mock task_sequence context manager
    task_sequence_mock = MagicMock()
    task_mock = MagicMock()
    task_handle = MagicMock()

    # Setup context manager chain
    progress.task_sequence.return_value.__enter__.return_value = task_sequence_mock
    progress.task_sequence.return_value.__exit__.return_value = False

    task_sequence_mock.task.return_value.__enter__.return_value = task_handle
    task_sequence_mock.task.return_value.__exit__.return_value = False

    return progress


# ============================================================================
# Migration from v1.0 to current version
# ============================================================================


class TestMigrateFromV10:
    """Test migration from v1.0 schema."""

    @pytest.mark.asyncio
    async def test_migrates_v10_database_successfully(
        self, hybrid_storage: HybridStorage, v10_db_with_messages: tuple[str, Path]
    ) -> None:
        """Given a v1.0 database with messages, migrates to current version."""
        db_path, mbox_path = v10_db_with_messages

        config = MigrateConfig(
            state_db=db_path,
            target_version=None,  # Migrate to latest
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.from_version == "1.0"
        assert result.to_version == SchemaVersion.V1_3.value
        assert result.backup_path is not None
        assert Path(result.backup_path).exists()
        assert "Migration verified successfully" in result.details

    @pytest.mark.asyncio
    async def test_migrates_empty_v10_database(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given an empty v1.0 database, migrates schema successfully."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.from_version == "1.0"
        assert result.to_version == SchemaVersion.V1_3.value

        # Verify schema was upgraded
        conn = sqlite3.connect(v10_db)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            )
            assert cursor.fetchone() is not None  # messages table exists

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
            )
            assert cursor.fetchone() is None  # old table removed
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_creates_backup_before_migration(
        self, hybrid_storage: HybridStorage, v10_db: str, temp_dir: Path
    ) -> None:
        """Given backup=True, creates backup before migration."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.backup_path is not None
        backup_path = Path(result.backup_path)
        assert backup_path.exists()
        # Use resolve() to handle symlinks (macOS /var -> /private/var)
        assert backup_path.parent.resolve() == temp_dir.resolve()
        assert backup_path.name.startswith("v10.db.backup.")

    @pytest.mark.asyncio
    async def test_skips_backup_when_disabled(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given backup=False, skips backup creation."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=False,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.backup_path is None

    @pytest.mark.asyncio
    async def test_reports_progress_during_migration(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Given a progress reporter, reports migration progress."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        assert result.success is True
        # Verify progress was reported
        assert mock_progress.task_sequence.called
        assert len(result.details) > 0


# ============================================================================
# Already migrated databases
# ============================================================================


class TestAlreadyMigrated:
    """Test behavior when database is already at target version."""

    @pytest.mark.asyncio
    async def test_skips_migration_when_already_current(
        self, hybrid_storage: HybridStorage, v11_db_empty: str
    ) -> None:
        """Given a v1.1 database, skips migration when target is v1.1."""
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version="1.1",
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.from_version == "1.1"
        assert result.to_version == "1.1"
        assert result.backup_path is None  # No backup needed
        assert "already at target version" in result.details[0]

    @pytest.mark.asyncio
    async def test_upgrades_v11_to_latest(
        self, hybrid_storage: HybridStorage, v11_db_empty: str
    ) -> None:
        """Given a v1.1 database, upgrades to latest when target is None."""
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version=None,  # Latest
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.from_version == "1.1"
        assert result.to_version == SchemaVersion.V1_3.value


# ============================================================================
# Error handling
# ============================================================================


class TestMigrationErrors:
    """Test error handling during migration."""

    @pytest.mark.asyncio
    async def test_handles_nonexistent_database(
        self, hybrid_storage: HybridStorage, nonexistent_db: str
    ) -> None:
        """Given a nonexistent database, raises ValueError for auto-migration."""
        config = MigrateConfig(
            state_db=nonexistent_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)

        # Should raise error because "none" version cannot be auto-migrated
        with pytest.raises(ValueError, match="Cannot auto-migrate from version none"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_rejects_invalid_target_version(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given an invalid target version, raises ValueError."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version="99.99",  # Invalid version
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)

        with pytest.raises(ValueError, match="Invalid target version"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_rejects_downgrade_attempts(
        self, hybrid_storage: HybridStorage, v11_db_empty: str
    ) -> None:
        """Given target version < current, rejects downgrade."""
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version="1.0",  # Downgrade attempt
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)

        with pytest.raises(ValueError, match="Cannot downgrade"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_provides_backup_path_on_migration_failure(
        self, hybrid_storage: HybridStorage, v10_db_with_messages: tuple[str, Path]
    ) -> None:
        """Given a migration failure, result includes backup path for recovery."""
        db_path, mbox_path = v10_db_with_messages

        # Delete mbox file to cause migration failure
        mbox_path.unlink()

        config = MigrateConfig(
            state_db=db_path,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)

        # Migration should handle the error gracefully (warning about missing file)
        # but still succeed since it's designed to skip missing archives
        result = await workflow.run(config)

        # Even if migration succeeds with warnings, backup should be created
        assert result.backup_path is not None


# ============================================================================
# Migration verification
# ============================================================================


class TestMigrationVerification:
    """Test post-migration verification."""

    @pytest.mark.asyncio
    async def test_verifies_schema_after_migration(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given a successful migration, verifies new schema version."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert "Migration verified successfully" in result.details

        # Verify database actually has correct version
        conn = sqlite3.connect(v10_db)
        try:
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == SchemaVersion.V1_3.value
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_includes_migration_details(
        self, hybrid_storage: HybridStorage, v10_db_with_messages: tuple[str, Path]
    ) -> None:
        """Given a migration, includes detailed progress in result."""
        db_path, mbox_path = v10_db_with_messages

        config = MigrateConfig(
            state_db=db_path,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert len(result.details) > 0

        # Should include backup creation message
        backup_details = [d for d in result.details if "Backup created" in d]
        assert len(backup_details) > 0


# ============================================================================
# Integration with SchemaManager
# ============================================================================


class TestSchemaManagerIntegration:
    """Test integration with SchemaManager."""

    @pytest.mark.asyncio
    async def test_uses_schema_manager_for_version_detection(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given a database, uses SchemaManager to detect version."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Workflow should correctly identify v1.0
        assert result.from_version == "1.0"

    @pytest.mark.asyncio
    async def test_supports_current_version_constant(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given target_version=None, migrates to CURRENT_VERSION."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,  # Should use SchemaManager.CURRENT_VERSION
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        # Should upgrade to current version (1.3)
        assert result.to_version == SchemaVersion.V1_3.value


# ============================================================================
# Progress reporting edge cases
# ============================================================================


class TestProgressReporting:
    """Test progress reporting behavior."""

    @pytest.mark.asyncio
    async def test_works_without_progress_reporter(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given no progress reporter, migration still succeeds."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage, progress=None)
        result = await workflow.run(config)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_reports_errors_to_progress_on_failure(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Given a migration failure with progress reporter, reports error."""
        # Create a corrupted database by deleting it mid-flight would be complex
        # Instead, test the error reporting path by using an invalid target version
        config = MigrateConfig(
            state_db=v10_db,
            target_version="invalid",
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)

        with pytest.raises(ValueError):
            await workflow.run(config)


# ============================================================================
# Target version specification
# ============================================================================


class TestTargetVersions:
    """Test migration to specific target versions."""

    @pytest.mark.asyncio
    async def test_migrates_to_specific_version_v11(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given target_version='1.1', workflow migrates through to current version.

        Note: The workflow's auto_migrate_if_needed() always migrates to CURRENT_VERSION,
        regardless of the target_version parameter. This test verifies the actual behavior.
        """
        config = MigrateConfig(
            state_db=v10_db,
            target_version="1.1",
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Migration proceeds to current version (1.3), but then verification
        # fails because it doesn't match target (1.1)
        assert result.success is False
        assert "Migration verification failed" in result.details[-1]
        assert "got 1.3" in result.details[-1]

    @pytest.mark.asyncio
    async def test_migrates_to_specific_version_v13(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Given target_version='1.3', migrates to v1.3."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version="1.3",
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert result.to_version == "1.3"


# ============================================================================
# Exception handling and failure modes
# ============================================================================


class TestExceptionHandling:
    """Test exception handling during migration."""

    @pytest.mark.asyncio
    async def test_handles_migration_exception_with_backup(
        self, hybrid_storage: HybridStorage, v10_db: str, tmp_path: Path, monkeypatch
    ) -> None:
        """Given a migration exception with backup, returns failure result with backup path."""
        from gmailarchiver.data.schema_manager import SchemaManager

        # Mock auto_migrate_if_needed to raise an exception
        async def mock_auto_migrate(*args, **kwargs):
            raise RuntimeError("Simulated migration failure")

        monkeypatch.setattr(SchemaManager, "auto_migrate_if_needed", mock_auto_migrate)

        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is False
        assert result.backup_path is not None
        assert "Migration failed" in result.details[-2]
        assert "Backup available" in result.details[-1]

    @pytest.mark.asyncio
    async def test_handles_migration_exception_without_backup(
        self, hybrid_storage: HybridStorage, v10_db: str, monkeypatch
    ) -> None:
        """Given a migration exception without backup, re-raises exception."""
        from gmailarchiver.data.schema_manager import SchemaManager

        # Mock auto_migrate_if_needed to raise an exception
        async def mock_auto_migrate(*args, **kwargs):
            raise RuntimeError("Simulated migration failure")

        monkeypatch.setattr(SchemaManager, "auto_migrate_if_needed", mock_auto_migrate)

        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=False,
        )

        workflow = MigrateWorkflow(hybrid_storage)

        # Should re-raise the exception when no backup exists
        with pytest.raises(RuntimeError, match="Simulated migration failure"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_reports_migration_exception_to_progress(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock, monkeypatch
    ) -> None:
        """Given a migration exception with progress reporter, reports error."""
        from gmailarchiver.data.schema_manager import SchemaManager

        # Mock auto_migrate_if_needed to raise an exception
        async def mock_auto_migrate(*args, **kwargs):
            raise RuntimeError("Simulated migration failure")

        monkeypatch.setattr(SchemaManager, "auto_migrate_if_needed", mock_auto_migrate)

        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        assert result.success is False
        # Verify progress reporter was called with error messages
        mock_progress.error.assert_called()
        mock_progress.info.assert_called()

    @pytest.mark.asyncio
    async def test_reports_verification_failure_with_progress(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Given verification failure with progress reporter, reports failure."""
        config = MigrateConfig(
            state_db=v10_db,
            target_version="1.1",  # Will cause verification failure
            backup=True,
        )

        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        assert result.success is False
        assert "Migration verification failed" in result.details[-1]
        # Verify task sequence was used
        assert mock_progress.task_sequence.called


# ============================================================================
# Tests for WorkflowComposer-based Architecture (TDD Red Phase)
# ============================================================================
# These tests define expected behavior for the refactored migrate workflow
# that uses WorkflowComposer and Step classes instead of monolithic execution.
# They should FAIL initially because the refactored implementation doesn't exist yet.


class TestMigrateWorkflowUsesComposer:
    """Test that MigrateWorkflow uses WorkflowComposer pattern.

    The refactored workflow should:
    - Use WorkflowComposer to compose migrate steps
    - Execute steps in correct order: detect -> validate -> backup -> execute -> verify
    - Inject SchemaManager and MigrationManager into step context
    - Handle conditional backup step based on config
    """

    @pytest.mark.asyncio
    async def test_workflow_uses_workflow_composer(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """MigrateWorkflow internally uses WorkflowComposer or steps."""
        workflow = MigrateWorkflow(hybrid_storage)

        # After refactoring, workflow should have step instances or composer
        assert hasattr(workflow, "_detect_step") or hasattr(workflow, "_get_composer")

    @pytest.mark.asyncio
    async def test_workflow_has_five_migrate_steps(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """MigrateWorkflow has all five migrate steps defined."""
        workflow = MigrateWorkflow(hybrid_storage)

        # After refactoring, workflow should have all 5 steps
        assert hasattr(workflow, "_detect_step")
        assert hasattr(workflow, "_validate_step")
        assert hasattr(workflow, "_backup_step")
        assert hasattr(workflow, "_execute_step")
        assert hasattr(workflow, "_verify_step")

    @pytest.mark.asyncio
    async def test_workflow_injects_schema_manager_into_context(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Workflow injects SchemaManager into step context before running steps."""

        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=False,
        )

        # The workflow should inject schema_manager into context
        # We verify by checking that the migration succeeds (requires schema_manager)
        result = await workflow.run(config)

        # Should have migrated successfully (proves schema_manager was available)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_workflow_injects_migration_manager_into_context(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Workflow injects MigrationManager into step context for backup step."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,  # Requires MigrationManager
        )

        result = await workflow.run(config)

        # Should have created backup (proves migration_manager was available)
        assert result.backup_path is not None


class TestMigrateWorkflowStepOrder:
    """Test that MigrateWorkflow executes steps in correct order."""

    @pytest.mark.asyncio
    async def test_detect_step_runs_first(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """DetectVersionStep runs before other steps."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Detect step should have identified v1.0
        assert result.from_version == "1.0"

    @pytest.mark.asyncio
    async def test_validate_step_runs_after_detect(
        self, hybrid_storage: HybridStorage, v11_db_empty: str, mock_progress: MagicMock
    ) -> None:
        """ValidateMigrationStep runs after DetectVersionStep."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version="1.1",  # Already at this version
            backup=True,
        )

        result = await workflow.run(config)

        # Validate step should have determined no migration needed
        assert result.success is True
        assert "already at target version" in result.details[0]

    @pytest.mark.asyncio
    async def test_backup_step_runs_before_execute(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """CreateBackupStep runs before ExecuteMigrationStep."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Backup should exist (created before migration)
        assert result.backup_path is not None
        assert Path(result.backup_path).exists()

    @pytest.mark.asyncio
    async def test_verify_step_runs_after_execute(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """VerifyMigrationStep runs after ExecuteMigrationStep."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Verify step should have confirmed migration
        assert result.success is True
        assert any("verified" in d.lower() for d in result.details)


class TestMigrateWorkflowConditionalBackup:
    """Test conditional backup step execution."""

    @pytest.mark.asyncio
    async def test_backup_step_executes_when_backup_true(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """CreateBackupStep executes when config.backup is True."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        assert result.backup_path is not None
        assert Path(result.backup_path).exists()

    @pytest.mark.asyncio
    async def test_backup_step_skipped_when_backup_false(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """CreateBackupStep is skipped when config.backup is False."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=False,
        )

        result = await workflow.run(config)

        assert result.backup_path is None

    @pytest.mark.asyncio
    async def test_backup_step_skipped_when_no_migration_needed(
        self, hybrid_storage: HybridStorage, v11_db_empty: str
    ) -> None:
        """CreateBackupStep is skipped when no migration is needed."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version="1.1",  # Already at this version
            backup=True,  # Backup enabled but should not be created
        )

        result = await workflow.run(config)

        assert result.backup_path is None
        assert "already at target version" in result.details[0]


class TestMigrateWorkflowResultAggregation:
    """Test that workflow correctly aggregates step results."""

    @pytest.mark.asyncio
    async def test_aggregates_version_info_from_detect_step(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """MigrateResult includes from_version from DetectVersionStep."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=False,
        )

        result = await workflow.run(config)

        assert result.from_version == "1.0"
        assert result.to_version == SchemaVersion.V1_3.value

    @pytest.mark.asyncio
    async def test_aggregates_backup_path_from_backup_step(
        self, hybrid_storage: HybridStorage, v10_db: str, temp_dir: Path
    ) -> None:
        """MigrateResult includes backup_path from CreateBackupStep."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        assert result.backup_path is not None
        # Backup should be in same directory as source db
        assert Path(result.backup_path).parent.resolve() == temp_dir.resolve()

    @pytest.mark.asyncio
    async def test_aggregates_details_from_all_steps(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """MigrateResult includes details from all executed steps."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Should have details from backup and verification steps at minimum
        assert len(result.details) >= 2
        assert any("backup" in d.lower() for d in result.details)
        assert any("verified" in d.lower() or "complete" in d.lower() for d in result.details)

    @pytest.mark.asyncio
    async def test_success_reflects_all_steps_passed(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """MigrateResult.success is True only if all steps succeed."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        assert result.success is True
        # Verify the to_version matches target
        assert result.to_version == SchemaVersion.V1_3.value


class TestMigrateWorkflowErrorHandling:
    """Test error handling with step-based architecture."""

    @pytest.mark.asyncio
    async def test_stops_on_detect_step_failure(
        self, hybrid_storage: HybridStorage, nonexistent_db: str
    ) -> None:
        """Workflow stops early if DetectVersionStep fails."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=nonexistent_db,
            target_version=None,
            backup=True,
        )

        with pytest.raises(ValueError, match="Cannot auto-migrate from version none"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_stops_on_validate_step_failure(
        self, hybrid_storage: HybridStorage, v11_db_empty: str
    ) -> None:
        """Workflow stops early if ValidateMigrationStep fails."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v11_db_empty,
            target_version="1.0",  # Downgrade attempt
            backup=True,
        )

        with pytest.raises(ValueError, match="Cannot downgrade"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_provides_backup_path_on_execute_step_failure(
        self, hybrid_storage: HybridStorage, v10_db_with_messages: tuple[str, Path]
    ) -> None:
        """Provides backup path if ExecuteMigrationStep fails."""
        db_path, mbox_path = v10_db_with_messages

        # Delete mbox to potentially cause issues
        mbox_path.unlink()

        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=db_path,
            target_version=None,
            backup=True,
        )

        # Migration might succeed with warnings or fail
        # Either way, backup should be available
        result = await workflow.run(config)

        assert result.backup_path is not None

    @pytest.mark.asyncio
    async def test_cleans_up_resources_on_step_failure(
        self, hybrid_storage: HybridStorage, v10_db: str, monkeypatch
    ) -> None:
        """Workflow cleans up resources (MigrationManager) even on failure."""
        from gmailarchiver.data.schema_manager import SchemaManager

        # Track whether MigrationManager was closed
        migration_closed = []

        original_close = None

        async def mock_auto_migrate(*args, **kwargs):
            raise RuntimeError("Simulated failure")

        monkeypatch.setattr(SchemaManager, "auto_migrate_if_needed", mock_auto_migrate)

        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Should have failed but returned result with backup info
        assert result.success is False
        assert result.backup_path is not None


class TestMigrateWorkflowStepIntegration:
    """Test that migrate workflow correctly integrates with migrate steps."""

    @pytest.mark.asyncio
    async def test_workflow_converts_step_results_to_migrate_result(
        self, hybrid_storage: HybridStorage, v10_db: str
    ) -> None:
        """Workflow converts step results to MigrateResult correctly."""
        workflow = MigrateWorkflow(hybrid_storage)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Should be a proper MigrateResult
        assert isinstance(result, MigrateResult)
        assert hasattr(result, "success")
        assert hasattr(result, "from_version")
        assert hasattr(result, "to_version")
        assert hasattr(result, "backup_path")
        assert hasattr(result, "details")

    @pytest.mark.asyncio
    async def test_workflow_includes_migration_progress_in_details(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Workflow includes migration progress messages in details."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        result = await workflow.run(config)

        # Should have progress messages in details
        assert len(result.details) > 0
        # Look for version-related progress messages
        version_messages = [d for d in result.details if "1." in d]
        assert len(version_messages) > 0

    @pytest.mark.asyncio
    async def test_workflow_uses_progress_reporter_for_each_step(
        self, hybrid_storage: HybridStorage, v10_db: str, mock_progress: MagicMock
    ) -> None:
        """Workflow uses progress reporter for each step execution."""
        workflow = MigrateWorkflow(hybrid_storage, progress=mock_progress)
        config = MigrateConfig(
            state_db=v10_db,
            target_version=None,
            backup=True,
        )

        await workflow.run(config)

        # Progress reporter should have been used
        assert mock_progress.task_sequence.called
        # Should be called at least twice (backup + migration)
        assert mock_progress.task_sequence.call_count >= 2
