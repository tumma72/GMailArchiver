---
name: feature
description: "Guide through complete 6-phase development workflow"
argument_hint: "Feature, fix, or change to implement"
---

# Feature Workflow - Full 6-Phase Orchestration

Guide through the complete development workflow defined in `docs/PROCESS.md`.

## Arguments

- `$ARGUMENTS` - Description of the feature, fix, or change

## Workflow Overview

```
Phase 1: Context    → Understand project state
Phase 2: Design     → Architecture alignment
Phase 3: Test (Red) → Write failing tests
Phase 4: Code (Green) → Implement minimal code
Phase 5: Verify     → Quality gates
Phase 6: Review     → Documentation & commit
```

## Phase Execution

Execute each phase sequentially, pausing between phases for confirmation.
Use TodoWrite to track progress through the phases.

---

### Phase 1: Context

@.claude/commands/create-context.md

---

### Phase 2: Design

@.claude/commands/design.md

---

### Phase 3: Test (Red)

@.claude/commands/test.md

---

### Phase 4: Code (Green)

@.claude/commands/code.md

---

### Phase 5: Verify

@.claude/commands/verify.md

---

### Phase 6: Review

@.claude/commands/review.md

---

## Progress Tracking

Use TodoWrite to track phase completion:

```
- [ ] Phase 1: Context
- [ ] Phase 2: Design
- [ ] Phase 3: Test (Red)
- [ ] Phase 4: Code (Green)
- [ ] Phase 5: Verify
- [ ] Phase 6: Review
```

## Related Skills

All skills may be relevant during a full feature workflow (Claude loads them automatically):

- **tdd-workflow** - For TDD red-green-refactor cycle guidance across phases
- **gmailarchiver-patterns** - For architecture, layer patterns, and component design
- **coding-standards** - For Python style, ruff, mypy, and type hints
- **testing-guidelines** - For pytest patterns, fixtures, and coverage
- **database-operations** - For SQLite, DBManager, and schema operations

## Definition of Done

Feature is **DONE** when:
1. All 6 phases completed
2. All quality gates pass
3. Documentation updated
4. Committed with proper message
5. Ready for PR
