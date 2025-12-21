"""Migration steps for database schema upgrades.

This module provides steps for running database schema migrations:
- DetectVersionStep: Detect current and target schema versions
- ValidateMigrationStep: Validate migration prerequisites
- CreateBackupStep: Create database backup before migration
- ExecuteMigrationStep: Execute the schema migration
- VerifyMigrationStep: Verify migration completed successfully
"""

from pathlib import Path
from typing import Any

from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.data.schema_manager import SchemaManager, SchemaVersion
from gmailarchiver.shared.protocols import ProgressReporter


class DetectVersionStep:
    """Step that detects current and target schema versions.

    Detects the current database schema version and determines the target version.

    Input: None (uses schema_manager from context)
    Output: Dict with current_version and target_version
    Context: Reads "schema_manager", "config"; sets "current_version", "target_version"
    """

    name = "detect_version"
    description = "Detecting schema version"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[dict[str, Any]]:
        """Detect current and target schema versions.

        Args:
            context: Shared step context (expects "schema_manager" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with version information
        """
        schema_manager: SchemaManager | None = context.get("schema_manager")
        if not schema_manager:
            return StepResult.fail("SchemaManager not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Detecting schema version") as task:
                        current_version = await schema_manager.detect_version()

                        # Determine target version from config or use CURRENT_VERSION
                        config: dict[str, Any] = context.get("config", {}) or {}
                        target_version_str: str | None = (
                            config.get("target_version") if isinstance(config, dict) else None
                        )

                        if target_version_str:
                            target_version = SchemaVersion.from_string(target_version_str)
                        else:
                            target_version = schema_manager.CURRENT_VERSION

                        task.complete(
                            f"Current: {current_version.value}, Target: {target_version.value}"
                        )
            else:
                current_version = await schema_manager.detect_version()

                # Determine target version from config or use CURRENT_VERSION
                config_raw: dict[str, Any] | None = context.get("config", {})
                config_dict: dict[str, Any] = config_raw if isinstance(config_raw, dict) else {}
                target_version_str = config_dict.get("target_version")

                if target_version_str:
                    target_version = SchemaVersion.from_string(target_version_str)
                else:
                    target_version = schema_manager.CURRENT_VERSION

            # Store in context for subsequent steps
            context.set("current_version", current_version)
            context.set("target_version", target_version)

            return StepResult.ok(
                {
                    "current_version": current_version,
                    "target_version": target_version,
                }
            )

        except Exception as e:
            return StepResult.fail(f"Version detection failed: {e}")


class ValidateMigrationStep:
    """Step that validates migration prerequisites.

    Validates that migration is possible and needed.

    Input: None (uses schema_manager from context)
    Output: Dict with migration_needed and validation details
    Context: Reads "schema_manager", "current_version", "target_version";
             sets "migration_needed"
    """

    name = "validate_migration"
    description = "Validating migration requirements"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[dict[str, Any]]:
        """Validate migration prerequisites.

        Args:
            context: Shared step context (expects "schema_manager", versions)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with validation details
        """
        schema_manager: SchemaManager | None = context.get("schema_manager")
        if not schema_manager:
            return StepResult.fail("SchemaManager not found in context")

        current_version: SchemaVersion | None = context.get("current_version")
        target_version: SchemaVersion | None = context.get("target_version")

        if current_version is None:
            return StepResult.fail("current_version not found in context")

        if target_version is None:
            return StepResult.fail("target_version not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Validating migration requirements") as task:
                        # Check if already at target version
                        if current_version == target_version:
                            context.set("migration_needed", False)
                            task.complete("Already at target version")
                            return StepResult.ok(
                                {
                                    "migration_needed": False,
                                    "can_auto_migrate": True,
                                }
                            )

                        # Check for downgrade attempt
                        if current_version > target_version:
                            task.fail("Cannot downgrade")
                            return StepResult.fail(
                                f"Cannot downgrade from {current_version.value} "
                                f"to {target_version.value}"
                            )

                        # Check if auto-migration is possible
                        can_auto_migrate = await schema_manager.can_auto_migrate()
                        if not can_auto_migrate:
                            task.fail("Cannot auto-migrate")
                            return StepResult.fail(
                                f"Cannot auto-migrate from version {current_version.value}. "
                                "Manual migration required."
                            )

                        context.set("migration_needed", True)
                        task.complete("Migration validated")
            else:
                # Check if already at target version
                if current_version == target_version:
                    context.set("migration_needed", False)
                    return StepResult.ok(
                        {
                            "migration_needed": False,
                            "can_auto_migrate": True,
                        }
                    )

                # Check for downgrade attempt
                if current_version > target_version:
                    return StepResult.fail(
                        f"Cannot downgrade from {current_version.value} to {target_version.value}"
                    )

                # Check if auto-migration is possible
                can_auto_migrate = await schema_manager.can_auto_migrate()
                if not can_auto_migrate:
                    return StepResult.fail(
                        f"Cannot auto-migrate from version {current_version.value}. "
                        "Manual migration required."
                    )

                context.set("migration_needed", True)

            return StepResult.ok(
                {
                    "migration_needed": True,
                    "can_auto_migrate": True,
                }
            )

        except Exception as e:
            return StepResult.fail(f"Validation failed: {e}")


