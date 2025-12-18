"""Behavior tests for ConsolidateWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given multiple archives, it merges them into one
- It handles deduplication and sorting
"""

import mailbox
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.core.workflows.consolidate import (
    ConsolidateConfig,
    ConsolidateWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


@pytest.fixture
def two_mbox_files(tmp_path: Path) -> tuple[Path, Path]:
    """Create two mbox files with different messages."""
    mbox1_path = tmp_path / "archive1.mbox"
    mbox1 = mailbox.mbox(str(mbox1_path))

    for i in range(2):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg["Subject"] = f"Archive1 message {i}"
        msg["Message-ID"] = f"<archive1_msg{i}@example.com>"
        msg.set_payload(f"Body {i}")
        mbox1.add(msg)
    mbox1.close()

    mbox2_path = tmp_path / "archive2.mbox"
    mbox2 = mailbox.mbox(str(mbox2_path))

    for i in range(3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["Date"] = "Tue, 2 Jan 2024 00:00:00 +0000"
        msg["Subject"] = f"Archive2 message {i}"
        msg["Message-ID"] = f"<archive2_msg{i}@example.com>"
        msg.set_payload(f"Body {i}")
        mbox2.add(msg)
    mbox2.close()

    return mbox1_path, mbox2_path


# ============================================================================
# Basic Consolidation Tests
# ============================================================================


class TestConsolidateWorkflowBehavior:
    """Test ConsolidateWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_consolidates_multiple_archives(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Given multiple archives, consolidates them into one."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=False,
            sort_by_date=False,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.messages_count == 5  # 2 + 3
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_consolidates_with_deduplication(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given archives with duplicates, removes them during consolidation."""
        # Create two archives with overlapping messages
        mbox1_path = tmp_path / "archive1.mbox"
        mbox1 = mailbox.mbox(str(mbox1_path))

        msg1 = mailbox.mboxMessage()
        msg1["From"] = "sender@example.com"
        msg1["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg1["Subject"] = "Duplicate message"
        msg1["Message-ID"] = "<duplicate@example.com>"
        msg1.set_payload("Body")
        mbox1.add(msg1)
        mbox1.close()

        mbox2_path = tmp_path / "archive2.mbox"
        mbox2 = mailbox.mbox(str(mbox2_path))

        msg2 = mailbox.mboxMessage()
        msg2["From"] = "sender@example.com"
        msg2["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg2["Subject"] = "Duplicate message"
        msg2["Message-ID"] = "<duplicate@example.com>"  # Same Message-ID
        msg2.set_payload("Body")
        mbox2.add(msg2)
        mbox2.close()

        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1_path), str(mbox2_path)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=False,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Only 1 unique message
        assert result.messages_count == 1
        assert result.duplicates_removed == 1

    @pytest.mark.asyncio
    async def test_consolidates_with_sorting(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given unsorted messages, sorts by date during consolidation."""
        mbox_path = tmp_path / "unsorted.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        # Add messages in reverse chronological order
        msg2 = mailbox.mboxMessage()
        msg2["From"] = "sender@example.com"
        msg2["Date"] = "Tue, 2 Jan 2024 00:00:00 +0000"
        msg2["Subject"] = "Second"
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2.set_payload("Body 2")
        mbox.add(msg2)

        msg1 = mailbox.mboxMessage()
        msg1["From"] = "sender@example.com"
        msg1["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg1["Subject"] = "First"
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1.set_payload("Body 1")
        mbox.add(msg1)

        mbox.close()

        output_path = tmp_path / "sorted.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox_path)],
            output_file=str(output_path),
            dedupe=False,
            sort_by_date=True,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.messages_count == 2
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_handles_multiple_source_files(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Given multiple source files, consolidates them all."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=False,
            sort_by_date=False,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.messages_count == 5
        assert result.source_files_count == 2


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestConsolidateWorkflowErrors:
    """Test ConsolidateWorkflow error handling."""

    @pytest.mark.asyncio
    async def test_raises_error_when_source_file_missing(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """When source file doesn't exist, raises FileNotFoundError."""
        missing_file = tmp_path / "nonexistent.mbox"
        output_path = tmp_path / "output.mbox"

        config = ConsolidateConfig(
            source_files=[str(missing_file)],
            output_file=str(output_path),
        )

        workflow = ConsolidateWorkflow(hybrid_storage)

        with pytest.raises(FileNotFoundError, match="Source files not found"):
            await workflow.run(config)

    @pytest.mark.asyncio
    async def test_raises_error_when_multiple_source_files_missing(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When some source files are missing, reports all missing files."""
        mbox1, _ = two_mbox_files
        missing1 = tmp_path / "missing1.mbox"
        missing2 = tmp_path / "missing2.mbox"
        output_path = tmp_path / "output.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(missing1), str(missing2)],
            output_file=str(output_path),
        )

        workflow = ConsolidateWorkflow(hybrid_storage)

        with pytest.raises(FileNotFoundError) as exc_info:
            await workflow.run(config)

        # Both missing files should be mentioned
        error_msg = str(exc_info.value)
        assert "missing1.mbox" in error_msg
        assert "missing2.mbox" in error_msg

    @pytest.mark.asyncio
    async def test_raises_error_when_no_source_files(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """When no source files provided, raises ValueError."""
        output_path = tmp_path / "output.mbox"

        config = ConsolidateConfig(
            source_files=[],
            output_file=str(output_path),
        )

        workflow = ConsolidateWorkflow(hybrid_storage)

        with pytest.raises(ValueError, match="No source files specified"):
            await workflow.run(config)


# ============================================================================
# Progress Reporting Tests
# ============================================================================


class TestConsolidateWorkflowProgressReporting:
    """Test ConsolidateWorkflow progress reporting."""

    @pytest.mark.asyncio
    async def test_reports_progress_with_all_options_enabled(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When progress reporter provided, reports consolidation progress."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        # Mock progress reporter
        mock_progress = MagicMock()
        mock_task_sequence = MagicMock()
        mock_task = MagicMock()
        mock_progress.task_sequence.return_value.__enter__.return_value = mock_task_sequence
        mock_task_sequence.task.return_value.__enter__.return_value = mock_task

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=True,
            compress="gzip",
            dedupe_strategy="newest",
        )

        workflow = ConsolidateWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        # Verify progress info messages were called
        assert mock_progress.info.call_count >= 4
        info_calls = [str(call) for call in mock_progress.info.call_args_list]

        # Check for expected messages
        info_messages = " ".join(info_calls)
        assert "Consolidating 2 archives" in info_messages
        assert "Deduplication enabled" in info_messages
        assert "newest" in info_messages
        assert "sorted by date" in info_messages
        assert "gzip" in info_messages

        # Verify task sequence was used
        mock_progress.task_sequence.assert_called_once()
        mock_task_sequence.task.assert_called_once()

        # Verify task completion message
        mock_task.complete.assert_called_once()
        complete_msg = str(mock_task.complete.call_args)
        assert "messages" in complete_msg

        # Verify result
        assert result.messages_count == 5
        assert result.sort_applied is True
        assert result.compression_used == "gzip"

    @pytest.mark.asyncio
    async def test_reports_progress_without_deduplication(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When deduplication disabled, doesn't report dedupe info."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        mock_progress = MagicMock()
        mock_task_sequence = MagicMock()
        mock_task = MagicMock()
        mock_progress.task_sequence.return_value.__enter__.return_value = mock_task_sequence
        mock_task_sequence.task.return_value.__enter__.return_value = mock_task

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=False,
            sort_by_date=False,
        )

        workflow = ConsolidateWorkflow(hybrid_storage, progress=mock_progress)
        await workflow.run(config)

        # Verify basic info was called
        assert mock_progress.info.call_count >= 1
        info_calls = " ".join([str(call) for call in mock_progress.info.call_args_list])

        # Should NOT mention deduplication
        assert "Deduplication" not in info_calls
        assert "Messages will be sorted" not in info_calls

    @pytest.mark.asyncio
    async def test_reports_duplicate_removal_in_completion_message(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """When duplicates removed, includes count in completion message."""
        # Create archives with duplicates
        mbox1_path = tmp_path / "archive1.mbox"
        mbox1 = mailbox.mbox(str(mbox1_path))
        msg1 = mailbox.mboxMessage()
        msg1["From"] = "sender@example.com"
        msg1["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg1["Subject"] = "Duplicate"
        msg1["Message-ID"] = "<dup@example.com>"
        msg1.set_payload("Body")
        mbox1.add(msg1)
        mbox1.close()

        mbox2_path = tmp_path / "archive2.mbox"
        mbox2 = mailbox.mbox(str(mbox2_path))
        msg2 = mailbox.mboxMessage()
        msg2["From"] = "sender@example.com"
        msg2["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
        msg2["Subject"] = "Duplicate"
        msg2["Message-ID"] = "<dup@example.com>"
        msg2.set_payload("Body")
        mbox2.add(msg2)
        mbox2.close()

        output_path = tmp_path / "consolidated.mbox"

        mock_progress = MagicMock()
        mock_task_sequence = MagicMock()
        mock_task = MagicMock()
        mock_progress.task_sequence.return_value.__enter__.return_value = mock_task_sequence
        mock_task_sequence.task.return_value.__enter__.return_value = mock_task

        config = ConsolidateConfig(
            source_files=[str(mbox1_path), str(mbox2_path)],
            output_file=str(output_path),
            dedupe=True,
        )

        workflow = ConsolidateWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        # Verify completion message mentions duplicates
        mock_task.complete.assert_called_once()
        complete_msg = str(mock_task.complete.call_args)
        assert "duplicates removed" in complete_msg

        assert result.duplicates_removed == 1

    @pytest.mark.asyncio
    async def test_works_without_progress_reporter(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When no progress reporter provided, still consolidates successfully."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
        )

        # No progress reporter provided
        workflow = ConsolidateWorkflow(hybrid_storage, progress=None)
        result = await workflow.run(config)

        # Should still work
        assert result.messages_count == 5
        assert output_path.exists()


# ============================================================================
# Compression Tests
# ============================================================================


class TestConsolidateWorkflowCompression:
    """Test ConsolidateWorkflow compression options."""

    @pytest.mark.asyncio
    async def test_consolidates_with_gzip_compression(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When gzip compression requested, creates compressed output."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox.gz"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            compress="gzip",
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.compression_used == "gzip"
        assert output_path.exists()
        assert result.messages_count == 5

    @pytest.mark.asyncio
    async def test_consolidates_without_compression(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When no compression requested, creates uncompressed output."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            compress=None,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.compression_used is None
        assert output_path.exists()


# ============================================================================
# Result Verification Tests
# ============================================================================


class TestConsolidateWorkflowResults:
    """Test ConsolidateWorkflow result reporting."""

    @pytest.mark.asyncio
    async def test_result_includes_all_metadata(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Result includes all consolidation metadata."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=True,
            compress="gzip",
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Verify all result fields
        assert result.output_file == str(output_path)
        assert result.messages_count == 5
        assert result.source_files_count == 2
        assert result.duplicates_removed == 0  # No duplicates in fixture
        assert result.sort_applied is True
        assert result.compression_used == "gzip"

    @pytest.mark.asyncio
    async def test_result_reflects_no_sorting(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """When sorting disabled, result reflects this."""
        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            sort_by_date=False,
        )

        workflow = ConsolidateWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.sort_applied is False
