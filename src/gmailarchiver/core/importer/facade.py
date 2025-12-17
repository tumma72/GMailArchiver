"""Facade for archive importing with clean orchestration.

This module provides the public API for importing mbox archives.
It coordinates internal modules (scanner, reader, lookup, writer).
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gmailarchiver.core.importer._reader import MboxReader
from gmailarchiver.core.importer._scanner import FileScanner
from gmailarchiver.core.importer._writer import DatabaseWriter, WriteResult
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.shared.protocols import ProgressReporter

if TYPE_CHECKING:
    from gmailarchiver.connectors.gmail_client import GmailClient

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of scanning an archive for messages to import."""

    archive_file: str
    total_messages: int
    new_messages: int  # Messages not in database
    duplicate_messages: int  # Messages already in database
    # Internal: list of (rfc_message_id, offset, length) for new messages
    messages_to_import: list[tuple[str, int, int]] = field(default_factory=list)


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
        db_manager: DBManager,
        gmail_client: GmailClient | None = None,
    ) -> None:
        """Initialize importer facade.

        Args:
            db_manager: Database manager for data operations
            gmail_client: Optional GmailClient for looking up real Gmail IDs
        """
        self.db_manager = db_manager
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

    async def scan_archive(
        self,
        archive_path: str | Path,
        progress: ProgressReporter | None = None,
        skip_duplicates: bool = True,
    ) -> ScanResult:
        """Scan archive and identify messages to import (Phase 1).

        Fast scan that extracts RFC Message-IDs and compares with database.
        Does NOT connect to Gmail - that's done in import phase if needed.

        Args:
            archive_path: Path to mbox archive file
            progress: Optional progress reporter for status updates
            skip_duplicates: If True, filter out messages already in database

        Returns:
            ScanResult with counts and list of messages to import

        Raises:
            FileNotFoundError: If archive file doesn't exist
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        scanner = FileScanner()
        reader = MboxReader()

        # Decompress if needed
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path)

        try:
            # Fast scan: extract RFC Message-IDs with offsets
            # Note: reader expects raw callback, so we pass None for now
            # Progress reporting can be added when reader is refactored
            scanned_messages = reader.scan_rfc_message_ids(mbox_path, None)
            total_messages = len(scanned_messages)

            if skip_duplicates:
                # Get existing IDs from database (single query)
                existing_ids = await self.db_manager.get_all_rfc_message_ids()

                # Identify new messages (not in database)
                messages_to_import: list[tuple[str, int, int]] = []
                for rfc_id, offset, length in scanned_messages:
                    if rfc_id not in existing_ids:
                        messages_to_import.append((rfc_id, offset, length))

                return ScanResult(
                    archive_file=str(archive_path),
                    total_messages=total_messages,
                    new_messages=len(messages_to_import),
                    duplicate_messages=total_messages - len(messages_to_import),
                    messages_to_import=messages_to_import,
                )
            else:
                # When skip_duplicates=False, import all messages
                return ScanResult(
                    archive_file=str(archive_path),
                    total_messages=total_messages,
                    new_messages=total_messages,
                    duplicate_messages=0,
                    messages_to_import=scanned_messages,
                )

        finally:
            scanner.cleanup_temp_file(mbox_path, is_temp)

    async def import_archive(
        self,
        archive_path: str | Path,
        account_id: str = "default",
        skip_duplicates: bool = True,
        progress: ProgressReporter | None = None,
        scan_result: ScanResult | None = None,
    ) -> ImportResult:
        """Import single mbox archive into database.

        Multi-phase workflow:
        1. Scan mbox for RFC Message-IDs (if scan_result not provided)
        2. Compare with database to identify new messages
        3. Batch lookup Gmail IDs for new messages (if gmail_client provided)
        4. Import new messages to database

        Args:
            archive_path: Path to mbox archive file
            account_id: Account identifier (default: 'default')
            skip_duplicates: Skip messages that already exist (default: True)
            progress: Optional progress reporter for status updates
            scan_result: Pre-computed scan result (skips Phase 1 if provided)

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

        # Phase 1: Scan archive (or use pre-computed result)
        if scan_result is None:
            if progress:
                progress.info(f"Scanning archive: {archive_path.name}")
            scan_result = await self.scan_archive(archive_path, progress, skip_duplicates)

        # Early exit if nothing to import
        if scan_result.new_messages == 0:
            result.messages_skipped = scan_result.duplicate_messages
            result.execution_time_ms = (time.time() - start_time) * 1000
            if progress:
                progress.info("No new messages to import (all duplicates)")
            return result

        # Phase 2: Batch Gmail ID lookup (if client available)
        gmail_id_map: dict[str, str | None] = {}
        if self.gmail_client is not None:
            if progress:
                progress.info(
                    f"Looking up Gmail IDs for {len(scan_result.messages_to_import)} messages"
                )
            rfc_ids_to_lookup = [msg[0] for msg in scan_result.messages_to_import]
            # Note: gmail_client expects raw callback, progress reporting to be added later
            gmail_id_map = await self.gmail_client.search_by_rfc_message_ids_batch(
                rfc_ids_to_lookup,
                progress_callback=None,
            )
            result.gmail_ids_found = sum(1 for v in gmail_id_map.values() if v is not None)
            result.gmail_ids_not_found = len(gmail_id_map) - result.gmail_ids_found
            if progress:
                progress.info(
                    f"Found {result.gmail_ids_found} Gmail IDs, "
                    f"{result.gmail_ids_not_found} not found"
                )

        # Phase 3: Import messages to database
        scanner = FileScanner()
        reader = MboxReader()
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path)

        try:
            writer = DatabaseWriter(self.db_manager)
            await writer.load_existing_ids()

            # Build a map of offset -> (rfc_id, length) for quick lookup
            offset_map = {
                offset: (rfc_id, length)
                for rfc_id, offset, length in scan_result.messages_to_import
            }

            # Read messages and import only those in our import list
            total_to_import = len(scan_result.messages_to_import)
            imported_count = 0

            for mbox_msg in reader.read_messages(mbox_path, str(archive_path)):
                if mbox_msg.offset not in offset_map:
                    continue  # Skip messages not in our import list

                rfc_message_id, length = offset_map[mbox_msg.offset]
                imported_count += 1

                try:
                    # Get Gmail ID from our batch lookup
                    gmail_id = gmail_id_map.get(rfc_message_id)

                    # Extract full metadata
                    metadata = reader.extract_metadata(
                        msg=mbox_msg.message,
                        archive_path=str(archive_path),
                        offset=mbox_msg.offset,
                        length=mbox_msg.length,
                        account_id=account_id,
                        gmail_id=gmail_id,
                    )

                    # Write to database
                    write_result = await writer.write_message(metadata, skip_duplicates)

                    if write_result == WriteResult.IMPORTED:
                        result.messages_imported += 1
                        if progress:
                            gmail_status = (
                                f"Gmail ID: {gmail_id[:8]}..." if gmail_id else "No Gmail ID"
                            )
                            progress.info(
                                f"[{imported_count}/{total_to_import}] Imported ({gmail_status})"
                            )
                    elif write_result == WriteResult.SKIPPED:
                        result.messages_skipped += 1
                    else:
                        result.messages_failed += 1
                        if progress:
                            progress.warning(f"[{imported_count}/{total_to_import}] Database error")

                except Exception as e:
                    result.messages_failed += 1
                    result.errors.append(f"Message {rfc_message_id}: {str(e)}")
                    if progress:
                        progress.error(f"[{imported_count}/{total_to_import}] Error: {str(e)}")

            # Add duplicates from scan phase
            result.messages_skipped += scan_result.duplicate_messages

            # Record archive run if any messages were imported
            if result.messages_imported > 0:
                await writer.record_archive_run(
                    archive_file=str(archive_path),
                    messages_count=result.messages_imported,
                    account_id=account_id,
                )

            # Commit all changes
            await self.db_manager.commit()

        finally:
            scanner.cleanup_temp_file(mbox_path, is_temp)

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    async def import_multiple(
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
                file_result = await self.import_archive(
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