class CreateBackupStep:
    """Step that creates database backup before migration.

    Creates a backup of the database before migration.

    Input: None (uses migration_manager from context)
    Output: Path to backup file or None if skipped
    Context: Reads "migration_manager", "config"; sets "backup_path"
    """

    name = "create_backup"
    description = "Creating database backup"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[Path | None]:
        """Create database backup.

        Args:
            context: Shared step context (expects "migration_manager")
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with backup path or None if skipped
        """
        # Check if backup is disabled in config
        config: dict[str, Any] = context.get("config", {}) or {}
        if isinstance(config, dict) and config.get("backup") is False:
            context.set("backup_path", None)
            return StepResult.ok(None)

        migration_manager = context.get("migration_manager")
        if not migration_manager:
            return StepResult.fail("MigrationManager not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Creating database backup") as task:
                        backup_path = await migration_manager.create_backup()
                        context.set("backup_path", backup_path)
                        task.complete(f"Backup: {backup_path.name}")
            else:
                backup_path = await migration_manager.create_backup()
                context.set("backup_path", backup_path)

            return StepResult.ok(backup_path)

        except Exception as e:
            return StepResult.fail(f"Backup creation failed: {e}")

        finally:
            # Always close migration manager after backup
            if migration_manager:
                await migration_manager._close()


class ExecuteMigrationStep:
    """Step that executes the schema migration.

    Performs the actual schema migration.

    Input: None (uses schema_manager from context)
    Output: Dict with success flag and migration details
    Context: Reads "schema_manager", "migration_needed", "current_version", "target_version";
             sets "migration_success", "migration_details"
    """

    name = "execute_migration"
    description = "Executing schema migration"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[dict[str, Any]]:
        """Execute schema migration.

        Args:
            context: Shared step context (expects "schema_manager")
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with migration result
        """
        # Check if migration is needed
        migration_needed = context.get("migration_needed", False)
        if not migration_needed:
            context.set("migration_success", True)
            context.set("migration_details", [])
            return StepResult.ok({"success": True, "skipped": True})

        schema_manager: SchemaManager | None = context.get("schema_manager")
        if not schema_manager:
            return StepResult.fail("SchemaManager not found in context")

        migration_details: list[str] = []
        backup_path = context.get("backup_path")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    current: SchemaVersion = (
                        context.get("current_version", SchemaVersion.UNKNOWN)
                        or SchemaVersion.UNKNOWN
                    )
                    target: SchemaVersion = (
                        context.get("target_version", SchemaVersion.UNKNOWN)
                        or SchemaVersion.UNKNOWN
                    )

                    with seq.task(f"Migrating {current.value} -> {target.value}") as task:
                        # Create progress callback
                        def progress_callback(msg: str) -> None:
                            migration_details.append(msg)

                        success = await schema_manager.auto_migrate_if_needed(
                            confirm_callback=None,
                            progress_callback=progress_callback,
                        )

                        if success:
                            task.complete(f"Migrated to {target.value}")
                        else:
                            task.fail("Migration did not complete")
            else:
                # Create progress callback
                def progress_callback(msg: str) -> None:
                    migration_details.append(msg)

                success = await schema_manager.auto_migrate_if_needed(
                    confirm_callback=None,
                    progress_callback=progress_callback,
                )

            context.set("migration_details", migration_details)

            if success:
                context.set("migration_success", True)
                return StepResult.ok({"success": True})
            else:
                context.set("migration_success", False)
                return StepResult.fail("Migration did not complete successfully")

        except Exception as e:
            context.set("migration_success", False)
            context.set("migration_details", migration_details)

            # Include backup path in error metadata if available
            error_msg = f"Migration failed: {e}"
            if backup_path:
                error_msg += f". Backup available at: {backup_path}"

            return StepResult.fail(error_msg, backup_path=backup_path)


class VerifyMigrationStep:
    """Step that verifies migration completed successfully.

    Verifies that the database is now at the target version.

    Input: None (uses schema_manager from context)
    Output: Dict with verification details
    Context: Reads "schema_manager", "target_version", "migration_success";
             sets "verification_passed"
    """

    name = "verify_migration"
    description = "Verifying migration success"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[dict[str, Any]]:
        """Verify migration completed successfully.

        Args:
            context: Shared step context (expects "schema_manager", "target_version")
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with verification details
        """
        # Check if migration was skipped (no migration needed)
        migration_needed = context.get("migration_needed", True)
        if not migration_needed:
            context.set("verification_passed", True)
            return StepResult.ok({"verified_version": context.get("target_version")})

        schema_manager: SchemaManager | None = context.get("schema_manager")
        if not schema_manager:
            return StepResult.fail("SchemaManager not found in context")

        target_version: SchemaVersion | None = context.get("target_version")
        if target_version is None:
            return StepResult.fail("target_version not found in context")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Verifying migration") as task:
                        # Invalidate cache and re-detect version
                        schema_manager.invalidate_cache()
                        detected_version = await schema_manager.detect_version()

                        if detected_version == target_version:
                            context.set("verification_passed", True)
                            task.complete(f"Verified: {detected_version.value}")
                            return StepResult.ok({"verified_version": detected_version})
                        else:
                            context.set("verification_passed", False)
                            task.fail("Version mismatch")
                            return StepResult.fail(
                                f"Migration verification failed: expected {target_version.value}, "
                                f"got {detected_version.value}"
                            )
            else:
                # Invalidate cache and re-detect version
                schema_manager.invalidate_cache()
                detected_version = await schema_manager.detect_version()

                if detected_version == target_version:
                    context.set("verification_passed", True)
                    return StepResult.ok({"verified_version": detected_version})
                else:
                    context.set("verification_passed", False)
                    return StepResult.fail(
                        f"Migration verification failed: expected {target_version.value}, "
                        f"got {detected_version.value}"
                    )

        except Exception as e:
            context.set("verification_passed", False)
            return StepResult.fail(f"Verification failed: {e}")
