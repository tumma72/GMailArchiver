"""Migration workflow for database schema upgrades."""

from dataclasses import dataclass
from pathlib import Path

from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.data.migration import MigrationManager
from gmailarchiver.data.schema_manager import SchemaManager
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class MigrateConfig:
    """Configuration for migrate operation."""

    state_db: str
    target_version: str | None = None  # None = latest
    backup: bool = True


@dataclass
class MigrateResult:
    """Result of migrate operation."""

    success: bool
    from_version: str
    to_version: str
    backup_path: str | None
    details: list[str]


class MigrateWorkflow:
    """Workflow for database schema migration.

    This workflow coordinates schema detection, backup creation,
    and migration execution using SchemaManager and MigrationManager.
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        """Initialize migrate workflow.

        Args:
            storage: HybridStorage instance for database access
            progress: Optional progress reporter for UI feedback
        """
        self.storage = storage
        self.progress = progress

    async def run(self, config: MigrateConfig) -> MigrateResult:
        """Execute the migration workflow.

        Args:
            config: Migrate configuration dataclass

        Returns:
            MigrateResult with operation outcomes

        Raises:
            ValueError: If target version is invalid or not supported
        """
        details: list[str] = []
        backup_path: Path | None = None

        # Create schema manager
        schema_manager = SchemaManager(config.state_db)

        # Detect current version
        current_version = await schema_manager.detect_version()
        from_version = current_version.value

        # Determine target version
        if config.target_version is None:
            target_version = SchemaManager.CURRENT_VERSION
        else:
            target_version = SchemaManager.version_from_string(config.target_version)
            if not target_version.is_valid:
                raise ValueError(f"Invalid target version: {config.target_version}")

        to_version = target_version.value

        # Check if migration is needed
        if current_version == target_version:
            details.append("Database is already at target version")
            return MigrateResult(
                success=True,
                from_version=from_version,
                to_version=to_version,
                backup_path=None,
                details=details,
            )

        if current_version > target_version:
            raise ValueError(
                f"Cannot downgrade from {from_version} to {to_version}. "
                "Use rollback command instead."
            )

        # Check if auto-migration is possible
        if not await schema_manager.can_auto_migrate():
            raise ValueError(
                f"Cannot auto-migrate from version {from_version}. "
                "Manual migration or database recreation required."
            )

        # Create backup if requested
        if config.backup:
            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task("Creating backup") as task:
                        migrator = MigrationManager(config.state_db)
                        try:
                            backup_path = await migrator.create_backup()
                            details.append(f"Backup created: {backup_path}")
                            task.complete(f"Backup: {backup_path.name}")
                        finally:
                            await migrator._close()
            else:
                migrator = MigrationManager(config.state_db)
                try:
                    backup_path = await migrator.create_backup()
                    details.append(f"Backup created: {backup_path}")
                finally:
                    await migrator._close()

        # Perform migration
        try:
            if self.progress:
                with self.progress.task_sequence() as seq:
                    with seq.task(f"Migrating {from_version} → {to_version}") as task:
                        success = await schema_manager.auto_migrate_if_needed(
                            confirm_callback=None,  # Already confirmed by CLI
                            progress_callback=lambda msg: details.append(msg),
                        )

                        if success:
                            task.complete(f"Migrated to {to_version}")
                        else:
                            task.fail("Migration failed")

                        # Verify migration
                        new_version = await schema_manager.detect_version()
                        if new_version == target_version:
                            details.append("Migration verified successfully")
                        else:
                            success = False
                            details.append(
                                f"Migration verification failed: got {new_version.value}"
                            )
            else:
                success = await schema_manager.auto_migrate_if_needed(
                    confirm_callback=None,
                    progress_callback=lambda msg: details.append(msg),
                )

                # Verify migration
                new_version = await schema_manager.detect_version()
                if new_version == target_version:
                    details.append("Migration verified successfully")
                else:
                    success = False
                    details.append(f"Migration verification failed: got {new_version.value}")

            return MigrateResult(
                success=success,
                from_version=from_version,
                to_version=to_version,
                backup_path=str(backup_path) if backup_path else None,
                details=details,
            )

        except Exception as e:
            # Migration failed - rollback if we have a backup
            if backup_path and backup_path.exists():
                if self.progress:
                    self.progress.error(f"Migration failed: {e}")
                    self.progress.info(f"Backup available at: {backup_path}")

                details.append(f"Migration failed: {e}")
                details.append(f"Backup available at: {backup_path}")

                return MigrateResult(
                    success=False,
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=str(backup_path),
                    details=details,
                )
            else:
                raise
