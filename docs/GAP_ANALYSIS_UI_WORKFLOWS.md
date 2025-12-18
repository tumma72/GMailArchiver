# Gap Analysis: Workflows + Steps and CLI UI

**Generated:** 2025-12-18
**Purpose:** Compare declarative architecture (ideal) vs current implementation (actual)

This document identifies the work needed to align the codebase with the new architecture defined in:
- `src/gmailarchiver/core/workflows/ARCHITECTURE.md`
- `src/gmailarchiver/cli/ui/ARCHITECTURE.md`

---

## Executive Summary

| Area | Architecture Status | Implementation Status | Gap |
|------|--------------------|-----------------------|-----|
| **Step Protocol** | Defined | Implemented | Minor refinements |
| **Step Library** | 8 steps planned | 4 steps implemented | 4 new steps needed |
| **WorkflowComposer** | Defined | Implemented | Minor refinements |
| **Workflow Adoption** | 10 workflows | 1 uses steps | 9 workflows to migrate |
| **UIBuilder** | Defined | Implemented | Works correctly |
| **Widget Library** | 6 widgets planned | 4 widgets exist | 2 widgets needed |
| **Widget Adoption** | All commands | 0 commands | Full migration needed |
| **CLIProgressAdapter** | Defined | Implemented | Works correctly |
| **Progress Ownership** | Clear rules | Mixed patterns | Needs standardization |

---

## 1. Workflows + Steps Layer

### 1.1 Step Protocol

| Aspect | Architecture (Ideal) | Current Code (Actual) | Gap |
|--------|---------------------|----------------------|-----|
| Step interface | `name`, `description`, `execute()` | Implemented in `step.py` | None |
| StepResult | `ok()`, `fail()`, metadata | Implemented | None |
| StepContext | Dict-like, ContextKeys | Implemented | None |
| WorkflowError | step_name, error | Implemented | None |

**Status:** Step protocol is complete.

### 1.2 Step Library

| Step | Architecture | Current Status | Gap |
|------|-------------|----------------|-----|
| `ScanMboxStep` | Planned | Implemented (`steps/scan.py`) | None |
| `CheckDuplicatesStep` | Planned | Implemented (`steps/filter.py`) | None |
| `RecordMetadataStep` | Planned | Implemented (`steps/metadata.py`) | None |
| `ValidateArchiveStep` | Planned | Implemented (`steps/validate.py`) | None |
| `AuthenticateGmailStep` | Planned | **Not implemented** | **NEW STEP** |
| `ScanGmailMessagesStep` | Planned | **Not implemented** | **NEW STEP** |
| `WriteMessagesStep` | Planned | **Not implemented** | **NEW STEP** |
| `DeleteMessagesStep` | Planned | **Not implemented** | **NEW STEP** |

**Status:** 4/8 steps implemented. Need 4 new steps for archive workflow.

### 1.3 WorkflowComposer

| Aspect | Architecture | Current Status | Gap |
|--------|-------------|----------------|-----|
| Fluent `add_step()` | Defined | Implemented | None |
| `run()` with context | Defined | Implemented | None |
| `run_with_result()` | Defined | Implemented | None |
| Metadata propagation | step.name prefix | Implemented | None |
| Progress passthrough | Defined | Implemented | None |

**Status:** WorkflowComposer is complete.

### 1.4 Workflow Migration

| Workflow | Architecture | Uses Steps? | Uses Composer? | Gap |
|----------|-------------|-------------|----------------|-----|
| `ImportWorkflow` | Step composition | **YES** | **YES** | None |
| `ArchiveWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `VerifyWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `ValidateWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `RepairWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `ConsolidateWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `DedupeWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `MigrateWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `SearchWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |
| `StatusWorkflow` | Step composition | **NO** | **NO** | **MIGRATE** |

**Status:** 1/10 workflows use step composition. 9 need migration.

### 1.5 Progress Ownership

| Pattern | Architecture | Current Status | Gap |
|---------|-------------|----------------|-----|
| Workflow owns task sequence | Defined | Mixed | **STANDARDIZE** |
| CLI doesn't duplicate | Defined | Some duplication | **FIX** |
| Steps use progress.info() | Defined | Mostly correct | Minor fixes |

**Examples of duplication to fix:**
- `cli/import_.py:34-45` creates task sequence, but also `ImportWorkflow` can create sequences
- `cli/verify.py` creates task sequences AND calls workflow that may create sequences

---

## 2. CLI UI Layer

### 2.1 Widget Library

| Widget | Architecture | Current Status | Location | Gap |
|--------|-------------|----------------|----------|-----|
| `ReportCard` | Fluent builder | Implemented | `widgets.py` | None |
| `SuggestionList` | Fluent builder | Implemented | `widgets.py` | None |
| `ErrorPanel` | Fluent builder | Implemented | `widgets.py` | None |
| `ProgressSummary` | Fluent builder | Implemented | `widgets.py` | None |
| `ValidationPanel` | Fluent builder | **Not implemented** | - | **NEW WIDGET** |
| `AuthenticationStatus` | Fluent builder | **Not implemented** | - | **NEW WIDGET** |

**Status:** 4/6 widgets implemented. Need 2 new widgets.

### 2.2 Widget Adoption in Commands

| Command | Uses Widgets? | Current Pattern | Gap |
|---------|--------------|-----------------|-----|
| `import` | **NO** | Direct `ctx.show_report()` | **MIGRATE** |
| `archive` | **NO** | Direct output calls | **MIGRATE** |
| `verify-*` | **NO** | Direct `ctx.show_report()` | **MIGRATE** |
| `validate` | **NO** | Direct output calls | **MIGRATE** |
| `status` | **NO** | Direct output calls | **MIGRATE** |
| `dedupe` | **NO** | Direct output calls | **MIGRATE** |
| `consolidate` | **NO** | Direct output calls | **MIGRATE** |
| `search` | **NO** | Direct output calls | **MIGRATE** |
| `repair` | **NO** | Direct output calls | **MIGRATE** |
| `migrate` | **NO** | Direct output calls | **MIGRATE** |

