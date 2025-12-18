"""Behavior tests for DedupeWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given archives with or without duplicates, it scans for duplicates
- It respects dry-run mode
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.core.workflows.dedupe import (
    DedupeConfig,
    DedupeWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


class TestDedupeWorkflowBehavior:
    """Test DedupeWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_finds_no_duplicates_when_none_exist(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given archives without duplicates, returns zero count."""
        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=True,
        )

        workflow = DedupeWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.duplicates_found == 0
        assert result.duplicates_removed == 0
        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_returns_empty_result_for_empty_database(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given an empty database, returns zero counts."""
        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=False,
        )

        workflow = DedupeWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.duplicates_found == 0
        assert result.duplicates_removed == 0
        assert result.messages_kept == 0
        assert result.space_saved == 0

    @pytest.mark.asyncio
    async def test_reports_progress_when_scanning(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Reports progress during duplicate scanning."""
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

        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=True,
        )

        workflow = DedupeWorkflow(hybrid_storage, progress=progress)
        await workflow.run(config)

        # Progress should have been called
        progress.task_sequence.assert_called()

    @pytest.mark.asyncio
    async def test_respects_output_file_config(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Output file is included in result when specified."""
        output_file = str(tmp_path / "deduplicated.mbox")

        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=True,
            output_file=output_file,
        )

        workflow = DedupeWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.output_file == output_file

    @pytest.mark.asyncio
    async def test_respects_strategy_config(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Strategy is passed through to deduplication."""
        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=True,
            strategy="largest",
        )

        workflow = DedupeWorkflow(hybrid_storage)
        # Should not raise an error for valid strategy
        result = await workflow.run(config)

        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_reports_progress_when_duplicates_found(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Reports progress completion when duplicates are found."""
        from unittest.mock import AsyncMock, patch

        from gmailarchiver.core.deduplicator._scanner import MessageInfo
        from gmailarchiver.core.deduplicator.facade import DeduplicationResult

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

        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=True,
        )

        # Mock duplicates found
        mock_duplicates = {
            "<msg1@test.com>": [
                MessageInfo(
                    gmail_id="1",
                    archive_file="test.mbox",
                    mbox_offset=0,
                    mbox_length=500,
                    size_bytes=500,
                    archived_timestamp="2024-01-01T00:00:00Z",
                ),
                MessageInfo(
                    gmail_id="2",
                    archive_file="test.mbox",
                    mbox_offset=1000,
                    mbox_length=500,
                    size_bytes=500,
                    archived_timestamp="2024-01-02T00:00:00Z",
                ),
            ]
        }

        mock_result = DeduplicationResult(
            messages_removed=1,
            messages_kept=1,
            space_saved=1000,
            dry_run=True,
        )

        workflow = DedupeWorkflow(hybrid_storage, progress=progress)

        # Mock DeduplicatorFacade.create to return a mock facade
        with patch("gmailarchiver.core.workflows.dedupe.DeduplicatorFacade") as MockDedup:
            mock_dedup_instance = AsyncMock()
            mock_dedup_instance.find_duplicates = AsyncMock(return_value=mock_duplicates)
            mock_dedup_instance.deduplicate = AsyncMock(return_value=mock_result)
            MockDedup.create = AsyncMock(return_value=mock_dedup_instance)

            await workflow.run(config)

        # Verify progress was called (task.complete for duplicates found)
        task_cm.complete.assert_called()
        # Verify message about duplicates found
        calls = [str(c) for c in task_cm.complete.call_args_list]
        assert any("duplicate" in c.lower() for c in calls)

    @pytest.mark.asyncio
    async def test_deduplicate_messages_with_progress(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Tests deduplication step with progress reporting."""
        from unittest.mock import AsyncMock, patch

        from gmailarchiver.core.deduplicator._scanner import MessageInfo
        from gmailarchiver.core.deduplicator.facade import DeduplicationResult

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

        config = DedupeConfig(
            archive_files=[str(tmp_path / "test.mbox")],
            dry_run=False,  # Not dry run - actual removal
        )

        mock_duplicates = {
            "<msg1@test.com>": [
                MessageInfo(
                    gmail_id="1",
                    archive_file="test.mbox",
                    mbox_offset=0,
                    mbox_length=500,
                    size_bytes=500,
                    archived_timestamp="2024-01-01T00:00:00Z",
                ),
                MessageInfo(
                    gmail_id="2",
                    archive_file="test.mbox",
                    mbox_offset=1000,
                    mbox_length=500,
                    size_bytes=500,
                    archived_timestamp="2024-01-02T00:00:00Z",
                ),
            ]
        }

        mock_result = DeduplicationResult(
            messages_removed=1,
            messages_kept=1,
            space_saved=1000,
            dry_run=False,
        )

        workflow = DedupeWorkflow(hybrid_storage, progress=progress)

        # Mock DeduplicatorFacade.create to return a mock facade
        with patch("gmailarchiver.core.workflows.dedupe.DeduplicatorFacade") as MockDedup:
            mock_dedup_instance = AsyncMock()
            mock_dedup_instance.find_duplicates = AsyncMock(return_value=mock_duplicates)
            mock_dedup_instance.deduplicate = AsyncMock(return_value=mock_result)
            MockDedup.create = AsyncMock(return_value=mock_dedup_instance)

            await workflow.run(config)

        # Verify task.complete was called for both scanning and dedupe
        assert task_cm.complete.call_count >= 2
