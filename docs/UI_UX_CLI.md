# CLI UI/UX Guidelines

This document defines the visual language, interaction patterns, and composable components for Gmail Archiver's command-line interface. All commands MUST follow these guidelines to ensure a consistent, professional user experience.

**Status**: Iteration 2 - Log Window Support (Streaming Tasks)

---

## 1. Core Principles

### 1.1 Consistency
Same visual patterns across all commands. Users should recognize patterns from one command to another.

### 1.2 Clarity
Users always know what's happening and what to do next. Progress is visible, errors are actionable.

### 1.3 Hierarchy
Visual weight guides attention: `errors > warnings > info`. Critical information stands out.

### 1.4 Accessibility
Colors have text fallbacks. Symbols accompany colors. No meaning is conveyed through color alone.

---

## 2. Visual Language

### 2.1 Symbols & Semantics

| Symbol | Color | Meaning | Usage |
|--------|-------|---------|-------|
| `✓` | green | Success | Completed operations, passed checks |
| `✗` | red | Failure | Failed operations, errors |
| `⚠` | yellow | Warning | Non-fatal issues, caution needed |
| `ℹ` | blue | Info | Informational messages |
| `○` | dim | Pending | Not yet started |
| `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | cyan | Running | Animated spinner (braille pattern) |

### 2.2 Color Semantics

| Color | Rich Markup | Semantic Meaning |
|-------|-------------|------------------|
| Green | `[green]` | Success, completion, passed |
| Red | `[red]` | Errors, failures, critical |
| Yellow | `[yellow]` | Warnings, caution |
| Cyan | `[cyan]` | Information, highlights |
| Blue | `[blue]` | Operations, headers |
| Dim | `[dim]` | Secondary info, metadata |

### 2.3 Typography

| Style | Rich Markup | Usage |
|-------|-------------|-------|
| Bold | `[bold]` | Emphasis, headers, important values |
| Dim | `[dim]` | Secondary info, timestamps, paths |
| Normal | (none) | Primary content |

---

## 3. Message Types

### 3.1 Info Messages
Plain text, no symbol. Used for status updates and contextual information.

```
Authenticating with Gmail...
Found 1,234 messages matching query
```

**API**: `ctx.info("message")`

### 3.2 Success Messages
Green checkmark symbol. Used for completed operations.

```
✓ Authentication successful
✓ Archive validation passed
```

**API**: `ctx.success("message")`

### 3.3 Warning Messages
Yellow warning symbol. Used for non-fatal issues.

```
⚠ DRY RUN - no changes made
⚠ Some messages could not be processed
```

**API**: `ctx.warning("message")`

### 3.4 Error Messages
Red text with optional suggestion. Used for errors that don't require a panel.

```
Error: File not found
Suggestion: Check the file path and try again
```

**API**: `ctx.error("message", suggestion="optional suggestion")`

---

## 4. Panel Components

*[Placeholder - Iteration 2]*

### 4.1 Error Panel
When: Fatal errors requiring user attention.

### 4.2 Validation Panel
When: Multi-check validation results.

### 4.3 When to Use Panels
- **USE**: Final results, errors requiring attention, multi-item summaries
- **DON'T USE**: Progress updates, simple confirmations, inline status

---

## 5. Tables & Reports

*[Placeholder - Iteration 3]*

### 5.1 Key-Value Report
For summary data with labels and values.

### 5.2 Tabular Data
For multi-row data with headers.

---

## 6. Progress & Tasks

### 6.1 Spinner (Indeterminate Progress)
Used when total is unknown. Animated braille pattern spinner.

```
⠹ Loading messages...
⠸ Authenticating with Gmail...
```

### 6.2 Progress Bar (Determinate Progress)
Used when total is known. Shows percentage, count, and ETA.

```
⠹ Importing messages [████████░░░░] 67% • 1,234/2,000 • 2m remaining
```

### 6.3 Task Sequence (Issue #4 Pattern)
Used for multi-step operations. Each task shows spinner while running, then checkmark/X when complete.

**Running State:**
```
✓ Counting messages: Found 4,269 messages
⠹ Importing messages...
```

**Completed (Success):**
```
✓ Counting messages: Found 4,269 messages
✓ Importing messages: Imported 4,269 messages
✓ Verifying import: All messages valid
```

**Completed (Failure):**
```
✓ Counting messages: Found 4,269 messages
✗ Importing messages: FAILED → "Database write error"
```

**API (Fluent Builder):**
```python
with ctx.ui.task_sequence() as seq:
    with seq.task("Counting messages") as t:
        count = importer.count_messages(file)
        t.complete(f"Found {count:,} messages")

    with seq.task("Importing messages", total=count) as t:
        for msg in messages:
            process(msg)
            t.advance()
        t.complete(f"Imported {count:,} messages")
