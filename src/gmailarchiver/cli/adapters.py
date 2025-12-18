"""CLI adapters implementing shared protocols.

DEPRECATED: Import from gmailarchiver.cli.ui instead.

This module re-exports from the new location for backward compatibility.
"""

# Re-export from new location
from gmailarchiver.cli.ui.adapters import CLIProgressAdapter

__all__ = ["CLIProgressAdapter"]
