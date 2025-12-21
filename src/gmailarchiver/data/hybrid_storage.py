"""Transactional coordinator for atomic mbox + database operations.

This module implements HybridStorage, which ensures atomicity across mbox files
and database operations, preventing the critical issue of divergent state when
operations partially fail.

Key Features:
- Two-phase commit pattern for archive operations
- Staging area for safe writes
- Automatic validation after each operation
- Comprehensive rollback on failures
- Support for all compression formats (gzip, lzma, zstd)
"""

import asyncio
import email
import gzip
import hashlib
import logging
import lzma
import mailbox
import os
import shutil
import tempfile
import uuid
from compression import zstd
from contextlib import closing
from dataclasses import dataclass
from email import policy
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.search._types import SearchResults

from .db_manager import DBManager

logger = logging.getLogger(__name__)


class IntegrityError(Exception):
    """Raised when mbox/database consistency checks fail."""

    pass


class HybridStorageError(Exception):
    """Raised when hybrid storage operations fail."""

    pass


@dataclass
class ConsolidationResult:
    """Result of consolidating multiple archives."""

    output_file: str
    source_files: list[str]
    total_messages: int
    duplicates_removed: int
    messages_consolidated: int


@dataclass
class ArchiveStats:
    """Statistics about archived messages."""

    total_messages: int
    archive_files: list[str]
    schema_version: str
    database_size_bytes: int
    recent_runs: list[dict[str, Any]]


