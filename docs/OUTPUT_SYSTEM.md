# Unified Output System

**Status**: Core Infrastructure Complete (v1.3.1)
**Date**: 2025-11-24 (updated)
**Original**: 2025-11-19

---

## Overview

The Gmail Archiver now has a unified output system (`OutputManager`) that provides:

1. **Consistent Rich-formatted terminal output** with progress bars, spinners, and status indicators
2. **JSON output mode** for scripting and automation
3. **Structured logging** for debugging
4. **Actionable next-steps suggestions** after errors
5. **uv-style progress tracking** with moving window showing individual operations

---

## Architecture

### OutputManager Class

Location: `src/gmailarchiver/output.py`

**Key Features**:
- Mode switching: Normal (Rich), JSON, or Quiet
- Progress tracking with ETA and completion status
- Task status tracking with ✓/✗ emoji indicators
- Comprehensive error handling with suggestions
- Automatic JSON event streaming

**Example Usage**:
```python
from gmailarchiver.output import OutputManager

# Create output manager
output = OutputManager(json_mode=False)

# Start operation
output.start_operation("validate", "Validating archive.mbox")

# Show progress with context manager
with output.progress_context("Running validation checks", total=4) as progress:
    task = progress.add_task("Validation", total=4)

    # Do work...
    progress.update(task, advance=1)

# Show results
output.show_report("Validation Results", {
    "Count Check": "✓ PASSED",
    "Database Check": "✓ PASSED",
    "Integrity Check": "✗ FAILED",
    "Spot Check": "✓ PASSED"
})

# Suggest next steps on failure
if not all_passed:
    output.suggest_next_steps([
        "Verify database integrity: gmailarchiver verify-integrity",
        "Repair database: gmailarchiver repair --no-dry-run"
    ])

# End operation
output.end_operation(success=False, summary="Validation failed")
```

---

## Live Layout System (v1.3.1)

**Added**: 2025-11-24
**Status**: Implemented
**Components**: LogBuffer, SessionLogger, LiveLayoutContext

The v1.3.1 release adds infrastructure for flicker-free live layouts with integrated logging.

### LogBuffer

**Location**: `src/gmailarchiver/output.py` (lines 89-156)
**Purpose**: Ring buffer for displaying recent log messages in live UI
**Coverage**: 100%

**Features**:
- Fixed-size FIFO queue (default: 10 visible messages)
- Message deduplication with counters (e.g., "Installing packages... (3x)")
- Severity-based styling (ℹ/⚠/✗/✓ with blue/yellow/red/green colors)
- Rich Panel rendering

**Example Usage**:
```python
from gmailarchiver.output import LogBuffer

log_buffer = LogBuffer(max_visible=10)
log_buffer.add("Processing started", "INFO")
log_buffer.add("Warning: Rate limit approaching", "WARNING")
log_buffer.add("Error: Connection failed", "ERROR")
log_buffer.add("Success: All messages archived", "SUCCESS")

# Render as Rich Panel
panel = log_buffer.render()
```

### SessionLogger

**Location**: `src/gmailarchiver/output.py` (lines 158-219)
**Purpose**: Persistent file logging with automatic cleanup
**Coverage**: 97% (Windows paths not tested on macOS)

**Features**:
- XDG-compliant paths (`~/.config/gmailarchiver/logs/` on Linux/macOS)
- Timestamped filenames (`session_YYYYMMDD_HHMMSS.log`)
- Automatic cleanup (keeps last N sessions, default: 10)
- Threadsafe file operations
- Graceful error handling (continues if cleanup fails)

**Example Usage**:
```python
from gmailarchiver.output import SessionLogger
from pathlib import Path

# Auto-detects XDG paths or use custom dir
logger = SessionLogger(log_dir=Path("/custom/logs"), keep_last=10)
logger.write("Operation started", "INFO")
logger.write("Warning: Low disk space", "WARNING")
logger.close()  # Triggers cleanup
```

### LiveLayoutContext

**Location**: `src/gmailarchiver/output.py` (lines 222-280)
**Purpose**: Unified context manager integrating LogBuffer + SessionLogger
**Coverage**: 100%

