---
name: code
description: "Phase 4: Implement minimal code to pass tests (TDD Green)"
argument_hint: "Module or feature name to implement"
---

# Code Phase - TDD Green

Think Harder: Execute Phase 4 (Code) of the development workflow defined in `docs/PROCESS.md`.

## Arguments

- `$ARGUMENTS` - Module or feature name to implement

## Required Steps

Delegate this code work to the @agent-coder

### 1. Review Failing Tests

Read the failing tests to understand:
- What behavior is expected
- What inputs are provided
- What outputs/effects are expected
- Edge cases and error conditions

### 2. Implement Minimal Code

Write the **simplest code** that makes tests pass:
- Do NOT add features not covered by tests
- Do NOT over-engineer or optimize prematurely
- Follow existing code patterns in the project

### 3. Iterate Until Green

Run tests after each change:
```bash
uv run pytest tests/<test_file>.py -v --no-cov
```

Work through one test at a time:
1. Make first test pass
2. Make second test pass
3. Continue until all pass

### 4. Refactor (Optional)

Once ALL tests pass, refactor for clarity:
- Remove code duplication
- Improve naming
- Simplify logic
- **Verify tests still pass after refactoring**

## Implementation Guidelines

### Project Patterns to Follow

**Context Manager Pattern** (for database operations):
```python
with DBManager(db_path) as db:
    db.record_archived_message(...)
```

**CommandContext Pattern** (for CLI commands):
```python
@app.command()
@with_context(requires_db=True, has_progress=True)
def my_command(ctx: CommandContext, ...) -> None:
    ctx.output.info("Message")
```

**HybridStorage Pattern** (for atomic writes):
```python
storage = HybridStorage(db_manager)
offset, length = storage.archive_message(msg, gmail_id, archive_path)
```

**Error Handling**:
```python
ctx.fail_and_exit(
    title="Error Title",
    message="What went wrong",
    suggestion="How to fix it"
)
```

### Code Quality Requirements

- **Type hints**: All functions must have complete type hints (mypy strict)
- **Line length**: 100 characters max
- **Imports**: Sorted by ruff (stdlib, third-party, local)
- **No placeholders**: No TODO, FIXME, or NotImplementedError in production code

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **coding-standards** - For Python style, formatting, ruff, mypy, and type hints
- **gmailarchiver-patterns** - For architecture, layer patterns, and component design
- **database-operations** - For SQLite, DBManager, HybridStorage, and schema operations
- **tdd-workflow** - For TDD red-green-refactor cycle guidance

## Exit Criteria Checklist

- [ ] All new tests pass
- [ ] Existing tests still pass
- [ ] Code follows existing patterns
- [ ] No obvious code smells
- [ ] Type hints are complete

## Next Step

After tests pass, run `/verify` to check quality gates (Phase 5).
