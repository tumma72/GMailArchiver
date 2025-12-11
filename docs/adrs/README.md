# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for Gmail Archiver. ADRs document significant architectural and design decisions made throughout the project.

## What is an ADR?

An Architecture Decision Record (ADR) is a document that captures an important architectural decision made along with its context and consequences. ADRs help:

- **Document rationale** - Explain why decisions were made
- **Track evolution** - Show how architecture evolved over time
- **Onboard new contributors** - Provide context for current state
- **Avoid revisiting** - Prevent re-litigating settled decisions
- **Learn from history** - Understand what worked and what didn't

## ADR Format

Each ADR follows this structure:

- **Title** - Short descriptive name (numbered sequentially)
- **Status** - Proposed, Accepted, Deprecated, or Superseded
- **Date** - When the decision was made
- **Context** - What factors influenced the decision
- **Decision** - What was decided
- **Consequences** - Positive and negative outcomes
- **Alternatives Considered** - What else was evaluated and why it was rejected
- **Related Decisions** - Links to other relevant ADRs

## Decision Records

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [001](001-hybrid-architecture-model.md) | Hybrid Architecture Model (mbox + SQLite) | ✅ Accepted | 2025-11-14 |
| [002](002-sqlite-fts5-search.md) | SQLite FTS5 for Full-Text Search | ✅ Accepted | 2025-11-14 |
| [003](003-web-ui-technology-stack.md) | Web UI Technology Stack (Svelte 5 + FastAPI) | ✅ Accepted | 2025-11-14 |
| [004](004-message-deduplication.md) | Message Deduplication Strategy (Message-ID Exact Matching) | ✅ Accepted | 2025-11-14 |
| [005](005-distribution-strategy.md) | Distribution Strategy (Multi-Tiered Approach) | ✅ Accepted | 2025-11-14 |
| [006](006-async-first-architecture.md) | Async-First Architecture | ✅ Accepted | 2025-12-10 |
| [007](007-strict-dependency-injection.md) | Strict Dependency Injection | ✅ Accepted | 2025-12-10 |

## Quick Reference by Topic

### Core Architecture
- **[ADR-001: Hybrid Architecture Model](001-hybrid-architecture-model.md)** - Why we use mbox + SQLite instead of pure database or pure files

### Search & Indexing
- **[ADR-002: SQLite FTS5 for Search](002-sqlite-fts5-search.md)** - Why we chose SQLite FTS5 over Elasticsearch, grep, or custom indexing

### User Interface
- **[ADR-003: Web UI Technology Stack](003-web-ui-technology-stack.md)** - Why Svelte 5 + FastAPI + Tailwind for the web interface

### Data Management
- **[ADR-004: Message Deduplication](004-message-deduplication.md)** - Why Message-ID exact matching (not fuzzy matching)

### Distribution & Installation
- **[ADR-005: Distribution Strategy](005-distribution-strategy.md)** - Multi-tiered approach (PyPI, install script, standalone executables)

### Code Architecture
- **[ADR-006: Async-First Architecture](006-async-first-architecture.md)** - Why we use async/await throughout the data and core layers
- **[ADR-007: Strict Dependency Injection](007-strict-dependency-injection.md)** - Why HybridStorage is the single data gateway

## Decision-Making Process

When proposing a new ADR:

1. **Create a draft** - Copy the template (see below)
2. **Research alternatives** - Evaluate at least 2-3 options
3. **Document trade-offs** - List pros and cons for each
4. **Propose decision** - Recommend a specific option with rationale
5. **Review** - Discuss with team/community
6. **Accept** - Update status to "Accepted" once consensus is reached

## ADR Template

```markdown
# ADR-NNN: [Short Title]

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Deciders:** [List of people involved]
**Technical Story:** [Optional: Link to issue/PR]

---

## Context

What is the issue we're facing? What factors are driving this decision?

---

## Decision

What have we decided to do?

---

## Consequences

### Positive

What are the benefits of this decision?

### Negative

What are the drawbacks or trade-offs?

---

## Alternatives Considered

### Alternative 1: [Name]

**Pros:**
- [List benefits]

**Cons:**
- [List drawbacks]

**Verdict:** Rejected - [Reason]

---

## Implementation Details

[Optional: Code examples, schemas, configurations]

---

## Related Decisions

- [Link to other ADRs]

---

## References

- [External links, RFCs, documentation]

---

**Last Updated:** YYYY-MM-DD
```

## Changing or Superseding Decisions

Decisions can evolve:

- **Deprecate** - Mark as no longer current, add link to replacement
- **Supersede** - Create new ADR that replaces old one, update both
- **Never delete** - Keep historical ADRs for reference (even if superseded)

Example:
```markdown
# ADR-001: Original Decision

**Status:** ~~Accepted~~ Superseded by [ADR-042](042-new-decision.md)
**Date:** 2025-01-01
**Superseded:** 2025-06-01

[Rest of original ADR content...]

## Superseded By

[ADR-042: New Decision](042-new-decision.md) - Explains why we changed approach
```

## References

- **ADR Concept**: https://adr.github.io/
- **Michael Nygard's Original Post**: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- **ADR Tools**: https://github.com/npryce/adr-tools

---

**Contributing:** See [CONTRIBUTING.md](../../CONTRIBUTING.md) for development guidelines

**Questions?** Open an issue with the `architecture` label
