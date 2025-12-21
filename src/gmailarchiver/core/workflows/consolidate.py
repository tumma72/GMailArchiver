"""Workflow for consolidating multiple archives.

This workflow coordinates the consolidation of multiple mbox files into
a single archive with optional deduplication and sorting.

Provides two workflow implementations:
- ConsolidateWorkflow: Original direct workflow
- ConsolidateStepWorkflow: Step-based workflow using WorkflowComposer
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from gmailarchiver.core.consolidator.facade import ArchiveConsolidator
from gmailarchiver.core.workflows.composer import WorkflowComposer
from gmailarchiver.core.workflows.step import StepContext, StepResult, WorkflowError
from gmailarchiver.core.workflows.steps.consolidate import (
    LoadArchivesStep,
    MergeAndProcessStep,
    ValidateConsolidationStep,
)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ConsolidateConfig:
    """Configuration for consolidate operation."""

    source_files: list[str]
    output_file: str
    dedupe: bool = True
    sort_by_date: bool = True
    compress: str | None = None
    dedupe_strategy: str = "newest"
    validate: bool = True


@dataclass
class ConsolidateResult:
    """Result of consolidate operation."""

    output_file: str
    messages_count: int
    source_files_count: int
    duplicates_removed: int
    sort_applied: bool
    compression_used: str | None


class ConsolidateWorkflow:
    """Workflow for consolidating multiple archives into one."""

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize consolidate workflow.

        Args:
            storage: HybridStorage instance for data operations
            progress: Optional progress reporter for status updates
        """
        self.storage = storage
        self.progress = progress
        # Initialize facade with storage's db_manager
        self.consolidator = ArchiveConsolidator(db_manager=storage.db)

    async def run(self, config: ConsolidateConfig) -> ConsolidateResult:
        """Run the full consolidation workflow.

        Args:
            config: ConsolidateConfig with consolidation settings

        Returns:
            ConsolidateResult with operation statistics
        """
        # Validate source files exist
        source_paths = [Path(f) for f in config.source_files]
        missing_files = [str(p) for p in source_paths if not p.exists()]
        if missing_files:
            raise FileNotFoundError(f"Source files not found: {', '.join(missing_files)}")

        if not source_paths:
            raise ValueError("No source files specified")

        # Report start
        if self.progress:
            self.progress.info(
                f"Consolidating {len(source_paths)} archives into {config.output_file}"
            )
            if config.dedupe:
                self.progress.info(f"Deduplication enabled (strategy: {config.dedupe_strategy})")
            if config.sort_by_date:
                self.progress.info("Messages will be sorted by date")
            if config.compress:
                self.progress.info(f"Compression: {config.compress}")

        # Execute consolidation with progress reporting
        if self.progress:
            with self.progress.task_sequence() as seq:
                with seq.task(
                    f"Consolidating {len(source_paths)} archives", total=len(source_paths)
                ) as task:
                    result = await self.consolidator.consolidate(
                        source_archives=cast(list[str | Path], source_paths),
                        output_archive=config.output_file,
                        sort_by_date=config.sort_by_date,
                        deduplicate=config.dedupe,
                        dedupe_strategy=config.dedupe_strategy,
                        compress=config.compress,
                    )

                    msg_parts = [f"{result.messages_consolidated:,} messages"]
                    if result.duplicates_removed > 0:
                        msg_parts.append(f"{result.duplicates_removed:,} duplicates removed")
                    task.complete(", ".join(msg_parts))
        else:
            result = await self.consolidator.consolidate(
                source_archives=cast(list[str | Path], source_paths),
                output_archive=config.output_file,
                sort_by_date=config.sort_by_date,
                deduplicate=config.dedupe,
                dedupe_strategy=config.dedupe_strategy,
                compress=config.compress,
            )

        return ConsolidateResult(
            output_file=result.output_file,
            messages_count=result.messages_consolidated,
            source_files_count=len(result.source_files),
            duplicates_removed=result.duplicates_removed,
            sort_applied=result.sort_applied,
            compression_used=result.compression_used,
        )


