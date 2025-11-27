---
name: verify
description: "Phase 5: Run all quality gates"
---

# Verify Phase - Quality Gates

Think Harder: Execute Phase 5 (Verify) of the development workflow defined in `docs/PROCESS.md`.

## Quality Gate Checks

Run each check in order. ALL must pass before work is considered complete.

### 1. Linting (ruff check)

```bash
uv run ruff check .
```

**Requirement**: Zero errors

If errors found:
- Auto-fix: `uv run ruff check . --fix`
- Review changes and re-run

### 2. Formatting (ruff format)

```bash
uv run ruff format --check .
```

**Requirement**: No changes needed

If formatting required:
- Auto-fix: `uv run ruff format .`
- Review changes and re-run

### 3. Type Checking (mypy)

```bash
uv run mypy src/gmailarchiver
```

**Requirement**: Zero errors

If errors found:
- Add missing type hints
- Fix type mismatches
- Import types from `typing` module as needed

### 4. Tests (pytest)

```bash
uv run pytest
```

**Requirements**:
- All tests must pass
- Coverage must be 95%+ overall

If tests fail:
- Fix the failing tests or implementation
- Do NOT skip or ignore failing tests

## Quality Requirements Summary

| Check | Command | Requirement |
|-------|---------|-------------|
| Lint | `uv run ruff check .` | No errors |
| Format | `uv run ruff format --check .` | No changes needed |
| Types | `uv run mypy src/gmailarchiver` | No errors |
| Tests | `uv run pytest` | All pass, 95%+ coverage |

## Quick Combined Check

Run all checks in sequence:
```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/gmailarchiver && uv run pytest
```

## Exit Criteria Checklist

- [ ] `ruff check` passes
- [ ] `ruff format --check` passes
- [ ] `mypy` passes
- [ ] All tests pass
- [ ] Coverage requirements met

## Next Step

After all gates pass, run `/review` to finalize documentation (Phase 6).

## Troubleshooting

### Common Linting Issues
- **I001**: Import sorting - run `ruff check . --fix`
- **N806**: Variable naming - rename to lowercase
- **UP037**: Remove quotes from type annotations

### Common Type Errors
- Missing return type → Add `-> ReturnType`
- Missing parameter type → Add `: ParamType`
- Optional not handled → Use `if x is not None:` check

### Coverage Gaps
- Missing branch coverage → Add tests for all code paths
- Uncovered error handling → Add tests that trigger exceptions

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **coding-standards** - For fixing ruff lint errors, mypy type hints, and formatting issues
- **testing-guidelines** - For pytest patterns and coverage improvements
