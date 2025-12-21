"""Consolidate steps for merging multiple archives.

This module provides steps for consolidation operations:
- LoadArchivesStep: Validate source files, detect compression, collect metadata
- MergeAndProcessStep: Consolidate archives with optional dedup/sort
- ValidateConsolidationStep: Verify consolidated archive integrity
"""

from pathlib import Path
from typing import Any, cast

from gmailarchiver.core.consolidator.facade import ArchiveConsolidator, ConsolidationResult
from gmailarchiver.core.workflows.step import (
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


class LoadArchivesStep:
    """Step that validates source files and collects archive metadata.

    Validates that all source files exist and detects compression formats.

    Input: None (uses config from context)
    Output: List of archive info dicts
    Context: Reads "config"; sets "archive_info"
    """

    name = "load_archives"
    description = "Loading and validating source archives"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[list[dict[str, Any]]]:
        """Validate source files and collect metadata.

        Args:
            context: Shared step context (expects "config" key)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with list of archive info dicts
        """
        config: dict[str, Any] = context.get("config", {}) or {}
        source_files: list[str] = config.get("source_files", []) or []

        if not source_files:
            return StepResult.fail("No source files specified")

        try:
            archive_info: list[dict[str, Any]] = []
            missing_files: list[str] = []

            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Validating source archives", total=len(source_files)) as task:
                        for file_path in source_files:
                            path = Path(file_path)
                            if not path.exists():
                                missing_files.append(file_path)
                            else:
                                compression = self._detect_compression(path)
                                size_bytes = path.stat().st_size
                                archive_info.append(
                                    {
                                        "path": file_path,
                                        "compression": compression,
                                        "size_bytes": size_bytes,
                                    }
                                )
                            task.advance(1)

                        if missing_files:
                            task.fail(f"Missing {len(missing_files)} files")
                        else:
                            task.complete(f"Validated {len(archive_info)} archives")
            else:
                for file_path in source_files:
                    path = Path(file_path)
                    if not path.exists():
                        missing_files.append(file_path)
                    else:
                        compression = self._detect_compression(path)
                        size_bytes = path.stat().st_size
                        archive_info.append(
                            {
                                "path": file_path,
                                "compression": compression,
                                "size_bytes": size_bytes,
                            }
                        )

            if missing_files:
                return StepResult.fail(f"Source files not found: {', '.join(missing_files)}")

            # Store in context for subsequent steps
            context.set("archive_info", archive_info)

            return StepResult.ok(archive_info)

        except Exception as e:
            return StepResult.fail(f"Failed to load archives: {e}")

    def _detect_compression(self, path: Path) -> str | None:
        """Detect compression format from file extension.

        Args:
            path: File path

        Returns:
            Compression format ('gzip', 'lzma', 'zstd') or None
        """
        suffix = path.suffix.lower()
        if suffix == ".gz":
            return "gzip"
        elif suffix in (".xz", ".lzma"):
            return "lzma"
        elif suffix == ".zst":
            return "zstd"
        return None


class MergeAndProcessStep:
    """Step that merges and processes archives using ArchiveConsolidator.

    Uses the ArchiveConsolidator facade to consolidate archives with
    optional deduplication and sorting.

    Input: None (uses config and consolidator from context)
    Output: ConsolidationResult
    Context: Reads "config", "consolidator";
             sets "merged_count", "duplicates_removed", "total_messages"
    """

    name = "merge_and_process"
    description = "Merging and processing archives"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[ConsolidationResult]:
        """Merge and process archives.

        Args:
            context: Shared step context (expects "config", "consolidator" keys)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with ConsolidationResult data
        """
        consolidator: ArchiveConsolidator | None = context.get("consolidator")
        if not consolidator:
            return StepResult.fail("Consolidator not found in context")

        config: dict[str, Any] = context.get("config", {}) or {}
        source_files: list[str] = config.get("source_files", []) or []
        output_file: str = config.get("output_file", "")
        dedupe: bool = config.get("dedupe", False)
        sort_by_date: bool = config.get("sort_by_date", False)
        compress: str | None = config.get("compress")
        dedupe_strategy: str = config.get("dedupe_strategy", "newest")

        try:
            # Cast source_files to the expected type
            source_archives = cast(list[str | Path], source_files)

            if progress:
                with progress.task_sequence() as seq:
                    with seq.task(
                        f"Consolidating {len(source_files)} archives",
                        total=len(source_files),
                    ) as task:
                        result = await consolidator.consolidate(
                            source_archives=source_archives,
                            output_archive=output_file,
                            sort_by_date=sort_by_date,
                            deduplicate=dedupe,
                            dedupe_strategy=dedupe_strategy,
                            compress=compress,
                        )

                        msg_parts = [f"{result.messages_consolidated:,} messages"]
                        if result.duplicates_removed > 0:
                            msg_parts.append(f"{result.duplicates_removed:,} duplicates removed")
                        task.complete(", ".join(msg_parts))
            else:
                result = await consolidator.consolidate(
                    source_archives=source_archives,
                    output_archive=output_file,
                    sort_by_date=sort_by_date,
                    deduplicate=dedupe,
                    dedupe_strategy=dedupe_strategy,
                    compress=compress,
                )

            # Store in context for subsequent steps
            context.set("merged_count", result.messages_consolidated)
            context.set("duplicates_removed", result.duplicates_removed)
            context.set("total_messages", result.total_messages)

            return StepResult.ok(result)

        except Exception as e:
            return StepResult.fail(str(e))


class ValidateConsolidationStep:
    """Step that validates the consolidated archive integrity.

    Uses HybridStorage to verify the consolidated archive is valid.

    Input: None (uses config and storage from context)
    Output: Validation result
    Context: Reads "config", "storage";
             sets "validation_passed", "validation_details"
    """

    name = "validate_consolidation"
    description = "Validating consolidated archive"

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[bool | dict[str, Any]]:
        """Validate consolidated archive.

        Args:
            context: Shared step context (expects "config", "storage" keys)
            input_data: Ignored (no input needed)
            progress: Optional progress reporter

        Returns:
            StepResult with validation result
        """
        storage = context.get("storage")
        if not storage:
            return StepResult.fail("Storage not found in context")

        config: dict[str, Any] = context.get("config", {}) or {}
        output_file: str = config.get("output_file", "")

        # Check if output file exists
        output_path = Path(output_file)
        if not output_path.exists():
            context.set("validation_passed", False)
            context.set("validation_details", {"error": "Output file not found"})
            return StepResult.fail(f"Output file not found: {output_file}")

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task("Validating archive integrity") as task:
                        validation_passed = await storage.validate_archive_integrity(output_file)
                        if validation_passed:
                            task.complete("Validation passed")
                        else:
                            task.fail("Validation failed")
            else:
                validation_passed = await storage.validate_archive_integrity(output_file)

            # Store in context
            context.set("validation_passed", validation_passed)
            context.set("validation_details", {"validation_passed": validation_passed})

            if validation_passed:
                return StepResult.ok({"validation_passed": validation_passed})
            else:
                return StepResult.fail("Archive validation failed")

        except Exception as e:
            context.set("validation_passed", False)
            context.set("validation_details", {"error": str(e)})
            return StepResult.fail(str(e))
