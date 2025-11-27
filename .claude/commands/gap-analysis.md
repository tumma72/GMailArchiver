---
name: gap-analysis
description: "Compare ARCHITECTURE.md (ideal) vs README.md (actual) for a layer"
argument_hint: "Layer name: cli, core, data, connectors, or shared"
---

# Gap Analysis - Architecture vs Implementation

Ultrathink: Compare declarative (ideal) and documentative (actual) artifacts to identify work to be done.

## Arguments

- `$ARGUMENTS` - Layer name: `cli`, `core`, `data`, `connectors`, or `shared`

## Philosophy

From `docs/PROCESS.md`:

| Type | Purpose | Example | Updates When |
|------|---------|---------|--------------|
| **Declarative** | Describes ideal state | ARCHITECTURE.md | Design decisions change |
| **Documentative** | Describes current state | README.md | Implementation changes |

The **gap** between declarative and documentative artifacts defines work to be done.

## Analysis Steps

Delegate this work to the @agent-architect

### 1. Read Layer Documents

For layer `$ARGUMENTS`:
- Read `src/gmailarchiver/$ARGUMENTS/ARCHITECTURE.md` (Declarative: ideal state)
- Read `src/gmailarchiver/$ARGUMENTS/README.md` (Documentative: current state)

### 2. Compare Artifacts

For each aspect, compare what SHOULD exist vs what DOES exist:

| Aspect | ARCHITECTURE.md | README.md | Status |
|--------|-----------------|-----------|--------|
| Classes | Expected classes | Implemented classes | Gap/Match |
| Methods | Expected interfaces | Implemented methods | Gap/Match |
| Patterns | Design patterns | Used patterns | Gap/Match |
| Contracts | Interface contracts | Actual behavior | Gap/Match |

### 3. Identify Gaps

**Gaps** (work to do):
- Features in ARCHITECTURE.md not yet implemented
- Interfaces defined but not implemented
- Behaviors specified but not tested

**Drift** (potential issues):
- Implementation differs from architecture
- Undocumented features in README.md
- Patterns not matching design

### 4. Output Analysis

Provide structured gap report:

```markdown
## Gap Analysis: $ARGUMENTS Layer

### Summary
- **Architecture Version**: <from ARCHITECTURE.md>
- **Implementation Status**: <from README.md>
- **Gap Count**: X items

### Gaps (Work To Do)
1. [ ] Feature A - defined in ARCH, not in README
2. [ ] Method B - interface specified, not implemented
3. [ ] Pattern C - design pattern not applied

### Architectural Drift
1. Feature D - implemented differently than designed
2. Method E - not in architecture but exists

### Recommendations
- Priority 1: <most important gap>
- Priority 2: <next important>
- Consider: <architectural update if drift is intentional>
```

## Available Layers

| Layer | Path | Purpose |
|-------|------|---------|
| `cli` | `src/gmailarchiver/cli/` | Command-line interface |
| `core` | `src/gmailarchiver/core/` | Business logic |
| `data` | `src/gmailarchiver/data/` | Data access |
| `connectors` | `src/gmailarchiver/connectors/` | External services |
| `shared` | `src/gmailarchiver/shared/` | Utilities |

## Use Cases

1. **Before implementation**: Identify what needs to be built
2. **After implementation**: Verify README.md is updated
3. **Design review**: Check for architectural drift
4. **Sprint planning**: Prioritize gaps as work items

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **gmailarchiver-patterns** - For understanding architecture and layer contracts
- **database-operations** - For understanding schema design and data integrity patterns
