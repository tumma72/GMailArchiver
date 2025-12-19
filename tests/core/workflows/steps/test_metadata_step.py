"""Behavior tests for RecordMetadataStep.

These tests verify the step's behavior from a user's perspective:
- Given messages to import, it writes their metadata to the database
- It handles various input types correctly
"""

import mailbox
from pathlib import Path

import pytest

from gmailarchiver.core.workflows.step import ContextKeys, StepContext
from gmailarchiver.core.workflows.steps.filter import FilterOutput
from gmailarchiver.core.workflows.steps.metadata import (
    MetadataInput,
    RecordMetadataStep,
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


class TestRecordMetadataStepBehavior:
    """Test RecordMetadataStep behavior."""

    @pytest.mark.asyncio
    async def test_imports_messages_from_filter_output(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Given FilterOutput from previous step, imports those messages."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        # Simulate FilterOutput from CheckDuplicatesStep
        # Note: need to get actual offsets from the mbox
        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output)

        assert result.success is True
        assert result.data is not None
        assert result.data.imported_count == 3
        assert result.data.failed_count == 0

    @pytest.mark.asyncio
    async def test_messages_are_persisted_to_database(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Imported messages can be queried from the database."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        await step.execute(context, filter_output)

        # Verify messages are in database
        existing_ids = await db_manager.get_all_rfc_message_ids()
        assert "<msg0@example.com>" in existing_ids
        assert "<msg1@example.com>" in existing_ids
        assert "<msg2@example.com>" in existing_ids

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, db_manager: DBManager) -> None:
        """Given no messages to import, returns success with zero count."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, "/some/path.mbox")

        filter_output = FilterOutput(
            to_process=[],
            total_count=0,
            new_count=0,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output)

        assert result.success is True
        assert result.data is not None
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_reads_from_context_when_no_input(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """When input is None, reads messages from context."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        # Set up context as if previous steps ran
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set(ContextKeys.TO_ARCHIVE, scanned)
        context.set("account_id", "default")

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        assert result.data.imported_count == 3

    @pytest.mark.asyncio
    async def test_fails_when_no_archive_path(self, db_manager: DBManager) -> None:
        """Fails gracefully when archive path is not provided."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        # Don't set ARCHIVE_FILE

        filter_output = FilterOutput(
            to_process=[("<msg@example.com>", 0, 100)],
            total_count=1,
            new_count=1,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output)

        assert result.success is False
        assert result.error is not None
        assert "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fails_when_archive_file_missing(
        self, db_manager: DBManager, tmp_path: Path
    ) -> None:
        """Fails gracefully when archive file doesn't exist."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(tmp_path / "nonexistent.mbox"))

        filter_output = FilterOutput(
            to_process=[("<msg@example.com>", 0, 100)],
            total_count=1,
            new_count=1,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output)

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stores_imported_count_in_context(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step stores the imported count in context for subsequent steps."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        await step.execute(context, filter_output)

        assert context.get(ContextKeys.IMPORTED_COUNT) == 3

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self, db_manager: DBManager) -> None:
        """Step has a name for identification in workflows."""
        step = RecordMetadataStep(db_manager)

        assert step.name == "record_metadata"
        assert len(step.description) > 0

    @pytest.mark.asyncio
    async def test_accepts_metadata_input_directly(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step accepts MetadataInput as input type."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        metadata_input = MetadataInput(
            messages_to_import=scanned,
            archive_path=str(mbox_with_messages),
            account_id="test_account",
        )

        result = await step.execute(context, metadata_input)

        assert result.success is True
        assert result.data is not None
        assert result.data.imported_count == 3


class TestRecordMetadataStepWithProgress:
    """Test metadata recording with progress reporting."""

    @pytest.mark.asyncio
    async def test_reports_progress_during_import(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Metadata recording reports progress when progress reporter is provided."""
        from unittest.mock import MagicMock

        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        task_cm.set_status = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output, progress)

        assert result.success is True
        progress.task_sequence.assert_called_once()
        task_cm.complete.assert_called_once()
        # Should show import count in completion message
        call_arg = task_cm.complete.call_args[0][0]
        assert "3" in call_arg or "imported" in call_arg.lower()

    @pytest.mark.asyncio
    async def test_reports_empty_import_progress(self, db_manager: DBManager) -> None:
        """Progress shows appropriate message when no messages imported."""
        from unittest.mock import MagicMock

        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        task_cm.set_status = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, "/some/path.mbox")

        filter_output = FilterOutput(
            to_process=[],
            total_count=0,
            new_count=0,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output, progress)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_skips_messages_not_in_offset_map_with_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Messages not in offset_map are skipped (continue statement with progress)."""
        from unittest.mock import MagicMock

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        # Create progress mock
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.advance = MagicMock()
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        # Pass messages with wrong offsets so they get skipped (continue path)
        # Using offset 999 which won't exist in the mbox file
        filter_output = FilterOutput(
            to_process=[
                ("<msg0@example.com>", 999, 100),  # Wrong offset - will continue
                ("<msg1@example.com>", 888, 100),  # Wrong offset - will continue
            ],
            total_count=2,
            new_count=2,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output, progress)

        assert result.success is True
        # No messages were imported due to offset mismatches
        assert result.data is not None
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_handles_write_result_skipped_with_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Test handling of WriteResult.SKIPPED with progress reporting."""
        from unittest.mock import MagicMock, patch

        from gmailarchiver.core.importer._writer import WriteResult

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        # Mock the writer to return SKIPPED for all writes
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.advance = MagicMock()
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.return_value = WriteResult.SKIPPED

            result = await step.execute(context, filter_output, progress)

        assert result.success is True
        assert result.data is not None
        assert result.data.skipped_count == 3
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_handles_write_result_failed_with_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Test handling of WriteResult.FAILED with progress reporting."""
        from unittest.mock import MagicMock, patch

        from gmailarchiver.core.importer._writer import WriteResult

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        # Create progress mock
        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.advance = MagicMock()
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        # Mock the writer to return FAILED for all writes
        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.return_value = WriteResult.FAILED

            result = await step.execute(context, filter_output, progress)

        assert result.success is True
        assert result.data is not None
        assert result.data.failed_count == 3
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_shows_no_messages_imported_message_with_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Progress task shows 'No new messages' when no imports happen."""
        from unittest.mock import MagicMock, patch

        from gmailarchiver.core.importer._writer import WriteResult

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.advance = MagicMock()
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.return_value = WriteResult.SKIPPED

            await step.execute(context, filter_output, progress)

        # Should show "No new messages" when imported_count is 0
        call_arg = task_cm.complete.call_args[0][0]
        assert "No new messages" in call_arg


class TestRecordMetadataStepWithoutProgress:
    """Test metadata recording without progress reporter."""

    @pytest.mark.asyncio
    async def test_skips_messages_not_in_offset_map_without_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Messages not in offset_map are skipped (continue statement without progress)."""
        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        # Pass messages with wrong offsets so they get skipped (continue path)
        # Using offset 999 which won't exist in the mbox file
        filter_output = FilterOutput(
            to_process=[
                ("<msg0@example.com>", 999, 100),  # Wrong offset - will continue
                ("<msg1@example.com>", 888, 100),  # Wrong offset - will continue
            ],
            total_count=2,
            new_count=2,
            duplicate_count=0,
        )

        result = await step.execute(context, filter_output, progress=None)

        assert result.success is True
        assert result.data is not None
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_handles_write_result_skipped_without_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Test handling of WriteResult.SKIPPED without progress reporting."""
        from unittest.mock import patch

        from gmailarchiver.core.importer._writer import WriteResult

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.return_value = WriteResult.SKIPPED

            result = await step.execute(context, filter_output, progress=None)

        assert result.success is True
        assert result.data is not None
        assert result.data.skipped_count == 3
        assert result.data.imported_count == 0

    @pytest.mark.asyncio
    async def test_handles_write_result_failed_without_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Test handling of WriteResult.FAILED without progress reporting."""
        from unittest.mock import patch

        from gmailarchiver.core.importer._writer import WriteResult

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.return_value = WriteResult.FAILED

            result = await step.execute(context, filter_output, progress=None)

        assert result.success is True
        assert result.data is not None
        assert result.data.failed_count == 3
        assert result.data.imported_count == 0


class TestRecordMetadataStepErrorHandling:
    """Test error handling in metadata recording."""

    @pytest.mark.asyncio
    async def test_catches_exception_during_message_processing(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step catches exceptions during message processing and records them."""
        from unittest.mock import patch

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        # Mock write_message to raise an exception
        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.side_effect = RuntimeError("Database write failed")

            result = await step.execute(context, filter_output, progress=None)

        assert result.success is True
        assert result.data is not None
        assert result.data.failed_count == 3
        assert result.data.imported_count == 0
        assert len(result.data.errors) == 3
        assert all("Message" in error for error in result.data.errors)

    @pytest.mark.asyncio
    async def test_handles_exception_during_metadata_extraction(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step catches exceptions during metadata extraction."""
        from unittest.mock import patch

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        # Mock extract_metadata to raise an exception
        with patch.object(MboxReader, "extract_metadata") as mock_extract:
            mock_extract.side_effect = ValueError("Invalid message format")

            result = await step.execute(context, filter_output, progress=None)

        assert result.success is True
        assert result.data is not None
        assert result.data.failed_count == 3
        assert result.data.imported_count == 0
        assert len(result.data.errors) == 3

    @pytest.mark.asyncio
    async def test_handles_exception_during_processing_with_progress(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step catches exceptions during processing and reports progress."""
        from unittest.mock import MagicMock, patch

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))
        context.set("account_id", "test_account")

        from gmailarchiver.core.importer._reader import MboxReader

        reader = MboxReader()
        scanned = reader.scan_rfc_message_ids(mbox_with_messages, None)

        filter_output = FilterOutput(
            to_process=scanned,
            total_count=3,
            new_count=3,
            duplicate_count=0,
        )

        progress = MagicMock()
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.advance = MagicMock()
        task_cm.complete = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        with patch(
            "gmailarchiver.core.importer._writer.DatabaseWriter.write_message"
        ) as mock_write:
            mock_write.side_effect = RuntimeError("Database write failed")

            result = await step.execute(context, filter_output, progress)

        assert result.success is True
        assert result.data is not None
        assert result.data.failed_count == 3

    @pytest.mark.asyncio
    async def test_returns_failure_on_reader_initialization_exception(
        self, db_manager: DBManager, mbox_with_messages: Path
    ) -> None:
        """Step returns failure if exception occurs during core setup."""
        from unittest.mock import patch

        step = RecordMetadataStep(db_manager)
        context = StepContext()
        context.set(ContextKeys.ARCHIVE_FILE, str(mbox_with_messages))

        filter_output = FilterOutput(
            to_process=[("<msg@example.com>", 0, 100)],
            total_count=1,
            new_count=1,
            duplicate_count=0,
        )

        # Mock db_manager.commit to raise an exception
        with patch.object(db_manager, "commit", side_effect=RuntimeError("Commit failed")):
            result = await step.execute(context, filter_output)

        assert result.success is False
        assert result.error is not None
        assert "Failed to record metadata" in result.error
