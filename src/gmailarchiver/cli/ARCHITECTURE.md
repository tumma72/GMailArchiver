# CLI Layer Architecture

This document defines the design of the CLI layer, which handles user interaction,
command processing, and output formatting for the Gmail Archiver application.

## Layer Overview

The CLI layer provides:
1. **OutputManager**: Unified output system (Rich terminal / JSON modes)
2. **CommandContext**: Dependency injection for CLI commands
3. **Search Output**: Formatted search result display

```mermaid
graph TB
    subgraph CLI["cli/ - User Interface Layer"]
        Output["output.py<br/>OutputManager"]
        Context["command_context.py<br/>CommandContext"]
        SearchOutput["_output_search.py<br/>Search Formatting"]
    end

    subgraph Entry["Entry Point"]
        Main["__main__.py<br/>Typer CLI"]
    end

    Main --> Output
    Main --> Context
    Main --> SearchOutput
    Context --> Output
```

## Component Design

### OutputManager (output.py)

The unified output system supporting both rich terminal output and JSON mode.

```mermaid
classDiagram
    class OutputManager {
        +console: Console
        +json_mode: bool
        +progress: Progress
        +print(message: str)
        +print_success(message: str)
        +print_error(message: str)
        +print_warning(message: str)
        +create_progress() Progress
        +json_output(data: dict)
        +operation_context(name: str) OperationHandle
    }

    class OperationHandle {
        +output: OutputManager
        +name: str
        +start()
        +update(message: str)
        +complete()
        +fail(error: str)
    }

    class SearchResultEntry {
        +gmail_id: str
        +subject: str
        +from_addr: str
        +date: str
        +body_preview: str
    }

    OutputManager --> OperationHandle : creates
    OutputManager --> SearchResultEntry : formats
```

**Key Features:**
- Rich console output with colors, progress bars, status indicators
- JSON output mode (`--json`) for scripting and automation
- Progress tracking (uv-style spinners and progress bars)
- Actionable next-step suggestions on errors
- Operation contexts for start/update/complete tracking

### CommandContext (command_context.py)

Dependency injection container for CLI commands, providing consistent access to
shared resources across all commands.

```mermaid
classDiagram
    class CommandContext {
        +output: OutputManager
        +db_path: Path
        +json_mode: bool
        +verbose: bool
        +get_db_manager() DBManager
        +get_authenticator() GmailAuthenticator
        +get_client() GmailClient
        +handle_error(error: Exception)
    }

    CommandContext --> OutputManager : owns
    CommandContext --> DBManager : creates
    CommandContext --> GmailAuthenticator : creates
    CommandContext --> GmailClient : creates
```

**Key Features:**
- Lazy initialization of expensive resources
- Consistent error handling across commands
- Shared configuration (db path, verbosity, JSON mode)
- Clean resource cleanup on exit

### Search Output (_output_search.py)

Specialized formatting for search results with relevance highlighting.

```mermaid
flowchart LR
    SearchResults --> Formatter
    Formatter --> Table[Rich Table]
    Formatter --> JSON[JSON Output]

    subgraph Formatter["_output_search.py"]
        Format[format_results]
        Highlight[highlight_matches]
        Truncate[truncate_preview]
    end
```

## Data Flow

### Command Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant Main as __main__.py
    participant Ctx as CommandContext
    participant Output as OutputManager
    participant Core as core/

    User->>Main: gmailarchiver <command>
    Main->>Ctx: create context
    Ctx->>Output: initialize output

    alt --json flag
        Output->>Output: enable JSON mode
    end

    Main->>Output: create_progress()
    Main->>Core: execute operation
    Core->>Output: operation_context()
    Output-->>User: progress updates
    Core-->>Main: result

    alt success
        Main->>Output: print_success()
    else failure
        Main->>Output: print_error()
        Output->>Output: suggest_next_steps()
    end
```

### Output Mode Decision

```mermaid
flowchart TD
    Input[Command Output] --> Check{JSON Mode?}
    Check -->|Yes| JSON[json_output()]
    Check -->|No| Rich[Rich Console]

    Rich --> Table[Tables]
    Rich --> Progress[Progress Bars]
    Rich --> Status[Status Messages]

    JSON --> Structured[Structured Data]
    Structured --> Stdout[stdout]
```

## Integration Points

### Dependencies (imports from other layers)

```python
# From data layer
from gmailarchiver.data.db_manager import DBManager

# From connectors layer
from gmailarchiver.connectors.auth import GmailAuthenticator
from gmailarchiver.connectors.gmail_client import GmailClient

# From core layer
from gmailarchiver.core.search import SearchResults
```

### Dependents (imported by)

```python
# Entry point
from gmailarchiver.cli.output import OutputManager
from gmailarchiver.cli.command_context import CommandContext

# Core layer (for progress reporting)
from gmailarchiver.cli.output import OperationHandle
```

## Design Decisions

### Why Separate CLI Layer?

1. **Separation of Concerns**: CLI-specific logic (formatting, progress, user interaction)
   is isolated from business logic
2. **Testability**: Core logic can be tested without CLI dependencies
3. **Alternative Interfaces**: Future GUI or API could reuse core without CLI code
4. **JSON Mode**: Clean implementation of dual output modes

### OutputManager in CLI vs Shared

OutputManager is in CLI because:
- It's fundamentally about user output (Rich console, JSON)
- Core components receive `OperationHandle` for progress, not full OutputManager
- This maintains the boundary between business logic and presentation

### Entry Point Location

`__main__.py` remains at package root because:
- Python convention for `python -m gmailarchiver`
- Typer app definition is the natural entry point
- CLI layer provides supporting infrastructure
