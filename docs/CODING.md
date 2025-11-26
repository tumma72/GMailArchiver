# Coding Guidelines

**Last Updated:** 2025-11-26

This document defines the coding standards, patterns, and practices for the Gmail Archiver codebase.

---

## Table of Contents

- [Code Style](#code-style)
- [Type System](#type-system)
- [Module Structure](#module-structure)
- [Error Handling](#error-handling)
- [Database Operations](#database-operations)
- [Patterns and Idioms](#patterns-and-idioms)
- [Do's and Don'ts](#dos-and-donts)

---

## Code Style

### Formatting

All code is formatted with **ruff** using these settings:

```toml
[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

| Rule Set | Purpose |
|----------|---------|
| E | pycodestyle errors |
| F | pyflakes |
| I | isort (import sorting) |
| N | pep8-naming |
| W | pycodestyle warnings |
| UP | pyupgrade (modern Python) |

### Running Code Quality Checks

```bash
# Lint check (no changes)
uv run ruff check .

# Lint with auto-fix
uv run ruff check . --fix

# Format code
uv run ruff format .

# Type check (strict mode)
uv run mypy gmailarchiver

# Run all checks before commit
uv run ruff check . && uv run mypy gmailarchiver && uv run pytest
```

---

## Type System

### Strict Typing

All code uses **strict mypy** type checking:

```toml
[tool.mypy]
python_version = "3.14"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

### Type Annotation Patterns

```python
# Use future annotations for forward references
from __future__ import annotations

# Standard library types
from collections.abc import Generator, Callable, Sequence
from pathlib import Path
from typing import Any

# Function signatures - always typed
def process_message(
    msg_id: str,
    archive_file: Path,
    compress: bool = False,
) -> tuple[int, int]:
    """Returns (offset, length)."""
    ...

# Optional values - use union with None
def get_message(msg_id: str) -> dict[str, Any] | None:
    ...

# Generator functions
def iter_messages(archive: Path) -> Generator[Message]:
    ...

# Callbacks
ProgressCallback = Callable[[int, int, str], None]

def import_archive(
    path: Path,
    progress_callback: ProgressCallback | None = None,
) -> ImportResult:
    ...
```

### Return Type Conventions

| Pattern | When to Use |
|---------|-------------|
| `-> None` | Functions that don't return meaningful values |
| `-> T | None` | Functions that may fail to find/produce a result |
| `-> T` | Functions that always return a value (may raise on error) |
| `-> NoReturn` | Functions that always raise or exit |

---

## Module Structure

### Module Docstring

Every module begins with a docstring explaining its purpose:

```python
"""Centralized database operations manager for Gmail Archiver.

This module provides the DBManager class which serves as the single source of truth
for all database operations, addressing critical architectural issues:
- SQL queries scattered across 8+ modules
- No transaction coordination
- Missing audit trails

ALL database operations MUST go through this class.
No direct SQL queries allowed in other modules.
"""
```

### Import Order

Imports are organized by ruff/isort in this order:

```python
# 1. Future imports
from __future__ import annotations

# 2. Standard library
import logging
import sqlite3
from pathlib import Path
from typing import Any

# 3. Third-party packages
import typer
from rich.progress import Progress

# 4. Local imports (relative)
from .db_manager import DBManager
from .output import OutputManager
```

### Module-Level Logger

Each module defines its own logger:

```python
import logging

logger = logging.getLogger(__name__)
```

### Constants

Constants use `UPPER_SNAKE_CASE`:

```python
DEFAULT_BATCH_SIZE = 10
MAX_RETRIES = 5
SUPPORTED_COMPRESSIONS = frozenset({"gzip", "lzma", "zstd"})
```

---

## Error Handling

### Custom Exception Classes

Define custom exceptions for domain-specific errors:

```python
class DBManagerError(Exception):
    """Raised when database operations fail."""
    pass


class SchemaValidationError(DBManagerError):
    """Raised when schema validation fails."""
    pass


class IntegrityError(Exception):
    """Raised when mbox/database consistency checks fail."""
    pass
```

### Exception Hierarchy

```
Exception
├── DBManagerError
│   └── SchemaValidationError
├── HybridStorageError
│   └── IntegrityError
└── ValidationError
    └── PathValidationError
```

### Error Handling Pattern

```python
def connect_database(db_path: Path) -> sqlite3.Connection:
    """Connect to database with proper error handling."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logger.error(f"Failed to connect to database: {e}")
        raise DBManagerError(f"Cannot open database: {db_path}") from e
```

### Logging Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed diagnostic info (e.g., "Pre-loaded 16,132 RFC IDs") |
| `INFO` | Normal operation milestones (e.g., "Migration complete") |
| `WARNING` | Recoverable issues (e.g., "Token expired, refreshing") |
| `ERROR` | Operation failures (e.g., "Database update failed") |
| `CRITICAL` | System failures requiring immediate attention |

---

## Database Operations

### Parameterized Queries Only

**NEVER** use string formatting for SQL. Always use parameterized queries:

```python
# DO: Parameterized query (safe)
cursor.execute(
    "SELECT * FROM messages WHERE gmail_id = ?",
    (gmail_id,)
)

# DO: Named parameters for complex queries
cursor.execute("""
    INSERT INTO messages (gmail_id, subject, archive_file)
    VALUES (:gmail_id, :subject, :archive_file)
""", {
    "gmail_id": msg.gmail_id,
    "subject": msg.subject,
    "archive_file": str(archive_path),
})

# DON'T: String formatting (SQL injection risk!)
cursor.execute(f"SELECT * FROM messages WHERE gmail_id = '{gmail_id}'")
```

### Transaction Pattern

Use context managers for transactions:

```python
@contextmanager
def _transaction(self) -> Generator[None]:
    """Transaction with automatic rollback on error."""
    try:
        yield
        self.conn.commit()
    except Exception as e:
        self.conn.rollback()
        logger.error(f"Transaction rolled back: {e}")
        raise

# Usage
with self._transaction():
    self.conn.execute("INSERT INTO messages ...")
    self.conn.execute("UPDATE archive_runs ...")
```

### Row Factory

Always enable row factory for dict-like access:

```python
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row  # Enables row["column_name"]
```

---

## Patterns and Idioms

### Context Manager Pattern

Classes that manage resources implement the context manager protocol:

```python
class DBManager:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.conn = self._connect()

    def __enter__(self) -> DBManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
```

### Dataclasses for Results

Use dataclasses for structured return values:

```python
from dataclasses import dataclass

@dataclass
class ImportResult:
    """Result of importing an archive file."""
    archive_file: str
    messages_imported: int
    messages_skipped: int
    messages_failed: int
    errors: list[str]

@dataclass
class ConsolidationResult:
    """Result of consolidating multiple archives."""
    output_file: str
    source_files: list[str]
    total_messages: int
    duplicates_removed: int
```

### Factory Pattern

Use factory functions or methods for complex object creation:

```python
@classmethod
def from_mbox_message(cls, msg: mailbox.mboxMessage) -> MessageMetadata:
    """Create MessageMetadata from an mbox message."""
    return cls(
        message_id=msg.get("Message-ID", ""),
        subject=msg.get("Subject", ""),
        from_addr=msg.get("From", ""),
        date=parse_date(msg.get("Date", "")),
    )
```

### Generator Pattern

Use generators for memory-efficient iteration:

```python
def iter_archive_messages(
    archive_path: Path,
) -> Generator[tuple[int, mailbox.mboxMessage]]:
    """Iterate archive messages with offsets.

    Yields:
        (offset, message) tuples
    """
    with open(archive_path, "rb") as f:
        mbox = mailbox.mbox(str(archive_path))
        try:
            for key in mbox.keys():
                offset = f.tell()
                yield offset, mbox[key]
        finally:
            mbox.close()
```

### Callback Pattern

Use optional callbacks for progress reporting:

```python
ProgressCallback = Callable[[int, int, str], None]

def import_archive(
    path: Path,
    progress_callback: ProgressCallback | None = None,
) -> ImportResult:
    """Import archive with optional progress reporting."""
    for i, msg in enumerate(messages):
        # Process message...
        if progress_callback:
            progress_callback(i + 1, total, f"Importing {msg.subject[:30]}")
```

---

## Do's and Don'ts

### Do's

| Practice | Rationale |
|----------|-----------|
| Use type hints everywhere | Catches bugs early, improves IDE support |
| Use context managers for resources | Ensures cleanup even on exceptions |
| Use parameterized SQL queries | Prevents SQL injection |
| Use dataclasses for structured data | Clear, immutable, self-documenting |
| Use generators for large datasets | Memory efficient |
| Log at appropriate levels | Enables debugging without noise |
| Write module docstrings | Documents purpose and responsibilities |
| Use `from __future__ import annotations` | Enables forward references |

### Don'ts

| Anti-Pattern | Why It's Bad | Alternative |
|--------------|--------------|-------------|
| String formatting in SQL | SQL injection vulnerability | Use parameterized queries |
| Bare `except:` clauses | Catches system exceptions like KeyboardInterrupt | Catch specific exceptions |
| Global mutable state | Hard to test, race conditions | Pass dependencies explicitly |
| `print()` statements | Not suppressible, no levels | Use `logging` module |
| Magic numbers | Unclear meaning | Define named constants |
| Long functions (>50 lines) | Hard to test and maintain | Extract helper functions |
| Deeply nested code (>3 levels) | Hard to follow | Use early returns, extract functions |
| Ignoring return values | May miss errors | Handle or explicitly ignore with `_` |

### Code Examples

```python
# DON'T: Bare except
try:
    process_message(msg)
except:  # Catches EVERYTHING including Ctrl+C
    pass

# DO: Specific exceptions
try:
    process_message(msg)
except MessageParseError as e:
    logger.warning(f"Skipping malformed message: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise

# DON'T: Magic numbers
if retry_count > 5:
    raise TooManyRetries()

# DO: Named constants
MAX_RETRIES = 5
if retry_count > MAX_RETRIES:
    raise TooManyRetries(f"Exceeded {MAX_RETRIES} retries")

# DON'T: Deep nesting
def process(items):
    for item in items:
        if item.valid:
            if item.type == "email":
                if not item.archived:
                    # Finally do something...

# DO: Early returns
def process(items):
    for item in items:
        if not item.valid:
            continue
        if item.type != "email":
            continue
        if item.archived:
            continue
        # Do something with clean item
```

---

## Version Compatibility

### Python 3.14+ Features

The codebase uses Python 3.14+ features:

| Feature | Usage |
|---------|-------|
| Native zstd compression | `compression.zstd` module |
| Union syntax (`X \| Y`) | Type hints |
| Match statements | Pattern matching (where appropriate) |

### Third-Party Compatibility

| Package | Minimum Version | Notes |
|---------|-----------------|-------|
| typer | 0.9.0 | CLI framework |
| rich | 13.0.0 | Terminal UI |
| google-api-python-client | 2.100.0 | Gmail API |

---

## References

- [PEP 8 - Style Guide](https://peps.python.org/pep-0008/)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [mypy Documentation](https://mypy.readthedocs.io/)
