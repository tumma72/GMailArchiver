---
name: gh-issue
description: "Create a GitHub issue with proper labels and formatting"
argument_hint: "Issue description or type"
---

# Create GitHub Issue

Create a properly formatted GitHub issue using the `gh` CLI.

## Arguments

- `$ARGUMENTS` - Issue description or type

## Issue Types

Determine the issue type based on `$ARGUMENTS`:

| Type | Labels | Template |
|------|--------|----------|
| `bug` | `bug`, `triage` | Bug report |
| `feature` | `enhancement` | Feature request |
| `task` | `task` | Development task |
| `docs` | `documentation` | Documentation update |

## Required Information

Gather the following before creating:

### For Bug Reports
- **Title**: Clear, concise bug description
- **Version**: `gmailarchiver --version`
- **Steps to reproduce**: Numbered list
- **Expected vs actual behavior**
- **Error output/logs** (if any)

### For Feature Requests
- **Title**: Feature name
- **Layer(s) affected**: cli, core, data, connectors, shared
- **Problem statement**: Why is this needed?
- **Proposed solution**: How should it work?

### For Tasks
- **Title**: Task description
- **Layer(s) affected**
- **Acceptance criteria**: Checklist of requirements
- **6-phase workflow checklist** (from PROCESS.md)

## Create Issue Command

```bash
gh issue create \
  --title "<title>" \
  --body "<body>" \
  --label "<label1>,<label2>"
```

## Body Templates

### Bug Report Body
```markdown
## Bug Description
<description>

## Version
<version>

## Steps to Reproduce
1. Step one
2. Step two
3. Step three

## Expected Behavior
<what should happen>

## Actual Behavior
<what actually happens>

## Error Output
```
<error logs>
```
```

### Feature Request Body
```markdown
## Problem Statement
<why this feature is needed>

## Proposed Solution
<how it should work>

## Affected Layer(s)
- [ ] cli
- [ ] core
- [ ] data
- [ ] connectors
- [ ] shared

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
```

### Task Body
```markdown
## Task Description
<what needs to be done>

## Affected Layer(s)
- [ ] cli
- [ ] core
- [ ] data
- [ ] connectors
- [ ] shared

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Workflow Phases
- [ ] Phase 1: Context
- [ ] Phase 2: Design
- [ ] Phase 3: Test (Red)
- [ ] Phase 4: Code (Green)
- [ ] Phase 5: Verify
- [ ] Phase 6: Review
```

## After Creation

Report the issue URL and number for reference.

## List Open Issues

To see existing issues:
```bash
gh issue list --state open
```

## View Issue

To view an issue:
```bash
gh issue view <number>
```
