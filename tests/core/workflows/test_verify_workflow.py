"""Tests for verify workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.workflows.verify import (
    VerifyConfig,
    VerifyResult,
    VerifyType,
    VerifyWorkflow,
)


async def create_mock_doctor(mock_doctor):
    """Helper to create an awaitable Doctor.create() mock."""
    return mock_doctor


@pytest.fixture
def mock_progress():
    """Create a mock progress reporter for testing."""
    progress = MagicMock()

    # Create mock task sequence
    task_seq = MagicMock()
    progress.task_sequence.return_value.__enter__ = MagicMock(return_value=task_seq)
    progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)

    # Create mock task handle
    task_handle = MagicMock()
    task_seq.task.return_value.__enter__ = MagicMock(return_value=task_handle)
    task_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    return progress


class TestVerifyWorkflowInitialization:
    """Test workflow initialization."""

    @pytest.mark.asyncio
    async def test_initialization_with_storage_and_progress(self, hybrid_storage, mock_progress):
        """Workflow initializes with storage and progress reporter."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)

        assert workflow.storage is hybrid_storage
        assert workflow.progress is mock_progress

    @pytest.mark.asyncio
    async def test_initialization_without_progress(self, hybrid_storage):
        """Workflow initializes without progress reporter."""
        workflow = VerifyWorkflow(hybrid_storage, None)

        assert workflow.storage is hybrid_storage
        assert workflow.progress is None


