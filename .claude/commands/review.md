---
name: review
description: "Phase 6: Code review and documentation update"
---

# Review Phase - Documentation & Commit

Think Harder: Execute Phase 6 (Review) of the development workflow defined in `docs/PROCESS.md`.

## Required Steps

Delegate this work to the @agent-reviewer

### 1. Code Review Checklist

Self-review the changes:

- [ ] Implementation aligns with architecture design
- [ ] No unintended architectural drift
- [ ] Code follows project patterns (see CLAUDE.md)
- [ ] Error handling is appropriate
- [ ] No security concerns (input validation, path traversal)
- [ ] No placeholder code (TODO, FIXME, NotImplementedError)

### 2. Update Layer README.md

For each affected layer, update `src/gmailarchiver/<layer>/README.md`:

- Document what **IS** (not what SHOULD BE)
- Update class/method inventory if changed
- Update "Current Status" section
- Note any known limitations or technical debt

### 3. Update CHANGELOG.md

Add entry under `## [Unreleased]`:

```markdown
## [Unreleased]

### Added
- New feature X in <layer> layer

### Changed
- Modified behavior Y in <layer> layer

### Fixed
- Bug Z in <layer> layer

### Deprecated
- Old API that will be removed

### Removed
- Removed deprecated feature
```

Categories:
- **Added**: New features
- **Changed**: Changes to existing features
- **Deprecated**: Features to be removed in future
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security-related changes

### 4. Review Git Changes

```bash
git status
git diff
```

Verify:
- Only intended files are modified
- No sensitive data (credentials, tokens) included
- No temporary/debug code left behind

### 5. Prepare Commit

Stage changes:
```bash
git add <files>
```

Create commit with conventional format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, no code change
- `refactor`: Code change that doesn't fix bug or add feature
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(search): add BM25 ranking improvements
fix(auth): handle token refresh edge case
docs(readme): update installation instructions
refactor(db): simplify transaction handling
```

## Exit Criteria Checklist

- [ ] Code review complete (self or peer)
- [ ] README.md reflects actual implementation
- [ ] CHANGELOG.md entry added
- [ ] Changes committed with conventional format

## Definition of Done

Work is **DONE** when:
1. All 6 phases completed
2. All quality gates pass (`/verify`)
3. Documentation updated
4. Committed with proper message
5. Ready for PR (if applicable)

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **coding-standards** - For verifying style, formatting, and type hint compliance
- **gmailarchiver-patterns** - For checking architecture alignment and layer contracts
- **testing-guidelines** - For reviewing test quality and coverage

## Next Step

If creating a PR, run `/gh-pr` to create pull request with checklist.
