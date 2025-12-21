"""Migration workflow for database schema upgrades."""

from dataclasses import dataclass
from pathlib import Path

from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.core.workflows.steps.migrate import (
    CreateBackupStep,
    DetectVersionStep,
    ExecuteMigrationStep,
    ValidateMigrationStep,
    VerifyMigrationStep,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.data.migration import MigrationManager
from gmailarchiver.data.schema_manager import SchemaManager, SchemaVersion
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
    and migration execution using a step-based architecture with
    SchemaManager and MigrationManager.
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

        # Initialize steps
        self._detect_step = DetectVersionStep()
        self._validate_step = ValidateMigrationStep()
        self._backup_step = CreateBackupStep()
        self._execute_step = ExecuteMigrationStep()
        self._verify_step = VerifyMigrationStep()

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

        # Create facades
        schema_manager = SchemaManager(config.state_db)

        # Validate target version early if specified
        if config.target_version is not None:
            target_version = SchemaManager.version_from_string(config.target_version)
            if not target_version.is_valid:
                raise ValueError(f"Invalid target version: {config.target_version}")

        # Create context and inject dependencies
        context = StepContext()
        context.set(
            "config",
            {
                "state_db": config.state_db,
                "target_version": config.target_version,
                "backup": config.backup,
            },
        )
        context.set("schema_manager", schema_manager)

        # Step 1: Detect current and target versions
        detect_result = await self._detect_step.execute(context, None, progress=self.progress)
        if not detect_result.success:
            raise ValueError(f"Version detection failed: {detect_result.error}")

        current_version: SchemaVersion = context.get("current_version")  # type: ignore
        target_version: SchemaVersion = context.get("target_version")  # type: ignore
        from_version = current_version.value
        to_version = target_version.value

        # Step 2: Validate migration requirements
        validate_result = await self._validate_step.execute(context, None, progress=self.progress)
        if not validate_result.success:
            raise ValueError(validate_result.error or "Validation failed")

        # Check if migration is needed
        migration_needed = context.get("migration_needed", False)
        if not migration_needed:
            details.append("Database is already at target version")
            return MigrateResult(
                success=True,
                from_version=from_version,
                to_version=to_version,
                backup_path=None,
                details=details,
            )

        # Step 3: Create backup if needed and requested
        if config.backup:
            # Create migration manager for backup
            migration_manager = MigrationManager(config.state_db)
            context.set("migration_manager", migration_manager)

            backup_result = await self._backup_step.execute(context, None, progress=self.progress)
            if not backup_result.success:
                raise ValueError(backup_result.error or "Backup creation failed")

            backup_path = context.get("backup_path")
            if backup_path:
                details.append(f"Backup created: {backup_path}")

        # Step 4: Execute migration
        try:
            execute_result = await self._execute_step.execute(context, None, progress=self.progress)

            # Collect migration details
            migration_details: list[str] = context.get("migration_details", []) or []
            details.extend(migration_details)

            if not execute_result.success:
                # Migration failed - check if we have a backup
                if backup_path and backup_path.exists():
                    if self.progress:
                        self.progress.error(f"Migration failed: {execute_result.error}")
                        self.progress.info(f"Backup available at: {backup_path}")

                    details.append(f"Migration failed: {execute_result.error}")
                    details.append(f"Backup available at: {backup_path}")

                    return MigrateResult(
                        success=False,
                        from_version=from_version,
                        to_version=to_version,
                        backup_path=str(backup_path),
                        details=details,
                    )
                else:
                    raise RuntimeError(execute_result.error or "Migration failed")

            # Step 5: Verify migration
            verify_result = await self._verify_step.execute(context, None, progress=self.progress)

            if verify_result.success:
                details.append("Migration verified successfully")
                return MigrateResult(
                    success=True,
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=str(backup_path) if backup_path else None,
                    details=details,
                )
            else:
                # Verification failed
                details.append(verify_result.error or "Migration verification failed")
                return MigrateResult(
                    success=False,
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=str(backup_path) if backup_path else None,
                    details=details,
                )

        except Exception as e:
            # Migration failed - check if we have a backup
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
