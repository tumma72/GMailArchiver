"""Common workflow steps library.

This module provides reusable steps for composing workflows:

**Mbox Steps:**
- ScanMboxStep: Scan mbox files for messages
- ValidateArchiveStep: Validate archive integrity

**Database Steps:**
- CheckDuplicatesStep: Check for duplicate messages in database
- RecordMetadataStep: Write message metadata to database

**Gmail Steps:**
- ScanGmailMessagesStep: List messages from Gmail matching criteria
- FilterGmailMessagesStep: Filter out already-archived messages
- DeleteGmailMessagesStep: Delete or trash messages from Gmail

**Write Steps:**
- WriteMessagesStep: Archive messages to mbox file

**Stats Steps:**
- GetArchiveStatsStep: Retrieve archive statistics

**Search Steps:**
- SearchMessagesStep: Search messages using full-text search
"""

# Mbox steps
# Database steps
from gmailarchiver.core.workflows.steps.filter import CheckDuplicatesStep

# Gmail steps
from gmailarchiver.core.workflows.steps.gmail import (
    DeleteGmailMessagesStep,
    FilterGmailMessagesStep,
    ScanGmailMessagesStep,
)
from gmailarchiver.core.workflows.steps.metadata import RecordMetadataStep
from gmailarchiver.core.workflows.steps.scan import ScanMboxStep

# Search steps
from gmailarchiver.core.workflows.steps.search import SearchMessagesStep

# Stats steps
from gmailarchiver.core.workflows.steps.stats import GetArchiveStatsStep
from gmailarchiver.core.workflows.steps.validate import ValidateArchiveStep

# Write steps
from gmailarchiver.core.workflows.steps.write import WriteMessagesStep

__all__ = [
    # Mbox
    "ScanMboxStep",
    "ValidateArchiveStep",
    # Database
    "CheckDuplicatesStep",
    "RecordMetadataStep",
    # Gmail
    "ScanGmailMessagesStep",
    "FilterGmailMessagesStep",
    "DeleteGmailMessagesStep",
    # Write
    "WriteMessagesStep",
    # Stats
    "GetArchiveStatsStep",
    # Search
    "SearchMessagesStep",
]
