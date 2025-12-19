"""Behavior tests for ScanMboxStep.

These tests verify the step's behavior from a user's perspective:
- Given an mbox file, it scans and returns message information
- It handles various edge cases gracefully
"""

import mailbox
from pathlib import Path

import pytest

from gmailarchiver.core.workflows.step import StepContext
from gmailarchiver.core.workflows.steps.scan import MboxScanInput, ScanMboxStep


class TestScanMboxStepBehavior:
    """Test ScanMboxStep behavior with real mbox files."""

    @pytest.fixture
    def mbox_with_messages(self, tmp_path: Path) -> Path:
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
    def empty_mbox(self, tmp_path: Path) -> Path:
        """Create an empty mbox file."""
        mbox_path = tmp_path / "empty.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        mbox.close()
        return mbox_path

    @pytest.mark.asyncio
    async def test_scans_mbox_and_returns_message_count(self, mbox_with_messages: Path) -> None:
        """Given an mbox with 3 messages, scan returns count of 3."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(mbox_with_messages)))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_messages == 3

    @pytest.mark.asyncio
    async def test_extracts_rfc_message_ids(self, mbox_with_messages: Path) -> None:
        """Scan extracts RFC Message-IDs from each message."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(mbox_with_messages)))

        assert result.success is True
        assert result.data is not None
        # Check that we got 3 messages with their IDs
        scanned = result.data.scanned_messages
        assert len(scanned) == 3
        # Each entry is (rfc_id, offset, length)
        rfc_ids = [msg[0] for msg in scanned]
        assert "<msg0@example.com>" in rfc_ids
        assert "<msg1@example.com>" in rfc_ids
        assert "<msg2@example.com>" in rfc_ids

    @pytest.mark.asyncio
    async def test_returns_archive_file_path(self, mbox_with_messages: Path) -> None:
        """Scan result includes the archive file path."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(mbox_with_messages)))

        assert result.success is True
        assert result.data is not None
        assert result.data.archive_file == str(mbox_with_messages)

    @pytest.mark.asyncio
    async def test_handles_empty_mbox(self, empty_mbox: Path) -> None:
        """Given an empty mbox, returns zero messages."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(empty_mbox)))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_messages == 0
        assert result.data.scanned_messages == []

    @pytest.mark.asyncio
    async def test_fails_gracefully_for_missing_file(self, tmp_path: Path) -> None:
        """Given a non-existent file, returns failure result."""
        step = ScanMboxStep()
        context = StepContext()
        nonexistent = tmp_path / "does_not_exist.mbox"

        result = await step.execute(context, MboxScanInput(str(nonexistent)))

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_accepts_path_string_directly(self, mbox_with_messages: Path) -> None:
        """Step accepts a path string as input (not just MboxScanInput)."""
        step = ScanMboxStep()
        context = StepContext()

        # Pass string directly instead of MboxScanInput
        result = await step.execute(context, str(mbox_with_messages))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_messages == 3

    @pytest.mark.asyncio
    async def test_accepts_path_object_directly(self, mbox_with_messages: Path) -> None:
        """Step accepts a Path object as input."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, mbox_with_messages)

        assert result.success is True
        assert result.data is not None
        assert result.data.total_messages == 3

    @pytest.mark.asyncio
    async def test_stores_path_in_context(self, mbox_with_messages: Path) -> None:
        """Scan stores the archive path in context for subsequent steps."""
        step = ScanMboxStep()
        context = StepContext()

        await step.execute(context, MboxScanInput(str(mbox_with_messages)))

        # Context should have the path stored
        assert "mbox_path" in context or "archive_file" in context

    @pytest.mark.asyncio
    async def test_step_has_descriptive_name(self) -> None:
        """Step has a name for identification in workflows."""
        step = ScanMboxStep()
        assert step.name == "scan_mbox"
        assert len(step.description) > 0


class TestScanMboxStepWithProgress:
    """Test scanning with progress reporting."""

    @pytest.fixture
    def mbox_with_messages(self, tmp_path: Path) -> Path:
        """Create an mbox file with test messages."""
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        for i in range(3):
            msg = mailbox.mboxMessage()
            msg["From"] = f"sender{i}@example.com"
            msg["Subject"] = f"Test message {i}"
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg.set_payload(f"Body {i}")
            mbox.add(msg)

        mbox.close()
        return mbox_path

    @pytest.mark.asyncio
    async def test_reports_progress_during_scan(self, mbox_with_messages: Path) -> None:
        """Scan reports progress when progress reporter is provided."""
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
        progress.task_sequence = MagicMock(return_value=seq_cm)

        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(mbox_with_messages)), progress)

        assert result.success is True
        progress.task_sequence.assert_called_once()
        task_cm.complete.assert_called_once()


class TestScanMboxStepWithCompression:
    """Test scanning compressed mbox files."""

    @pytest.fixture
    def gzipped_mbox(self, tmp_path: Path) -> Path:
        """Create a gzipped mbox file."""
        import gzip

        # First create uncompressed
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["From"] = "sender@example.com"
        msg["Subject"] = "Compressed message"
        msg["Message-ID"] = "<compressed@example.com>"
        msg.set_payload("Body")
        mbox.add(msg)
        mbox.close()

        # Compress it
        gz_path = tmp_path / "test.mbox.gz"
        with open(mbox_path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                f_out.write(f_in.read())

        return gz_path

    @pytest.mark.asyncio
    async def test_scans_gzipped_mbox(self, gzipped_mbox: Path) -> None:
        """Given a gzipped mbox, scan decompresses and returns messages."""
        step = ScanMboxStep()
        context = StepContext()

        result = await step.execute(context, MboxScanInput(str(gzipped_mbox)))

        assert result.success is True
        assert result.data is not None
        assert result.data.total_messages == 1


class TestScanMboxStepEdgeCases:
    """Test edge cases and error handling in ScanMboxStep."""

    @pytest.mark.asyncio
    async def test_handles_none_input_gracefully(self) -> None:
        """ScanMboxStep returns failure with clear message on None input."""
        step = ScanMboxStep()
        context = StepContext()

        # Pass None as input - step should gracefully handle this
        result = await step.execute(context, None)  # type: ignore[arg-type]

        # Should fail with a clear error message
        assert result.success is False
        assert result.error is not None
        # Error should mention archive/path in some way
        error_lower = result.error.lower()
        assert "archive" in error_lower or "path" in error_lower or "not found" in error_lower
