---
name: gh-pr
description: "Create a pull request with 6-phase workflow checklist"
argument_hint: "PR title or related issue number"
---

# Create Pull Request

Create a properly formatted pull request using the `gh` CLI.

## Arguments

- `$ARGUMENTS` - PR title or related issue number

## Pre-PR Checklist

Before creating PR, verify:

1. **Quality gates pass** - Run the verify command:

@.claude/commands/verify.md

2. **Branch is up to date**:
   ```bash
   git fetch origin main
   git rebase origin/main
   ```

3. **Changes are committed**:
   ```bash
   git status
   git log --oneline -5
   ```

## Gather PR Information

### From Git
```bash
# Get branch name
git branch --show-current

# Get commit summary
git log origin/main..HEAD --oneline

# Get changed files
git diff --stat origin/main..HEAD
```

### Determine Affected Layers

Based on changed files, identify affected layers:
- `src/gmailarchiver/cli/` → cli
- `src/gmailarchiver/core/` → core
- `src/gmailarchiver/data/` → data
- `src/gmailarchiver/connectors/` → connectors
- `src/gmailarchiver/shared/` → shared

## Create PR Command

```bash
gh pr create \
  --title "<title>" \
  --body "<body>" \
  --base main
```

## PR Body Template

```markdown
## Summary
<Brief description of changes>

## Related Issue
Fixes #<issue_number>

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Affected Layer(s)
- [ ] cli
- [ ] core
- [ ] data
- [ ] connectors
- [ ] shared

## 6-Phase Workflow Checklist
- [ ] **Phase 1: Context** - Understood project state, read relevant docs
- [ ] **Phase 2: Design** - Architecture alignment verified
- [ ] **Phase 3: Test (Red)** - Failing tests written first
- [ ] **Phase 4: Code (Green)** - Implementation complete, tests pass
- [ ] **Phase 5: Verify** - All quality gates pass
- [ ] **Phase 6: Review** - Documentation updated

## Quality Gates
- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy src/gmailarchiver` passes
- [ ] `uv run pytest` passes with 95%+ coverage

## Documentation
- [ ] README.md updated (if applicable)
- [ ] CHANGELOG.md updated
- [ ] Docstrings added/updated

## Testing
<Describe how to test these changes>

## Screenshots/Output
<If applicable, add screenshots or command output>
```

## After Creation

Report the PR URL for review.

## Useful Commands

```bash
# View PR status
gh pr status

# View specific PR
gh pr view <number>

# Check CI status
gh pr checks <number>

# Request review
gh pr edit <number> --add-reviewer <username>
```