**Features**:
- Combines ring buffer (UI) with persistent logging (file)
- Context manager for automatic cleanup
- Single `add_log()` method writes to both destinations
- Can accept pre-created components or create them automatically

**Example Usage**:
```python
from gmailarchiver.output import LiveLayoutContext
from pathlib import Path

with LiveLayoutContext(max_visible=10, log_dir=Path("logs")) as live:
    live.add_log("Starting archive operation", "INFO")
    live.add_log("Processing 100 messages...", "INFO")
    live.add_log("Archive complete!", "SUCCESS")
# Automatically closes logger and cleans up old sessions
```

### OutputManager Integration

**Method**: `live_layout_context(max_visible=10, log_dir=None)`
**Location**: `src/gmailarchiver/output.py` (lines 730-756)

**Example Usage**:
```python
from gmailarchiver.output import OutputManager

output = OutputManager()
with output.live_layout_context(max_visible=10) as live:
    live.add_log("Processing started", "INFO")
    # ... perform operations ...
    live.add_log("Processing complete", "SUCCESS")
```

---

## Proof-of-Concept: validate Command

The `validate` command has been updated to use the new output system as a proof-of-concept.

### Before (Plain Text):
```
Validating archive: consolidated_20251114.mbox

============================================================
ARCHIVE VALIDATION REPORT
============================================================
Count Check          ✗ FAILED
Database Check       ✗ FAILED
Integrity Check      ✓ PASSED
Spot Check           ✗ FAILED

Errors:
  - Count mismatch: 32217 in archive vs 26543 expected
  - DB count mismatch: 0 in DB vs 26543 expected
  - Spot check: 0/100 messages found in DB

============================================================
VALIDATION: ✗ FAILED
============================================================
```

**Problems**:
- No progress feedback (silent for seconds/minutes)
- Plain text output (not Rich)
- No suggestions for what to do next
- No JSON output option

### After (Rich + Progress + Suggestions):
```bash
# Normal mode with Rich output
$ gmailarchiver validate consolidated_20251114.mbox

validate: Validating consolidated_20251114.mbox

Validating 26,543 expected messages...

⠋ Running validation checks ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:05

┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Validation Results ┃          ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ Count Check        │ ✗ FAILED │
│ Database Check     │ ✗ FAILED │
│ Integrity Check    │ ✓ PASSED │
│ Spot Check         │ ✗ FAILED │
└────────────────────┴──────────┘

⚠  Found 3 error(s):
  • Count mismatch: 32217 in archive vs 26543 expected
  • DB count mismatch: 0 in DB vs 26543 expected
  • Spot check: 0/100 messages found in DB

Next steps:
  1. Import archive into database: gmailarchiver import consolidated_20251114.mbox
  2. Verify database integrity: gmailarchiver verify-integrity
  3. Repair database if needed: gmailarchiver repair --no-dry-run

✗ FAILED (5.2s)
Validation failed
```

**Improvements**:
- ✅ Progress bar with ETA
- ✅ Rich-formatted table
- ✅ Actionable next-steps suggestions
- ✅ Time tracking

### JSON Output Mode:
```bash
$ gmailarchiver validate consolidated_20251114.mbox --json
```

```json
{
  "events": [
    {
      "event": "operation_start",
      "operation": "validate",
      "description": "Validating consolidated_20251114.mbox"
    },
    {
      "event": "progress_start",
      "description": "Running validation checks",
      "total": 4
    },
    {
      "event": "progress_end",
      "description": "Running validation checks"
    },
    {
      "event": "report",
      "title": "Validation Results",
      "data": {
        "Count Check": "✗ FAILED",
        "Database Check": "✗ FAILED",
        "Integrity Check": "✓ PASSED",
        "Spot Check": "✗ FAILED"
      },
      "summary": null
    },
    {
      "event": "warning",
      "message": "Found 3 error(s):"
    },
    {
      "event": "next_steps",
      "suggestions": [
        "Import archive into database: gmailarchiver import consolidated_20251114.mbox",
        "Verify database integrity: gmailarchiver verify-integrity",
        "Repair database if needed: gmailarchiver repair --no-dry-run"
      ]
    },
    {
      "event": "operation_end",
      "success": false,
      "summary": "Validation failed",
      "elapsed": 5.23
    }
  ],
  "timestamp": 1734643200.0
}
```

