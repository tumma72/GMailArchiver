# Workflows & UI Frameworks Refactoring Plan

**Created:** 2025-12-19
**Status:** Planning

This document outlines the refactoring work to complete the workflows/steps and UI/widgets frameworks, using the archive command as the reference implementation.

---

## Overview

The GMailArchiver has two new internal frameworks:

1. **Workflows/Steps Framework** (`core/workflows/`): Composable, reusable workflow steps
2. **UI/Widgets Framework** (`cli/ui/`): Composable UI widgets for consistent output

The archive command is the reference implementation. This plan describes the work to:
- Complete the framework implementations
- Migrate all commands to use the new patterns
- Remove deprecated/backward-compatibility code

---

## Phase 1: Framework Completion

### 1.1 WorkflowComposer Enhancements

**File:** `src/gmailarchiver/core/workflows/composer.py`

| Task | Description | Priority |
|------|-------------|----------|
| Add `add_conditional_step()` | Implement conditional step execution | High |
| Update `run()` | Handle conditional step skipping | High |
| Add tests | Test conditional step behavior | High |

**Implementation:**
```python
def add_conditional_step(
    self,
    step: Step,
    condition: Callable[[StepContext], bool],
) -> WorkflowComposer:
    """Add a step that only executes when condition(context) is True."""
    self._steps.append((step, condition))
    return self
```

### 1.2 TaskHandle Protocol Additions

**Files:**
- `src/gmailarchiver/cli/ui/protocols.py`
- `src/gmailarchiver/shared/protocols.py`

| Task | Description | Priority |
|------|-------------|----------|
| Add `set_status()` | Dynamic status updates | High |
| Add `warn()` | Warning completion status | Medium |
| Update NoOpTaskHandle | Implement new methods | High |

### 1.3 Step Empty Input Handling

**Files:** All step files in `src/gmailarchiver/core/workflows/steps/`

| Task | Description | Priority |
|------|-------------|----------|
| Audit all steps | Ensure empty input returns success | High |
| Add tests | Test empty input scenarios | High |

---

## Phase 2: Code Cleanup

### 2.1 Remove Deprecated Methods from ArchiveWorkflow

**File:** `src/gmailarchiver/core/workflows/archive.py`

| Method | Lines | Action |
|--------|-------|--------|
| `_scan_messages()` | 267-279 | Remove |
| `_filter_messages()` | 281-308 | Remove |
| `_archive_messages()` | 310-336 | Remove |
| `_validate_archive()` | 338-357 | Remove |

### 2.2 Remove Backward Compatibility from builder.py

**File:** `src/gmailarchiver/cli/ui/builder.py`

| Item | Lines | Action |
|------|-------|--------|
| `TaskState` class | 65-91 | Remove |
| `LOG_SYMBOLS` constant | 49-54 | Remove |
| `_tasks` property | 371-390 | Remove |

### 2.3 Consolidate LogLevel

**Files:**
- `src/gmailarchiver/cli/ui/builder.py`
- `src/gmailarchiver/cli/ui/widgets/log_window.py`

| Task | Description |
|------|-------------|
| Remove LOG_SYMBOLS from builder.py | Use LogLevel enum instead |
| Update `_log()` method | Accept LogLevel enum |

---

## Phase 3: Migrate ArchiveWorkflow to WorkflowComposer

### 3.1 Refactor archive.py

**Current Pattern (manual orchestration):**
```python
scan_result = await self._scan_step.execute(context, input, progress)
if not scan_result.success or not scan_result.data:
    return ArchiveResult(archived_count=0, ...)

filter_result = await self._filter_step.execute(context, ...)
if messages_to_archive and not config.dry_run:
    write_result = await self._write_step.execute(...)
```

**Target Pattern (WorkflowComposer):**
```python
context = StepContext()
context.set("dry_run", config.dry_run)
context.set("compress", config.compress)
context.set(ContextKeys.ARCHIVE_FILE, output_file)

workflow = (
    WorkflowComposer("archive")
    .add_step(ScanGmailMessagesStep(self.archiver))
    .add_step(FilterGmailMessagesStep(self.archiver))
    .add_conditional_step(
        WriteMessagesStep(self.archiver),
        lambda ctx: bool(ctx.get(ContextKeys.TO_ARCHIVE)) and not ctx.get("dry_run")
    )
    .add_conditional_step(
        ValidateArchiveStep(self.storage.db),
        lambda ctx: ctx.get(ContextKeys.ARCHIVED_COUNT, 0) > 0 and not ctx.get("dry_run")
    )
)

result_context = await workflow.run(
    ScanGmailInput(age_threshold=config.age_threshold),
    progress=self.progress,
    context=context,
)

return ArchiveResult(
    archived_count=result_context.get(ContextKeys.ARCHIVED_COUNT, 0),
    skipped_count=result_context.get(ContextKeys.SKIPPED_COUNT, 0),
    duplicate_count=result_context.get(ContextKeys.DUPLICATE_COUNT, 0),
    found_count=result_context.get("found_count", 0),
    actual_file=result_context.get(ContextKeys.ACTUAL_FILE, output_file),
    gmail_query=result_context.get(ContextKeys.GMAIL_QUERY, ""),
    validation_passed=result_context.get(ContextKeys.VALIDATION_PASSED, True),
    validation_details=result_context.get(ContextKeys.VALIDATION_DETAILS),
)
```

