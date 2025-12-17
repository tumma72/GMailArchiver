"""Shared utilities with no internal dependencies.

This layer contains pure utility functions and validators that can be
used by all other layers. It has no dependencies on other gmailarchiver modules.

Components:
- utils: Date/time parsing, formatting, list utilities
- input_validator: User input validation and sanitization
- path_validator: File path security (traversal prevention)
- protocols: Cross-layer communication protocols
"""

from .input_validator import (
    InvalidInputError,
    sanitize_filename,
    validate_age_expression,
    validate_compression_format,
    validate_gmail_query,
)
from .path_validator import (
    PathTraversalError,
    validate_file_path,
    validate_file_path_for_writing,
)
from .protocols import (
    NoOpTaskHandle,
    NoOpTaskSequence,
    ProgressReporter,
    TaskHandle,
    TaskSequence,
)
from .utils import chunk_list, datetime_to_gmail_query, format_bytes, parse_age

__all__ = [
    # utils
    "parse_age",
    "datetime_to_gmail_query",
    "format_bytes",
    "chunk_list",
    # input_validator
    "InvalidInputError",
    "validate_gmail_query",
    "validate_age_expression",
    "validate_compression_format",
    "sanitize_filename",
    # path_validator
    "PathTraversalError",
    "validate_file_path",
    "validate_file_path_for_writing",
    # protocols
    "ProgressReporter",
    "TaskSequence",
    "TaskHandle",
    "NoOpTaskSequence",
    "NoOpTaskHandle",
]
