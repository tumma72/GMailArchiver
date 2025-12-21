"""Tests for migrate steps - TDD Red Phase.

These tests define the expected behavior for:
- DetectVersionStep: Detects current and target schema versions
- ValidateMigrationStep: Validates migration is possible
- CreateBackupStep: Creates database backup before migration
- ExecuteMigrationStep: Executes the schema migration
- VerifyMigrationStep: Verifies migration completed successfully

All tests should FAIL initially because the steps don't exist yet.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.data.schema_manager import SchemaVersion

# Import the steps that don't exist yet - these imports will fail
# until implementation is complete. We use try/except to allow
# tests to be collected, but they will fail when the module doesn't exist.
try:
    from gmailarchiver.core.workflows.steps.migrate import (
        CreateBackupStep,
        DetectVersionStep,
        ExecuteMigrationStep,
        ValidateMigrationStep,
        VerifyMigrationStep,
    )
except ImportError:
    # Mark module as missing for pytest.skip
    DetectVersionStep = None
    ValidateMigrationStep = None
    CreateBackupStep = None
    ExecuteMigrationStep = None
    VerifyMigrationStep = None

# Skip all tests in this module if the migrate steps module doesn't exist
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        DetectVersionStep is None,
        reason="migrate steps module not implemented yet (TDD Red Phase)",
    ),
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_schema_manager() -> AsyncMock:
    """Create a mock SchemaManager for testing."""
    manager = AsyncMock()
    # Default: database at v1.1, can migrate to v1.3
    manager.detect_version.return_value = SchemaVersion.V1_1
    manager.can_auto_migrate.return_value = True
    manager.needs_migration.return_value = True
    manager.CURRENT_VERSION = SchemaVersion.V1_3
    manager.auto_migrate_if_needed.return_value = True
    # invalidate_cache is a sync method in the real SchemaManager,
    # so we must use MagicMock to avoid unawaited coroutine warnings
    manager.invalidate_cache = MagicMock(return_value=None)
    return manager


@pytest.fixture
def mock_migration_manager() -> AsyncMock:
    """Create a mock MigrationManager for testing."""
    manager = AsyncMock()
    manager.create_backup.return_value = Path("/tmp/backup.db")
    manager._close.return_value = None
    return manager


@pytest.fixture
def mock_progress() -> MagicMock:
    """Create a mock progress reporter for testing."""
    progress = MagicMock()

    # Create mock task sequence with proper context manager
    task_seq = MagicMock()
    progress.task_sequence.return_value.__enter__ = MagicMock(return_value=task_seq)
    progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)

    # Create mock task handle
    task_handle = MagicMock()
    task_seq.task.return_value.__enter__ = MagicMock(return_value=task_handle)
    task_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    return progress


@pytest.fixture
def context_with_schema_manager(mock_schema_manager: AsyncMock) -> StepContext:
    """Create a StepContext with mock SchemaManager injected."""
    context = StepContext()
    context.set("schema_manager", mock_schema_manager)
    return context


@pytest.fixture
def context_with_managers(
    mock_schema_manager: AsyncMock, mock_migration_manager: AsyncMock
) -> StepContext:
    """Create a StepContext with both managers injected."""
    context = StepContext()
    context.set("schema_manager", mock_schema_manager)
    context.set("migration_manager", mock_migration_manager)
    return context


@pytest.fixture
def migrate_config() -> dict:
    """Create a sample migrate configuration."""
    return {
        "state_db": "/path/to/test.db",
        "target_version": None,  # Migrate to latest
        "backup": True,
    }


# ============================================================================
# Test: DetectVersionStep
# ============================================================================


class TestDetectVersionStep:
    """Test DetectVersionStep execution."""

    async def test_can_instantiate(self) -> None:
        """DetectVersionStep can be instantiated."""
        step = DetectVersionStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """DetectVersionStep has the correct name attribute."""
        step = DetectVersionStep()
        assert step.name == "detect_version"

    async def test_has_correct_description(self) -> None:
        """DetectVersionStep has the correct description attribute."""
        step = DetectVersionStep()
        assert step.description == "Detecting schema version"

    async def test_execute_detects_current_version(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute detects current schema version."""
        step = DetectVersionStep()

        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_1

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        mock_schema_manager.detect_version.assert_called_once()

    async def test_stores_current_version_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores current_version in context."""
        step = DetectVersionStep()

        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_0

        await step.execute(context_with_schema_manager, None)

        stored_version = context_with_schema_manager.get("current_version")
        assert stored_version is not None
        assert stored_version == SchemaVersion.V1_0

    async def test_stores_target_version_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores target_version in context."""
        step = DetectVersionStep()

        mock_schema_manager.CURRENT_VERSION = SchemaVersion.V1_3

        await step.execute(context_with_schema_manager, None)

        stored_version = context_with_schema_manager.get("target_version")
        assert stored_version is not None
        assert stored_version == SchemaVersion.V1_3

    async def test_uses_config_target_version_when_provided(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute uses config.target_version when provided."""
        step = DetectVersionStep()

        # Set config with explicit target version
        context_with_schema_manager.set("config", {"target_version": "1.2"})

        await step.execute(context_with_schema_manager, None)

        stored_version = context_with_schema_manager.get("target_version")
        assert stored_version == SchemaVersion.V1_2

    async def test_fails_without_schema_manager_in_context(self) -> None:
        """Execute fails gracefully when SchemaManager not in context."""
        step = DetectVersionStep()
        context = StepContext()  # No schema_manager injected

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "SchemaManager not found in context"

    async def test_handles_schema_manager_exception(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute handles exceptions from SchemaManager."""
        step = DetectVersionStep()

        mock_schema_manager.detect_version.side_effect = Exception("Database error")

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Version detection failed" in result.error
        assert "Database error" in result.error

    async def test_handles_no_progress_reporter(
        self, context_with_schema_manager: StepContext
    ) -> None:
        """Step works without progress reporter."""
        step = DetectVersionStep()

        result = await step.execute(context_with_schema_manager, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_schema_manager: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = DetectVersionStep()

        result = await step.execute(context_with_schema_manager, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_versions(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute result data contains both versions."""
        step = DetectVersionStep()

        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_1
        mock_schema_manager.CURRENT_VERSION = SchemaVersion.V1_3

        result = await step.execute(context_with_schema_manager, None)

        assert result.data is not None
        assert "current_version" in result.data
        assert "target_version" in result.data
        assert result.data["current_version"] == SchemaVersion.V1_1
        assert result.data["target_version"] == SchemaVersion.V1_3

    async def test_detects_v10_database(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Correctly identifies v1.0 database."""
        step = DetectVersionStep()

        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_0

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        assert context_with_schema_manager.get("current_version") == SchemaVersion.V1_0


# ============================================================================
# Test: ValidateMigrationStep
# ============================================================================


class TestValidateMigrationStep:
    """Test ValidateMigrationStep execution."""

    async def test_can_instantiate(self) -> None:
        """ValidateMigrationStep can be instantiated."""
        step = ValidateMigrationStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """ValidateMigrationStep has the correct name attribute."""
        step = ValidateMigrationStep()
        assert step.name == "validate_migration"

    async def test_has_correct_description(self) -> None:
        """ValidateMigrationStep has the correct description attribute."""
        step = ValidateMigrationStep()
        assert step.description == "Validating migration requirements"

    async def test_execute_validates_migration_possible(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute validates that migration is possible."""
        step = ValidateMigrationStep()

        # Set up context with versions from DetectVersionStep
        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        mock_schema_manager.can_auto_migrate.assert_called_once()

    async def test_returns_no_migration_needed_when_versions_equal(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute indicates no migration needed when at target version."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        assert result.data is not None
        assert result.data.get("migration_needed") is False

    async def test_stores_migration_needed_flag_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores migration_needed flag in context."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        await step.execute(context_with_schema_manager, None)

        assert context_with_schema_manager.get("migration_needed") is True

    async def test_fails_when_downgrade_attempted(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute fails when target version is lower than current."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_1)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Cannot downgrade" in result.error

    async def test_fails_when_auto_migrate_not_possible(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute fails when auto-migration is not possible."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_0)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        mock_schema_manager.can_auto_migrate.return_value = False

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Cannot auto-migrate" in result.error

    async def test_fails_without_schema_manager_in_context(self) -> None:
        """Execute fails gracefully when SchemaManager not in context."""
        step = ValidateMigrationStep()
        context = StepContext()

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "SchemaManager not found in context"

    async def test_fails_without_versions_in_context(
        self, context_with_schema_manager: StepContext
    ) -> None:
        """Execute fails when versions not set by previous step."""
        step = ValidateMigrationStep()
        # Don't set current_version or target_version

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "current_version not found" in result.error

    async def test_handles_schema_manager_exception(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute handles exceptions from SchemaManager."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        mock_schema_manager.can_auto_migrate.side_effect = Exception("Check failed")

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Validation failed" in result.error
        assert "Check failed" in result.error

    async def test_handles_no_progress_reporter(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Step works without progress reporter."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self,
        context_with_schema_manager: StepContext,
        mock_schema_manager: AsyncMock,
        mock_progress: MagicMock,
    ) -> None:
        """Step reports progress when provided."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_validation_details(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute result data contains validation details."""
        step = ValidateMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None)

        assert result.data is not None
        assert "migration_needed" in result.data
        assert "can_auto_migrate" in result.data


# ============================================================================
# Test: CreateBackupStep
# ============================================================================


class TestCreateBackupStep:
    """Test CreateBackupStep execution."""

    async def test_can_instantiate(self) -> None:
        """CreateBackupStep can be instantiated."""
        step = CreateBackupStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """CreateBackupStep has the correct name attribute."""
        step = CreateBackupStep()
        assert step.name == "create_backup"

    async def test_has_correct_description(self) -> None:
        """CreateBackupStep has the correct description attribute."""
        step = CreateBackupStep()
        assert step.description == "Creating database backup"

    async def test_execute_creates_backup(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute creates database backup."""
        step = CreateBackupStep()

        mock_migration_manager.create_backup.return_value = Path("/tmp/backup.db")

        result = await step.execute(context_with_managers, None)

        assert result.success is True
        mock_migration_manager.create_backup.assert_called_once()

    async def test_stores_backup_path_in_context(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute stores backup_path in context."""
        step = CreateBackupStep()

        expected_path = Path("/tmp/test_backup.db")
        mock_migration_manager.create_backup.return_value = expected_path

        await step.execute(context_with_managers, None)

        stored_path = context_with_managers.get("backup_path")
        assert stored_path is not None
        assert stored_path == expected_path

    async def test_fails_without_migration_manager_in_context(self) -> None:
        """Execute fails gracefully when MigrationManager not in context."""
        step = CreateBackupStep()
        context = StepContext()

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "MigrationManager not found in context"

    async def test_handles_backup_failure(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute handles backup creation failure."""
        step = CreateBackupStep()

        mock_migration_manager.create_backup.side_effect = OSError("Disk full")

        result = await step.execute(context_with_managers, None)

        assert result.success is False
        assert "Backup creation failed" in result.error
        assert "Disk full" in result.error

    async def test_closes_migration_manager_after_backup(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute closes MigrationManager after backup."""
        step = CreateBackupStep()

        await step.execute(context_with_managers, None)

        mock_migration_manager._close.assert_called_once()

    async def test_closes_migration_manager_on_failure(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute closes MigrationManager even on failure."""
        step = CreateBackupStep()

        mock_migration_manager.create_backup.side_effect = Exception("Backup failed")

        await step.execute(context_with_managers, None)

        mock_migration_manager._close.assert_called_once()

    async def test_handles_no_progress_reporter(self, context_with_managers: StepContext) -> None:
        """Step works without progress reporter."""
        step = CreateBackupStep()

        result = await step.execute(context_with_managers, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_managers: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = CreateBackupStep()

        result = await step.execute(context_with_managers, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_backup_path(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute result data contains backup path."""
        step = CreateBackupStep()

        expected_path = Path("/tmp/backup_2024.db")
        mock_migration_manager.create_backup.return_value = expected_path

        result = await step.execute(context_with_managers, None)

        assert result.data is not None
        assert result.data == expected_path

    async def test_skips_when_backup_disabled(
        self, context_with_managers: StepContext, mock_migration_manager: AsyncMock
    ) -> None:
        """Execute skips backup when config.backup is False."""
        step = CreateBackupStep()

        context_with_managers.set("config", {"backup": False})

        result = await step.execute(context_with_managers, None)

        assert result.success is True
        mock_migration_manager.create_backup.assert_not_called()
        assert context_with_managers.get("backup_path") is None


# ============================================================================
# Test: ExecuteMigrationStep
# ============================================================================


class TestExecuteMigrationStep:
    """Test ExecuteMigrationStep execution."""

    async def test_can_instantiate(self) -> None:
        """ExecuteMigrationStep can be instantiated."""
        step = ExecuteMigrationStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """ExecuteMigrationStep has the correct name attribute."""
        step = ExecuteMigrationStep()
        assert step.name == "execute_migration"

    async def test_has_correct_description(self) -> None:
        """ExecuteMigrationStep has the correct description attribute."""
        step = ExecuteMigrationStep()
        assert step.description == "Executing schema migration"

    async def test_execute_performs_migration(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute performs schema migration."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        mock_schema_manager.auto_migrate_if_needed.assert_called_once()

    async def test_stores_migration_success_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores migration_success in context."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)
        mock_schema_manager.auto_migrate_if_needed.return_value = True

        await step.execute(context_with_schema_manager, None)

        assert context_with_schema_manager.get("migration_success") is True

    async def test_skips_when_no_migration_needed(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute skips migration when not needed."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("migration_needed", False)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        mock_schema_manager.auto_migrate_if_needed.assert_not_called()
        assert context_with_schema_manager.get("migration_success") is True

    async def test_handles_migration_failure(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute handles migration failure."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)
        mock_schema_manager.auto_migrate_if_needed.return_value = False

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Migration did not complete" in result.error

    async def test_handles_migration_exception(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute handles exceptions during migration."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)
        mock_schema_manager.auto_migrate_if_needed.side_effect = Exception("Migration error")

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Migration failed" in result.error
        assert "Migration error" in result.error

    async def test_fails_without_schema_manager_in_context(self) -> None:
        """Execute fails gracefully when SchemaManager not in context."""
        step = ExecuteMigrationStep()
        context = StepContext()
        context.set("migration_needed", True)

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "SchemaManager not found in context"

    async def test_passes_progress_callback(
        self,
        context_with_schema_manager: StepContext,
        mock_schema_manager: AsyncMock,
        mock_progress: MagicMock,
    ) -> None:
        """Execute passes progress callback to schema manager."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)

        await step.execute(context_with_schema_manager, None, progress=mock_progress)

        # Verify auto_migrate_if_needed was called with a progress_callback
        call_kwargs = mock_schema_manager.auto_migrate_if_needed.call_args.kwargs
        assert "progress_callback" in call_kwargs
        assert call_kwargs["progress_callback"] is not None

    async def test_handles_no_progress_reporter(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Step works without progress reporter."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("migration_needed", False)

        result = await step.execute(context_with_schema_manager, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self,
        context_with_schema_manager: StepContext,
        mock_schema_manager: AsyncMock,
        mock_progress: MagicMock,
    ) -> None:
        """Step reports progress when provided."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)

        result = await step.execute(context_with_schema_manager, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_migration_result(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute result data contains migration result."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)
        mock_schema_manager.auto_migrate_if_needed.return_value = True

        result = await step.execute(context_with_schema_manager, None)

        assert result.data is not None
        assert result.data.get("success") is True

    async def test_stores_migration_details_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores migration details in context."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)

        await step.execute(context_with_schema_manager, None)

        details = context_with_schema_manager.get("migration_details")
        assert details is not None
        assert isinstance(details, list)

    async def test_uses_backup_path_from_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute uses backup_path from context for error recovery info."""
        step = ExecuteMigrationStep()

        context_with_schema_manager.set("current_version", SchemaVersion.V1_1)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_needed", True)
        context_with_schema_manager.set("backup_path", Path("/tmp/backup.db"))
        mock_schema_manager.auto_migrate_if_needed.side_effect = Exception("Migration failed")

        result = await step.execute(context_with_schema_manager, None)

        # Error should mention backup path for recovery
        assert result.success is False
        assert "backup" in result.error.lower() or result.metadata.get("backup_path")


# ============================================================================
# Test: VerifyMigrationStep
# ============================================================================


class TestVerifyMigrationStep:
    """Test VerifyMigrationStep execution."""

    async def test_can_instantiate(self) -> None:
        """VerifyMigrationStep can be instantiated."""
        step = VerifyMigrationStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """VerifyMigrationStep has the correct name attribute."""
        step = VerifyMigrationStep()
        assert step.name == "verify_migration"

    async def test_has_correct_description(self) -> None:
        """VerifyMigrationStep has the correct description attribute."""
        step = VerifyMigrationStep()
        assert step.description == "Verifying migration success"

    async def test_execute_verifies_migration(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute verifies migration completed successfully."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.invalidate_cache.return_value = None
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        # Should invalidate cache and re-detect
        mock_schema_manager.invalidate_cache.assert_called_once()
        # detect_version called at least once for verification
        mock_schema_manager.detect_version.assert_called()

    async def test_stores_verification_passed_in_context(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute stores verification_passed in context."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        await step.execute(context_with_schema_manager, None)

        assert context_with_schema_manager.get("verification_passed") is True

    async def test_fails_when_version_mismatch(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute fails when detected version doesn't match target."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_1  # Wrong!

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "verification failed" in result.error.lower()
        assert context_with_schema_manager.get("verification_passed") is False

    async def test_skips_verification_when_migration_not_performed(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute skips verification when no migration was performed."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("migration_success", True)
        context_with_schema_manager.set("migration_needed", False)
        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is True
        # Should not invalidate cache if no migration happened
        assert context_with_schema_manager.get("verification_passed") is True

    async def test_fails_without_schema_manager_in_context(self) -> None:
        """Execute fails gracefully when SchemaManager not in context."""
        step = VerifyMigrationStep()
        context = StepContext()
        context.set("migration_success", True)
        context.set("target_version", SchemaVersion.V1_3)

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "SchemaManager not found in context"

    async def test_fails_without_target_version_in_context(
        self, context_with_schema_manager: StepContext
    ) -> None:
        """Execute fails when target_version not set."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("migration_success", True)
        # Don't set target_version

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "target_version not found" in result.error

    async def test_handles_schema_manager_exception(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute handles exceptions from SchemaManager."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.side_effect = Exception("Database error")

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        assert "Verification failed" in result.error
        assert "Database error" in result.error

    async def test_handles_no_progress_reporter(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Step works without progress reporter."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        result = await step.execute(context_with_schema_manager, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self,
        context_with_schema_manager: StepContext,
        mock_schema_manager: AsyncMock,
        mock_progress: MagicMock,
    ) -> None:
        """Step reports progress when provided."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        result = await step.execute(context_with_schema_manager, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_verification_details(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute result data contains verification details."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        result = await step.execute(context_with_schema_manager, None)

        assert result.data is not None
        assert "verified_version" in result.data
        assert result.data["verified_version"] == SchemaVersion.V1_3

    async def test_reports_version_mismatch_details(
        self, context_with_schema_manager: StepContext, mock_schema_manager: AsyncMock
    ) -> None:
        """Execute reports expected vs actual version on mismatch."""
        step = VerifyMigrationStep()

        context_with_schema_manager.set("target_version", SchemaVersion.V1_3)
        context_with_schema_manager.set("migration_success", True)
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_2

        result = await step.execute(context_with_schema_manager, None)

        assert result.success is False
        # Error should mention both expected and actual versions
        assert "1.3" in result.error or "V1_3" in result.error
        assert "1.2" in result.error or "V1_2" in result.error


# ============================================================================
# Test: Step Integration
# ============================================================================


class TestMigrateStepsIntegration:
    """Test migrate steps work correctly together."""

    async def test_all_steps_share_schema_manager_from_context(
        self, mock_schema_manager: AsyncMock, mock_migration_manager: AsyncMock
    ) -> None:
        """All migrate steps can share the same SchemaManager from context."""
        context = StepContext()
        context.set("schema_manager", mock_schema_manager)
        context.set("migration_manager", mock_migration_manager)
        context.set("config", {"backup": True})

        # Set up mock responses
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_1
        mock_schema_manager.can_auto_migrate.return_value = True
        mock_schema_manager.auto_migrate_if_needed.return_value = True
        mock_migration_manager.create_backup.return_value = Path("/tmp/backup.db")

        detect_step = DetectVersionStep()
        validate_step = ValidateMigrationStep()
        backup_step = CreateBackupStep()
        execute_step = ExecuteMigrationStep()
        verify_step = VerifyMigrationStep()

        r1 = await detect_step.execute(context, None)
        r2 = await validate_step.execute(context, None)
        r3 = await backup_step.execute(context, None)

        # Update for successful migration before execute
        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_3

        r4 = await execute_step.execute(context, None)
        r5 = await verify_step.execute(context, None)

        assert r1.success is True
        assert r2.success is True
        assert r3.success is True
        assert r4.success is True
        assert r5.success is True

        # All results stored in context
        assert context.get("current_version") is not None
        assert context.get("target_version") is not None
        assert context.get("migration_needed") is not None
        assert context.get("backup_path") is not None
        assert context.get("migration_success") is not None
        assert context.get("verification_passed") is not None

    async def test_steps_follow_protocol(self) -> None:
        """All migrate steps follow the Step protocol."""
        detect_step = DetectVersionStep()
        validate_step = ValidateMigrationStep()
        backup_step = CreateBackupStep()
        execute_step = ExecuteMigrationStep()
        verify_step = VerifyMigrationStep()

        for step in [detect_step, validate_step, backup_step, execute_step, verify_step]:
            # Should have name property
            assert hasattr(step, "name")
            assert isinstance(step.name, str)

            # Should have description property
            assert hasattr(step, "description")
            assert isinstance(step.description, str)

            # Should have execute method
            assert hasattr(step, "execute")
            assert callable(step.execute)

    async def test_steps_pass_data_through_context(
        self, mock_schema_manager: AsyncMock, mock_migration_manager: AsyncMock
    ) -> None:
        """Steps correctly pass data to subsequent steps via context."""
        context = StepContext()
        context.set("schema_manager", mock_schema_manager)
        context.set("migration_manager", mock_migration_manager)
        context.set("config", {"backup": True})

        mock_schema_manager.detect_version.return_value = SchemaVersion.V1_0
        mock_schema_manager.can_auto_migrate.return_value = True
        mock_migration_manager.create_backup.return_value = Path("/tmp/backup.db")

        # Run detect step
        detect_step = DetectVersionStep()
        await detect_step.execute(context, None)

        # Validate step should see versions from detect step
        assert context.get("current_version") == SchemaVersion.V1_0
        assert context.get("target_version") is not None

        # Run validate step
        validate_step = ValidateMigrationStep()
        await validate_step.execute(context, None)

        # Backup step should see migration_needed from validate step
        assert context.get("migration_needed") is True
