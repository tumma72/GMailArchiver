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

**Doctor Steps:**
- DatabaseDiagnosticStep: Run database health diagnostics
- EnvironmentDiagnosticStep: Run environment health diagnostics
- SystemDiagnosticStep: Run system health diagnostics

**Verify Steps:**
- VerifyIntegrityStep: Run database integrity checks
- VerifyConsistencyStep: Run database-archive consistency checks
- VerifyOffsetsStep: Run mbox offset accuracy checks

**Migrate Steps:**
- DetectVersionStep: Detect current and target schema versions
- ValidateMigrationStep: Validate migration prerequisites
- CreateBackupStep: Create database backup before migration
- ExecuteMigrationStep: Execute the schema migration
- VerifyMigrationStep: Verify migration completed successfully

**Repair Steps:**
- DiagnoseStep: Run full diagnostics and identify issues
- AutoFixStep: Attempt to auto-fix fixable issues (with optional backfill)
- ValidateRepairStep: Re-validate after repair to confirm fixes

**Consolidate Steps:**
- LoadArchivesStep: Load and validate source archives
- MergeAndProcessStep: Merge and process archives with dedup/sort
- ValidateConsolidationStep: Validate consolidated archive integrity
"""

# Consolidate steps
from gmailarchiver.core.workflows.steps.consolidate import (
    LoadArchivesStep,
    MergeAndProcessStep,
    ValidateConsolidationStep,
)

# Database steps
# Doctor steps
from gmailarchiver.core.workflows.steps.doctor import (
    DatabaseDiagnosticStep,
    EnvironmentDiagnosticStep,
    SystemDiagnosticStep,
)
from gmailarchiver.core.workflows.steps.filter import CheckDuplicatesStep

# Gmail steps
from gmailarchiver.core.workflows.steps.gmail import (
    DeleteGmailMessagesStep,
    FilterGmailMessagesStep,
    ScanGmailMessagesStep,
)
from gmailarchiver.core.workflows.steps.metadata import RecordMetadataStep

# Migrate steps
from gmailarchiver.core.workflows.steps.migrate import (
    CreateBackupStep,
    DetectVersionStep,
    ExecuteMigrationStep,
    ValidateMigrationStep,
    VerifyMigrationStep,
)

# Repair steps
from gmailarchiver.core.workflows.steps.repair import (
    AutoFixStep,
    DiagnoseStep,
    ValidateRepairStep,
)

# Mbox steps
from gmailarchiver.core.workflows.steps.scan import ScanMboxStep

# Search steps
from gmailarchiver.core.workflows.steps.search import SearchMessagesStep

# Stats steps
from gmailarchiver.core.workflows.steps.stats import GetArchiveStatsStep
from gmailarchiver.core.workflows.steps.validate import ValidateArchiveStep

# Verify steps
from gmailarchiver.core.workflows.steps.verify import (
    VerifyConsistencyStep,
    VerifyIntegrityStep,
    VerifyOffsetsStep,
)

# Write steps
from gmailarchiver.core.workflows.steps.write import WriteMessagesStep

__all__ = [
    # Consolidate
    "LoadArchivesStep",
    "MergeAndProcessStep",
    "ValidateConsolidationStep",
    # Database
    "CheckDuplicatesStep",
    "RecordMetadataStep",
    # Doctor
    "DatabaseDiagnosticStep",
    "EnvironmentDiagnosticStep",
    "SystemDiagnosticStep",
    # Gmail
    "DeleteGmailMessagesStep",
    "FilterGmailMessagesStep",
    "ScanGmailMessagesStep",
    # Mbox
    "ScanMboxStep",
    "ValidateArchiveStep",
    # Migrate
    "CreateBackupStep",
    "DetectVersionStep",
    "ExecuteMigrationStep",
    "ValidateMigrationStep",
    "VerifyMigrationStep",
    # Repair
    "AutoFixStep",
    "DiagnoseStep",
    "ValidateRepairStep",
    # Search
    "SearchMessagesStep",
    # Stats
    "GetArchiveStatsStep",
    # Verify
    "VerifyConsistencyStep",
    "VerifyIntegrityStep",
    "VerifyOffsetsStep",
    # Write
    "WriteMessagesStep",
]