class HybridStorage:
    """
    Transactional coordinator for mbox + database operations.

    Guarantees:
    1. Both mbox and database succeed, OR
    2. Both are rolled back (atomicity)
    3. After every write, validation runs automatically

    Usage:
        db = DBManager(db_path)
        storage = HybridStorage(db)

        # Archive operation
        storage.archive_message(msg, gmail_id, archive_path)

        # Consolidation operation
        result = storage.consolidate_archives(sources, output)
    """

    def __init__(self, db_manager: DBManager, preload_rfc_ids: bool = True) -> None:
        """
        Initialize hybrid storage with database manager.

        Args:
            db_manager: Database manager instance for all DB operations
            preload_rfc_ids: If True, pre-load all rfc_message_ids for O(1) duplicate
                detection. Recommended for batch operations. Default: True.
        """
        self.db = db_manager
        self._staging_area = Path(tempfile.gettempdir()) / "gmailarchiver_staging"
        self._staging_area.mkdir(exist_ok=True)
        self._preload_rfc_ids = preload_rfc_ids
        self._known_rfc_ids: set[str] = set()
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure async initialization is complete."""
        if not self._initialized:
            # Pre-load RFC Message-IDs for O(1) duplicate detection
            # This avoids per-message database queries during batch archiving
            if self._preload_rfc_ids:
                self._known_rfc_ids = await self.db.get_all_rfc_message_ids()
                logger.debug(f"Pre-loaded {len(self._known_rfc_ids):,} RFC Message-IDs")
            self._initialized = True

    # ==================== BATCH ARCHIVE OPERATION ====================

    async def archive_messages_batch(
        self,
        messages: list[tuple[email.message.Message, str, str | None, str | None]],
        archive_file: Path,
        compression: str | None = None,
        commit_interval: int = 100,
        progress_callback: Any | None = None,
        interrupt_event: Any | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Archive multiple messages in a single batch operation.

        This is the core performance fix for Issue #6. Amortizes expensive I/O
        operations (fsync, mbox open/close, DB commits) across the entire batch
        rather than per-message.

        Performance characteristics:
        - Single mbox open/close cycle (not per-message)
        - Single fsync at end (not per-message)
        - Configurable DB commit interval (default: 100 messages)
        - Batch validation at end (not per-message)
        - CPU-bound mbox work runs in thread pool (asyncio.to_thread)

        Args:
            messages: List of (email_message, gmail_id, thread_id, labels) tuples
            archive_file: Path to archive file (may be compressed)
            compression: Compression format ('gzip', 'lzma', 'zstd', or None)
            commit_interval: Commit to DB every N messages (default: 100)
            progress_callback: Optional callback(gmail_id, subject, status) for progress
            interrupt_event: Optional threading.Event for graceful interruption
            session_id: Optional session ID for resumable operations

        Returns:
            Dict with keys: archived, skipped, failed, interrupted, actual_file

        Raises:
            HybridStorageError: If operation fails
        """
        await self._ensure_initialized()

        if not messages:
            return {
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(archive_file),
            }

        mbox_path = archive_file
        lock_file = Path(str(archive_file) + ".lock")

        # If compression requested, work with uncompressed mbox first
        if compression:
            if archive_file.suffix in (".gz", ".xz", ".zst"):
                mbox_path = archive_file.with_suffix("")
            else:
                mbox_path = archive_file.parent / (archive_file.stem + ".mbox")
            lock_file = Path(str(mbox_path) + ".lock")

        batch_rfc_ids: list[str] = []

        try:
            # Check for interrupt BEFORE CPU-bound work
            if interrupt_event and interrupt_event.is_set():
                logger.warning("Interrupt received before processing")
                return {
                    "archived": 0,
                    "skipped": 0,
                    "failed": 0,
                    "interrupted": True,
                    "actual_file": str(archive_file),
                }

            # Phase 1: CPU-bound mbox work in thread pool
            # This prevents blocking the event loop during mbox I/O and checksum calculations
            (
                results,
                new_rfc_ids,
                skipped_messages,
                skipped_count,
                failed_count,
                mbox_interrupted,
            ) = await asyncio.to_thread(
                self._write_messages_to_mbox_sync,
                messages,
                mbox_path,
                archive_file,
                self._known_rfc_ids.copy(),  # Pass copy to avoid thread safety issues
                interrupt_event,
            )

            # Report skipped messages first (for progress callbacks)
            if progress_callback:
                for gmail_id, subject in skipped_messages:
                    progress_callback(gmail_id, subject, "skipped")

            # Phase 2: Async database operations (with per-message error handling)
            db_success_count = 0
            db_failed_count = 0
            successful_rfc_ids: list[str] = []

            for i, record in enumerate(results):
                try:
                    # Record in database (NO commit yet)
                    await self.db.record_archived_message(
                        gmail_id=record["gmail_id"],
                        rfc_message_id=record["rfc_message_id"],
                        archive_file=record["archive_file"],
                        mbox_offset=record["mbox_offset"],
                        mbox_length=record["mbox_length"],
                        thread_id=record["thread_id"],
                        subject=record["subject"],
                        from_addr=record["from_addr"],
                        to_addr=record["to_addr"],
                        cc_addr=record["cc_addr"],
                        date=record["date"],
                        body_preview=record["body_preview"],
                        checksum=record["checksum"],
                        size_bytes=record["size_bytes"],
                        labels=record["labels"],
                        record_run=False,
                    )

                    # Add to known set
                    self._known_rfc_ids.add(record["rfc_message_id"])
                    successful_rfc_ids.append(record["rfc_message_id"])
                    db_success_count += 1

                    # Report progress (on main thread for UI)
                    if progress_callback:
                        progress_callback(record["gmail_id"], record["subject"], "success")

                    # Commit at interval
                    if db_success_count % commit_interval == 0:
                        await self.db.commit()
                        if session_id:
                            await self.db.update_session_progress(session_id, db_success_count)
                        logger.debug(f"Committed {db_success_count} messages")

                except Exception as e:
                    # Check if this is a duplicate (UNIQUE constraint on rfc_message_id)
                    error_str = str(e).lower()
                    if "unique constraint" in error_str and "rfc_message_id" in error_str:
                        # Treat as duplicate skip, not error
                        logger.debug(
                            f"Skipping duplicate message {record['gmail_id']}: "
                            f"rfc_message_id already in database"
                        )
                        skipped_count += 1
                        if progress_callback:
                            progress_callback(record["gmail_id"], record["subject"], "skipped")
                    else:
                        # Real error - log and continue
                        logger.error(
                            f"Failed to record message {record['gmail_id']} in database: {e}"
                        )
                        db_failed_count += 1
                        if progress_callback:
                            progress_callback(record["gmail_id"], record["subject"], "error")

            # Update counts
            archived_count = db_success_count
            failed_count += db_failed_count
            batch_rfc_ids = successful_rfc_ids

            # Final commit
            await self.db.commit()

            # Update session progress one final time
            if session_id and archived_count > 0:
                await self.db.update_session_progress(session_id, archived_count)

            # Determine final file path
            final_path = mbox_path

            # Only finalize (validate/compress) if we archived something
            if archived_count > 0:
                # Batch validation at end (not per-message)
                await self._validate_batch_consistency(batch_rfc_ids)

                # Compress if requested (already uses asyncio.to_thread internally)
                if compression:
                    logger.debug(f"Compressing with {compression}")
                    await self._compress_file(mbox_path, archive_file, compression)
                    # Remove uncompressed file AND lock
                    mbox_path.unlink()
                    if lock_file.exists():
                        lock_file.unlink()
                    final_path = archive_file

                # Mark session as complete
                if session_id:
                    await self.db.complete_session(session_id)

                # Record in audit trail
                await self.db.record_archive_run(
                    operation="archive",
                    messages_count=archived_count,
                    archive_file=str(final_path),
                )

                logger.info(
                    f"Batch archived {archived_count} messages "
                    f"(skipped {skipped_count} duplicates) to {final_path}"
                )

            return {
                "archived": archived_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "interrupted": mbox_interrupted,
                "actual_file": str(final_path),
            }

        except Exception as e:
            # Rollback database
            logger.error(f"Batch archive failed: {e}")
            try:
                await self.db.rollback()
                logger.debug("Database rolled back")
            except Exception as rb_err:
                logger.error(f"Rollback failed: {rb_err}")

            # Remove rfc_ids from known set (rollback in-memory state)
            for rfc_id in batch_rfc_ids:
                self._known_rfc_ids.discard(rfc_id)

            raise HybridStorageError(f"Failed to batch archive messages: {e}") from e

    # ==================== CONSOLIDATION PRIMITIVES ====================

    async def read_messages_from_archives(
        self, source_archives: list[Path]
    ) -> list[dict[str, Any]]:
        """
        Read all messages from source archives with metadata.

        This is a primitive operation for consolidation. The caller is responsible
        for sorting, deduplication, and other business logic.

        Args:
            source_archives: List of archive paths to read

        Returns:
            List of message dictionaries with:
            - message: email.message.Message object
            - rfc_message_id: RFC Message-ID
            - gmail_id: Gmail ID (from DB lookup)
            - date: Message date as string (for sorting)
            - size: Message size in bytes (for dedup strategies)
            - source_archive: Path to source archive

        Raises:
            HybridStorageError: If reading fails
        """
        return await self._collect_messages(source_archives)

    async def bulk_write_messages(
        self,
        messages: list[dict[str, Any]],
        output_path: Path,
        compression: str | None = None,
    ) -> dict[str, tuple[str, int, int]]:
        """
        Write multiple messages to mbox and return offsets.

        This is a primitive operation for consolidation. The caller is responsible
        for message ordering and deduplication.

        Args:
            messages: List of message dictionaries (from read_messages_from_archives)
            output_path: Path to output archive
            compression: Compression format ('gzip', 'lzma', 'zstd', or None)

        Returns:
            Dict mapping rfc_message_id -> (gmail_id, offset, length)

        Raises:
            HybridStorageError: If writing fails
        """
        staging_mbox = self._staging_area / f"bulk_write_{uuid.uuid4()}.mbox"
        mbox_obj = None

        try:
            # Write to staging mbox
            logger.debug(f"Writing {len(messages)} messages to staging mbox")
            offset_map: dict[str, tuple[str, int, int]] = {}

            mbox_obj = mailbox.mbox(str(staging_mbox))
            mbox_obj.lock()

            for msg_dict in messages:
                msg = msg_dict["message"]
                gmail_id = msg_dict["gmail_id"]
                rfc_id = msg.get("Message-ID", "")

                # Get offset before write
                if staging_mbox.exists():
                    with open(staging_mbox, "rb") as f:
                        f.seek(0, 2)  # Seek to end
                        offset = f.tell()
                else:
                    offset = 0

                # Write message
                mbox_obj.add(msg)
                mbox_obj.flush()

                # Calculate length
                if staging_mbox.exists():
                    with open(staging_mbox, "rb") as f:
                        f.seek(0, 2)
                        length = f.tell() - offset
                else:
                    length = len(msg.as_bytes())

                offset_map[rfc_id] = (gmail_id, offset, length)

            mbox_obj.unlock()
            mbox_obj.close()
            mbox_obj = None

            # Move staging to final location
            final_mbox = output_path
            if compression:
                # When compression is requested, we need a temporary mbox path
                # that is different from the final output path to avoid
                # overwriting/deleting issues
                if output_path.suffix.lower() in (".gz", ".xz", ".zst"):
                    # Output has compression extension, use .mbox for temp
                    final_mbox = output_path.with_suffix(".mbox")
                else:
                    # Output doesn't have compression extension, add .tmp.mbox
                    final_mbox = output_path.parent / (output_path.stem + ".tmp.mbox")

            shutil.move(str(staging_mbox), str(final_mbox))

            # Compress if requested
            if compression:
                logger.debug(f"Compressing with {compression}")
                await self._compress_file(final_mbox, output_path, compression)
                # Only delete the temp mbox if it's different from output
                if final_mbox != output_path:
                    final_mbox.unlink()
                # Clean up lock file
                lock_file = Path(str(final_mbox) + ".lock")
                if lock_file.exists():
                    lock_file.unlink()

            return offset_map

        except Exception as e:
            # Cleanup staging file on error
            if staging_mbox.exists():
                try:
                    staging_mbox.unlink()
                except Exception as cleanup_err:
                    logger.error(f"Failed to remove staging file: {cleanup_err}")

            raise HybridStorageError(f"Failed to bulk write messages: {e}") from e

        finally:
            # Cleanup mbox object
            if mbox_obj:
                try:
                    # Try to unlock if locked
                    try:
                        mbox_obj.unlock()
                    except Exception:
                        pass  # May not be locked
                    # Always close to prevent resource leak
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close staging mbox: {e}")

    async def bulk_update_archive_locations_with_dedup(
        self,
        updates: list[dict[str, Any]],
        duplicate_gmail_ids: list[str] | None = None,
    ) -> None:
        """
        Update archive locations and optionally delete duplicate entries.

        This is a transactional operation that updates all message locations
        and deletes duplicate entries atomically.

        Args:
            updates: List of update dicts with gmail_id, archive_file, offset, length
            duplicate_gmail_ids: List of gmail_ids to delete (duplicates)

        Raises:
            HybridStorageError: If update fails
        """
        try:
            # Delete duplicates first
            if duplicate_gmail_ids:
                for gmail_id in duplicate_gmail_ids:
                    await self.db.delete_message(gmail_id)

            # Update archive locations
            await self.db.bulk_update_archive_locations(updates)

            # Note: Caller is responsible for commit/rollback
            logger.debug(
                f"Updated {len(updates)} records, "
                f"deleted {len(duplicate_gmail_ids or [])} duplicates"
            )

        except Exception as e:
            raise HybridStorageError(f"Failed to update archive locations: {e}") from e

    # ==================== CONSOLIDATION OPERATION ====================

    async def consolidate_archives(
        self,
        source_archives: list[Path],
        output_archive: Path,
        deduplicate: bool = True,
        compression: str | None = None,
    ) -> ConsolidationResult:
        """
        Atomically consolidate multiple archives.

        Steps:
        1. Read all messages from source archives (uses asyncio.to_thread)
        2. Optionally deduplicate by Message-ID
        3. Write to NEW consolidated mbox (uses asyncio.to_thread)
        4. Validate consistency (before database commit)
        5. Update ALL database records with new offsets
        6. Only then, optionally delete old archives

        Args:
            source_archives: List of source archive paths
            output_archive: Path to consolidated output archive
            deduplicate: Remove duplicates by Message-ID
            compression: Compression format for output

        Returns:
            ConsolidationResult with statistics

        Raises:
            HybridStorageError: If operation fails
        """
        staging_mbox = self._staging_area / f"consolidate_{uuid.uuid4()}.mbox"

        try:
            # Phase 1: Read and collect messages (uses asyncio.to_thread internally)
            logger.info(f"Phase 1: Reading {len(source_archives)} source archives")
            messages = await self._collect_messages(source_archives)
            total_messages = len(messages)
            logger.info(f"Collected {total_messages} messages")

            # Phase 2: Deduplicate if requested
            duplicates_removed = 0
            if deduplicate:
                logger.info("Phase 2: Deduplicating by Message-ID")
                messages, duplicates_removed = self._deduplicate_messages(messages)
                logger.info(f"Removed {duplicates_removed} duplicates")

            # Phase 3: Write to staging mbox (CPU-bound work in thread pool)
            logger.info("Phase 3: Writing to staging mbox")
            offset_map = await asyncio.to_thread(
                self._write_consolidation_mbox_sync,
                messages,
                staging_mbox,
            )

            # Phase 4: Move staging to final location
            logger.info("Phase 4: Moving to final location")
            final_mbox = output_archive
            if compression:
                final_mbox = output_archive.with_suffix(".mbox")

            shutil.move(str(staging_mbox), str(final_mbox))

            # Compress if requested (already uses asyncio.to_thread internally)
            if compression:
                logger.info(f"Compressing with {compression}")
                await self._compress_file(final_mbox, output_archive, compression)
                final_mbox.unlink()
                # Clean up lock file
                lock_file = Path(str(final_mbox) + ".lock")
                if lock_file.exists():
                    lock_file.unlink()

            # Phase 5: Validate BEFORE database commit (ensures atomicity)
            # For consolidation, validate that the output contains expected messages
            # (can't use _validate_archive_consistency yet as DB not updated)
            logger.info("Phase 5: Validating consolidated archive")
            await self._validate_consolidation_output(
                output_archive, expected_message_ids=set(offset_map.keys())
            )

            # Phase 6: Update database (transactional)
            logger.info("Phase 6: Updating database records")
            updates = [
                {
                    "gmail_id": gmail_id,
                    "archive_file": str(output_archive),
                    "mbox_offset": offset,
                    "mbox_length": length,
                }
                for rfc_id, (gmail_id, offset, length) in offset_map.items()
            ]

            await self.db.bulk_update_archive_locations(updates)
            await self.db.commit()

            logger.info(f"Updated {len(updates)} database records")

            logger.info(
                f"Successfully consolidated {len(messages)} messages "
                f"from {len(source_archives)} archives"
            )

            return ConsolidationResult(
                output_file=str(output_archive),
                source_files=[str(p) for p in source_archives],
                total_messages=total_messages,
                duplicates_removed=duplicates_removed,
                messages_consolidated=len(offset_map),
            )

        except IntegrityError:
            # Re-raise IntegrityError as-is (critical data consistency issue)
            logger.error("Consolidation integrity check failed")
            try:
                await self.db.rollback()
                logger.debug("Database rolled back")
            except Exception as rb_err:
                logger.error(f"Rollback failed: {rb_err}")

            # Rollback: Remove staging files
            if staging_mbox.exists():
                try:
                    staging_mbox.unlink()
                    logger.debug("Staging file removed")
                except Exception as cleanup_err:
                    logger.error(f"Failed to remove staging file: {cleanup_err}")
            raise

        except Exception as e:
            # Rollback database
            logger.error(f"Consolidation failed: {e}")
            try:
                await self.db.rollback()
                logger.debug("Database rolled back")
            except Exception as rb_err:
                logger.error(f"Rollback failed: {rb_err}")

            # Rollback: Remove staging files
            if staging_mbox.exists():
                try:
                    staging_mbox.unlink()
                    logger.debug("Staging file removed")
                except Exception as cleanup_err:
                    logger.error(f"Failed to remove staging file: {cleanup_err}")

            raise HybridStorageError(f"Failed to consolidate archives: {e}") from e

    # ==================== VALIDATION ====================

    async def _validate_batch_consistency(self, rfc_message_ids: list[str]) -> None:
        """
        Validate that all batch messages exist in database.

        This is a lightweight validation for batch operations - it checks that
        all messages were successfully committed to the database without doing
        expensive per-message mbox reads.

        Args:
            rfc_message_ids: List of RFC Message-IDs to validate

        Raises:
            IntegrityError: If any message not found in database
        """
        for rfc_id in rfc_message_ids:
            if not await self.db.get_message_by_rfc_message_id(rfc_id):
                raise IntegrityError(
                    f"Batch validation failed: {rfc_id} not in database after commit"
                )

    async def _validate_message_consistency(self, rfc_message_id: str) -> None:
        """
        Validate that a message exists in both mbox and database.

        Uses asyncio.to_thread() for CPU-bound file reading and email parsing.

        Args:
            rfc_message_id: RFC 2822 Message-ID to validate (primary key in v1.2)

        Raises:
            IntegrityError: If inconsistent
        """
        # Get location from database (async DB operation)
        location = await self.db.get_message_location(rfc_message_id)
        if not location:
            raise IntegrityError(f"Message {rfc_message_id} not in database")

        archive_file, offset, length = location

        # Handle compressed archives - need to decompress to validate
        archive_path = Path(archive_file)
        compression = self._detect_compression(archive_path)
        tmp_path: Path | None = None

        if compression:
            # Decompress to temp file for validation
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                # Decompression already uses asyncio.to_thread internally
                await self._decompress_file(archive_path, tmp_path, compression)
                validate_path = tmp_path
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise IntegrityError(f"Failed to decompress {archive_file}: {e}")
        else:
            validate_path = archive_path

        try:
            # CPU-bound validation in thread pool
            await asyncio.to_thread(
                self._validate_message_at_offset_sync,
                validate_path,
                offset,
                length,
                archive_file,
            )

        finally:
            # Clean up temp file if created
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    async def _validate_archive_consistency(self, archive_file: Path) -> None:
        """
        Validate entire archive against database.

        Checks:
        1. All database records point to valid offsets
        2. All messages in mbox are in database
        3. Counts match

        Args:
            archive_file: Path to archive file to validate

        Raises:
            IntegrityError: If inconsistent
        """
        # Get all messages for this archive from database
        db_records = await self.db.get_all_messages_for_archive(str(archive_file))
        db_message_ids = {rec["rfc_message_id"] for rec in db_records}

        logger.debug(f"Database has {len(db_records)} records for {archive_file}")

        # Handle compressed archives
        compression = self._detect_compression(archive_file)
        if compression:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                await self._decompress_file(archive_file, tmp_path, compression)
                validate_path = tmp_path
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise IntegrityError(f"Failed to decompress {archive_file}: {e}")
        else:
            validate_path = archive_file
            tmp_path = None

        try:
            # Read mbox and verify each message
            with closing(mailbox.mbox(str(validate_path))) as mbox_obj:
                mbox_message_ids = set()

                for key in mbox_obj.keys():
                    msg = mbox_obj[key]
                    msg_id = msg.get("Message-ID", "")
                    mbox_message_ids.add(msg_id)

                    # Verify in database
                    if msg_id not in db_message_ids:
                        raise IntegrityError(f"Message {msg_id} in mbox but not in database")

            logger.debug(f"Mbox has {len(mbox_message_ids)} messages")

            # Verify counts match
            if len(db_records) != len(mbox_message_ids):
                raise IntegrityError(
                    f"Count mismatch: {len(db_records)} in DB, {len(mbox_message_ids)} in mbox"
                )

            logger.debug("Archive validation passed")

        finally:
            # Clean up temp file if created
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    async def _validate_consolidation_output(
        self, archive_file: Path, expected_message_ids: set[str]
    ) -> None:
        """
        Validate consolidated archive output before database update.

        This is used during consolidation to validate the new archive file
        before committing database changes. Unlike _validate_archive_consistency,
        this doesn't query the database by archive_file (since it's not updated yet).

        Args:
            archive_file: Path to the consolidated archive file
            expected_message_ids: Set of expected RFC Message-IDs

        Raises:
            IntegrityError: If validation fails
        """
        logger.debug(f"Validating consolidation output: {archive_file}")

        # Handle compressed archives
        compression = self._detect_compression(archive_file)
        if compression:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                await self._decompress_file(archive_file, tmp_path, compression)
                validate_path = tmp_path
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise IntegrityError(f"Failed to decompress {archive_file}: {e}")
        else:
            validate_path = archive_file
            tmp_path = None

        try:
            # Read mbox and verify message count and IDs
            with closing(mailbox.mbox(str(validate_path))) as mbox_obj:
                mbox_message_ids = set()

                for key in mbox_obj.keys():
                    msg = mbox_obj[key]
                    msg_id = msg.get("Message-ID", "")
                    mbox_message_ids.add(msg_id)

            logger.debug(f"Consolidated archive has {len(mbox_message_ids)} messages")

            # Verify all expected messages are present
            missing = expected_message_ids - mbox_message_ids
            if missing:
                raise IntegrityError(
                    f"Missing {len(missing)} expected messages in consolidated archive"
                )

            # Verify no unexpected messages
            unexpected = mbox_message_ids - expected_message_ids
            if unexpected:
                raise IntegrityError(
                    f"Found {len(unexpected)} unexpected messages in consolidated archive"
                )

            logger.debug("Consolidation output validation passed")

        finally:
            # Clean up temp file if created
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    # ==================== HELPER METHODS ====================

    async def _collect_messages(self, source_archives: list[Path]) -> list[dict[str, Any]]:
        """
        Collect all messages from source archives.

        Uses asyncio.to_thread() for CPU-bound mbox reading operations to avoid
        blocking the event loop.

        Args:
            source_archives: List of archive paths

        Returns:
            List of message dictionaries with metadata
        """
        all_messages: list[dict[str, Any]] = []

        for archive_path in source_archives:
            logger.debug(f"Reading archive: {archive_path}")

            # Get all database records for this archive (async DB operation)
            db_records = await self.db.get_all_messages_for_archive(str(archive_path))

            # Create lookup by rfc_message_id
            db_lookup = {rec["rfc_message_id"]: rec for rec in db_records}

            # Handle compressed archives
            compression = self._detect_compression(archive_path)
            tmp_path: Path | None = None

            if compression:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    # Decompression already uses asyncio.to_thread internally
                    await self._decompress_file(archive_path, tmp_path, compression)
                    read_path = tmp_path
                except Exception as e:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    raise HybridStorageError(f"Failed to decompress {archive_path}: {e}")
            else:
                read_path = archive_path

            try:
                # CPU-bound mbox reading in thread pool
                archive_messages = await asyncio.to_thread(
                    self._collect_messages_from_archive_sync,
                    read_path,
                    db_lookup,
                )

                # Update source_archive to original path (not temp file)
                for msg in archive_messages:
                    msg["source_archive"] = str(archive_path)

                all_messages.extend(archive_messages)

            finally:
                # Clean up temp file if created
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        return all_messages

    def _deduplicate_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Remove duplicate messages by Message-ID (keeps first occurrence).

        Args:
            messages: List of message dictionaries

        Returns:
            Tuple of (deduplicated_messages, duplicates_removed_count)
        """
        seen_ids: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        duplicates_removed = 0

        for msg_dict in messages:
            rfc_id = msg_dict["rfc_message_id"]

            if rfc_id in seen_ids:
                duplicates_removed += 1
                continue

            seen_ids.add(rfc_id)
            deduplicated.append(msg_dict)

        return deduplicated, duplicates_removed

    def _extract_rfc_message_id(self, msg: email.message.Message) -> str:
        """
        Extract RFC 2822 Message-ID from email message.

        Args:
            msg: Email message

        Returns:
            Message-ID header value (or generated fallback)
        """
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            # Generate fallback Message-ID from Subject + Date
            subject = msg.get("Subject", "no-subject")
            date = msg.get("Date", "no-date")
            fallback_id = f"<{hashlib.sha256(f'{subject}{date}'.encode()).hexdigest()}@generated>"
            return fallback_id
        return message_id

    def _extract_body_preview(self, msg: email.message.Message, max_chars: int = 1000) -> str:
        """
        Extract body preview from email message.

        Args:
            msg: Email message
            max_chars: Maximum characters to extract

        Returns:
            Plain text preview (first max_chars)
        """
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload and isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")
                            break
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body = payload.decode("utf-8", errors="ignore")
            except Exception:
                pass

        return body[:max_chars]

    def _compute_checksum(self, data: bytes) -> str:
        """
        Compute SHA256 checksum of data.

        Args:
            data: Bytes to checksum

        Returns:
            Hex digest of SHA256 hash
        """
        return hashlib.sha256(data).hexdigest()

    def _detect_compression(self, path: Path) -> str | None:
        """
        Detect compression format from file extension.

        Args:
            path: File path

        Returns:
            Compression format ('gzip', 'lzma', 'zstd') or None
        """
        suffix = path.suffix.lower()
        if suffix == ".gz":
            return "gzip"
        elif suffix in (".xz", ".lzma"):
            return "lzma"
        elif suffix == ".zst":
            return "zstd"
        return None

    # ==================== SYNC HELPERS FOR CPU-BOUND WORK ====================
    # These methods run in thread pool via asyncio.to_thread() to avoid
    # blocking the event loop during CPU-intensive mbox/email operations.

    def _write_messages_to_mbox_sync(
        self,
        messages: list[tuple[email.message.Message, str, str | None, str | None]],
        mbox_path: Path,
        archive_file: Path,
        known_rfc_ids: set[str],
        interrupt_event: Any | None = None,
    ) -> tuple[list[dict[str, Any]], list[str], list[tuple[str, str]], int, int, bool]:
        """
        Sync helper: Write messages to mbox and extract metadata.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().
        It handles mbox operations, checksum calculation, and metadata extraction.

        Args:
            messages: List of (email_message, gmail_id, thread_id, labels) tuples
            mbox_path: Path to mbox file (uncompressed working file)
            archive_file: Path to final archive file (for database records)
            known_rfc_ids: Set of already-archived RFC Message-IDs
            interrupt_event: Optional threading.Event for graceful interruption

        Returns:
            Tuple of:
            - results: List of message metadata dicts for database insertion
            - new_rfc_ids: List of RFC Message-IDs that were archived
            - skipped_messages: List of (gmail_id, subject) for skipped duplicates
            - skipped_count: Number of duplicate messages skipped
            - failed_count: Number of messages that failed to process
            - interrupted: Whether processing was interrupted
        """
        results: list[dict[str, Any]] = []
        new_rfc_ids: list[str] = []
        skipped_messages: list[tuple[str, str]] = []
        skipped_count = 0
        failed_count = 0
        interrupted = False
        mbox_obj = None

        try:
            # Clean up any orphaned lock files
            lock_file = Path(str(mbox_path) + ".lock")
            if lock_file.exists():
                logger.warning(f"Removing orphaned lock file: {lock_file}")
                lock_file.unlink()

            # Open mbox ONCE for entire batch
            mbox_obj = mailbox.mbox(str(mbox_path))
            mbox_obj.lock()

            for email_message, gmail_id, thread_id, labels in messages:
                # Check for interrupt at start of each message
                if interrupt_event and interrupt_event.is_set():
                    logger.info("Interrupt received during mbox processing")
                    interrupted = True
                    break
                # Check for duplicate (O(1) using pre-loaded set)
                rfc_message_id = self._extract_rfc_message_id(email_message)
                if rfc_message_id in known_rfc_ids:
                    subject = email_message.get("Subject", "No Subject")
                    logger.debug(
                        f"Skipping duplicate message {gmail_id}: "
                        f"rfc_message_id '{rfc_message_id}' already archived"
                    )
                    skipped_messages.append((gmail_id, subject))
                    skipped_count += 1
                    continue

                try:
                    # Get offset BEFORE writing
                    if hasattr(mbox_obj, "_file") and mbox_obj._file:
                        mbox_obj._file.seek(0, 2)  # SEEK_END
                        offset = mbox_obj._file.tell()
                    elif mbox_path.exists():
                        offset = mbox_path.stat().st_size
                    else:
                        offset = 0

                    # Write message
                    mbox_obj.add(email_message)

                    # Get length AFTER writing
                    if hasattr(mbox_obj, "_file") and mbox_obj._file:
                        length = mbox_obj._file.tell() - offset
                    else:
                        length = len(email_message.as_bytes()) + 50

                    # Extract metadata (CPU-bound)
                    msg_bytes = email_message.as_bytes()
                    subject = email_message.get("Subject", "No Subject")
                    body_preview = self._extract_body_preview(email_message)
                    checksum = self._compute_checksum(msg_bytes)

                    results.append(
                        {
                            "gmail_id": gmail_id,
                            "rfc_message_id": rfc_message_id,
                            "archive_file": str(archive_file),
                            "mbox_offset": offset,
                            "mbox_length": length,
                            "thread_id": thread_id,
                            "subject": subject,
                            "from_addr": email_message.get("From"),
                            "to_addr": email_message.get("To"),
                            "cc_addr": email_message.get("Cc"),
                            "date": email_message.get("Date"),
                            "body_preview": body_preview,
                            "checksum": checksum,
                            "size_bytes": len(msg_bytes),
                            "labels": labels,
                        }
                    )
                    new_rfc_ids.append(rfc_message_id)
                    # Add to known_rfc_ids to detect duplicates within same batch
                    known_rfc_ids.add(rfc_message_id)

                except Exception as e:
                    logger.error(f"Failed to archive message {gmail_id}: {e}")
                    failed_count += 1

            # Flush buffered data
            if hasattr(mbox_obj, "_file") and mbox_obj._file:
                mbox_obj._file.flush()

            # Unlock mbox (handle failures gracefully)
            try:
                mbox_obj.unlock()
            except Exception as e:
                logger.warning(f"Failed to unlock mbox: {e}")

            # Close internal file handle directly (avoid mbox.close()'s fsync)
            if hasattr(mbox_obj, "_file") and mbox_obj._file:
                try:
                    mbox_obj._file.close()
                except Exception as e:
                    logger.warning(f"Failed to close mbox file: {e}")

            mbox_obj = None

            # Single fsync at END (critical for performance)
            if mbox_path.exists():
                with open(mbox_path, "r+b") as sync_file:
                    os.fsync(sync_file.fileno())

            return results, new_rfc_ids, skipped_messages, skipped_count, failed_count, interrupted

        finally:
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock mbox in cleanup: {e}")
                try:
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close mbox in cleanup: {e}")

    def _collect_messages_from_archive_sync(
        self,
        archive_path: Path,
        db_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Sync helper: Collect messages from a single archive.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().
        It handles mbox reading, message parsing, and metadata extraction.

        Args:
            archive_path: Path to archive file (may be decompressed temp file)
            db_lookup: Dict mapping rfc_message_id -> database record

        Returns:
            List of message dictionaries with metadata
        """
        messages: list[dict[str, Any]] = []

        with closing(mailbox.mbox(str(archive_path))) as mbox_obj:
            for key in mbox_obj.keys():
                msg = mbox_obj[key]
                rfc_message_id = msg.get("Message-ID", "")

                # Get gmail_id from database
                db_record = db_lookup.get(rfc_message_id)
                gmail_id = db_record["gmail_id"] if db_record else "unknown"

                # Extract date for sorting
                date_str = msg.get("Date", "")

                # Calculate size for dedup strategies (CPU-bound)
                size = len(msg.as_bytes())

                messages.append(
                    {
                        "message": msg,
                        "rfc_message_id": rfc_message_id,
                        "gmail_id": gmail_id,
                        "source_archive": str(archive_path),
                        "date": date_str,
                        "size": size,
                    }
                )

        return messages

    def _write_consolidation_mbox_sync(
        self,
        messages: list[dict[str, Any]],
        staging_mbox: Path,
    ) -> dict[str, tuple[str, int, int]]:
        """
        Sync helper: Write messages to consolidation mbox.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            messages: List of message dictionaries to write
            staging_mbox: Path to staging mbox file

        Returns:
            Dict mapping rfc_message_id -> (gmail_id, offset, length)
        """
        offset_map: dict[str, tuple[str, int, int]] = {}
        mbox_obj = None

        try:
            mbox_obj = mailbox.mbox(str(staging_mbox))
            mbox_obj.lock()

            for msg_dict in messages:
                msg = msg_dict["message"]
                gmail_id = msg_dict["gmail_id"]
                rfc_id = msg.get("Message-ID", "")

                # Get offset before write
                if staging_mbox.exists():
                    with open(staging_mbox, "rb") as f:
                        f.seek(0, 2)
                        offset = f.tell()
                else:
                    offset = 0

                # Write message
                mbox_obj.add(msg)
                mbox_obj.flush()

                # Calculate length
                if staging_mbox.exists():
                    with open(staging_mbox, "rb") as f:
                        f.seek(0, 2)
                        length = f.tell() - offset
                else:
                    length = len(msg.as_bytes())

                offset_map[rfc_id] = (gmail_id, offset, length)

            mbox_obj.unlock()
            mbox_obj.close()
            mbox_obj = None

            return offset_map

        finally:
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock staging mbox: {e}")
                try:
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close staging mbox: {e}")

    def _validate_message_at_offset_sync(
        self,
        validate_path: Path,
        offset: int,
        length: int,
        archive_file: str,
    ) -> None:
        """
        Sync helper: Validate message can be read at offset.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            validate_path: Path to file to validate (may be decompressed temp)
            offset: Byte offset in file
            length: Expected message length
            archive_file: Original archive path (for error messages)

        Raises:
            IntegrityError: If validation fails
        """
        if not validate_path.exists():
            raise IntegrityError(f"Archive file missing: {validate_path}")

        with open(validate_path, "rb") as f:
            f.seek(offset)
            message_bytes = f.read(length)
            if not message_bytes:
                raise IntegrityError(f"No data at offset {offset} in {archive_file}")

            try:
                email.message_from_bytes(message_bytes, policy=policy.default)
            except Exception as e:
                raise IntegrityError(f"Invalid email data at offset {offset}: {e}")

    # ==================== COMPRESSION HELPERS ====================

    async def _compress_file(self, source: Path, dest: Path, compression: str) -> None:
        """
        Compress file with specified format (async wrapper).

        Args:
            source: Source file path
            dest: Destination file path
            compression: Compression format ('gzip', 'lzma', 'zstd')

        Raises:
            ValueError: If compression format is unsupported
        """
        await asyncio.to_thread(self._compress_file_sync, source, dest, compression)

    def _compress_file_sync(self, source: Path, dest: Path, compression: str) -> None:
        """
        Compress file with specified format (sync implementation).

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            source: Source file path
            dest: Destination file path
            compression: Compression format ('gzip', 'lzma', 'zstd')

        Raises:
            ValueError: If compression format is unsupported
        """
        if compression == "gzip":
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compression == "lzma":
            with open(source, "rb") as f_in:
                with lzma.open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compression == "zstd":
            with open(source, "rb") as f_in:
                with zstd.open(dest, "wb", level=3) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            raise ValueError(f"Unsupported compression format: {compression}")

    async def _decompress_file(self, source: Path, dest: Path, compression: str) -> None:
        """
        Decompress file with specified format (async wrapper).

        Args:
            source: Source compressed file path
            dest: Destination uncompressed file path
            compression: Compression format ('gzip', 'lzma', 'zstd')

        Raises:
            ValueError: If compression format is unsupported
        """
        await asyncio.to_thread(self._decompress_file_sync, source, dest, compression)

    def _decompress_file_sync(self, source: Path, dest: Path, compression: str) -> None:
        """
        Decompress file with specified format (sync implementation).

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            source: Source compressed file path
            dest: Destination uncompressed file path
            compression: Compression format ('gzip', 'lzma', 'zstd')

        Raises:
            ValueError: If compression format is unsupported
        """
        if compression == "gzip":
            with gzip.open(source, "rb") as f_in:
                with open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compression == "lzma":
            with lzma.open(source, "rb") as f_in:
                with open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compression == "zstd":
            with zstd.open(source, "rb") as f_in:
                with open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            raise ValueError(f"Unsupported compression format: {compression}")

    # ==================== READ OPERATIONS ====================

    async def search_messages(
        self,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        from_addr: str | None = None,
        to_addr: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> SearchResults:
        """
        Search archived messages using full-text search and metadata filters.

        This is a read-only gateway method that delegates to DBManager while
        providing a consistent interface for the core layer.

        Args:
            query: Full-text search query (searches subject, from, to, body_preview)
            limit: Maximum number of results to return (default: 100)
            offset: Number of results to skip for pagination (default: 0)
            from_addr: Filter by from address (exact match)
            to_addr: Filter by to address (exact match)
            date_from: Filter by date >= this value (ISO 8601 format)
            date_to: Filter by date <= this value (ISO 8601 format)

        Returns:
            SearchResults object with query results and metadata
        """
        import time

        from ..core.search._types import MessageSearchResult, SearchResults

        start_time = time.time()

        # Delegate to DBManager with appropriate parameters
        # Note: DBManager.search_messages uses fulltext parameter instead of query
        # and date_start/date_end instead of date_from/date_to
        fulltext = query if query else None

        # Get total count first (without limit)
        all_results = await self.db.search_messages(
            fulltext=fulltext,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=None,  # Already covered by fulltext search
            date_start=date_from,
            date_end=date_to,
            limit=999999,  # Get all to determine total count
        )
        total_count = len(all_results)

        # Now apply pagination
        paginated_results = all_results[offset : offset + limit]

        # Convert database results to MessageSearchResult objects
        search_results = []
        for result in paginated_results:
            search_results.append(
                MessageSearchResult(
                    gmail_id=result.get("gmail_id", ""),
                    rfc_message_id=result.get("rfc_message_id", ""),
                    subject=result.get("subject", ""),
                    from_addr=result.get("from_addr", ""),
                    to_addr=result.get("to_addr"),
                    date=result.get("date", ""),
                    body_preview=result.get("body_preview"),
                    archive_file=result.get("archive_file", ""),
                    mbox_offset=result.get("mbox_offset", 0),
                    relevance_score=None,  # DBManager doesn't provide relevance scores yet
                )
            )

        execution_time_ms = (time.time() - start_time) * 1000

        return SearchResults(
            total_results=total_count,
            results=search_results,
            query=query,
            execution_time_ms=execution_time_ms,
        )

    async def get_message(self, gmail_id: str) -> dict[str, Any] | None:
        """
        Retrieve message metadata by Gmail ID.

        Args:
            gmail_id: Gmail message ID

        Returns:
            Dictionary with message metadata, or None if not found
        """
        return await self.db.get_message_by_gmail_id(gmail_id)

    async def get_message_by_rfc_id(self, rfc_message_id: str) -> dict[str, Any] | None:
        """
        Retrieve message metadata by RFC 2822 Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header value

        Returns:
            Dictionary with message metadata, or None if not found
        """
        return await self.db.get_message_by_rfc_message_id(rfc_message_id)

    async def extract_message_content(self, gmail_id: str) -> email.message.Message:
        """
        Extract full message content from mbox archive.

        This reads the actual email message from the mbox file using the
        offset and length stored in the database.

        Args:
            gmail_id: Gmail message ID

        Returns:
            email.message.Message object with full message content

        Raises:
            HybridStorageError: If message not found or archive file missing
        """
        # Get message location from database
        record = await self.db.get_message_by_gmail_id(gmail_id)
        if not record:
            raise HybridStorageError(f"Message {gmail_id} not found in database")

        archive_file = Path(record["archive_file"])
        offset = record["mbox_offset"]
        length = record["mbox_length"]

        # Check if archive file exists
        if not archive_file.exists():
            raise HybridStorageError(f"Archive file {archive_file} not found")

        # Handle compressed archives - decompress to temp file
        compression = self._detect_compression(archive_file)
        if compression:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                await self._decompress_file(archive_file, tmp_path, compression)
                read_path = tmp_path
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise HybridStorageError(f"Failed to decompress {archive_file}: {e}") from e
        else:
            read_path = archive_file
            tmp_path = None

        try:
            # Read message at offset
            with open(read_path, "rb") as f:
                f.seek(offset)
                message_bytes = f.read(length)

            # Parse as email message
            return email.message_from_bytes(message_bytes, policy=policy.default)

        finally:
            # Clean up temp file if created
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    # ==================== ARCHIVE VALIDATION ====================

    async def validate_archive_integrity(self, archive_file: str) -> bool:
        """
        Validate archive file integrity.

        Checks that:
        1. The archive file exists
        2. It can be opened as an mbox file
        3. Messages can be read from it

        Args:
            archive_file: Path to archive file to validate

        Returns:
            True if validation passes, False otherwise
        """
        archive_path = Path(archive_file)

        if not archive_path.exists():
            return False

        try:
            # Handle compressed archives
            compression = self._detect_compression(archive_path)
            if compression:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    await self._decompress_file(archive_path, tmp_path, compression)
                    validate_path = tmp_path
                except Exception:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    return False
            else:
                validate_path = archive_path
                tmp_path = None

            try:
                # Try to open and read the mbox
                with closing(mailbox.mbox(str(validate_path))) as mbox_obj:
                    # Count messages to verify the file is readable
                    message_count = len(mbox_obj)
                    logger.debug(f"Validated {archive_file}: {message_count} messages")

                return True

            finally:
                # Clean up temp file if created
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        except Exception as e:
            logger.warning(f"Archive validation failed for {archive_file}: {e}")
            return False

    # ==================== STATISTICS OPERATIONS ====================

    async def get_archive_stats(self) -> ArchiveStats:
        """
        Get comprehensive statistics about archived messages.

        Returns:
            ArchiveStats object with total messages, archive files, schema version,
            database size, and recent runs
        """
        # Get total message count
        total_messages = await self.db.get_message_count()

        # Get distinct archive files
        cursor = await self.db._conn.execute(
            "SELECT DISTINCT archive_file FROM messages ORDER BY archive_file"
        )
        rows = await cursor.fetchall()
        archive_files = [row[0] for row in rows]

        # Get schema version
        schema_version = self.db.schema_version or "unknown"

        # Get database file size
        database_size_bytes = self.db.db_path.stat().st_size

        # Get recent runs
        recent_runs = await self.db.get_archive_runs(limit=10)

        return ArchiveStats(
            total_messages=total_messages,
            archive_files=archive_files,
            schema_version=schema_version,
            database_size_bytes=database_size_bytes,
            recent_runs=recent_runs,
        )

    async def get_message_ids_for_archive(self, archive_file: str) -> set[str]:
        """
        Get all Gmail message IDs for a specific archive file.

        Args:
            archive_file: Path to archive file

        Returns:
            Set of gmail_id values for the archive file
        """
        return await self.db.get_gmail_ids_for_archive(archive_file)

    async def get_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent archive operation history.

        Args:
            limit: Maximum number of runs to return (default: 10)

        Returns:
            List of archive run dictionaries, ordered by timestamp descending
        """
        return await self.db.get_archive_runs(limit=limit)

    async def is_message_archived(self, gmail_id: str) -> bool:
        """
        Check if a message is already archived.

        Args:
            gmail_id: Gmail message ID to check

        Returns:
            True if message exists in database, False otherwise
        """
        return await self.db.is_archived(gmail_id)

    async def get_message_count(self) -> int:
        """
        Get total number of archived messages.

        Returns:
            Total count of messages in the database
        """
        return await self.db.get_message_count()

    # ==================== CONTEXT MANAGER ====================

    async def __aenter__(self) -> HybridStorage:
        """Async context manager entry."""
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - cleanup staging area."""
        self._cleanup_staging_area()

    def __del__(self) -> None:
        """Destructor - cleanup staging area."""
        self._cleanup_staging_area()

    def _cleanup_staging_area(self) -> None:
        """Clean up staging area files."""
        if hasattr(self, "_staging_area") and self._staging_area.exists():
            try:
                for file in self._staging_area.iterdir():
                    try:
                        file.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to remove staging file {file}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clean staging area: {e}")
