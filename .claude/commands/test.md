---
name: test
description: "Phase 3: Write failing tests first (TDD Red)"
argument_hint: "Behavior description or expected outcome"
---

# Test Phase - TDD Red

Think Hard: Execute Phase 3 (Test) of the development workflow defined in `docs/PROCESS.md`.

## Arguments

- `$ARGUMENTS` - Description of the behavior to test

## Required Steps

Delegate this work to the @agent-tester

### 1. Gap Analysis

Run a gap analysis to identify what needs to be tested:

@.claude/commands/gap-analysis.md

### 2. Analyze Existing Tests

Find relevant test files in `tests/`:
- Test files match source structure (`test_module.py` → `module.py`)
- Review `tests/conftest.py` for available fixtures
- Note testing patterns used in this project

Key fixtures available:
- `temp_dir` - Temporary directory
- `temp_db` - V1.1 database
- `populated_db` - Database with test messages
- `sample_message` - Sample email bytes

### 3. Write Failing Tests

Follow project testing patterns:

```python
def test_<behavior>_<expected_outcome>(self, fixture):
    """<Behavior description>."""
    # Arrange - setup using existing fixtures

    # Act - invoke the behavior

    # Assert - verify the outcome (not internal state)
```

Guidelines:
- **Test behavior, not implementation** - What the system does, not how
- **Use existing fixtures** - From `tests/conftest.py`
- **Correct location** - Match source structure
- **Clear names** - `test_<behavior>_<expected_outcome>`
- **Include edge cases** - Error conditions, boundary values

### 4. Verify Tests Fail

Run the new tests:
```bash
uv run pytest tests/<test_file>.py::<test_function> -v --no-cov
```

**CRITICAL**: All new tests MUST fail initially.

If tests pass immediately, they are NOT testing new behavior - revise them.

## Test Writing Guidelines

### Good Test Characteristics
- Tests ONE behavior
- Clear arrange-act-assert structure
- Uses descriptive names
- Independent of other tests
- Fast execution
- No external dependencies (mock Gmail API)

### Example Test

```python
def test_archive_message_records_in_database(self, temp_db, sample_message):
    """Archiving a message should record it in the database."""
    # Arrange
    storage = HybridStorage(temp_db)
    archive_path = Path("/tmp/test.mbox")

    # Act
    storage.archive_message(sample_message, "gmail123", archive_path)

    # Assert - verify behavior, not internal state
    assert temp_db.get_message_location("<test@example.com>") is not None
```

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **testing-guidelines** - For pytest patterns, fixtures, mocking, and coverage
- **tdd-workflow** - For TDD red-green-refactor cycle and failing test methodology
- **database-operations** - For mocking DBManager, HybridStorage, and database operations

## Exit Criteria Checklist

- [ ] Tests are written for all new/changed behavior
- [ ] Tests follow existing patterns and conventions
- [ ] Tests are in correct location
- [ ] **All new tests FAIL** (Red phase complete)

## Next Step

After tests are failing, suggest running `/code` to implement (Phase 4).
