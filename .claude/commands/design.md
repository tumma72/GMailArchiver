---
name: design
description: "Phase 2: Architecture-first design before implementation"
argument_hint: "Feature, fix, or change to design"
---

# Design Phase - Architecture First

Ultrathink: Execute Phase 2 (Design) of the development workflow defined in `docs/PROCESS.md`.

## Arguments

- `$ARGUMENTS` - Description of the feature, fix, or change to design

## Required Steps

Delegate this work to the @agent-architect

### 1. Analyze Request Against Architecture

Read and compare against `docs/ARCHITECTURE.md`:
- How does this request fit the existing architecture?
- Which component(s) should handle this?
- Does it follow established patterns?

### 2. Identify Affected Layers

Determine which layer(s) are affected:

| Layer | Responsibility |
|-------|----------------|
| `cli/` | Commands, user interaction, output formatting |
| `core/` | Business logic, orchestration, validation |
| `data/` | Database operations, storage, schema management |
| `connectors/` | External APIs (Gmail), authentication |
| `shared/` | Utilities, exceptions, types |

### 3. Check Layer Contracts

Verify dependency rules are respected:

| Layer | Can Depend On | Cannot Depend On |
|-------|---------------|------------------|
| cli (Interface) | All layers | - |
| core (Business Logic) | data, connectors, shared | cli |
| data | shared | cli, core, connectors |
| connectors | shared | cli, core, data |
| shared | (none) | All other layers |

### 4. SOLID Principles Check

- **Single Responsibility**: Does this fit within an existing component's responsibility?
- **Open/Closed**: Can we extend without modifying existing code?
- **Liskov Substitution**: Are interfaces properly abstracted?
- **Interface Segregation**: Are interfaces minimal and focused?
- **Dependency Inversion**: Are we depending on abstractions?

### 5. Architecture Decision

Determine if architecture needs to change:
- **Yes**: Document proposed changes to ARCHITECTURE.md first
- **No**: Document implementation approach within existing architecture

### 6. Output Design Document

Provide:
- Affected layers and components
- New classes/methods needed (if any)
- Implementation approach
- Any ARCHITECTURE.md updates required
- Potential risks or concerns

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **gmailarchiver-patterns** - For architecture, layer patterns, SOLID principles, and component dependencies
- **database-operations** - For schema design, DBManager contracts, and data integrity patterns

## Exit Criteria Checklist

- [ ] Request is mapped to specific layer(s)
- [ ] Architecture changes (if any) are documented
- [ ] Implementation approach is clear
- [ ] No SOLID violations anticipated

## Next Step

After design approval, suggest running `/test` to write failing tests (Phase 3).
