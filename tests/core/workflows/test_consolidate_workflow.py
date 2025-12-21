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


# ============================================================================
# Step-Based Workflow Tests (TDD Red Phase)
# ============================================================================

# Import the step-based workflow that doesn't exist yet
try:
    from gmailarchiver.core.workflows.composer import WorkflowComposer  # noqa: F401

    STEP_WORKFLOW_AVAILABLE = True
except ImportError:
    STEP_WORKFLOW_AVAILABLE = False


@pytest.mark.skipif(
    not STEP_WORKFLOW_AVAILABLE,
    reason="Step-based consolidate workflow not implemented yet (TDD Red Phase)",
)
class TestConsolidateWorkflowWithComposer:
    """Test ConsolidateWorkflow using WorkflowComposer architecture."""

    @pytest.mark.asyncio
    async def test_uses_workflow_composer(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Consolidate workflow uses WorkflowComposer for step orchestration."""
        # This tests that the workflow is composed using WorkflowComposer
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        workflow = ConsolidateStepWorkflow(hybrid_storage)

        # Should have a composer attribute
        assert hasattr(workflow, "composer")
        assert isinstance(workflow.composer, WorkflowComposer)

    @pytest.mark.asyncio
    async def test_all_three_steps_registered(self, hybrid_storage: HybridStorage) -> None:
        """Workflow registers all three steps: Load, Merge, Validate."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        workflow = ConsolidateStepWorkflow(hybrid_storage)

        # Check that all steps are registered in order
        step_names = [step.name for step in workflow.composer.steps]
        assert "load_archives" in step_names
        assert "merge_and_process" in step_names
        assert "validate_consolidation" in step_names

    @pytest.mark.asyncio
    async def test_steps_execute_in_order(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Steps execute in correct order: Load -> Merge -> Validate."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=True,
            validate=True,
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True
        assert output_path.exists()

        # Verify steps executed in order via step results
        assert result.step_results is not None
        step_order = [r.step_name for r in result.step_results]
        assert step_order == ["load_archives", "merge_and_process", "validate_consolidation"]

    @pytest.mark.asyncio
    async def test_validate_step_skipped_when_disabled(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Validate step is skipped when config.validate=False."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            validate=False,  # Validation disabled
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True

        # Validate step should be skipped
        step_names = [r.step_name for r in result.step_results]
        assert "validate_consolidation" not in step_names

    @pytest.mark.asyncio
    async def test_validate_step_runs_when_enabled(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Validate step runs when config.validate=True."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            validate=True,  # Validation enabled
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True

        # Validate step should have executed
        step_names = [r.step_name for r in result.step_results]
        assert "validate_consolidation" in step_names

    @pytest.mark.asyncio
    async def test_result_aggregation_from_context(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Result is aggregated from step context data."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=True,
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # Result should be aggregated from context
        assert result.messages_count is not None
        assert result.source_files_count == 2
        assert result.output_file == str(output_path)

    @pytest.mark.asyncio
    async def test_error_handling_stops_workflow(
        self,
        hybrid_storage: HybridStorage,
        tmp_path: Path,
    ) -> None:
        """Error in any step stops the workflow."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        missing_file = tmp_path / "nonexistent.mbox"
        output_path = tmp_path / "output.mbox"

        config = ConsolidateConfig(
            source_files=[str(missing_file)],
            output_file=str(output_path),
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

        # Only load step should have been attempted
        step_names = [r.step_name for r in result.step_results]
        assert "load_archives" in step_names
        assert "merge_and_process" not in step_names

    @pytest.mark.asyncio
    async def test_progress_reporter_integration(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Progress reporter is passed to each step."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

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
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage, progress=mock_progress)
        result = await workflow.run(config)

        assert result.success is True
        # Progress reporter should have been used
        assert mock_progress.task_sequence.call_count >= 1

    @pytest.mark.asyncio
    async def test_resource_cleanup_on_success(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Resources are cleaned up after successful workflow."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True

        # Verify no temporary files left behind
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

    @pytest.mark.asyncio
    async def test_resource_cleanup_on_failure(
        self,
        hybrid_storage: HybridStorage,
        tmp_path: Path,
    ) -> None:
        """Resources are cleaned up after failed workflow."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        missing_file = tmp_path / "nonexistent.mbox"
        output_path = tmp_path / "output.mbox"

        config = ConsolidateConfig(
            source_files=[str(missing_file)],
            output_file=str(output_path),
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is False

        # Verify no partial output files left behind
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_context_contains_all_step_data(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """After workflow, context contains data from all steps."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            validate=True,
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True

        # Context should contain data from all steps
        assert result.context is not None
        assert result.context.get("archive_info") is not None  # From LoadArchivesStep
        assert result.context.get("merged_count") is not None  # From MergeAndProcessStep
        assert result.context.get("validation_passed") is not None  # From ValidateConsolidationStep

    @pytest.mark.asyncio
    async def test_config_passed_to_all_steps(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Config is accessible to all steps via context."""
        from gmailarchiver.core.workflows.consolidate import ConsolidateStepWorkflow

        mbox1, mbox2 = two_mbox_files
        output_path = tmp_path / "consolidated.mbox"

        config = ConsolidateConfig(
            source_files=[str(mbox1), str(mbox2)],
            output_file=str(output_path),
            dedupe=True,
            sort_by_date=True,
            compress="gzip",
            dedupe_strategy="largest",
        )

        workflow = ConsolidateStepWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.success is True

        # Config should be in context
        stored_config = result.context.get("config")
        assert stored_config is not None
        assert stored_config["dedupe"] is True
        assert stored_config["sort_by_date"] is True
        assert stored_config["compress"] == "gzip"
        assert stored_config["dedupe_strategy"] == "largest"