@dataclass
class StepResultRecord:
    """Record of a single step execution in a workflow."""

    step_name: str
    success: bool
    error: str | None = None
    data: Any = None


@dataclass
class ConsolidateStepResult:
    """Result of step-based consolidate operation."""

    success: bool
    error: str | None = None
    output_file: str | None = None
    messages_count: int | None = None
    source_files_count: int = 0
    duplicates_removed: int = 0
    sort_applied: bool = False
    compression_used: str | None = None
    step_results: list[StepResultRecord] = field(default_factory=list)
    context: StepContext | None = None


class ConsolidateStepWorkflow:
    """Step-based workflow for consolidating multiple archives.

    Uses WorkflowComposer to orchestrate:
    1. LoadArchivesStep: Validate and load source archives
    2. MergeAndProcessStep: Consolidate with dedup/sort options
    3. ValidateConsolidationStep: Verify output integrity (conditional)
    """

    def __init__(self, storage: HybridStorage, progress: ProgressReporter | None = None) -> None:
        """Initialize step-based consolidate workflow.

        Args:
            storage: HybridStorage instance for data operations
            progress: Optional progress reporter for status updates
        """
        self.storage = storage
        self.progress = progress
        self._consolidator = ArchiveConsolidator(db_manager=storage.db)

        # Build the workflow composer
        self.composer = WorkflowComposer("consolidate")
        self.composer.add_step(LoadArchivesStep())
        self.composer.add_step(MergeAndProcessStep())

        # Validation is conditional based on config
        def should_validate(ctx: StepContext) -> bool:
            config_dict = ctx.get("config")
            if not config_dict or not isinstance(config_dict, dict):
                return True
            return config_dict.get("validate", True) is True

        self.composer.add_conditional_step(
            ValidateConsolidationStep(),
            should_validate,
        )

    async def run(self, config: ConsolidateConfig) -> ConsolidateStepResult:
        """Run the step-based consolidation workflow.

        Args:
            config: ConsolidateConfig with consolidation settings

        Returns:
            ConsolidateStepResult with operation statistics and step details
        """
        # Create context with config and dependencies
        context = StepContext()
        context.set(
            "config",
            {
                "source_files": config.source_files,
                "output_file": config.output_file,
                "dedupe": config.dedupe,
                "sort_by_date": config.sort_by_date,
                "compress": config.compress,
                "dedupe_strategy": config.dedupe_strategy,
                "validate": config.validate,
            },
        )
        context.set("consolidator", self._consolidator)
        context.set("storage", self.storage)

        step_results: list[StepResultRecord] = []

        try:
            # Execute workflow with step tracking
            current_input = None

            for step_index, step in enumerate(self.composer.steps):
                # Check if step should execute
                if not self.composer._should_execute_step(step_index, context):
                    continue

                result: StepResult[Any] = await step.execute(context, current_input, self.progress)

                # Record step result
                step_results.append(
                    StepResultRecord(
                        step_name=step.name,
                        success=result.success,
                        error=result.error,
                        data=result.data,
                    )
                )

                if not result.success:
                    # Workflow failed at this step
                    return ConsolidateStepResult(
                        success=False,
                        error=result.error,
                        step_results=step_results,
                        context=context,
                        source_files_count=len(config.source_files),
                    )

                current_input = result.data

            # Extract results from context
            merged_count = context.get("merged_count", 0) or 0
            duplicates_removed = context.get("duplicates_removed", 0) or 0

            return ConsolidateStepResult(
                success=True,
                output_file=config.output_file,
                messages_count=merged_count,
                source_files_count=len(config.source_files),
                duplicates_removed=duplicates_removed,
                sort_applied=config.sort_by_date,
                compression_used=config.compress,
                step_results=step_results,
                context=context,
            )

        except WorkflowError as e:
            return ConsolidateStepResult(
                success=False,
                error=str(e),
                step_results=step_results,
                context=context,
                source_files_count=len(config.source_files),
            )
        except Exception as e:
            return ConsolidateStepResult(
                success=False,
                error=str(e),
                step_results=step_results,
                context=context,
                source_files_count=len(config.source_files),
            )
