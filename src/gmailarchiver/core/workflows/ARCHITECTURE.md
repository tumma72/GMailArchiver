# Workflows Architecture

**Last Updated:** 2025-12-18
**Status:** Production (v1.9.0+)

This document defines the architecture of the workflows module, which contains the async business logic for all CLI commands. Workflows are **class-based** with a `run()` method, use **Step composition** for reusable operations, and use **protocol-based dependency injection** to maintain layer boundaries.

---

## Table of Contents

- [Design Principles](#design-principles)
- [Component Hierarchy](#component-hierarchy)
- [Step Architecture](#step-architecture)
- [Workflow Architecture](#workflow-architecture)
- [Progress Reporting](#progress-reporting)
- [Data Flow](#data-flow)
- [Step Library](#step-library)
- [Integration Points](#integration-points)
- [Testing Strategy](#testing-strategy)
- [Migration Checklist](#migration-checklist)

---

## Design Principles

### Thin Client Pattern

The workflows module implements the **thin client pattern** where:

1. **CLI commands are synchronous** (due to Typer limitations)
2. **Workflows are asynchronous** (business logic orchestration)
3. **Steps are reusable async units** (composable operations)
4. **Single `asyncio.run()` call per command** bridges the sync/async boundary
5. **All layers depend on protocols, not concrete types**

### Composition Over Inheritance

Workflows are built by **composing reusable Steps** rather than inheriting from base classes:

```
Workflow = Step1 + Step2 + Step3 + ...
```

This enables:
- **Code reuse**: Same step used across multiple workflows
- **Consistency**: Fix once, benefit everywhere
- **Testability**: Steps are independently testable units
- **Flexibility**: Workflows can mix-and-match steps as needed

### Single Responsibility

| Component | Responsibility |
|-----------|----------------|
| **Step** | One atomic operation (scan, filter, validate, etc.) |
| **Workflow** | Orchestrates steps for one command |
| **Facade** | Domain logic abstraction (called by steps) |
| **CLI Command** | User interface, result formatting |

---

## Component Hierarchy

```mermaid
graph TB
    subgraph "CLI Layer"
        CLI[CLI Command]
        Adapter[CLIProgressAdapter]
        Widgets[UI Widgets]
    end

    subgraph "Workflow Layer"
        Workflow[Workflow Class]
        Composer[WorkflowComposer]
    end

    subgraph "Step Layer"
        Step1[ScanMboxStep]
        Step2[CheckDuplicatesStep]
        Step3[RecordMetadataStep]
        Step4[ValidateArchiveStep]
        StepN[...more steps...]
    end

    subgraph "Core Layer (Facades)"
        ArchiverFacade
        ValidatorFacade
        ImporterFacade
    end

    subgraph "Data Layer"
        HybridStorage
        DBManager
        MBOX[(mbox Files)]
    end

    CLI --> Adapter
    CLI --> Widgets
    CLI -->|asyncio.run| Workflow
    Workflow --> Composer
    Composer --> Step1
    Composer --> Step2
    Composer --> Step3
    Composer --> Step4
    Step1 --> ArchiverFacade
    Step2 --> HybridStorage
    Step3 --> ImporterFacade
    Step4 --> ValidatorFacade
    ArchiverFacade --> HybridStorage
    ValidatorFacade --> HybridStorage
    ImporterFacade --> HybridStorage
    HybridStorage --> DBManager
    HybridStorage --> MBOX
```

---

## Step Architecture

### Step Protocol

A Step is a **reusable async unit of work** with a defined interface:

```python
from typing import Protocol, Any
from dataclasses import dataclass, field

@dataclass
class StepResult[T]:
    """Result from step execution."""
    success: bool
    data: T | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> StepResult[T]:
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> StepResult[T]:
        return cls(success=False, error=error, metadata=metadata)


class Step(Protocol):
    """Protocol for workflow steps."""

    @property
    def name(self) -> str:
        """Unique identifier for this step."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description (shown in progress)."""
        ...

    async def execute(
        self,
        context: StepContext,
        input_data: Any,
        progress: ProgressReporter | None = None,
    ) -> StepResult[Any]:
        """Execute this step."""
        ...
```

### StepContext

Steps communicate via a **shared context dictionary**:

```python
class StepContext:
    """Shared state passed between steps in a workflow."""

    def get(self, key: str, default: T | None = None) -> T | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def __contains__(self, key: str) -> bool: ...
    def __getitem__(self, key: str) -> Any: ...
    def __setitem__(self, key: str, value: Any) -> None: ...
```

**Standard Context Keys** (use `ContextKeys` enum for consistency):

| Key | Type | Set By | Used By |
|-----|------|--------|---------|
| `MBOX_PATH` | `str` | ScanMboxStep | RecordMetadataStep, ValidateArchiveStep |
| `ARCHIVE_FILE` | `str` | ScanMboxStep | RecordMetadataStep, ValidateArchiveStep |
| `MESSAGES` | `list[tuple]` | ScanMboxStep | CheckDuplicatesStep |
| `TO_ARCHIVE` | `list[tuple]` | CheckDuplicatesStep | RecordMetadataStep |
| `DUPLICATE_COUNT` | `int` | CheckDuplicatesStep | Workflow result |
| `IMPORTED_COUNT` | `int` | RecordMetadataStep | Workflow result |
| `VALIDATION_PASSED` | `bool` | ValidateArchiveStep | Workflow result |

### Step Implementation Pattern

```python
from dataclasses import dataclass
from gmailarchiver.core.workflows.step import Step, StepContext, StepResult, ContextKeys
from gmailarchiver.shared.protocols import ProgressReporter

@dataclass
class ScanOutput:
    """Typed output for ScanMboxStep."""
    archive_file: str
    total_messages: int
    scanned_messages: list[tuple[str, int, int]]  # (rfc_id, offset, length)


class ScanMboxStep:
    """Step that scans an mbox file for messages.

    Input: MboxScanInput with archive path
    Output: ScanOutput with message info
    Context: Sets MBOX_PATH, ARCHIVE_FILE, MESSAGES
    """

    name = "scan_mbox"
    description = "Scanning mbox for messages"

    async def execute(
        self,
        context: StepContext,
        input_data: str | Path,
        progress: ProgressReporter | None = None,
    ) -> StepResult[ScanOutput]:
        archive_path = Path(input_data)

        if not archive_path.exists():
            return StepResult.fail(f"Archive not found: {archive_path}")

        # Store in context for subsequent steps
        context.set(ContextKeys.MBOX_PATH, str(archive_path))
        context.set(ContextKeys.ARCHIVE_FILE, str(archive_path))

        # Perform scanning with progress feedback
        if progress:
            with progress.task_sequence() as seq:
                with seq.task(f"Scanning {archive_path.name}") as task:
                    messages = await self._scan(archive_path)
                    task.complete(f"Found {len(messages):,} messages")
        else:
            messages = await self._scan(archive_path)

        # Store in context
        context.set(ContextKeys.MESSAGES, messages)

        output = ScanOutput(
            archive_file=str(archive_path),
            total_messages=len(messages),
            scanned_messages=messages,
        )

        return StepResult.ok(output, count=len(messages))

    async def _scan(self, path: Path) -> list[tuple[str, int, int]]:
        # Actual scanning logic using facades/readers
        ...
```

### Step Dependencies

Steps receive dependencies via **constructor injection**:

```python
class CheckDuplicatesStep:
    """Step requiring database access."""

    def __init__(self, db_manager: DBManager) -> None:
        self.db_manager = db_manager

    async def execute(self, context: StepContext, input_data: Any, ...) -> StepResult[FilterOutput]:
        existing_ids = await self.db_manager.get_all_rfc_message_ids()
        # Filter logic...
```

---

## Workflow Architecture

### WorkflowComposer

The `WorkflowComposer` composes steps into executable workflows:

```python
class WorkflowComposer:
    """Composes steps into executable workflows."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._steps: list[Step] = []

    def add_step(self, step: Step) -> WorkflowComposer:
        """Fluent API for adding steps."""
        self._steps.append(step)
        return self

    async def run(
        self,
        initial_input: Any,
        progress: ProgressReporter | None = None,
        context: StepContext | None = None,
    ) -> StepContext:
        """Execute all steps in sequence.

        Each step's output becomes the next step's input.
        Raises WorkflowError if any step fails.
        """
        if context is None:
            context = StepContext()

        current_input = initial_input

        for step in self._steps:
            result = await step.execute(context, current_input, progress)

            if not result.success:
                raise WorkflowError(step.name, result.error)

            current_input = result.data

        return context
```

### Workflow Class Pattern

Workflows are **classes** that orchestrate steps:

```python
@dataclass
class ImportConfig:
    """Configuration for import workflow."""
    archive_patterns: list[str]
    state_db: str
    dedupe: bool = True
    account_id: str = "default"


@dataclass
class ImportResult:
    """Result from import workflow."""
    imported_count: int
    skipped_count: int
    duplicate_count: int
    files_processed: list[str]
    errors: list[str] = field(default_factory=list)


class ImportWorkflow:
    """Workflow for importing mbox archives.

    Uses step composition:
    1. ScanMboxStep - Scan for messages
    2. CheckDuplicatesStep - Filter duplicates
    3. RecordMetadataStep - Write to database
    """

    def __init__(
        self,
        storage: HybridStorage,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.storage = storage
        self.progress = progress

    async def run(self, config: ImportConfig) -> ImportResult:
        """Execute the import workflow."""
        total_imported = 0
        total_duplicates = 0
        files_processed = []
        errors = []

        for pattern in config.archive_patterns:
            for file_path in self._find_files(pattern):
                try:
                    result = await self._import_single_file(file_path, config)
                    total_imported += result["imported_count"]
                    total_duplicates += result["duplicate_count"]
                    files_processed.append(str(file_path))
                except WorkflowError as e:
                    errors.append(str(e))

        return ImportResult(
            imported_count=total_imported,
            skipped_count=0,
            duplicate_count=total_duplicates,
            files_processed=files_processed,
            errors=errors,
        )

    async def _import_single_file(self, file_path: str, config: ImportConfig) -> dict:
        """Import a single file using step composition."""
        workflow = (
            WorkflowComposer("import_single")
            .add_step(ScanMboxStep())
            .add_step(CheckDuplicatesStep(self.storage.db))
            .add_step(RecordMetadataStep(self.storage.db))
        )

        context = StepContext()
        context.set("account_id", config.account_id)
        context.set("skip_duplicates", config.dedupe)

        await workflow.run(file_path, progress=self.progress, context=context)

        return {
            "imported_count": context.get(ContextKeys.IMPORTED_COUNT, 0),
            "duplicate_count": context.get(ContextKeys.DUPLICATE_COUNT, 0),
        }
```

### When to Use Steps vs Direct Implementation

| Use Steps | Use Direct Implementation |
|-----------|---------------------------|
| Operation is reused across workflows | Operation is unique to one workflow |
| Operation has clear input/output | Operation has complex state dependencies |
| Operation can fail independently | Operation is tightly coupled to others |
| Testing in isolation adds value | Workflow-level test is sufficient |

---

## Progress Reporting

### Progress Ownership Pattern

**Key Principle**: Workflows own the task sequence, steps receive individual task handles OR use progress for their own sequences.

There are two valid patterns:

#### Pattern 1: Workflow-Owned Task Sequence (Recommended)

The workflow creates the task sequence and manages all tasks:

```python
class ImportWorkflow:
    async def run(self, config: ImportConfig) -> ImportResult:
        if self.progress:
            with self.progress.task_sequence() as seq:
                # Workflow manages task sequence
                with seq.task("Scanning archives") as task:
                    scan_result = await self._scan(config)
                    task.complete(f"Found {scan_result.count:,} messages")

                with seq.task("Filtering duplicates") as task:
                    filter_result = await self._filter(scan_result)
                    task.complete(f"{filter_result.new_count:,} new messages")

                with seq.task("Importing", total=filter_result.new_count) as task:
                    for msg in filter_result.messages:
                        await self._import_one(msg)
                        task.advance()
                    task.complete(f"Imported {filter_result.new_count:,} messages")
        else:
            # No progress - still works
            scan_result = await self._scan(config)
            filter_result = await self._filter(scan_result)
            # ...
```

#### Pattern 2: Step-Owned Task Sequences (For Complex Steps)

Steps manage their own task sequences when they have multiple sub-tasks:

```python
class ValidateArchiveStep:
    """Complex step with multiple validation checks."""

    async def execute(
        self,
        context: StepContext,
        input_data: str,
        progress: ProgressReporter | None = None,
    ) -> StepResult[ValidateOutput]:
        if progress:
            with progress.task_sequence() as seq:
                with seq.task("Count check") as t:
                    count_ok = await self._check_count()
                    t.complete("Passed" if count_ok else "Failed")

                with seq.task("Integrity check") as t:
                    integrity_ok = await self._check_integrity()
                    t.complete("Passed" if integrity_ok else "Failed")
        else:
            count_ok = await self._check_count()
            integrity_ok = await self._check_integrity()

        return StepResult.ok(ValidateOutput(count_ok=count_ok, integrity_ok=integrity_ok))
```

### Avoiding Double Task Sequences

**Anti-Pattern** (causes visual confusion):

```python
# CLI creates task sequence
with ctx.ui.task_sequence() as seq:
    with seq.task("Importing") as t:
        result = await workflow.run(config)  # Workflow ALSO creates task sequence!
        t.complete(...)
```

**Correct Pattern**:

```python
# Option A: CLI delegates entirely to workflow
result = await workflow.run(config)  # Workflow handles all progress

# Option B: CLI handles progress, workflow doesn't create sequences
with ctx.ui.task_sequence() as seq:
    with seq.task("Importing") as t:
        result = await workflow.run(config)  # Workflow uses progress.info() only
        t.complete(f"Imported {result.count:,}")
```

### ProgressReporter Protocol

```python
class ProgressReporter(Protocol):
    """Protocol for workflow progress reporting.

    Implementations:
    - CLIProgressAdapter: Rich terminal output
    - TestProgressReporter: Captures calls for testing
    - NoOpProgressReporter: Silent (for non-interactive use)
    """

    def info(self, message: str) -> None:
        """Log informational message."""
        ...

    def warning(self, message: str) -> None:
        """Log warning message."""
        ...

    def error(self, message: str) -> None:
        """Log error message."""
        ...

    def task_sequence(self) -> ContextManager[TaskSequence]:
        """Create a task sequence for multi-step operations."""
        ...


class TaskSequence(Protocol):
    """Protocol for task sequences."""

    def task(
        self, description: str, total: int | None = None
    ) -> ContextManager[TaskHandle]:
        """Create a task within the sequence."""
        ...


class TaskHandle(Protocol):
    """Protocol for controlling a single task."""

    def complete(self, message: str) -> None:
        """Mark task as successfully completed."""
        ...

    def fail(self, message: str, reason: str | None = None) -> None:
        """Mark task as failed."""
        ...

    def advance(self, n: int = 1) -> None:
        """Advance progress counter."""
        ...

    def set_total(self, total: int, description: str | None = None) -> None:
        """Set total for late-bound progress."""
        ...

    def log(self, message: str, level: str = "INFO") -> None:
        """Log message within task context."""
        ...
```

---

## Data Flow

### Step Data Flow

```mermaid
sequenceDiagram
    participant W as Workflow
    participant C as StepContext
    participant S1 as ScanMboxStep
    participant S2 as CheckDuplicatesStep
    participant S3 as RecordMetadataStep

    W->>S1: execute(context, path)
    S1->>C: set(MESSAGES, [...])
    S1-->>W: StepResult.ok(ScanOutput)

    W->>S2: execute(context, ScanOutput)
    S2->>C: get(MESSAGES)
    S2->>C: set(TO_ARCHIVE, [...])
    S2->>C: set(DUPLICATE_COUNT, n)
    S2-->>W: StepResult.ok(FilterOutput)

    W->>S3: execute(context, FilterOutput)
    S3->>C: get(TO_ARCHIVE)
    S3->>C: set(IMPORTED_COUNT, n)
    S3-->>W: StepResult.ok(MetadataOutput)

    W->>C: get(IMPORTED_COUNT)
    W->>C: get(DUPLICATE_COUNT)
    Note over W: Build ImportResult
```

### Command Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLI Command
    participant Adapter as CLIProgressAdapter
    participant WF as Workflow
    participant Composer as WorkflowComposer
    participant Step as Steps
    participant Facade as Facades
    participant Storage as HybridStorage

    User->>CLI: gmailarchiver import *.mbox
    CLI->>Adapter: CLIProgressAdapter(output, ui)
    CLI->>WF: ImportWorkflow(storage, adapter)
    CLI->>WF: asyncio.run(workflow.run(config))

    WF->>Composer: WorkflowComposer("import")
    Composer->>Step: ScanMboxStep.execute()
    Step->>Facade: MboxReader.scan()
    Facade-->>Step: messages
    Step-->>Composer: StepResult.ok(ScanOutput)

    Composer->>Step: CheckDuplicatesStep.execute()
    Step->>Storage: get_all_rfc_message_ids()
    Storage-->>Step: existing_ids
    Step-->>Composer: StepResult.ok(FilterOutput)

    Composer->>Step: RecordMetadataStep.execute()
    Step->>Storage: write_message()
    Step-->>Composer: StepResult.ok(MetadataOutput)

    Composer-->>WF: context
    WF-->>CLI: ImportResult
    CLI->>User: "Imported 42 messages"
```

---

## Step Library

### Current Steps

| Step | Purpose | Input | Output |
|------|---------|-------|--------|
| `ScanMboxStep` | Scan mbox for RFC Message-IDs | path | ScanOutput |
| `CheckDuplicatesStep` | Filter already-imported messages | ScanOutput | FilterOutput |
| `RecordMetadataStep` | Write message metadata to DB | FilterOutput | MetadataOutput |
| `ValidateArchiveStep` | Validate archive integrity | path | ValidateOutput |

### Planned Steps

| Step | Purpose | Used By |
|------|---------|---------|
| `AuthenticateGmailStep` | OAuth authentication | archive, retry-delete |
| `ScanGmailMessagesStep` | Query Gmail API | archive |
| `FilterArchivedMessagesStep` | Filter already-archived | archive |
| `WriteMessagesStep` | Write messages to mbox | archive, consolidate |
| `DeleteMessagesStep` | Trash/delete from Gmail | archive, retry-delete |
| `VerifyIntegrityStep` | Database integrity check | verify, doctor |
| `RepairDatabaseStep` | Fix database issues | repair, doctor |

### Step Naming Convention

```
<Verb><Noun>Step

Examples:
- ScanMboxStep (verb: Scan, noun: Mbox)
- CheckDuplicatesStep (verb: Check, noun: Duplicates)
- WriteArchiveStep (verb: Write, noun: Archive)
```

---

## Integration Points

### Dependencies (What Workflows/Steps CAN Import)

```python
# From core layer (FACADES)
from gmailarchiver.core.archiver import ArchiverFacade
from gmailarchiver.core.validator import ValidatorFacade
from gmailarchiver.core.importer import ImporterFacade
# ... other facades

# From data layer (via constructor injection)
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.data.db_manager import DBManager  # For steps only

# From connectors layer (via constructor injection)
from gmailarchiver.connectors.gmail_client import GmailClient

# From shared layer (protocols)
from gmailarchiver.shared.protocols import ProgressReporter, TaskSequence, TaskHandle
```

### Forbidden Dependencies (What Workflows/Steps MUST NOT Import)

```python
# NEVER import CLI types - breaks layer boundary
# ❌ from gmailarchiver.cli.output import OutputManager
# ❌ from gmailarchiver.cli.command_context import CommandContext
# ❌ from gmailarchiver.cli.ui_builder import UIBuilder
# ❌ from gmailarchiver.cli.widgets import ReportCard
```

### Dependents (Who Uses Workflows)

```python
# CLI commands import workflows
from gmailarchiver.core.workflows import ImportWorkflow, ImportConfig, ImportResult
from gmailarchiver.cli.adapters import CLIProgressAdapter

async def import_command(ctx: CommandContext, archive_pattern: str, ...):
    adapter = CLIProgressAdapter(ctx.output, ctx.ui)
    workflow = ImportWorkflow(ctx.storage, progress=adapter)
    config = ImportConfig(archive_patterns=[archive_pattern], ...)

    result = await workflow.run(config)

    # CLI handles display using widgets
    ReportCard("Import Results")
        .add_field("Imported", f"{result.imported_count:,}")
        .render(ctx.output)
```

---

## Testing Strategy

### Step Tests

```python
@pytest.mark.asyncio
async def test_scan_mbox_step_success(tmp_path: Path):
    """ScanMboxStep returns messages for valid mbox."""
    # Arrange
    mbox_path = tmp_path / "test.mbox"
    mbox_path.write_text("From test@example.com\nMessage-ID: <123>\n\nBody\n")

    step = ScanMboxStep()
    context = StepContext()

    # Act
    result = await step.execute(context, str(mbox_path))

    # Assert
    assert result.success
    assert result.data.total_messages == 1
    assert context.get(ContextKeys.MESSAGES) is not None


@pytest.mark.asyncio
async def test_scan_mbox_step_file_not_found():
    """ScanMboxStep fails gracefully for missing file."""
    step = ScanMboxStep()
    context = StepContext()

    result = await step.execute(context, "/nonexistent.mbox")

    assert not result.success
    assert "not found" in result.error.lower()
```

### Workflow Tests

```python
@pytest.mark.asyncio
async def test_import_workflow_success(mock_storage, tmp_mbox):
    """ImportWorkflow imports messages and returns result."""
    workflow = ImportWorkflow(mock_storage)
    config = ImportConfig(archive_patterns=[str(tmp_mbox)], state_db="test.db")

    result = await workflow.run(config)

    assert result.imported_count > 0
    assert str(tmp_mbox) in result.files_processed


@pytest.mark.asyncio
async def test_import_workflow_with_progress(mock_storage, tmp_mbox):
    """ImportWorkflow reports progress correctly."""
    progress = Mock(spec=ProgressReporter)
    progress.task_sequence.return_value.__enter__ = Mock(return_value=Mock())
    progress.task_sequence.return_value.__exit__ = Mock(return_value=None)

    workflow = ImportWorkflow(mock_storage, progress=progress)
    config = ImportConfig(archive_patterns=[str(tmp_mbox)], state_db="test.db")

    await workflow.run(config)

    progress.task_sequence.assert_called()
```

### Coverage Requirements

| Component | Target | Focus |
|-----------|--------|-------|
| Steps | 95%+ | All branches, error conditions |
| Workflows | 90%+ | Happy path, error handling |
| WorkflowComposer | 95%+ | Edge cases, failures |

---

## Migration Checklist

### Creating a New Step

1. [ ] Define **Input/Output dataclasses** with clear types
2. [ ] Implement **Step class** with `name`, `description`, `execute()`
3. [ ] Use **ContextKeys** for standard context keys
4. [ ] Accept **dependencies via constructor** (DBManager, etc.)
5. [ ] Handle **progress reporting** when progress is provided
6. [ ] Return **StepResult.ok()** or **StepResult.fail()**
7. [ ] Document **what context keys step reads/writes**
8. [ ] Write **unit tests** for success and failure cases
9. [ ] Add to **steps/__init__.py** exports

### Creating a New Workflow

1. [ ] Define **Config dataclass** for workflow parameters
2. [ ] Define **Result dataclass** for typed return values
3. [ ] Use **constructor injection** for dependencies (storage, client, progress)
4. [ ] Compose workflow using **WorkflowComposer** and existing steps
5. [ ] Handle **errors** and return meaningful error data
6. [ ] Document **which steps are used** in docstring
7. [ ] Write **tests** for workflow success, failure, and progress
8. [ ] Add to **workflows/__init__.py** exports

### Migrating Existing Workflow to Steps

1. [ ] Identify **reusable operations** in the workflow
2. [ ] Extract each operation to a **new Step class**
3. [ ] Update workflow to use **WorkflowComposer**
4. [ ] Verify **progress reporting** still works correctly
5. [ ] Ensure **no double task sequences**
6. [ ] Update **tests** to cover both step and workflow levels

---

## Related Documentation

- **[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md)** - System-wide architecture
- **[cli/ui/ARCHITECTURE.md](../../cli/ui/ARCHITECTURE.md)** - UI widgets and builders
- **[core/ARCHITECTURE.md](../../core/ARCHITECTURE.md)** - Business logic layer
- **[docs/PROCESS.md](../../../docs/PROCESS.md)** - Development workflow
- **[docs/UI_UX_CLI.md](../../../docs/UI_UX_CLI.md)** - CLI output guidelines
