"""Behavior tests for ValidateArchiveStep.

These tests verify the step's behavior from a user's perspective:
- Given an archive, it validates its integrity
- It reports validation results correctly
"""

import mailbox
from pathlib import Path

import pytest

from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.validate import (
    ValidateArchiveStep,
    ValidateInput,
)
from gmailarchiver.data.db_manager import DBManager


@pytest.fixture
def mbox_with_messages(tmp_path: Path) -> Path:
    """Create an mbox file with test messages."""
    mbox_path = tmp_path / "test.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    for i in range(3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Test message {i}"
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg.set_payload(f"Body of message {i}")
        mbox.add(msg)

    mbox.close()
    return mbox_path


@pytest.fixture
def empty_mbox(tmp_path: Path) -> Path:
    """Create an empty mbox file."""
    mbox_path = tmp_path / "empty.mbox"
    mbox = mailbox.mbox(str(mbox_path))
    mbox.close()
    return mbox_path


@pytest.fixture
async def db_with_archive_messages(
    db_manager: DBManager, mbox_with_messages: Path
) -> tuple[DBManager, Path]:
    """Set up database with messages matching the mbox file."""
    from gmailarchiver.core.importer._reader import MboxReader

    reader = MboxReader()
    scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

    for rfc_id, offset, length in scanned:
        await db_manager._conn.execute(
            """
            INSERT INTO messages (
                rfc_message_id, gmail_id, archived_timestamp, archive_file,
                mbox_offset, mbox_length, account_id
            ) VALUES (?, ?, datetime('now'), ?, ?, ?, ?)
            """,
            (rfc_id, f"gmail_{rfc_id}", str(mbox_with_messages), offset, length, "default"),
        )
    await db_manager.commit()
    return db_manager, mbox_with_messages


class TestValidateArchiveStepBehavior:
    """Test ValidateArchiveStep behavior."""

    @pytest.mark.asyncio
    async def test_validates_archive_successfully(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """Given a valid archive with matching database records, validation passes."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        result = await step.execute(context, ValidateInput(str(mbox_path)))

        assert result.success is True
        assert result.data is not None
        assert result.data.passed is True

    @pytest.mark.asyncio
    async def test_reads_archive_path_from_context(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """When input is None, reads archive path from context."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_path))

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_accepts_path_string_directly(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """Step accepts a path string as input."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        result = await step.execute(context, str(mbox_path))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_fails_when_no_archive_path(self, db_manager: DBManager) -> None:
        """Fails gracefully when archive path is not provided."""
        step = ValidateArchiveStep(db_manager)
        context = StepContext()
        # Don't set ARCHIVE_FILE

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error is not None
        assert "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fails_when_archive_file_missing(
        self, db_manager: DBManager, tmp_path: Path
    ) -> None:
        """Fails gracefully when archive file doesn't exist."""
        step = ValidateArchiveStep(db_manager)
        context = StepContext()
        nonexistent = tmp_path / "nonexistent.mbox"

        result = await step.execute(context, ValidateInput(str(nonexistent)))

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stores_validation_result_in_context(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """Step stores validation results in context."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        await step.execute(context, ValidateInput(str(mbox_path)))

        assert ContextKeys.VALIDATION_PASSED in context
        assert context.get(ContextKeys.VALIDATION_PASSED) is True

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self, db_manager: DBManager) -> None:
        """Step has a name for identification in workflows."""
        step = ValidateArchiveStep(db_manager)

        assert step.name == "validate_archive"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_output_contains_check_results(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """Output contains individual check results."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        result = await step.execute(context, ValidateInput(str(mbox_path)))

        assert result.success is True
        assert result.data is not None
        # Check that output has check fields
        assert hasattr(result.data, "count_check")
        assert hasattr(result.data, "database_check")
        assert hasattr(result.data, "integrity_check")
        assert hasattr(result.data, "spot_check")


class TestValidateArchiveStepWithEmptyArchive:
    """Test validation with edge cases."""

    @pytest.mark.asyncio
    async def test_validates_empty_archive(self, db_manager: DBManager, empty_mbox: Path) -> None:
        """Given an empty archive, validation still works."""
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        result = await step.execute(context, ValidateInput(str(empty_mbox)))

        # Should succeed (nothing to validate is valid)
        assert result.success is True
        assert result.data is not None


class TestValidateArchiveStepWithProgress:
    """Test validation with progress reporting."""

    @pytest.mark.asyncio
    async def test_reports_progress_during_validation(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """Validation reports progress when progress reporter is provided."""
        from unittest.mock import MagicMock

        db_manager, mbox_path = db_with_archive_messages

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

        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        result = await step.execute(context, ValidateInput(str(mbox_path)), progress)

        assert result.success is True
        progress.task_sequence.assert_called_once()
        # Either complete or fail should be called
        assert task_cm.complete.called or task_cm.fail.called

    @pytest.mark.asyncio
    async def test_reads_actual_file_from_context_with_fallback(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """When input is None, reads ACTUAL_FILE from context first."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        # Set ACTUAL_FILE in context (primary source)
        context.set(ContextKeys.ACTUAL_FILE, str(mbox_path))

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_falls_back_to_archive_file_when_actual_file_missing(
        self, db_with_archive_messages: tuple[DBManager, Path]
    ) -> None:
        """When ACTUAL_FILE is not in context, falls back to ARCHIVE_FILE."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        # Set only ARCHIVE_FILE (fallback source)
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_path))

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_prioritizes_actual_file_over_archive_file(
        self, db_with_archive_messages: tuple[DBManager, Path], tmp_path: Path
    ) -> None:
        """When both ACTUAL_FILE and ARCHIVE_FILE are in context, prioritizes ACTUAL_FILE."""
        db_manager, mbox_path = db_with_archive_messages
        step = ValidateArchiveStep(db_manager)
        context = StepContext()

        # Create a second mbox for ARCHIVE_FILE
        wrong_mbox = tmp_path / "wrong.mbox"
        wrong_mbox.touch()

        # Set both keys: ACTUAL_FILE should be preferred
        context.set(ContextKeys.ACTUAL_FILE, str(mbox_path))
        context.set(ContextKeys.ARCHIVE_FILE, str(wrong_mbox))

        result = await step.execute(context, None)

        # Should succeed because it used ACTUAL_FILE (the correct one)
        assert result.success is True
        assert result.data is not None
