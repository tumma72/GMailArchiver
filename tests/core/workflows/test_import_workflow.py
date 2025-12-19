"""Behavior tests for ImportWorkflow.

These tests verify the workflow's behavior from a user's perspective:
- Given mbox files, it imports them into the database
- It handles duplicates according to configuration
- It aggregates statistics across multiple files
"""

import mailbox
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gmailarchiver.core.workflows.import_ import (
    ImportConfig,
    ImportWorkflow,
)
from gmailarchiver.data.hybrid_storage import HybridStorage


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
def two_mbox_files(tmp_path: Path) -> tuple[Path, Path]:
    """Create two mbox files with different messages."""
    mbox1_path = tmp_path / "archive1.mbox"
    mbox1 = mailbox.mbox(str(mbox1_path))

    for i in range(2):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
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
        msg["Subject"] = f"Archive2 message {i}"
        msg["Message-ID"] = f"<archive2_msg{i}@example.com>"
        msg.set_payload(f"Body {i}")
        mbox2.add(msg)
    mbox2.close()

    return mbox1_path, mbox2_path


class TestImportWorkflowBehavior:
    """Test ImportWorkflow behavior."""

    @pytest.mark.asyncio
    async def test_imports_single_mbox_file(
        self, hybrid_storage: HybridStorage, mbox_with_messages: Path
    ) -> None:
        """Given an mbox file, imports all messages."""
        config = ImportConfig(
            archive_patterns=[str(mbox_with_messages)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.imported_count == 3
        assert len(result.files_processed) == 1
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_imports_multiple_files_via_pattern(
        self,
        hybrid_storage: HybridStorage,
        two_mbox_files: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        """Given a pattern matching multiple files, imports all."""
        config = ImportConfig(
            archive_patterns=[str(tmp_path / "*.mbox")],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)
        result = await workflow.run(config)

        # 2 + 3 = 5 messages total
        assert result.imported_count == 5
        assert len(result.files_processed) == 2
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_skips_duplicates_when_dedupe_enabled(
        self, hybrid_storage: HybridStorage, mbox_with_messages: Path
    ) -> None:
        """Given duplicate messages, skips them when dedupe is enabled."""
        config = ImportConfig(
            archive_patterns=[str(mbox_with_messages)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)

        # First import
        result1 = await workflow.run(config)
        assert result1.imported_count == 3

        # Second import - should find duplicates
        result2 = await workflow.run(config)
        assert result2.imported_count == 0
        assert result2.duplicate_count == 3

    @pytest.mark.asyncio
    async def test_handles_no_matching_files(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Given a pattern with no matches, returns empty result."""
        config = ImportConfig(
            archive_patterns=[str(tmp_path / "nonexistent*.mbox")],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.imported_count == 0
        assert len(result.files_processed) == 0

    @pytest.mark.asyncio
    async def test_reports_progress_during_import(
        self, hybrid_storage: HybridStorage, mbox_with_messages: Path
    ) -> None:
        """Given a progress reporter, passes it to step-based workflow."""
        progress = MagicMock()
        # Mock task_sequence for step-level progress
        seq_cm = MagicMock()
        task_cm = MagicMock()
        seq_cm.__enter__ = MagicMock(return_value=seq_cm)
        seq_cm.__exit__ = MagicMock(return_value=False)
        seq_cm.task = MagicMock(return_value=task_cm)
        task_cm.__enter__ = MagicMock(return_value=task_cm)
        task_cm.__exit__ = MagicMock(return_value=False)
        task_cm.complete = MagicMock()
        task_cm.advance = MagicMock()
        progress.task_sequence = MagicMock(return_value=seq_cm)

        config = ImportConfig(
            archive_patterns=[str(mbox_with_messages)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage, progress=progress)
        await workflow.run(config)

        # Progress is passed to steps which use task_sequence
        # (step-level progress reporting, not workflow-level info calls)
        assert progress.task_sequence.called

    @pytest.mark.asyncio
    async def test_aggregates_results_from_multiple_patterns(
        self, hybrid_storage: HybridStorage, two_mbox_files: tuple[Path, Path]
    ) -> None:
        """Given multiple patterns, aggregates results from all."""
        mbox1, mbox2 = two_mbox_files

        config = ImportConfig(
            archive_patterns=[str(mbox1), str(mbox2)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)
        result = await workflow.run(config)

        assert result.imported_count == 5
        assert len(result.files_processed) == 2


class TestImportWorkflowErrorHandling:
    """Test ImportWorkflow error handling paths."""

    @pytest.mark.asyncio
    async def test_handles_import_errors_with_progress(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Collects errors in result when import fails."""
        from unittest.mock import AsyncMock, patch

        from gmailarchiver.core.workflows.step import WorkflowError

        # Create a valid mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox_path.write_text("")

        config = ImportConfig(
            archive_patterns=[str(mbox_path)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)

        # Mock _import_single_file to raise a WorkflowError
        with patch.object(
            workflow,
            "_import_single_file",
            new=AsyncMock(side_effect=WorkflowError("import_step", "Import failed")),
        ):
            result = await workflow.run(config)

        # Should have errors in result (error handling is now at CLI layer)
        assert len(result.errors) > 0
        assert "Import failed" in result.errors[0] or "import_step" in result.errors[0]

    @pytest.mark.asyncio
    async def test_handles_general_exception_with_progress(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Collects general exceptions in result."""
        from unittest.mock import AsyncMock, patch

        # Create a valid mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox_path.write_text("")

        config = ImportConfig(
            archive_patterns=[str(mbox_path)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)

        # Mock _import_single_file to raise a general exception
        with patch.object(
            workflow,
            "_import_single_file",
            new=AsyncMock(side_effect=Exception("Unexpected error")),
        ):
            result = await workflow.run(config)

        # Should have errors in result (error handling is now at CLI layer)
        assert len(result.errors) > 0
        assert "Unexpected error" in result.errors[0]

    @pytest.mark.asyncio
    async def test_collects_errors_from_single_file_result(
        self, hybrid_storage: HybridStorage, tmp_path: Path
    ) -> None:
        """Collects errors returned in single file result."""
        from unittest.mock import AsyncMock, patch

        # Create a valid mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox_path.write_text("")

        config = ImportConfig(
            archive_patterns=[str(mbox_path)],
            state_db=str(hybrid_storage.db.db_path),
            dedupe=True,
        )

        workflow = ImportWorkflow(hybrid_storage)

        # Mock _import_single_file to return a result with errors
        mock_result = {
            "imported_count": 0,
            "duplicate_count": 0,
            "skipped_count": 0,
            "errors": ["Error reading message"],
        }

        with patch.object(workflow, "_import_single_file", new=AsyncMock(return_value=mock_result)):
            result = await workflow.run(config)

        # Should have collected the error
        assert len(result.errors) > 0
        assert "Error reading message" in result.errors