class TestVerifyWorkflowIntegrityCheck:
    """Test integrity verification workflow."""

    @pytest.mark.asyncio
    async def test_verify_integrity_success_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Integrity check passes with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock successful integrity check
            mock_doctor.check_database_integrity.return_value = CheckResult(
                name="Database integrity",
                severity=CheckSeverity.OK,
                message="All integrity checks passed",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify doctor was closed
            mock_doctor.close.assert_called_once()

            # Verify result
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "integrity"

            # Verify progress was used
            mock_progress.task_sequence.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_integrity_failure_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Integrity check fails with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock failed integrity check
            mock_doctor.check_database_integrity.return_value = CheckResult(
                name="Database corruption",
                severity=CheckSeverity.ERROR,
                message="Database file is corrupted",
                fixable=True,
                details="Run PRAGMA integrity_check",
            )

            result = await workflow.run(config)

            # Verify result
            assert result.passed is False
            assert result.issues_found == 1
            assert len(result.issues) == 1
            assert result.issues[0]["name"] == "Database corruption"
            assert result.issues[0]["severity"] == "ERROR"
            assert result.issues[0]["message"] == "Database file is corrupted"
            assert result.issues[0]["fixable"] is True
            assert result.issues[0]["details"] == "Run PRAGMA integrity_check"
            assert result.verify_type == "integrity"

    @pytest.mark.asyncio
    async def test_verify_integrity_success_without_progress(self, hybrid_storage, v11_db):
        """Integrity check passes without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock successful integrity check
            mock_doctor.check_database_integrity.return_value = CheckResult(
                name="Database integrity",
                severity=CheckSeverity.OK,
                message="All integrity checks passed",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "integrity"

    @pytest.mark.asyncio
    async def test_verify_integrity_failure_without_progress(self, hybrid_storage, v11_db):
        """Integrity check fails without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock failed integrity check
            mock_doctor.check_database_integrity.return_value = CheckResult(
                name="Database corruption",
                severity=CheckSeverity.ERROR,
                message="Database file is corrupted",
                fixable=True,
                details="Run PRAGMA integrity_check",
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is False
            assert result.issues_found == 1
            assert len(result.issues) == 1
            assert result.verify_type == "integrity"


class TestVerifyWorkflowConsistencyCheck:
    """Test consistency verification workflow."""

    @pytest.mark.asyncio
    async def test_verify_consistency_all_pass_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Consistency checks all pass with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.CONSISTENCY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock all checks passing
            mock_doctor.check_database_schema.return_value = CheckResult(
                name="Database schema",
                severity=CheckSeverity.OK,
                message="Schema version 1.1",
                fixable=False,
            )
            mock_doctor.check_orphaned_fts.return_value = CheckResult(
                name="Orphaned FTS records",
                severity=CheckSeverity.OK,
                message="No orphaned FTS records",
                fixable=False,
            )
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="All archive files exist",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify all checks were called
            mock_doctor.check_database_schema.assert_called_once()
            mock_doctor.check_orphaned_fts.assert_called_once()
            mock_doctor.check_archive_files_exist.assert_called_once()

            # Verify result
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "consistency"

    @pytest.mark.asyncio
    async def test_verify_consistency_with_failures_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Consistency checks find issues with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.CONSISTENCY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock mixed check results
            mock_doctor.check_database_schema.return_value = CheckResult(
                name="Database schema",
                severity=CheckSeverity.WARNING,
                message="Schema version mismatch",
                fixable=True,
                details="Run migration",
            )
            mock_doctor.check_orphaned_fts.return_value = CheckResult(
                name="Orphaned FTS records",
                severity=CheckSeverity.ERROR,
                message="Found 5 orphaned FTS records",
                fixable=True,
                details="Run repair",
            )
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="All archive files exist",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify result
            assert result.passed is False
            assert result.issues_found == 2
            assert len(result.issues) == 2
            assert result.issues[0]["name"] == "Database schema"
            assert result.issues[0]["severity"] == "WARNING"
            assert result.issues[1]["name"] == "Orphaned FTS records"
            assert result.issues[1]["severity"] == "ERROR"
            assert result.verify_type == "consistency"

    @pytest.mark.asyncio
    async def test_verify_consistency_all_pass_without_progress(self, hybrid_storage, v11_db):
        """Consistency checks all pass without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.CONSISTENCY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock all checks passing
            mock_doctor.check_database_schema.return_value = CheckResult(
                name="Database schema",
                severity=CheckSeverity.OK,
                message="Schema version 1.1",
                fixable=False,
            )
            mock_doctor.check_orphaned_fts.return_value = CheckResult(
                name="Orphaned FTS records",
                severity=CheckSeverity.OK,
                message="No orphaned FTS records",
                fixable=False,
            )
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="All archive files exist",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "consistency"

    @pytest.mark.asyncio
    async def test_verify_consistency_with_failures_without_progress(self, hybrid_storage, v11_db):
        """Consistency checks find issues without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.CONSISTENCY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock mixed check results
            mock_doctor.check_database_schema.return_value = CheckResult(
                name="Database schema",
                severity=CheckSeverity.WARNING,
                message="Schema version mismatch",
                fixable=True,
                details="Run migration",
            )
            mock_doctor.check_orphaned_fts.return_value = CheckResult(
                name="Orphaned FTS records",
                severity=CheckSeverity.OK,
                message="No orphaned FTS records",
                fixable=False,
            )
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.ERROR,
                message="Missing archive file: test.mbox",
                fixable=False,
                details="File not found",
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is False
            assert result.issues_found == 2
            assert len(result.issues) == 2
            assert result.verify_type == "consistency"


class TestVerifyWorkflowOffsetsCheck:
    """Test offset verification workflow."""

    @pytest.mark.asyncio
    async def test_verify_offsets_success_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Offset verification passes with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.OFFSETS,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock successful archive files check
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="All archive files exist",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify check was called
            mock_doctor.check_archive_files_exist.assert_called_once()

            # Verify result
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "offsets"

    @pytest.mark.asyncio
    async def test_verify_offsets_failure_with_progress(
        self, hybrid_storage, mock_progress, v11_db
    ):
        """Offset verification fails with progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, mock_progress)
        config = VerifyConfig(
            verify_type=VerifyType.OFFSETS,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock failed archive files check
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.ERROR,
                message="Missing archive files",
                fixable=False,
                details="test.mbox not found",
            )

            result = await workflow.run(config)

            # Verify result
            assert result.passed is False
            assert result.issues_found == 1
            assert len(result.issues) == 1
            assert result.issues[0]["name"] == "Archive files"
            assert result.issues[0]["severity"] == "ERROR"
            assert result.verify_type == "offsets"

    @pytest.mark.asyncio
    async def test_verify_offsets_success_without_progress(self, hybrid_storage, v11_db):
        """Offset verification passes without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.OFFSETS,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock successful archive files check
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.OK,
                message="All archive files exist",
                fixable=False,
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is True
            assert result.issues_found == 0
            assert result.issues == []
            assert result.verify_type == "offsets"

    @pytest.mark.asyncio
    async def test_verify_offsets_failure_without_progress(self, hybrid_storage, v11_db):
        """Offset verification fails without progress reporting."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.OFFSETS,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Mock failed archive files check
            mock_doctor.check_archive_files_exist.return_value = CheckResult(
                name="Archive files",
                severity=CheckSeverity.ERROR,
                message="Missing archive files",
                fixable=False,
                details="test.mbox not found",
            )

            result = await workflow.run(config)

            # Verify result (no progress path)
            assert result.passed is False
            assert result.issues_found == 1
            assert len(result.issues) == 1
            assert result.verify_type == "offsets"


class TestVerifyWorkflowErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_unknown_verify_type_raises_error(self, hybrid_storage, v11_db):
        """Unknown verify type raises ValueError."""
        workflow = VerifyWorkflow(hybrid_storage, None)

        # Create a config with an invalid verify type by bypassing enum validation
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,  # Start with valid
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Patch the verify_type after creation to simulate invalid state
            with patch.object(config, "verify_type", "invalid_type"):
                with pytest.raises(ValueError, match="Unknown verify type"):
                    await workflow.run(config)

                # Ensure doctor was still cleaned up
                mock_doctor.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_doctor_cleanup_on_exception(self, hybrid_storage, v11_db):
        """Doctor is properly closed even when check raises exception."""
        workflow = VerifyWorkflow(hybrid_storage, None)
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db=v11_db,
            verbose=False,
        )

        with patch("gmailarchiver.core.workflows.verify.Doctor") as MockDoctor:
            mock_doctor = AsyncMock()
            MockDoctor.create.side_effect = lambda *args, **kwargs: create_mock_doctor(mock_doctor)

            # Make the check raise an exception
            mock_doctor.check_database_integrity.side_effect = RuntimeError("Database error")

            with pytest.raises(RuntimeError, match="Database error"):
                await workflow.run(config)

            # Ensure doctor was still cleaned up
            mock_doctor.close.assert_called_once()


class TestVerifyConfig:
    """Test configuration data class."""

    def test_verify_config_defaults(self):
        """VerifyConfig has correct default values."""
        config = VerifyConfig(
            verify_type=VerifyType.INTEGRITY,
            state_db="/path/to/db",
        )

        assert config.verify_type == VerifyType.INTEGRITY
        assert config.state_db == "/path/to/db"
        assert config.verbose is False
        assert config.archive_file is None

    def test_verify_config_with_all_params(self):
        """VerifyConfig accepts all parameters."""
        config = VerifyConfig(
            verify_type=VerifyType.CONSISTENCY,
            state_db="/path/to/db",
            verbose=True,
            archive_file="/path/to/archive.mbox",
        )

        assert config.verify_type == VerifyType.CONSISTENCY
        assert config.state_db == "/path/to/db"
        assert config.verbose is True
        assert config.archive_file == "/path/to/archive.mbox"


class TestVerifyResult:
    """Test result data class."""

    def test_verify_result_structure(self):
        """VerifyResult has correct structure."""
        result = VerifyResult(
            passed=True,
            issues_found=0,
            issues=[],
            verify_type="integrity",
        )

        assert result.passed is True
        assert result.issues_found == 0
        assert result.issues == []
        assert result.verify_type == "integrity"

    def test_verify_result_with_issues(self):
        """VerifyResult stores issue details."""
        issues = [
            {
                "name": "Test issue",
                "severity": "ERROR",
                "message": "Test message",
                "fixable": True,
                "details": "Test details",
            }
        ]

        result = VerifyResult(
            passed=False,
            issues_found=1,
            issues=issues,
            verify_type="consistency",
        )

        assert result.passed is False
        assert result.issues_found == 1
        assert len(result.issues) == 1
        assert result.issues[0]["name"] == "Test issue"


class TestVerifyType:
    """Test verify type enum."""

    def test_verify_type_values(self):
        """VerifyType enum has correct values."""
        assert VerifyType.INTEGRITY.value == "integrity"
        assert VerifyType.CONSISTENCY.value == "consistency"
        assert VerifyType.OFFSETS.value == "offsets"
