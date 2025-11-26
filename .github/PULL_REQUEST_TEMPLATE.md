## Summary

<!-- Brief description of changes -->

## Related Issue

<!-- Link to related issue: Fixes #123 -->

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)
- [ ] Test improvements

## Affected Layer(s)

- [ ] cli
- [ ] core
- [ ] data
- [ ] connectors
- [ ] shared

## 6-Phase Workflow Checklist

<!-- Verify you've completed each phase from PROCESS.md -->

- [ ] **Phase 1: Context** - Understood project state, read relevant docs
- [ ] **Phase 2: Design** - Architecture alignment verified, no SOLID violations
- [ ] **Phase 3: Test (Red)** - Failing tests written first (TDD)
- [ ] **Phase 4: Code (Green)** - Implementation complete, all tests pass
- [ ] **Phase 5: Verify** - All quality gates pass
- [ ] **Phase 6: Review** - Documentation updated, self-reviewed

## Quality Gates

<!-- All must pass before merge -->

- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy src/gmailarchiver` passes
- [ ] `uv run pytest` passes with 95%+ coverage

## Documentation

- [ ] Layer README.md updated (if implementation changed)
- [ ] CHANGELOG.md updated with entry
- [ ] Docstrings added/updated for new code
- [ ] ARCHITECTURE.md updated (if design changed)

## Testing

<!-- Describe how to test these changes -->

## Screenshots / Output

<!-- If applicable, add screenshots or command output -->

---

### Reviewer Notes

<!-- Any specific areas you'd like reviewers to focus on -->
