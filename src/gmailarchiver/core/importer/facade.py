"""Facade for archive importing with clean orchestration.

This module provides the public API for importing mbox archives.
It coordinates internal modules (scanner, reader, lookup, writer).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gmailarchiver.core.importer._gmail_lookup import GmailLookup
from gmailarchiver.core.importer._reader import MboxReader
from gmailarchiver.core.importer._scanner import FileScanner
from gmailarchiver.core.importer._writer import DatabaseWriter, WriteResult
from gmailarchiver.data.db_manager import DBManager

if TYPE_CHECKING:
    from gmailarchiver.connectors.gmail_client import GmailClient

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of importing a single archive."""

    archive_file: str
    messages_imported: int
    messages_skipped: int
    messages_failed: int
    execution_time_ms: float
    gmail_ids_found: int = 0
    gmail_ids_not_found: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class MultiImportResult:
    """Result of importing multiple archives."""

    total_files: int
    total_messages_imported: int
    total_messages_skipped: int
    total_messages_failed: int
    total_gmail_ids_found: int = 0
    total_gmail_ids_not_found: int = 0
    file_results: list[ImportResult] = field(default_factory=list)


class ImporterFacade:
    """Public facade for mbox archive importing.

    Provides clean API for importing mbox archives into the database
    with support for compression, deduplication, and Gmail ID lookups.
    """

    def __init__(
        self,
        state_db_path: str,
        gmail_client: GmailClient | None = None,
    ) -> None:
        """Initialize importer facade.

        Args:
            state_db_path: Path to SQLite database file
            gmail_client: Optional GmailClient for looking up real Gmail IDs
        """
        self.state_db_path = state_db_path
        self.gmail_client = gmail_client

    def count_messages(self, archive_path: str | Path) -> int:
        """Count messages in an mbox archive without importing.

        Args:
            archive_path: Path to mbox archive file

        Returns:
            Number of messages in the archive
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            return 0

        # Decompress if needed
        scanner = FileScanner()
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path)

        try:
            reader = MboxReader()
            return reader.count_messages(mbox_path)
        finally:
            scanner.cleanup_temp_file(mbox_path, is_temp)

    def import_archive(
        self,
        archive_path: str | Path,
        account_id: str = "default",
        skip_duplicates: bool = True,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> ImportResult:
        """Import single mbox archive into database.

        Parses mbox file, extracts metadata, calculates byte offsets,
        and populates database with all required fields.

        Args:
            archive_path: Path to mbox archive file
            account_id: Account identifier (default: 'default')
            skip_duplicates: Skip messages that already exist (default: True)
            progress_callback: Optional callback(current, total, status) for progress

        Returns:
            ImportResult with statistics and errors

        Raises:
            FileNotFoundError: If archive file doesn't exist
            RuntimeError: If decompression fails
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        result = ImportResult(
            archive_file=str(archive_path),
            messages_imported=0,
            messages_skipped=0,
            messages_failed=0,
            execution_time_ms=0.0,
        )

        start_time = time.time()

        # Initialize modules
        scanner = FileScanner()
        reader = MboxReader()
        gmail_lookup = GmailLookup(self.gmail_client)

        # Decompress if needed
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path)

        try:
            # Open database with context manager
            with DBManager(self.state_db_path, validate_schema=False, auto_create=True) as db:
                # Initialize database writer
                writer = DatabaseWriter(db)
                writer.load_existing_ids()

                # Read messages with offset tracking
                messages = list(reader.read_messages(mbox_path, str(archive_path)))
                total_messages = len(messages)

                # Process each message
                for msg_index, mbox_msg in enumerate(messages):
                    try:
                        # Extract RFC Message-ID
                        rfc_message_id = reader.extract_rfc_message_id(mbox_msg.message)

                        # Skip duplicates early if enabled
                        if skip_duplicates and writer.is_duplicate(rfc_message_id):
                            result.messages_skipped += 1
                            if progress_callback:
                                progress_callback(
                                    msg_index + 1, total_messages, "Skipped duplicate"
                                )
                            continue

                        # Look up Gmail ID if enabled
                        gmail_id = None
                        if gmail_lookup.is_enabled():
                            if progress_callback:
                                progress_callback(
                                    msg_index + 1, total_messages, "Looking up Gmail ID..."
                                )
                            lookup_result = gmail_lookup.lookup_gmail_id(rfc_message_id)
                            gmail_id = lookup_result.gmail_id
                            if lookup_result.found:
                                result.gmail_ids_found += 1
                            else:
                                result.gmail_ids_not_found += 1

                        # Extract metadata
                        metadata = reader.extract_metadata(
                            msg=mbox_msg.message,
                            archive_path=str(archive_path),
                            offset=mbox_msg.offset,
                            length=mbox_msg.length,
                            account_id=account_id,
                            gmail_id=gmail_id,
                        )

                        # Write to database
                        write_result = writer.write_message(metadata, skip_duplicates)

                        if write_result == WriteResult.IMPORTED:
                            result.messages_imported += 1
                            if progress_callback:
                                gmail_status = (
                                    f"Gmail ID: {gmail_id[:8]}..." if gmail_id else "No Gmail ID"
                                )
                                progress_callback(
                                    msg_index + 1, total_messages, f"Imported ({gmail_status})"
                                )
                        elif write_result == WriteResult.SKIPPED:
                            result.messages_skipped += 1
                            if progress_callback:
                                progress_callback(
                                    msg_index + 1, total_messages, "Skipped duplicate"
                                )
                        else:  # FAILED
                            result.messages_failed += 1
                            if progress_callback:
                                progress_callback(msg_index + 1, total_messages, "DB error")

                    except Exception as e:
                        result.messages_failed += 1
                        error_msg = f"Message {msg_index}: {str(e)}"
                        result.errors.append(error_msg)
                        if progress_callback:
                            progress_callback(msg_index + 1, total_messages, "Error")

                # Record archive run if any messages were imported
                if result.messages_imported > 0:
                    writer.record_archive_run(
                        archive_file=str(archive_path),
                        messages_count=result.messages_imported,
                        account_id=account_id,
                    )

        finally:
            # Clean up temporary file if created
            scanner.cleanup_temp_file(mbox_path, is_temp)

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def import_multiple(
        self,
        pattern: str,
        account_id: str = "default",
        skip_duplicates: bool = True,
    ) -> MultiImportResult:
        """Import multiple archives using glob pattern.

        Args:
            pattern: Glob pattern for archive files (e.g., "archives/*.mbox")
            account_id: Account identifier (default: 'default')
            skip_duplicates: Skip messages that already exist (default: True)

        Returns:
            MultiImportResult with aggregate statistics
        """
        scanner = FileScanner()
        files = scanner.scan_pattern(pattern)

        result = MultiImportResult(
            total_files=len(files),
            total_messages_imported=0,
            total_messages_skipped=0,
            total_messages_failed=0,
        )

        for file_path in files:
            try:
                file_result = self.import_archive(
                    file_path, account_id=account_id, skip_duplicates=skip_duplicates
                )

                result.file_results.append(file_result)
                result.total_messages_imported += file_result.messages_imported
                result.total_messages_skipped += file_result.messages_skipped
                result.total_messages_failed += file_result.messages_failed
                result.total_gmail_ids_found += file_result.gmail_ids_found
                result.total_gmail_ids_not_found += file_result.gmail_ids_not_found

            except Exception as e:
                # Record failure for this file
                file_result = ImportResult(
                    archive_file=str(file_path),
                    messages_imported=0,
                    messages_skipped=0,
                    messages_failed=0,
                    execution_time_ms=0.0,
                    errors=[f"Failed to import: {str(e)}"],
                )
                result.file_results.append(file_result)

        return result
