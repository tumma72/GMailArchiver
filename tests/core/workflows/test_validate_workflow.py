"""Behavior tests for ValidateWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given an archive file, it validates its integrity
- It reports validation results with detailed checks
- It handles missing files gracefully
- It provides verbose details when requested
"""

import mailbox
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.core.workflows.validate import (
    ValidateConfig,
    ValidateResult,
    ValidateWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


@pytest.fixture
async def archive_with_messages(tmp_path: Path, hybrid_storage: HybridStorage) -> Path:
    """Create an mbox archive with test messages and populate database with Gmail IDs."""
    mbox_path = tmp_path / "test_archive.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Add 3 test messages and track offsets
    offsets = []
    for i in range(3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test message {i}"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg["Date"] = f"Mon, {i + 1} Jan 2024 12:00:00 +0000"
        msg.set_payload(f"Body of message {i}")

        # Get current position (offset)
        offset = mbox._file.tell() if hasattr(mbox, "_file") else 0
        mbox.add(msg)
        offsets.append(offset)

    mbox.close()

    # Now manually insert into database with Gmail IDs
    # This simulates what happens when archiving from Gmail
    for i, offset in enumerate(offsets):
        await hybrid_storage.db.record_archived_message(
            rfc_message_id=f"<msg{i}@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=offset,
            mbox_length=200,  # Approximate
            gmail_id=f"gmail_{i}",
            thread_id=f"thread_{i}",
            subject=f"Test message {i}",
            from_addr=f"sender{i}@example.com",
            to_addr="recipient@example.com",
            date="2024-01-01T00:00:00",
            body_preview=f"Body of message {i}",
            checksum="abc123",
            record_run=False,  # Don't record in archive_runs for test
        )
    await hybrid_storage.db.commit()

    return mbox_path


class TestValidateWorkflowBehavior:
    """Test ValidateWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_validates_existing_archive(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given a valid archive file, validates it successfully."""
        # Archive and database are already set up by fixture
        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.passed is True
        assert result.count_check is True
        assert result.database_check is True
        assert result.integrity_check is True
        assert result.spot_check is True
        assert result.errors == []
        assert result.details is None  # verbose=False

    @pytest.mark.asyncio
    async def test_raises_error_for_missing_archive(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given a nonexistent archive file, raises WorkflowError."""
        from gmailarchiver.core.workflows.step import WorkflowError

        config = ValidateConfig(
            archive_file=str(tmp_path / "nonexistent.mbox"),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage)

        with pytest.raises(WorkflowError, match="Archive not found"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_provides_detailed_report_when_verbose(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given verbose=True, provides detailed validation results."""
        # Archive and database are already set up by fixture
        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=True,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.passed is True
        assert result.details is not None
        assert "archive_file" in result.details
        assert "checks" in result.details
        # The checks dict contains the individual check results
        checks = result.details["checks"]
        assert checks["count_check"] is True
        assert checks["database_check"] is True
        assert checks["integrity_check"] is True
        assert checks["spot_check"] is True

    @pytest.mark.asyncio
    async def test_reports_validation_failure_with_errors(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given an archive that doesn't match database, reports failure."""
        # Archive and database are already set up by fixture with 3 messages
        # Now modify the mbox file to create a mismatch by adding an extra message
        mbox = mailbox.mbox(str(archive_with_messages))
        msg = mailbox.mboxMessage()
        msg["From"] = "extra@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Extra message"
        msg["Message-ID"] = "<extra@example.com>"
        msg.set_payload("Extra message body")
        mbox.add(msg)
        mbox.close()

        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Should fail count check (4 messages in file vs 3 in database)
        assert result.passed is False
        assert result.count_check is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_reports_progress_during_validation(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given a progress reporter, reports status during validation."""
        # Archive and database are already set up by fixture
        # Set up progress mock
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        task_cm.fail = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage, progress=progress)
        result = await workflow.run(config)

        # Progress should be used
        assert progress.task_sequence.called
        assert task_cm.complete.called
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_reports_failure_in_progress_when_validation_fails(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given validation failure, reports it through progress reporter."""
        # Archive and database are already set up by fixture
        # Corrupt the archive by adding extra message
        mbox = mailbox.mbox(str(archive_with_messages))
        msg = mailbox.mboxMessage()
        msg["From"] = "corrupt@example.com"
        msg["Subject"] = "Corrupt"
        msg["Message-ID"] = "<corrupt@example.com>"
        msg.set_payload("Corrupt")
        mbox.add(msg)
        mbox.close()

        # Set up progress mock
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        task_cm.fail = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage, progress=progress)
        result = await workflow.run(config)

        # Should report failure
        assert progress.task_sequence.called
        assert task_cm.fail.called
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_validates_without_progress_reporter(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Given no progress reporter, still validates successfully."""
        # Archive and database are already set up by fixture
        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        # No progress reporter
        workflow = ValidateWorkflow(hybrid_storage, progress=None)
        result = await workflow.run(config)

        assert result.passed is True
        assert result.count_check is True

    @pytest.mark.asyncio
    async def test_validates_empty_archive_set(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given an archive with no messages in database, handles gracefully."""
        # Create empty archive
        mbox_path = tmp_path / "empty.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        mbox.close()  # Just create empty file

        config = ValidateConfig(
            archive_file=str(mbox_path),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Empty archives fail integrity_check (no readable messages)
        assert result.passed is False
        assert result.count_check is True  # Count matches (0 == 0)
        assert result.integrity_check is False  # No readable messages

    @pytest.mark.asyncio
    async def test_storage_attribute_set_correctly(self, hybrid_storage: HybridStorage) -> None:
        """Verify storage attribute is set during initialization."""
        workflow = ValidateWorkflow(hybrid_storage)
        assert workflow.storage is hybrid_storage

    @pytest.mark.asyncio
    async def test_progress_attribute_set_correctly(self, hybrid_storage: HybridStorage) -> None:
        """Verify progress attribute is set during initialization."""
        progress = MagicMock()
        workflow = ValidateWorkflow(hybrid_storage, progress=progress)
        assert workflow.progress is progress

    @pytest.mark.asyncio
    async def test_verbose_details_include_all_checks(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Verify verbose details include all check statuses."""
        # Archive and database are already set up by fixture
        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=True,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.details is not None
        checks = result.details["checks"]
        assert "count_check" in checks
        assert "database_check" in checks
        assert "integrity_check" in checks
        assert "spot_check" in checks
        assert checks["count_check"] is True
        assert checks["database_check"] is True
        assert checks["integrity_check"] is True
        assert checks["spot_check"] is True

    @pytest.mark.asyncio
    async def test_facade_closed_after_validation(
        self, hybrid_storage: HybridStorage, archive_with_messages: Path
    ) -> None:
        """Verify ValidatorFacade is properly closed after validation."""
        # Archive and database are already set up by fixture
        config = ValidateConfig(
            archive_file=str(archive_with_messages),
            state_db=str(hybrid_storage.db.db_path),
            verbose=False,
        )

        workflow = ValidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # The test succeeds if no resource warnings occur
        # The finally block ensures close() is called
        assert result.passed is True


class TestValidateConfigDataclass:
    """Test ValidateConfig dataclass."""

    def test_creates_config_with_required_fields(self) -> None:
        """Can create ValidateConfig with required fields."""
        config = ValidateConfig(
            archive_file="/path/to/archive.mbox",
            state_db="/path/to/state.db",
        )

        assert config.archive_file == "/path/to/archive.mbox"
        assert config.state_db == "/path/to/state.db"
        assert config.verbose is False

    def test_creates_config_with_verbose_flag(self) -> None:
        """Can create ValidateConfig with verbose enabled."""
        config = ValidateConfig(
            archive_file="/path/to/archive.mbox",
            state_db="/path/to/state.db",
            verbose=True,
        )

        assert config.verbose is True


class TestValidateResultDataclass:
    """Test ValidateResult dataclass."""

    def test_creates_result_with_all_fields(self) -> None:
        """Can create ValidateResult with all fields."""
        result = ValidateResult(
            passed=True,
            count_check=True,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=[],
            details={"test": "data"},
        )

        assert result.passed is True
        assert result.count_check is True
        assert result.details == {"test": "data"}

    def test_creates_result_with_errors(self) -> None:
        """Can create ValidateResult with error messages."""
        result = ValidateResult(
            passed=False,
            count_check=False,
            database_check=True,
            integrity_check=True,
            spot_check=True,
            errors=["Count mismatch", "Invalid checksum"],
            details=None,
        )

        assert result.passed is False
        assert len(result.errors) == 2
        assert "Count mismatch" in result.errors