### 3.2 Update Gmail Steps for Empty Input

Ensure all Gmail steps handle empty input gracefully:

| Step | Empty Input Behavior |
|------|---------------------|
| ScanGmailMessagesStep | Return success with empty messages list |
| FilterGmailMessagesStep | Return success with empty to_archive list |
| WriteMessagesStep | Return success with archived_count=0 |
| ValidateArchiveStep | Return success with passed=True (nothing to validate) |

---

## Phase 4: Migrate Other Commands

### 4.1 Command Migration Priority

| Priority | Command | Complexity | Notes |
|----------|---------|------------|-------|
| 1 | `status` | Low | Simple, good starting point |
| 2 | `validate` | Low | Already uses ValidateArchiveStep |
| 3 | `import` | Medium | Multiple files, uses ScanMboxStep |
| 4 | `consolidate` | Medium | Multi-file operations |
| 5 | `dedupe` | Medium | Cross-archive logic |
| 6 | `verify-integrity` | Low | Database-focused |
| 7 | `verify-consistency` | Medium | DB + mbox comparison |
| 8 | `repair` | Medium | Database operations |
| 9 | `search` | Low | Query-based |
| 10 | `migrate` | Medium | Schema migration |

### 4.2 Migration Checklist per Command

For each command:

1. [ ] **Audit current implementation**
   - Identify reusable operations
   - Check if steps already exist

2. [ ] **Create/update steps** (if needed)
   - Define Input/Output dataclasses
   - Implement with empty input handling
   - Use ContextKeys for context storage
   - Write tests

3. [ ] **Create/update workflow**
   - Define Config/Result dataclasses
   - Use WorkflowComposer with add_step/add_conditional_step
   - Store config in context
   - Build result from context

4. [ ] **Update CLI command**
   - Use CLIProgressAdapter
   - Use workflow_sequence() for Log Window pattern
   - Use widgets for result display
   - Handle WorkflowError

5. [ ] **Update tests**
   - Step-level tests
   - Workflow-level tests
   - CLI integration tests

6. [ ] **Update documentation**
   - README.md if behavior changed
   - CHANGELOG.md entry

---

## Phase 5: Verification

### 5.1 Quality Gates

| Check | Command | Requirement |
|-------|---------|-------------|
| Lint | `uv run ruff check .` | No errors |
| Format | `uv run ruff format --check .` | No changes |
| Types | `uv run mypy src/gmailarchiver` | No errors |
| Tests | `uv run pytest` | All pass |
| Coverage | `uv run pytest --cov` | 90%+ overall |

### 5.2 Manual Testing

| Scenario | Command | Expected |
|----------|---------|----------|
| Archive with messages | `gmailarchiver archive 3y` | Archives successfully |
| Archive no messages | `gmailarchiver archive 10y` | Completes with zeros |
| Archive dry run | `gmailarchiver archive 3y --dry-run` | No changes made |
| Archive with compression | `gmailarchiver archive 3y -c zstd` | Compressed output |
| Archive interrupted | Ctrl+C during archive | Partial save, resumable |

---

## Timeline

| Phase | Description | Estimated Tasks |
|-------|-------------|-----------------|
| 1 | Framework Completion | 6 tasks |
| 2 | Code Cleanup | 7 tasks |
| 3 | Migrate ArchiveWorkflow | 4 tasks |
| 4 | Migrate Other Commands | ~30 tasks (3 per command) |
| 5 | Verification | 2 tasks |

**Total: ~49 tasks**

---

## Success Criteria

1. **All workflows use WorkflowComposer** - No manual step orchestration
2. **All steps handle empty input** - Return success with zeros/empty
3. **All deprecated code removed** - No backward compatibility wrappers
4. **All protocols aligned** - TaskHandle has set_status(), warn()
5. **All tests pass** - 90%+ coverage maintained
6. **Documentation updated** - ARCHITECTURE.md files reflect reality

---

## References

- [workflows/ARCHITECTURE.md](../src/gmailarchiver/core/workflows/ARCHITECTURE.md)
- [cli/ui/ARCHITECTURE.md](../src/gmailarchiver/cli/ui/ARCHITECTURE.md)
- [docs/PROCESS.md](PROCESS.md)
- [docs/UI_UX_CLI.md](UI_UX_CLI.md)