---

## API Reference

### OutputManager

#### Initialization
```python
OutputManager(json_mode: bool = False, quiet: bool = False)
```

#### Methods

**start_operation(name: str, description: str | None = None) -> None**
- Start a new operation with optional description
- Shows operation header in terminal or logs event in JSON

**progress_context(description: str, total: int | None = None) -> Generator[Progress | None]**
- Context manager for progress tracking
- Shows spinner, progress bar, elapsed time, ETA
- Returns Progress object for updating or None (JSON/quiet mode)

**task_complete(name: str, success: bool, details: str | None = None, elapsed: float | None = None) -> None**
- Mark a task as complete with status indicator
- Tracks in internal list, updates live display

**show_report(title: str, data: dict | list[dict], summary: dict | None = None) -> None**
- Show formatted report (table or key-value pairs)
- JSON mode: logs structured data

**suggest_next_steps(suggestions: Sequence[str]) -> None**
- Show numbered list of actionable next steps
- Critical for user ergonomics

**error(message: str, suggestion: str | None = None, exit_code: int = 1) -> None**
- Show error with optional suggestion
- Exits with code if exit_code > 0

**success(message: str) -> None**
- Show success message with ✓ icon

**warning(message: str) -> None**
- Show warning message with ⚠ icon

**info(message: str) -> None**
- Show informational message

**end_operation(success: bool, summary: str | None = None) -> None**
- End operation with final status (✓/✗)
- Shows elapsed time
- Flushes JSON events

---

## Testing

**Test file**: `tests/test_output.py`
**Coverage**: 96% output.py overall (402 statements, 18 missed)
**Total tests**: 80 tests (v1.3.1)

**Test categories**:
- Initialization (normal, JSON, quiet modes)
- Start/end operations
- Progress tracking
- Task completion
- Reports (dict, table, JSON)
- Error handling with exit codes
- Success/warning/info messages
- Next-steps suggestions
- JSON event streaming
- **LogBuffer** (16 tests, 100% coverage)
- **SessionLogger** (34 tests, 97% coverage)
- **LiveLayoutContext** (7 tests, 100% coverage)

**All 80 tests pass** ✓

**New test files** (v1.3.1):
- `tests/test_session_logger.py` - SessionLogger comprehensive tests
- `tests/test_archiver.py::TestGmailArchiverWithOutput` - OutputManager integration tests

---

## Rollout Plan

### Phase 1: Proof-of-Concept ✅ COMPLETE
- [x] Create `OutputManager` class
- [x] Update `validate` command
- [x] Write comprehensive tests
- [x] Document system

### Phase 2: Core Commands (Week 1-2)
Update these commands to use `OutputManager`:
- [ ] `verify-integrity` - Database health check
- [ ] `verify-consistency` - Deep consistency check
- [ ] `verify-offsets` - Offset validation
- [ ] `repair` - Database repair
- [ ] `import` - Archive import
- [ ] `consolidate` - Archive consolidation

**Success criteria**:
- All show progress bars for long operations
- All support `--json` flag
- All provide next-steps on errors
- No plain text output (use Rich)

### Phase 3: Remaining Commands (Week 3)
- [ ] `archive` - Gmail archiving
- [ ] `search` - Message search
- [ ] `status` - Show statistics (includes schema version and database size)
- [ ] `dedupe` - Deduplication (use `--dry-run` for preview)
- [ ] `migrate` - Schema migration
- [ ] `rollback` - Rollback migration

### Phase 4: New Commands (Week 4)
Apply to new v1.2.0 features:
- [ ] `extract` - Message extraction
- [ ] `check` - Meta health check
- [ ] `compress` - Post-hoc compression
- [ ] `doctor` - Comprehensive diagnostics
- [ ] `schedule` - Cron job creation

---

## Design Decisions

