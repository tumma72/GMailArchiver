# CLI Layer

**Status**: ✅ Complete
**Tests**: `tests/cli/` (all passing)

## Purpose

The CLI layer provides user interface components for the Gmail Archiver application, including output formatting, progress tracking, and command infrastructure.

## Components

| Module | Class | Description |
|--------|-------|-------------|
| `output.py` | `OutputManager` | Unified output system (Rich/JSON modes) |
| `output.py` | `OperationHandle` | Progress context for operations |
| `output.py` | `ProgressTracker` | ETA and rate calculations |
| `output.py` | `SessionLogger` | File-based session logging |
| `output.py` | `LogBuffer` | Scrolling log display |
| `command_context.py` | `CommandContext` | Dependency injection for commands |
| `command_context.py` | `with_context` | Decorator for command boilerplate |
| `_output_search.py` | - | Search result formatting |

## Dependencies

```
cli/ ────► data/ (DBManager, SchemaManager)
     └──► connectors/ (GmailAuthenticator, GmailClient)
```

**Note**: `output.py` has no layer dependencies (only external: Rich).

## Import Convention

Within CLI layer (relative imports):
```python
from .output import OutputManager, OperationHandle
```

Cross-layer (absolute imports):
```python
from gmailarchiver.connectors.auth import GmailAuthenticator
from gmailarchiver.data.db_manager import DBManager
```

## Usage Examples

### OutputManager
```python
from gmailarchiver.cli.output import OutputManager

output = OutputManager(json_mode=False)
output.print_success("Archive created", "archive.mbox")
output.print_error("Failed", "File not found")
```

### JSON Mode
```python
output = OutputManager(json_mode=True)
output.json_output({
    "status": "success",
    "messages_archived": 100
})
```

### Progress Tracking
```python
with output.operation_context("Archiving") as op:
    for msg in messages:
        process(msg)
        op.update(f"Processing {msg.id}")
```

### CommandContext (CLI commands)
```python
from gmailarchiver.cli.command_context import with_context, CommandContext

@app.command()
@with_context(requires_db=True, has_progress=True)
def archive(ctx: CommandContext, age: str) -> None:
    ctx.info(f"Archiving messages older than {age}")
    # ctx provides: output, db, gmail, progress
```

## Design Documentation

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed component design with Mermaid diagrams.