**Status:** 0/10+ commands use widgets. Full migration needed.

### 2.3 UIBuilder

| Aspect | Architecture | Current Status | Gap |
|--------|-------------|----------------|-----|
| `task_sequence()` | Defined | Implemented | None |
| `spinner()` | Defined | Implemented | None |
| TaskSequenceImpl | Rich Live | Implemented | None |
| TaskHandleImpl | All methods | Implemented | None |
| JSON mode | Events emitted | Implemented | None |

**Status:** UIBuilder is complete.

### 2.4 CLIProgressAdapter

| Aspect | Architecture | Current Status | Gap |
|--------|-------------|----------------|-----|
| Implements ProgressReporter | Required | Implemented | None |
| Delegates to UIBuilder | Required | Implemented | None |
| NoOpTaskSequence fallback | Required | Implemented | None |

**Status:** CLIProgressAdapter is complete.

### 2.5 UI Directory Structure

| Path | Architecture | Current Status | Gap |
|------|-------------|----------------|-----|
| `cli/ui/` | Submodule root | Created | None |
| `cli/ui/__init__.py` | Public exports | Created (minimal) | Expand |
| `cli/ui/ARCHITECTURE.md` | Design doc | Created | None |
| `cli/ui/protocols.py` | Widget protocols | Not created | **CREATE** |
| `cli/ui/builder.py` | UIBuilder impl | Not moved | **MOVE** from ui_builder.py |
| `cli/ui/adapters.py` | CLIProgressAdapter | Not moved | **MOVE** from adapters.py |
| `cli/ui/widgets/` | Widget directory | Not created | **CREATE** |

**Status:** Directory structure started. Need to reorganize files.

---

## 3. Priority Implementation Plan

### Phase 1: Infrastructure (Low Risk)

1. **Create `cli/ui/widgets/` directory**
   - Move `widgets.py` → `cli/ui/widgets/` (split into modules)
   - Create `protocols.py` with Widget protocol

2. **Move existing files to `cli/ui/`**
   - `ui_builder.py` → `cli/ui/builder.py`
   - `adapters.py` → `cli/ui/adapters.py`
   - Update imports

### Phase 2: New Steps (Medium Risk)

1. **Create `AuthenticateGmailStep`**
   - Extract from `CommandContext.authenticate_gmail()`
   - Use in archive workflow

2. **Create `ScanGmailMessagesStep`**
   - Extract from `ArchiveWorkflow._scan_messages()`
   - Reuse in retry-delete workflow

3. **Create `WriteMessagesStep`**
   - Extract from `ArchiverFacade.archive()`
   - Reuse in consolidate workflow

4. **Create `DeleteMessagesStep`**
   - Extract from `ArchiveWorkflow._delete_messages()`
   - Reuse in retry-delete workflow

### Phase 3: Workflow Migration (Higher Risk)

Priority order by complexity and reuse opportunity:

1. **`VerifyWorkflow`** - Simple, uses facades directly
2. **`ValidateWorkflow`** - Already has ValidateArchiveStep
3. **`RepairWorkflow`** - Simple database operations
4. **`DedupeWorkflow`** - Uses filter patterns from import
5. **`ConsolidateWorkflow`** - Uses write patterns
6. **`ArchiveWorkflow`** - Most complex, most benefit
7. Remaining workflows...

### Phase 4: Widget Adoption (Low-Medium Risk)

One command at a time:

1. **`import` command** - Already thin, easy migration
2. **`verify-*` commands** - Similar patterns
3. **`status` command** - Simple report
4. Continue through remaining commands...

### Phase 5: New Widgets (Low Risk)

1. **`ValidationPanel`** - For verify/validate commands
2. **`AuthenticationStatus`** - For Gmail auth display

---

## 4. Metrics

### Current State

| Metric | Value |
|--------|-------|
| Steps implemented | 4 |
| Steps planned | 8 |
| Workflows using steps | 1/10 (10%) |
| Widgets implemented | 4 |
| Commands using widgets | 0/10+ (0%) |

### Target State (After Migration)

| Metric | Target |
|--------|--------|
| Steps implemented | 8+ |
| Workflows using steps | 10/10 (100%) |
| Widgets implemented | 6+ |
| Commands using widgets | 10+/10+ (100%) |

---

## 5. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing tests | High | Migrate one workflow at a time with tests |
| Progress output changes | Medium | Screenshot before/after, maintain UI/UX |
| Import cycle with new ui/ | Low | Careful import ordering |
| Widget API changes | Low | Widgets already follow fluent pattern |

---

## 6. Success Criteria

Phase 1 complete when:
- [ ] `cli/ui/` directory fully organized
- [ ] All imports updated and working
- [ ] Tests pass

Phase 2 complete when:
- [ ] All 8 planned steps implemented
- [ ] Steps have 95%+ test coverage

Phase 3 complete when:
- [ ] All workflows use step composition
- [ ] No double task sequences
- [ ] Clear progress ownership

Phase 4 complete when:
- [ ] All commands use widgets
- [ ] Consistent output across commands
- [ ] JSON mode works correctly

---

## Related Documents

- [workflows/ARCHITECTURE.md](../src/gmailarchiver/core/workflows/ARCHITECTURE.md)
- [cli/ui/ARCHITECTURE.md](../src/gmailarchiver/cli/ui/ARCHITECTURE.md)
- [docs/UI_UX_CLI.md](UI_UX_CLI.md)
- [docs/PROCESS.md](PROCESS.md)
