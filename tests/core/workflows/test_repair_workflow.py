"""Tests for repair workflow.

Tests verify repair workflow behavior including diagnostics, auto-fix,
backfill operations, dry-run mode, and progress reporting.
"""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult
from gmailarchiver.core.doctor._repair import FixResult
from gmailarchiver.core.doctor.facade import CheckSeverity, DoctorReport
from gmailarchiver.core.workflows.repair import RepairConfig, RepairWorkflow
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import NoOpProgressReporter


@pytest.fixture
def repair_workflow(hybrid_storage: HybridStorage) -> RepairWorkflow:
    """Create a repair workflow instance without progress reporting."""
    return RepairWorkflow(storage=hybrid_storage, progress=None)


@pytest.fixture
def repair_workflow_with_progress(hybrid_storage: HybridStorage) -> RepairWorkflow:
    """Create a repair workflow instance with mock progress reporter."""
    progress = NoOpProgressReporter()
    return RepairWorkflow(storage=hybrid_storage, progress=progress)


@pytest.fixture
def broken_db(temp_dir: Path) -> str:
    """Create a database with integrity issues."""
    db_path = temp_dir / "broken.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create minimal schema but missing FTS table
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

        # Intentionally skip FTS table creation to simulate broken DB

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
            """
        )

        conn.execute("PRAGMA user_version = 11")
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
            ("1.1", "1970-01-01T00:00:00"),
        )

        conn.commit()
    finally:
        conn.close()

    return str(db_path)


@pytest.fixture
def db_with_invalid_offsets(temp_dir: Path) -> str:
    """Create a database with invalid mbox offsets."""
    db_path = temp_dir / "invalid_offsets.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create full v1.1 schema
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
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject,
                from_addr,
                to_addr,
                body_preview,
                content=messages,
                content_rowid=rowid,
                tokenize='porter unicode61 remove_diacritics 1'
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

        conn.execute("PRAGMA user_version = 11")
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, migrated_timestamp) VALUES (?, ?)",
            ("1.1", "1970-01-01T00:00:00"),
        )

        # Insert messages with invalid offsets
        conn.execute(
            """
            INSERT INTO messages (
                gmail_id, rfc_message_id, thread_id, subject, from_addr,
                to_addr, archived_timestamp, archive_file, mbox_offset, mbox_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg001",
                "<invalid1@example.com>",
                "thread1",
                "Invalid Offset Message 1",
                "sender@example.com",
                "recipient@example.com",
                "2024-01-01T00:00:00",
                "archive.mbox",
                -1,  # Invalid offset
                100,
            ),
        )

        conn.execute(
            """
            INSERT INTO messages (
                gmail_id, rfc_message_id, thread_id, subject, from_addr,
                to_addr, archived_timestamp, archive_file, mbox_offset, mbox_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg002",
                "<invalid2@example.com>",
                "thread2",
                "Invalid Offset Message 2",
                "sender@example.com",
                "recipient@example.com",
                "2024-01-02T00:00:00",
                "archive.mbox",
                0,
                -50,  # Invalid length
            ),
        )

        conn.commit()
    finally:
        conn.close()

    return str(db_path)


class TestRepairWorkflowBasics:
    """Test basic repair workflow functionality."""

    @pytest.mark.asyncio
    async def test_repair_with_no_issues_found(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should succeed when no issues are found."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics with no issues
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[
                    CheckResult(
                        name="database_schema",
                        severity=CheckSeverity.OK,
                        message="Schema version is valid",
                        fixable=False,
                    )
                ],
                checks_passed=1,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            result = await repair_workflow.run(config)

        assert result.issues_found == 0
        assert result.issues_fixed == 0
        assert result.dry_run is False
        # Details should be empty when no issues found (OK checks shouldn't be in details)
        assert len(result.details) == 0

    @pytest.mark.asyncio
    async def test_repair_dry_run_does_not_fix_issues(
        self, repair_workflow: RepairWorkflow, broken_db: str
    ) -> None:
        """Dry run should detect but not fix issues."""
        config = RepairConfig(state_db=broken_db, backfill=False, dry_run=True)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics with errors
            mock_report = DoctorReport(
                overall_status=CheckSeverity.ERROR,
                checks=[
                    CheckResult(
                        name="orphaned_fts",
                        severity=CheckSeverity.ERROR,
                        message="FTS table is missing",
                        fixable=True,
                    ),
                    CheckResult(
                        name="database_integrity",
                        severity=CheckSeverity.WARNING,
                        message="Minor integrity issues",
                        fixable=False,
                    ),
                ],
                checks_passed=0,
                warnings=1,
                errors=1,
                fixable_issues=["orphaned_fts"],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            result = await repair_workflow.run(config)

        assert result.issues_found == 2  # 1 error + 1 warning
        assert result.issues_fixed == 0  # Dry run doesn't fix
        assert result.dry_run is True
        assert len(result.details) == 2
        assert any("orphaned_fts" in detail for detail in result.details)
        assert any("database_integrity" in detail for detail in result.details)

        # Verify auto-fix was NOT called in dry run mode
        mock_doctor.run_auto_fix.assert_not_called()

    @pytest.mark.asyncio
    async def test_repair_fixes_detected_issues(
        self, repair_workflow: RepairWorkflow, broken_db: str
    ) -> None:
        """Repair should fix all fixable issues when not in dry run mode."""
        config = RepairConfig(state_db=broken_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics with fixable issues
            mock_report = DoctorReport(
                overall_status=CheckSeverity.ERROR,
                checks=[
                    CheckResult(
                        name="orphaned_fts",
                        severity=CheckSeverity.ERROR,
                        message="FTS table is missing",
                        fixable=True,
                    ),
                    CheckResult(
                        name="stale_locks",
                        severity=CheckSeverity.WARNING,
                        message="Stale lock files found",
                        fixable=True,
                    ),
                ],
                checks_passed=0,
                warnings=1,
                errors=1,
                fixable_issues=["orphaned_fts", "stale_locks"],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock successful fixes
            mock_doctor.run_auto_fix.return_value = [
                FixResult(
                    check_name="orphaned_fts",
                    success=True,
                    message="FTS table rebuilt successfully",
                ),
                FixResult(
                    check_name="stale_locks",
                    success=True,
                    message="Removed 2 stale lock files",
                ),
            ]

            result = await repair_workflow.run(config)

        assert result.issues_found == 2
        assert result.issues_fixed == 2
        assert result.dry_run is False
        assert len(result.details) == 4  # 2 issues detected + 2 fixes applied
        assert any("Fixed: FTS table rebuilt" in detail for detail in result.details)
        assert any("Fixed: Removed 2 stale lock files" in detail for detail in result.details)

    @pytest.mark.asyncio
    async def test_repair_handles_partial_fix_success(
        self, repair_workflow: RepairWorkflow, broken_db: str
    ) -> None:
        """Repair should handle when some fixes succeed and others fail."""
        config = RepairConfig(state_db=broken_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.ERROR,
                checks=[
                    CheckResult(
                        name="orphaned_fts",
                        severity=CheckSeverity.ERROR,
                        message="FTS table is missing",
                        fixable=True,
                    ),
                    CheckResult(
                        name="corrupt_index",
                        severity=CheckSeverity.ERROR,
                        message="Index is corrupted",
                        fixable=True,
                    ),
                ],
                checks_passed=0,
                warnings=0,
                errors=2,
                fixable_issues=["orphaned_fts", "corrupt_index"],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock mixed fix results
            mock_doctor.run_auto_fix.return_value = [
                FixResult(
                    check_name="orphaned_fts",
                    success=True,
                    message="FTS table rebuilt successfully",
                ),
                FixResult(
                    check_name="corrupt_index",
                    success=False,
                    message="Failed to rebuild index: permission denied",
                ),
            ]

            result = await repair_workflow.run(config)

        assert result.issues_found == 2
        assert result.issues_fixed == 1  # Only one succeeded
        assert result.dry_run is False
        assert any("Fixed: FTS table rebuilt" in detail for detail in result.details)
        assert any("Failed: Failed to rebuild index" in detail for detail in result.details)


class TestRepairWorkflowBackfill:
    """Test backfill operations."""

    @pytest.mark.asyncio
    async def test_backfill_when_no_invalid_offsets(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Backfill should report no work needed when all offsets are valid."""
        config = RepairConfig(state_db=v11_db, backfill=True, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[
                    CheckResult(
                        name="database_schema",
                        severity=CheckSeverity.OK,
                        message="Schema is valid",
                        fixable=False,
                    )
                ],
                checks_passed=1,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock no invalid offsets
            mock_db_manager = AsyncMock()
            mock_db_manager.get_messages_with_invalid_offsets = AsyncMock(return_value=[])
            mock_doctor._get_db_manager = Mock(return_value=mock_db_manager)

            result = await repair_workflow.run(config)

        assert result.issues_found == 0
        assert result.issues_fixed == 0
        assert not any("Backfilled" in detail for detail in result.details)

    @pytest.mark.asyncio
    async def test_backfill_repairs_invalid_offsets(
        self, repair_workflow: RepairWorkflow, db_with_invalid_offsets: str
    ) -> None:
        """Backfill should repair messages with invalid offsets."""
        config = RepairConfig(state_db=db_with_invalid_offsets, backfill=True, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[
                    CheckResult(
                        name="database_schema",
                        severity=CheckSeverity.OK,
                        message="Schema is valid",
                        fixable=False,
                    )
                ],
                checks_passed=1,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock invalid offsets found
            mock_db_manager = AsyncMock()
            mock_db_manager.get_messages_with_invalid_offsets = AsyncMock(
                return_value=[
                    {"gmail_id": "msg001", "rfc_message_id": "<invalid1@example.com>"},
                    {"gmail_id": "msg002", "rfc_message_id": "<invalid2@example.com>"},
                ]
            )
            mock_doctor._get_db_manager = Mock(return_value=mock_db_manager)

            # Mock migration manager that performs backfill
            with patch("gmailarchiver.data.migration.MigrationManager") as mock_migration_class:
                mock_migrator = AsyncMock()
                mock_migration_class.return_value = mock_migrator
                mock_migrator.backfill_offsets_from_mbox.return_value = 2

                result = await repair_workflow.run(config)

        assert result.issues_found == 0  # No diagnostic issues
        assert result.issues_fixed == 2  # 2 messages backfilled
        assert any("Backfilled 2 messages" in detail for detail in result.details)

    @pytest.mark.asyncio
    async def test_backfill_without_db_manager_returns_zero(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Backfill should handle missing DBManager gracefully."""
        config = RepairConfig(state_db=v11_db, backfill=True, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[],
                checks_passed=0,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock missing DBManager
            mock_doctor._get_db_manager = Mock(return_value=None)

            result = await repair_workflow.run(config)

        # Should not fail, just skip backfill
        assert result.issues_fixed == 0
        assert not any("Backfilled" in detail for detail in result.details)


class TestRepairWorkflowProgress:
    """Test progress reporting during repair operations."""

    @pytest.mark.asyncio
    async def test_repair_reports_diagnostics_progress(
        self, repair_workflow_with_progress: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should report progress during diagnostics."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=False)

        # Create mock progress components
        mock_task = Mock()
        mock_task.complete = Mock()
        mock_task.advance = Mock()

        mock_seq = Mock()
        mock_seq.task = Mock(return_value=mock_task)
        mock_seq.__enter__ = Mock(return_value=mock_seq)
        mock_seq.__exit__ = Mock(return_value=False)

        mock_task.__enter__ = Mock(return_value=mock_task)
        mock_task.__exit__ = Mock(return_value=False)

        # Attach to progress reporter
        repair_workflow_with_progress.progress.task_sequence = Mock(return_value=mock_seq)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[
                    CheckResult(
                        name="database_schema",
                        severity=CheckSeverity.OK,
                        message="Schema is valid",
                        fixable=False,
                    )
                ],
                checks_passed=1,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            result = await repair_workflow_with_progress.run(config)

        # Verify progress reporting was used
        repair_workflow_with_progress.progress.task_sequence.assert_called()
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_repair_reports_fix_progress(
        self, repair_workflow_with_progress: RepairWorkflow, broken_db: str
    ) -> None:
        """Repair should report progress during auto-fix operations."""
        config = RepairConfig(state_db=broken_db, backfill=False, dry_run=False)

        # Create mock progress components
        mock_task = Mock()
        mock_task.complete = Mock()
        mock_task.advance = Mock()

        mock_seq = Mock()
        mock_seq.task = Mock(return_value=mock_task)
        mock_seq.__enter__ = Mock(return_value=mock_seq)
        mock_seq.__exit__ = Mock(return_value=False)

        mock_task.__enter__ = Mock(return_value=mock_task)
        mock_task.__exit__ = Mock(return_value=False)

        # Attach to progress reporter
        repair_workflow_with_progress.progress.task_sequence = Mock(return_value=mock_seq)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics with fixable issues
            mock_report = DoctorReport(
                overall_status=CheckSeverity.ERROR,
                checks=[
                    CheckResult(
                        name="orphaned_fts",
                        severity=CheckSeverity.ERROR,
                        message="FTS missing",
                        fixable=True,
                    ),
                    CheckResult(
                        name="stale_locks",
                        severity=CheckSeverity.WARNING,
                        message="Lock files exist",
                        fixable=True,
                    ),
                ],
                checks_passed=0,
                warnings=1,
                errors=1,
                fixable_issues=["orphaned_fts", "stale_locks"],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock successful fixes
            mock_doctor.run_auto_fix.return_value = [
                FixResult(check_name="orphaned_fts", success=True, message="Fixed FTS"),
                FixResult(check_name="stale_locks", success=True, message="Removed locks"),
            ]

            result = await repair_workflow_with_progress.run(config)

        # Verify progress reporting was used
        repair_workflow_with_progress.progress.task_sequence.assert_called()
        # Task.advance should be called for each fix
        assert mock_task.advance.call_count == 2
        assert result.issues_fixed == 2

    @pytest.mark.asyncio
    async def test_repair_reports_backfill_progress(
        self, repair_workflow_with_progress: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should report progress during backfill operations."""
        config = RepairConfig(state_db=v11_db, backfill=True, dry_run=False)

        # Create mock progress components
        mock_task = Mock()
        mock_task.complete = Mock()
        mock_task.advance = Mock()

        mock_seq = Mock()
        mock_seq.task = Mock(return_value=mock_task)
        mock_seq.__enter__ = Mock(return_value=mock_seq)
        mock_seq.__exit__ = Mock(return_value=False)

        mock_task.__enter__ = Mock(return_value=mock_task)
        mock_task.__exit__ = Mock(return_value=False)

        # Attach to progress reporter
        repair_workflow_with_progress.progress.task_sequence = Mock(return_value=mock_seq)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[],
                checks_passed=0,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock invalid offsets
            mock_db_manager = AsyncMock()
            mock_db_manager.get_messages_with_invalid_offsets = AsyncMock(
                return_value=[
                    {"gmail_id": "msg001", "rfc_message_id": "<msg1@example.com>"},
                ]
            )
            mock_doctor._get_db_manager = Mock(return_value=mock_db_manager)

            # Mock migration manager
            with patch("gmailarchiver.data.migration.MigrationManager") as mock_migration_class:
                mock_migrator = AsyncMock()
                mock_migration_class.return_value = mock_migrator
                mock_migrator.backfill_offsets_from_mbox.return_value = 1

                result = await repair_workflow_with_progress.run(config)

        # Verify progress reporting was used for backfill
        repair_workflow_with_progress.progress.task_sequence.assert_called()
        assert result.issues_fixed == 1


class TestRepairWorkflowErrorHandling:
    """Test error handling in repair workflow."""

    @pytest.mark.asyncio
    async def test_repair_closes_doctor_on_success(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should close Doctor even when operation succeeds."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[],
                checks_passed=0,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            await repair_workflow.run(config)

        # Verify Doctor was closed
        mock_doctor.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_repair_closes_doctor_on_exception(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should close Doctor even when operation fails."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics that raises exception
            mock_doctor.run_diagnostics.side_effect = RuntimeError("Database is corrupt")

            with pytest.raises(RuntimeError, match="Database is corrupt"):
                await repair_workflow.run(config)

        # Verify Doctor was closed despite exception
        mock_doctor.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_repair_handles_backfill_exception(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should close migrator even when backfill fails."""
        config = RepairConfig(state_db=v11_db, backfill=True, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[],
                checks_passed=0,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            # Mock invalid offsets
            mock_db_manager = AsyncMock()
            mock_db_manager.get_messages_with_invalid_offsets = AsyncMock(
                return_value=[
                    {"gmail_id": "msg001", "rfc_message_id": "<msg1@example.com>"},
                ]
            )
            mock_doctor._get_db_manager = Mock(return_value=mock_db_manager)

            # Mock migration manager that fails
            with patch("gmailarchiver.data.migration.MigrationManager") as mock_migration_class:
                mock_migrator = AsyncMock()
                mock_migration_class.return_value = mock_migrator
                mock_migrator.backfill_offsets_from_mbox.side_effect = RuntimeError(
                    "Archive file not found"
                )

                with pytest.raises(RuntimeError, match="Archive file not found"):
                    await repair_workflow.run(config)

                # Verify migrator was closed despite exception
                mock_migrator._close.assert_called_once()


class TestRepairWorkflowIntegration:
    """Test repair workflow integration with Doctor facade."""

    @pytest.mark.asyncio
    async def test_repair_creates_doctor_with_correct_params(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should create Doctor with validation disabled."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=False)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock clean diagnostics
            mock_report = DoctorReport(
                overall_status=CheckSeverity.OK,
                checks=[],
                checks_passed=0,
                warnings=0,
                errors=0,
                fixable_issues=[],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            await repair_workflow.run(config)

        # Verify Doctor.create was called with correct params
        mock_doctor_class.create.assert_called_once_with(
            db_path=v11_db,
            validate_schema=False,  # Doctor needs to inspect any schema version
            auto_create=False,
        )

    @pytest.mark.asyncio
    async def test_repair_collects_all_check_details(
        self, repair_workflow: RepairWorkflow, v11_db: str
    ) -> None:
        """Repair should collect details from all non-OK checks."""
        config = RepairConfig(state_db=v11_db, backfill=False, dry_run=True)

        with patch("gmailarchiver.core.workflows.repair.Doctor") as mock_doctor_class:
            mock_doctor = AsyncMock()
            mock_doctor_class.create = AsyncMock(return_value=mock_doctor)

            # Mock diagnostics with multiple issues
            mock_report = DoctorReport(
                overall_status=CheckSeverity.ERROR,
                checks=[
                    CheckResult(
                        name="database_schema",
                        severity=CheckSeverity.OK,
                        message="Schema is valid",
                        fixable=False,
                    ),
                    CheckResult(
                        name="orphaned_fts",
                        severity=CheckSeverity.ERROR,
                        message="FTS records are orphaned",
                        fixable=True,
                    ),
                    CheckResult(
                        name="stale_locks",
                        severity=CheckSeverity.WARNING,
                        message="3 stale lock files found",
                        fixable=True,
                    ),
                    CheckResult(
                        name="disk_space",
                        severity=CheckSeverity.WARNING,
                        message="Low disk space: 100MB remaining",
                        fixable=False,
                    ),
                ],
                checks_passed=1,
                warnings=2,
                errors=1,
                fixable_issues=["orphaned_fts", "stale_locks"],
            )
            mock_doctor.run_diagnostics.return_value = mock_report

            result = await repair_workflow.run(config)

        # Verify all non-OK checks are in details (only)
        assert result.issues_found == 3  # 1 error + 2 warnings
        # Should only have 3 details (OK check excluded)
        assert len(result.details) == 3
        assert any("orphaned_fts: FTS records are orphaned" in detail for detail in result.details)
        assert any("stale_locks: 3 stale lock files found" in detail for detail in result.details)
        assert any("disk_space: Low disk space" in detail for detail in result.details)
        # OK check should NOT be in details
        assert not any("database_schema" in detail for detail in result.details)
