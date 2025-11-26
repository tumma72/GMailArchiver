# Shared Layer

**Current Status:** Complete
**Last Updated:** 2025-11-26

Pure utility functions and validators with no internal dependencies.

## Contents

| File | Purpose | Functions/Classes |
|------|---------|-------------------|
| `utils.py` | Date/time utilities | `parse_age`, `datetime_to_gmail_query`, `format_bytes`, `chunk_list` |
| `input_validator.py` | Input validation | `validate_gmail_query`, `validate_age_expression`, `validate_compression_format`, `sanitize_filename`, `InvalidInputError` |
| `path_validator.py` | Path security | `validate_file_path`, `validate_file_path_for_writing`, `PathTraversalError` |

## Dependencies

- Python standard library (`re`, `datetime`, `pathlib`)
- `python-dateutil` (for `relativedelta` in `utils.py`)

No dependencies on other gmailarchiver modules.

## Usage

```python
# Import from shared layer
from gmailarchiver.shared.utils import parse_age, format_bytes
from gmailarchiver.shared.input_validator import validate_gmail_query
from gmailarchiver.shared.path_validator import validate_file_path

# Or import via __init__.py
from gmailarchiver.shared import parse_age, validate_gmail_query, PathTraversalError
```

## Tests

Tests are in `tests/shared/`:

```bash
# Run shared layer tests only
uv run pytest tests/shared/ -v

# Current: 130 tests, all passing
```

## Notes

- All functions are pure (no side effects) except `validate_file_path_for_writing` which may create directories
- All functions are thread-safe (no shared state)
- Input validators raise exceptions immediately on invalid input (fail-fast)