```

**Task Handle Methods:**
- `t.complete(message)` - Mark task as successful (shows ✓)
- `t.fail(message, reason=None)` - Mark task as failed (shows ✗)
- `t.advance(n=1)` - Advance progress counter (if total was set)
- `t.set_total(total)` - Set total after task started (for late-bound totals)
- `t.set_status(text)` - Update task description (e.g., for live counters)
- `t.log(message, level)` - Log a message within the task

### 6.4 Log Window (Streaming Tasks)
For operations with streaming output, use `show_logs=True` to display a scrolling log window below the tasks.

**Archive Command Example:**
```
✓ Scanning messages from Gmail: Found 15,000 messages
✓ Checking for already archived: Identified 13,267 to archive (1,733 already archived)
⠹ Archiving messages [████░░░░░░░░] 30% • 3,980/13,267
──────────────────────────────────────────────────────
✓ Archived: RE: Q4 Budget Review
✓ Archived: Meeting Notes - Product Sync
✓ Archived: Invoice #12345
⚠ Skipped (duplicate): FW: Contract Update
```

**API:**
```python
with ctx.ui.task_sequence(show_logs=True) as seq:
    # Task 1: Discovery (spinner with live counter)
    with seq.task("Scanning messages from Gmail") as t:
        def progress(count, page):
            t.set_status(f"Scanning messages from Gmail... {count:,} found")
        messages = client.list_messages(query, progress_callback=progress)
        t.complete(f"Found {len(messages):,} messages")

    # Task 2: Filtering (quick)
    with seq.task("Checking for already archived") as t:
        to_archive, skipped = filter_archived(messages)
        t.complete(f"Identified {len(to_archive):,} to archive")

    # Task 3: Archiving (progress bar + log window)
    with seq.task("Archiving messages", total=len(to_archive)) as t:
        for msg in archive(to_archive):
            t.log(f"Archived: {msg.subject}", "SUCCESS")
            t.advance()
        t.complete(f"Archived {len(to_archive):,} messages")
```

**Log Symbols:**
| Level | Symbol | Color |
|-------|--------|-------|
| INFO | ℹ | blue |
| WARNING | ⚠ | yellow |
| ERROR | ✗ | red |
| SUCCESS | ✓ | green |

---

## 7. Suggestions & Next Steps

*[Placeholder - Iteration 2]*

---

## 8. JSON Mode

All output MUST have a JSON equivalent for automation. When `--json` flag is used:

```json
{
  "events": [
    {"event": "task_start", "description": "Counting messages", "timestamp": 1234567890.123},
    {"event": "task_complete", "description": "Counting messages", "success": true, "result": "Found 4,269 messages"},
    {"event": "task_start", "description": "Importing messages", "total": 4269},
    {"event": "progress", "completed": 100, "total": 4269},
    {"event": "task_complete", "description": "Importing messages", "success": true, "result": "Imported 4,269 messages"}
  ],
  "timestamp": 1234567890.999,
  "success": true,
  "status": "ok"
}
```

---

## 9. Accessibility

### 9.1 Color Independence
- **NEVER** convey meaning through color alone
- **ALWAYS** pair colors with symbols (✓/✗/⚠)
- Text labels accompany all status indicators

### 9.2 Non-TTY Environments
- Graceful degradation when no terminal detected
- Plain text fallback without Rich formatting
- JSON mode (`--json`) for piping and automation

### 9.3 Screen Reader Considerations
- Meaningful text descriptions (not just symbols)
- Avoid ASCII art that doesn't linearize well
- Progress updates at reasonable intervals (not every item)

---

## 10. Error Recovery Patterns

*[Placeholder - Iteration 4]*

### 10.1 Retryable Errors
### 10.2 Partial Success
### 10.3 Rollback Scenarios
### 10.4 Graceful Interruption (Ctrl+C)

---

## 11. Component Composition Rules

- **One live context at a time**: No nested progress bars or task sequences
- **Task sequences contain tasks**: Not other sequences (flat structure)
- **Panels appear after progress**: Never show bordered panels during live progress
- **JSON events are real-time**: Emit events as they happen, don't buffer

---

## Appendix: Implementation Reference

### A.1 Files
- `src/gmailarchiver/cli/ui_builder.py` - Fluent builder implementation
- `src/gmailarchiver/cli/output.py` - OutputManager (existing, being wrapped)
- `src/gmailarchiver/cli/command_context.py` - CommandContext with `ui` property

### A.2 Migration Status

| Command | Status | Pattern |
|---------|--------|---------|
| `import` | ✓ Iteration 1 | task_sequence |
| `archive` | ✓ Iteration 2 | task_sequence + show_logs |
| `validate` | Pending | task_sequence |
| (other commands) | Pending | See implementation plan |