### Why Rich Instead of Plain Text?
- **Professional appearance**: Tables, progress bars, colors
- **Better UX**: Real-time feedback, status indicators
- **Standard in modern CLIs**: uv, poetry, pipx all use Rich
- **Accessibility**: Supports NO_COLOR environment variable

### Why Context Manager for Progress?
- **Automatic cleanup**: Ensures display is reset even on exceptions
- **Clear lifecycle**: Enter = start, yield = work, exit = cleanup
- **Pythonic pattern**: Familiar to Python developers

### Why JSON Mode?
- **Scripting**: Machines can parse structured output
- **Logging**: Structured logs for debugging
- **CI/CD**: Easy integration with automation tools

### Why Next-Steps Suggestions?
- **User ergonomics**: Don't make users guess what to do after errors
- **Self-documenting**: Commands teach users how to fix issues
- **Reduces support burden**: Users can self-serve

---

## Migration Guide for Developers

### Before (old style):
```python
def my_command():
    console.print("Running operation...")
    # Do work
    print("Operation complete")
```

### After (new style):
```python
def my_command(json_output: bool = typer.Option(False, "--json")):
    output = OutputManager(json_mode=json_output)
    output.start_operation("my_command", "Running operation")

    with output.progress_context("Processing items", total=100) as progress:
        task = progress.add_task("Items", total=100) if progress else None

        for i in range(100):
            # Do work
            if progress and task:
                progress.update(task, advance=1)

    output.end_operation(success=True, summary="Operation complete")
```

### Adding --json Flag to All Commands

**Pattern**:
```python
@app.command()
def my_command(
    # ... existing args ...
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """Command description."""
    output = OutputManager(json_mode=json_output)
    # ... use output instead of console ...
```

---

## Future Enhancements

### Logging Integration
- Write all output events to structured log files
- Configurable log levels (DEBUG, INFO, WARNING, ERROR)
- Log rotation and archiving

### Verbosity Levels
- `-v` / `--verbose`: More detailed progress
- `-vv`: Debug-level output
- `-q` / `--quiet`: Suppress non-error output

### Color Themes
- Respect `NO_COLOR` environment variable
- Support custom color schemes
- High-contrast mode for accessibility

### Progress Estimation Improvements
- Learn from past runs to improve ETA accuracy
- Show throughput (e.g., "150 messages/second")
- Adaptive progress based on operation complexity

---

## Examples

### Example 1: Simple Operation
```python
output = OutputManager()
output.start_operation("example", "Running example")
output.info("Processing data...")
output.success("Operation completed successfully!")
output.end_operation(success=True)
```

### Example 2: Operation with Progress
```python
output = OutputManager()
output.start_operation("batch", "Processing 1000 items")

with output.progress_context("Processing", total=1000) as progress:
    task = progress.add_task("Items", total=1000) if progress else None

    for i in range(1000):
        # Process item
        time.sleep(0.01)

        if progress and task:
            progress.update(task, advance=1)

        if i % 100 == 0:
            output.task_complete(f"Batch {i//100}", success=True, elapsed=1.0)

output.end_operation(success=True)
```

### Example 3: Error Handling
```python
output = OutputManager()
output.start_operation("risky", "Running risky operation")

try:
    # Risky operation
    if error_condition:
        output.suggest_next_steps([
            "Check your configuration file",
            "Verify permissions: chmod 644 file.txt",
            "Contact support if issue persists"
        ])
        output.error(
            "Operation failed due to permission error",
            suggestion="Run 'chmod 644 file.txt' to fix permissions",
            exit_code=1
        )
except Exception as e:
    output.error(f"Unexpected error: {e}", exit_code=1)
```

---

## Related Documents

- [ERGONOMICS_ANALYSIS.md](./ERGONOMICS_ANALYSIS.md) - Full CLI ergonomics analysis
- [PLAN_v2.md](./PLAN_v2.md) - Development roadmap including output system rollout
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Developer guide

---

**Last Updated**: 2025-11-24
**Implementation Status**: Core Infrastructure Complete (v1.3.1), Command Rollout Pending
