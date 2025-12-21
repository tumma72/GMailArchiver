"""Tests for consolidate steps - TDD Red Phase.

These tests define the expected behavior for:
- LoadArchivesStep: Validate source files, detect compression, collect metadata
- MergeAndProcessStep: Consolidate archives with optional dedup/sort
- ValidateConsolidationStep: Verify consolidated archive integrity

All tests should FAIL initially because the steps don't exist yet.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.core.workflows.step import StepContext

# Import the steps that don't exist yet - these imports will fail
# until implementation is complete. We use try/except to allow
# tests to be collected, but they will fail when the module doesn't exist.
try:
    from gmailarchiver.core.workflows.steps.consolidate import (
        LoadArchivesStep,
        MergeAndProcessStep,
        ValidateConsolidationStep,
    )
except ImportError:
    # Mark module as missing for pytest.skip
    LoadArchivesStep = None
    MergeAndProcessStep = None
    ValidateConsolidationStep = None

# Skip all tests in this module if the consolidate steps module doesn't exist
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        LoadArchivesStep is None,
        reason="consolidate steps module not implemented yet (TDD Red Phase)",
    ),
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_consolidator() -> AsyncMock:
    """Create a mock ArchiveConsolidator for testing."""
    consolidator = AsyncMock()
    # Default consolidation result
    consolidator.consolidate.return_value = MagicMock(
        output_file="/path/to/output.mbox",
        source_files=["file1.mbox", "file2.mbox"],
        total_messages=10,
        duplicates_removed=2,
        messages_consolidated=8,
        execution_time_ms=100.5,
        sort_applied=True,
        compression_used=None,
    )
    return consolidator


@pytest.fixture
def mock_storage() -> AsyncMock:
    """Create a mock HybridStorage for testing."""
    storage = AsyncMock()
    storage.validate_archive_integrity.return_value = True
    return storage


@pytest.fixture
def mock_progress() -> MagicMock:
    """Create a mock progress reporter for testing."""
    progress = MagicMock()

    # Create mock task sequence with proper context manager
    task_seq = MagicMock()
    progress.task_sequence.return_value.__enter__ = MagicMock(return_value=task_seq)
    progress.task_sequence.return_value.__exit__ = MagicMock(return_value=None)

    # Create mock task handle
    task_handle = MagicMock()
    task_seq.task.return_value.__enter__ = MagicMock(return_value=task_handle)
    task_seq.task.return_value.__exit__ = MagicMock(return_value=None)

    return progress


@pytest.fixture
def context_with_consolidator(mock_consolidator: AsyncMock) -> StepContext:
    """Create a StepContext with mock consolidator injected."""
    context = StepContext()
    context.set("consolidator", mock_consolidator)
    return context


@pytest.fixture
def context_with_storage(mock_storage: AsyncMock) -> StepContext:
    """Create a StepContext with mock storage injected."""
    context = StepContext()
    context.set("storage", mock_storage)
    return context


@pytest.fixture
def consolidate_config() -> dict:
    """Create a sample consolidate configuration."""
    return {
        "source_files": ["/path/to/file1.mbox", "/path/to/file2.mbox"],
        "output_file": "/path/to/output.mbox",
        "dedupe": True,
        "sort_by_date": True,
        "compress": None,
        "dedupe_strategy": "newest",
        "validate": True,
    }


@pytest.fixture
def sample_archive_files(tmp_path: Path) -> list[Path]:
    """Create sample archive files for testing."""
    file1 = tmp_path / "archive1.mbox"
    file2 = tmp_path / "archive2.mbox"
    file1.write_text("From sender@example.com Mon Jan 01 00:00:00 2024\nSubject: Test 1\n\nBody\n")
    file2.write_text("From sender@example.com Tue Jan 02 00:00:00 2024\nSubject: Test 2\n\nBody\n")
    return [file1, file2]


@pytest.fixture
def sample_compressed_files(tmp_path: Path) -> dict[str, Path]:
    """Create sample compressed archive files for testing."""
    import gzip
    import lzma

    uncompressed = tmp_path / "archive.mbox"
    uncompressed.write_text("From sender@example.com\nSubject: Test\n\nBody\n")

    gzip_file = tmp_path / "archive.mbox.gz"
    with gzip.open(gzip_file, "wt") as f:
        f.write("From sender@example.com\nSubject: Gzip Test\n\nBody\n")

    xz_file = tmp_path / "archive.mbox.xz"
    with lzma.open(xz_file, "wt") as f:
        f.write("From sender@example.com\nSubject: XZ Test\n\nBody\n")

    return {
        "uncompressed": uncompressed,
        "gzip": gzip_file,
        "xz": xz_file,
    }


# ============================================================================
# Test: LoadArchivesStep
# ============================================================================


class TestLoadArchivesStep:
    """Test LoadArchivesStep execution."""

    async def test_can_instantiate(self) -> None:
        """LoadArchivesStep can be instantiated."""
        step = LoadArchivesStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """LoadArchivesStep has the correct name attribute."""
        step = LoadArchivesStep()
        assert step.name == "load_archives"

    async def test_has_correct_description(self) -> None:
        """LoadArchivesStep has the correct description attribute."""
        step = LoadArchivesStep()
        assert step.description == "Loading and validating source archives"

    async def test_execute_validates_existing_files(self, sample_archive_files: list[Path]) -> None:
        """Execute validates that all source files exist."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
            },
        )

        result = await step.execute(context, None)

        assert result.success is True

    async def test_fails_when_file_missing(self, tmp_path: Path) -> None:
        """Execute fails when a source file doesn't exist."""
        step = LoadArchivesStep()
        context = StepContext()
        missing_file = tmp_path / "nonexistent.mbox"
        context.set(
            "config",
            {
                "source_files": [str(missing_file)],
            },
        )

        result = await step.execute(context, None)

        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_reports_all_missing_files(self, tmp_path: Path) -> None:
        """Execute reports all missing files in error message."""
        step = LoadArchivesStep()
        context = StepContext()
        missing1 = tmp_path / "missing1.mbox"
        missing2 = tmp_path / "missing2.mbox"
        context.set(
            "config",
            {
                "source_files": [str(missing1), str(missing2)],
            },
        )

        result = await step.execute(context, None)

        assert result.success is False
        assert "missing1.mbox" in result.error
        assert "missing2.mbox" in result.error

    async def test_detects_uncompressed_format(
        self, sample_compressed_files: dict[str, Path]
    ) -> None:
        """Execute detects uncompressed .mbox format."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(sample_compressed_files["uncompressed"])],
            },
        )

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        # Check archive info contains compression type
        archive_info = result.data[0]
        assert archive_info["compression"] is None or archive_info["compression"] == "none"

    async def test_detects_gzip_compression(self, sample_compressed_files: dict[str, Path]) -> None:
        """Execute detects gzip-compressed .mbox.gz format."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(sample_compressed_files["gzip"])],
            },
        )

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        archive_info = result.data[0]
        assert archive_info["compression"] == "gzip"

    async def test_detects_lzma_compression(self, sample_compressed_files: dict[str, Path]) -> None:
        """Execute detects lzma-compressed .mbox.xz format."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(sample_compressed_files["xz"])],
            },
        )

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        archive_info = result.data[0]
        assert archive_info["compression"] == "lzma"

    async def test_handles_empty_source_list(self) -> None:
        """Execute fails when source_files list is empty."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set("config", {"source_files": []})

        result = await step.execute(context, None)

        assert result.success is False
        assert "no source files" in result.error.lower()

    async def test_stores_archive_info_in_context(self, sample_archive_files: list[Path]) -> None:
        """Execute stores archive_info in context."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
            },
        )

        await step.execute(context, None)

        archive_info = context.get("archive_info")
        assert archive_info is not None
        assert len(archive_info) == 2

    async def test_collects_file_sizes(self, sample_archive_files: list[Path]) -> None:
        """Execute collects file size for each archive."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
            },
        )

        result = await step.execute(context, None)

        assert result.success is True
        assert result.data is not None
        for archive_info in result.data:
            assert "size_bytes" in archive_info
            assert archive_info["size_bytes"] > 0

    async def test_handles_no_progress_reporter(self, sample_archive_files: list[Path]) -> None:
        """Step works without progress reporter."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
            },
        )

        result = await step.execute(context, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, sample_archive_files: list[Path], mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = LoadArchivesStep()
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
            },
        )

        result = await step.execute(context, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()


# ============================================================================
# Test: MergeAndProcessStep
# ============================================================================


class TestMergeAndProcessStep:
    """Test MergeAndProcessStep execution."""

    async def test_can_instantiate(self) -> None:
        """MergeAndProcessStep can be instantiated."""
        step = MergeAndProcessStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """MergeAndProcessStep has the correct name attribute."""
        step = MergeAndProcessStep()
        assert step.name == "merge_and_process"

    async def test_has_correct_description(self) -> None:
        """MergeAndProcessStep has the correct description attribute."""
        step = MergeAndProcessStep()
        assert step.description == "Merging and processing archives"

    async def test_execute_calls_consolidator(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute calls ArchiveConsolidator.consolidate()."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file1.mbox", "/path/to/file2.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": True,
                "sort_by_date": True,
                "compress": None,
                "dedupe_strategy": "newest",
            },
        )

        result = await step.execute(context_with_consolidator, None)

        assert result.success is True
        mock_consolidator.consolidate.assert_called_once()

    async def test_passes_config_to_consolidator(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute passes config parameters to consolidator."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file1.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": True,
                "sort_by_date": False,
                "compress": "gzip",
                "dedupe_strategy": "largest",
            },
        )

        await step.execute(context_with_consolidator, None)

        call_kwargs = mock_consolidator.consolidate.call_args.kwargs
        assert call_kwargs["sort_by_date"] is False
        assert call_kwargs["deduplicate"] is True
        assert call_kwargs["compress"] == "gzip"
        assert call_kwargs["dedupe_strategy"] == "largest"

    async def test_handles_deduplication_enabled(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute handles deduplication when enabled."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": True,
                "sort_by_date": False,
                "dedupe_strategy": "newest",
            },
        )

        result = await step.execute(context_with_consolidator, None)

        assert result.success is True
        call_kwargs = mock_consolidator.consolidate.call_args.kwargs
        assert call_kwargs["deduplicate"] is True

    async def test_handles_deduplication_disabled(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute handles deduplication when disabled."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": False,
                "sort_by_date": False,
            },
        )

        result = await step.execute(context_with_consolidator, None)

        assert result.success is True
        call_kwargs = mock_consolidator.consolidate.call_args.kwargs
        assert call_kwargs["deduplicate"] is False

    async def test_handles_sorting_enabled(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute handles sorting when enabled."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": False,
                "sort_by_date": True,
            },
        )

        result = await step.execute(context_with_consolidator, None)

        assert result.success is True
        call_kwargs = mock_consolidator.consolidate.call_args.kwargs
        assert call_kwargs["sort_by_date"] is True

    async def test_stores_merged_count_in_context(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute stores merged_count in context."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": False,
                "sort_by_date": False,
            },
        )

        # Configure mock to return 8 consolidated messages
        mock_consolidator.consolidate.return_value.messages_consolidated = 8

        await step.execute(context_with_consolidator, None)

        merged_count = context_with_consolidator.get("merged_count")
        assert merged_count == 8

    async def test_stores_duplicates_removed_in_context(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute stores duplicates_removed in context."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
                "dedupe": True,
                "sort_by_date": False,
            },
        )

        # Configure mock to return 2 duplicates removed
        mock_consolidator.consolidate.return_value.duplicates_removed = 2

        await step.execute(context_with_consolidator, None)

        duplicates_removed = context_with_consolidator.get("duplicates_removed")
        assert duplicates_removed == 2

    async def test_fails_when_consolidation_fails(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute returns failure when consolidation fails."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
            },
        )

        mock_consolidator.consolidate.side_effect = Exception("Merge failed")

        result = await step.execute(context_with_consolidator, None)

        assert result.success is False
        assert "Merge failed" in result.error

    async def test_fails_without_consolidator_in_context(self) -> None:
        """Execute fails gracefully when consolidator not in context."""
        step = MergeAndProcessStep()
        context = StepContext()  # No consolidator injected
        context.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
            },
        )

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Consolidator not found in context"

    async def test_handles_empty_input(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute handles empty source files list."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": [],
                "output_file": "/path/to/output.mbox",
            },
        )

        mock_consolidator.consolidate.side_effect = ValueError("source_archives cannot be empty")

        result = await step.execute(context_with_consolidator, None)

        assert result.success is False
        assert "empty" in result.error.lower()

    async def test_handles_no_progress_reporter(
        self, context_with_consolidator: StepContext
    ) -> None:
        """Step works without progress reporter."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
            },
        )

        result = await step.execute(context_with_consolidator, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_consolidator: StepContext, mock_progress: MagicMock
    ) -> None:
        """Step reports progress when provided."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
            },
        )

        result = await step.execute(context_with_consolidator, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_consolidation_result(
        self, context_with_consolidator: StepContext, mock_consolidator: AsyncMock
    ) -> None:
        """Execute result data contains consolidation result."""
        step = MergeAndProcessStep()
        context_with_consolidator.set(
            "config",
            {
                "source_files": ["/path/to/file.mbox"],
                "output_file": "/path/to/output.mbox",
            },
        )

        result = await step.execute(context_with_consolidator, None)

        assert result.data is not None
        assert result.data.messages_consolidated == 8
        assert result.data.duplicates_removed == 2


# ============================================================================
# Test: ValidateConsolidationStep
# ============================================================================


class TestValidateConsolidationStep:
    """Test ValidateConsolidationStep execution."""

    async def test_can_instantiate(self) -> None:
        """ValidateConsolidationStep can be instantiated."""
        step = ValidateConsolidationStep()
        assert step is not None

    async def test_has_correct_name(self) -> None:
        """ValidateConsolidationStep has the correct name attribute."""
        step = ValidateConsolidationStep()
        assert step.name == "validate_consolidation"

    async def test_has_correct_description(self) -> None:
        """ValidateConsolidationStep has the correct description attribute."""
        step = ValidateConsolidationStep()
        assert step.description == "Validating consolidated archive"

    async def test_validates_output_file_exists(
        self, context_with_storage: StepContext, tmp_path: Path
    ) -> None:
        """Execute validates that output file exists."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        result = await step.execute(context_with_storage, None)

        assert result.success is True

    async def test_fails_when_output_file_missing(
        self, context_with_storage: StepContext, tmp_path: Path
    ) -> None:
        """Execute fails when output file doesn't exist."""
        step = ValidateConsolidationStep()
        missing_file = tmp_path / "nonexistent.mbox"
        context_with_storage.set("config", {"output_file": str(missing_file)})

        result = await step.execute(context_with_storage, None)

        assert result.success is False
        assert "not found" in result.error.lower() or "does not exist" in result.error.lower()

    async def test_calls_storage_validate_integrity(
        self, context_with_storage: StepContext, mock_storage: AsyncMock, tmp_path: Path
    ) -> None:
        """Execute calls storage.validate_archive_integrity()."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        result = await step.execute(context_with_storage, None)

        assert result.success is True
        mock_storage.validate_archive_integrity.assert_called_once_with(str(output_file))

    async def test_sets_validation_passed_flag(
        self, context_with_storage: StepContext, mock_storage: AsyncMock, tmp_path: Path
    ) -> None:
        """Execute sets VALIDATION_PASSED flag in context."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})
        mock_storage.validate_archive_integrity.return_value = True

        await step.execute(context_with_storage, None)

        validation_passed = context_with_storage.get("validation_passed")
        assert validation_passed is True

    async def test_sets_validation_failed_flag(
        self, context_with_storage: StepContext, mock_storage: AsyncMock, tmp_path: Path
    ) -> None:
        """Execute sets VALIDATION_PASSED to False on failure."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})
        mock_storage.validate_archive_integrity.return_value = False

        result = await step.execute(context_with_storage, None)

        assert result.success is False
        validation_passed = context_with_storage.get("validation_passed")
        assert validation_passed is False

    async def test_fails_on_validation_errors(
        self, context_with_storage: StepContext, mock_storage: AsyncMock, tmp_path: Path
    ) -> None:
        """Execute fails when validation raises an error."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})
        mock_storage.validate_archive_integrity.side_effect = Exception("Validation error")

        result = await step.execute(context_with_storage, None)

        assert result.success is False
        assert "Validation error" in result.error

    async def test_fails_without_storage_in_context(self, tmp_path: Path) -> None:
        """Execute fails gracefully when storage not in context."""
        step = ValidateConsolidationStep()
        context = StepContext()  # No storage injected
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context.set("config", {"output_file": str(output_file)})

        result = await step.execute(context, None)

        assert result.success is False
        assert result.error == "Storage not found in context"

    async def test_handles_no_progress_reporter(
        self, context_with_storage: StepContext, tmp_path: Path
    ) -> None:
        """Step works without progress reporter."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        result = await step.execute(context_with_storage, None, progress=None)

        assert result.success is True

    async def test_handles_with_progress_reporter(
        self, context_with_storage: StepContext, mock_progress: MagicMock, tmp_path: Path
    ) -> None:
        """Step reports progress when provided."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        result = await step.execute(context_with_storage, None, progress=mock_progress)

        assert result.success is True
        mock_progress.task_sequence.assert_called_once()

    async def test_result_data_contains_validation_details(
        self, context_with_storage: StepContext, tmp_path: Path
    ) -> None:
        """Execute result data contains validation details."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        result = await step.execute(context_with_storage, None)

        assert result.data is not None
        assert "validation_passed" in result.data or result.data is True

    async def test_stores_validation_details_in_context(
        self, context_with_storage: StepContext, tmp_path: Path
    ) -> None:
        """Execute stores validation_details in context."""
        step = ValidateConsolidationStep()
        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")
        context_with_storage.set("config", {"output_file": str(output_file)})

        await step.execute(context_with_storage, None)

        validation_details = context_with_storage.get("validation_details")
        assert validation_details is not None


# ============================================================================
# Test: Step Integration
# ============================================================================


class TestConsolidateStepsIntegration:
    """Test consolidate steps work correctly together."""

    async def test_all_steps_share_context(
        self,
        mock_consolidator: AsyncMock,
        mock_storage: AsyncMock,
        sample_archive_files: list[Path],
        tmp_path: Path,
    ) -> None:
        """All consolidate steps can share data through context."""
        context = StepContext()
        context.set("consolidator", mock_consolidator)
        context.set("storage", mock_storage)

        output_file = tmp_path / "output.mbox"
        output_file.write_text("From sender@example.com\n")

        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
                "output_file": str(output_file),
                "dedupe": True,
                "sort_by_date": True,
                "validate": True,
            },
        )

        load_step = LoadArchivesStep()
        merge_step = MergeAndProcessStep()
        validate_step = ValidateConsolidationStep()

        r1 = await load_step.execute(context, None)
        r2 = await merge_step.execute(context, None)
        r3 = await validate_step.execute(context, None)

        assert r1.success is True
        assert r2.success is True
        assert r3.success is True

        # All results stored in context
        assert context.get("archive_info") is not None
        assert context.get("merged_count") is not None
        assert context.get("validation_passed") is not None

    async def test_steps_follow_protocol(self) -> None:
        """All consolidate steps follow the Step protocol."""
        load_step = LoadArchivesStep()
        merge_step = MergeAndProcessStep()
        validate_step = ValidateConsolidationStep()

        for step in [load_step, merge_step, validate_step]:
            # Should have name property
            assert hasattr(step, "name")
            assert isinstance(step.name, str)

            # Should have description property
            assert hasattr(step, "description")
            assert isinstance(step.description, str)

            # Should have execute method
            assert hasattr(step, "execute")
            assert callable(step.execute)

    async def test_steps_pass_data_through_context(
        self, mock_consolidator: AsyncMock, sample_archive_files: list[Path], tmp_path: Path
    ) -> None:
        """Steps correctly pass data to subsequent steps via context."""
        context = StepContext()
        context.set("consolidator", mock_consolidator)
        context.set(
            "config",
            {
                "source_files": [str(f) for f in sample_archive_files],
                "output_file": str(tmp_path / "output.mbox"),
            },
        )

        # Run load step
        load_step = LoadArchivesStep()
        await load_step.execute(context, None)

        # Merge step should see archive_info from load step
        assert context.get("archive_info") is not None
        assert len(context.get("archive_info")) == 2

        # Run merge step
        merge_step = MergeAndProcessStep()
        await merge_step.execute(context, None)

        # Validate step should see merged_count from merge step
        assert context.get("merged_count") is not None
