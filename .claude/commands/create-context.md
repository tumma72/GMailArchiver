---
name: create-context
description: "Phase 1: Establish context for development work"
argument_hint: "Optional layer name: cli, core, data, connectors, or shared"
---

# Context Phase - Exploration

Execute Phase 1 (Context) of the development workflow defined in `docs/PROCESS.md`.

## Arguments

- `$ARGUMENTS` - Optional layer name: `cli`, `core`, `data`, `connectors`, or `shared`

## Required Steps

### 1. Read Project Documentation

Read these files to understand the system:
- `docs/ARCHITECTURE.md` - System overview and design decisions
- `docs/PROCESS.md` - Development workflow reference
- `CLAUDE.md` - Quick reference for AI assistants

### 2. Read Layer Documentation (if specified)

If a layer is specified (`$ARGUMENTS`), also read:
- `src/gmailarchiver/$ARGUMENTS/ARCHITECTURE.md` - Layer design and contracts
- `src/gmailarchiver/$ARGUMENTS/README.md` - Current implementation status

If no layer specified, list available layers:
- `cli/` - Command-line interface (Typer, OutputManager)
- `core/` - Business logic (Archiver, Validator, Search, etc.)
- `data/` - Data access (DBManager, HybridStorage, SchemaManager)
- `connectors/` - External services (GmailClient, GmailAuthenticator)
- `shared/` - Cross-cutting utilities

### 3. Verify Test Health

Run a quick test check:
```bash
uv run pytest --no-cov -q
```

Report any failures that need attention before proceeding.

### 4. Gap Analysis (if layer specified)

If a layer was specified, run gap analysis to identify work to do:

@.claude/commands/gap-analysis.md

### 5. Context Summary

Provide a summary including:
- Overall system architecture understanding
- Affected layer(s) and their current state
- Test health status
- Any blockers or concerns
- Gaps identified (from gap analysis)

## Exit Criteria Checklist

- [ ] Understand overall system architecture
- [ ] Understand affected layer(s) design
- [ ] Know current implementation state
- [ ] Tests are passing (or failures understood)

## Related Skills

These skills provide additional context (Claude loads them automatically when relevant):

- **gmailarchiver-patterns** - For architecture overview, layer patterns, and component design
- **database-operations** - For understanding DBManager, HybridStorage, and schema design

## Next Step

After completing context gathering, suggest running `/design` to proceed to Phase 2.
