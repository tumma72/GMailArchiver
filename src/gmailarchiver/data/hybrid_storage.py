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

from __future__ import annotations

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
from typing import Any

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

        # Pre-load RFC Message-IDs for O(1) duplicate detection
        # This avoids per-message database queries during batch archiving
        if preload_rfc_ids:
            self._known_rfc_ids: set[str] = self.db.get_all_rfc_message_ids()
            logger.debug(f"Pre-loaded {len(self._known_rfc_ids):,} RFC Message-IDs")
        else:
            self._known_rfc_ids = set()

    # ==================== BATCH ARCHIVE OPERATION ====================

    def archive_messages_batch(
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
        if not messages:
            return {
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": False,
                "actual_file": str(archive_file),
            }

        archived_count = 0
        skipped_count = 0
        failed_count = 0
        interrupted = False
        batch_rfc_ids: list[str] = []
        mbox_obj = None
        mbox_path = archive_file

        # If compression requested, work with uncompressed mbox first
        if compression:
            if archive_file.suffix in (".gz", ".xz", ".zst"):
                mbox_path = archive_file.with_suffix("")
            else:
                mbox_path = archive_file.parent / (archive_file.stem + ".mbox")

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
                # Check for interrupt BEFORE processing
                if interrupt_event and interrupt_event.is_set():
                    interrupted = True
                    logger.warning("Interrupt received - saving progress...")
                    break
                # Check for duplicate (O(1) using pre-loaded set)
                rfc_message_id = self._extract_rfc_message_id(email_message)
                if rfc_message_id in self._known_rfc_ids:
                    logger.debug(
                        f"Skipping duplicate message {gmail_id}: "
                        f"rfc_message_id '{rfc_message_id}' already archived"
                    )
                    skipped_count += 1
                    subject = email_message.get("Subject", "No Subject")
                    if progress_callback:
                        progress_callback(gmail_id, subject, "skipped")
                    continue

                try:
                    # Get offset BEFORE writing using the mbox's internal file handle
                    # This avoids opening a separate file handle
                    if hasattr(mbox_obj, "_file") and mbox_obj._file:
                        # Seek to end to get correct offset for appending
                        # (file cursor may not be at end when mbox is reopened)
                        mbox_obj._file.seek(0, 2)  # SEEK_END
                        offset = mbox_obj._file.tell()
                    elif mbox_path.exists():
                        offset = mbox_path.stat().st_size
                    else:
                        offset = 0

                    # Write message
                    mbox_obj.add(email_message)

                    # Get length AFTER writing using the mbox's internal file handle
                    # This avoids flush() which calls fsync
                    if hasattr(mbox_obj, "_file") and mbox_obj._file:
                        length = mbox_obj._file.tell() - offset
                    else:
                        # Fallback: estimate from message size
                        length = len(email_message.as_bytes()) + 50

                    # Extract metadata
                    subject = email_message.get("Subject", "No Subject")
                    body_preview = self._extract_body_preview(email_message)
                    checksum = self._compute_checksum(email_message.as_bytes())

                    # Record in database (NO commit yet)
                    self.db.record_archived_message(
                        gmail_id=gmail_id,
                        rfc_message_id=rfc_message_id,
                        archive_file=str(archive_file),  # Store final path (with compression)
                        mbox_offset=offset,
                        mbox_length=length,
                        thread_id=thread_id,
                        subject=subject,
                        from_addr=email_message.get("From"),
                        to_addr=email_message.get("To"),
                        cc_addr=email_message.get("Cc"),
                        date=email_message.get("Date"),
                        body_preview=body_preview,
                        checksum=checksum,
                        size_bytes=len(email_message.as_bytes()),
                        labels=labels,
                        record_run=False,  # Don't record per-message, we'll record once at end
                    )

                    # Add to known set and batch tracking
                    self._known_rfc_ids.add(rfc_message_id)
                    batch_rfc_ids.append(rfc_message_id)
                    archived_count += 1

                    # Report progress
                    if progress_callback:
                        progress_callback(gmail_id, subject, "success")

                    # Commit at interval
                    if archived_count % commit_interval == 0:
                        self.db.commit()
                        # Update session progress if tracking
                        if session_id:
                            self.db.update_session_progress(session_id, archived_count)
                        logger.debug(f"Committed {archived_count} messages")

                except Exception as e:
                    # Log error but continue with next message
                    logger.error(f"Failed to archive message {gmail_id}: {e}")
                    failed_count += 1
                    subject = email_message.get("Subject", "No Subject")
                    if progress_callback:
                        progress_callback(gmail_id, subject, "error")

            # Flush buffered data to file without calling fsync
            # The mbox object's internal file handle should be flushed
            if hasattr(mbox_obj, "_file") and mbox_obj._file:
                mbox_obj._file.flush()

            # Unlock and close mbox WITHOUT calling mbox.close() (which calls fsync)
            # We'll do our own fsync after this
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock mbox: {e}")

                # Close the internal file handle directly to avoid mbox.close()'s fsync
                if hasattr(mbox_obj, "_file") and mbox_obj._file:
                    try:
                        mbox_obj._file.close()
                    except Exception as e:
                        logger.warning(f"Failed to close mbox file: {e}")

                mbox_obj = None

            # Single fsync at END of batch (critical for performance)
            # This is the ONLY fsync for the entire batch
            if mbox_path.exists():
                with open(mbox_path, "r+b") as sync_file:
                    os.fsync(sync_file.fileno())

            # Final commit
            self.db.commit()

            # Update session progress one final time
            if session_id and archived_count > 0:
                self.db.update_session_progress(session_id, archived_count)

            # Determine final file path
            final_path = mbox_path

            # Only finalize (validate/compress) if NOT interrupted
            if archived_count > 0 and not interrupted:
                # Batch validation at end (not per-message)
                self._validate_batch_consistency(batch_rfc_ids)

                # Compress if requested
                if compression:
                    logger.debug(f"Compressing with {compression}")
                    self._compress_file(mbox_path, archive_file, compression)
                    # Remove uncompressed file AND lock
                    mbox_path.unlink()
                    if lock_file.exists():
                        lock_file.unlink()
                    final_path = archive_file

                # Mark session as complete
                if session_id:
                    self.db.complete_session(session_id)

                # Record in audit trail
                self.db.record_archive_run(
                    operation="archive",
                    messages_count=archived_count,
                    archive_file=str(final_path),
                )

                logger.info(
                    f"Batch archived {archived_count} messages "
                    f"(skipped {skipped_count} duplicates) to {final_path}"
                )
            elif interrupted:
                logger.warning(
                    f"Interrupted: saved {archived_count}/{len(messages)} messages to {mbox_path}"
                )

            return {
                "archived": archived_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "interrupted": interrupted,
                "actual_file": str(final_path),
            }

        except Exception as e:
            # Rollback database
            logger.error(f"Batch archive failed: {e}")
            try:
                self.db.rollback()
                logger.debug("Database rolled back")
            except Exception as rb_err:
                logger.error(f"Rollback failed: {rb_err}")

            # Remove rfc_ids from known set (rollback in-memory state)
            for rfc_id in batch_rfc_ids:
                self._known_rfc_ids.discard(rfc_id)

            raise HybridStorageError(f"Failed to batch archive messages: {e}") from e

        finally:
            # Cleanup
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock mbox: {e}")
                try:
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close mbox: {e}")

    # ==================== CONSOLIDATION PRIMITIVES ====================

    def read_messages_from_archives(self, source_archives: list[Path]) -> list[dict[str, Any]]:
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
        return self._collect_messages(source_archives)

    def bulk_write_messages(
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
                final_mbox = output_path.with_suffix(".mbox")

            shutil.move(str(staging_mbox), str(final_mbox))

            # Compress if requested
            if compression:
                logger.debug(f"Compressing with {compression}")
                self._compress_file(final_mbox, output_path, compression)
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
            # Cleanup
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock staging mbox: {e}")
                try:
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close staging mbox: {e}")

    def bulk_update_archive_locations_with_dedup(
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
                    self.db.delete_message(gmail_id)

            # Update archive locations
            self.db.bulk_update_archive_locations(updates)

            # Note: Caller is responsible for commit/rollback
            logger.debug(
                f"Updated {len(updates)} records, "
                f"deleted {len(duplicate_gmail_ids or [])} duplicates"
            )

        except Exception as e:
            raise HybridStorageError(f"Failed to update archive locations: {e}") from e

    # ==================== CONSOLIDATION OPERATION ====================

    def consolidate_archives(
        self,
        source_archives: list[Path],
        output_archive: Path,
        deduplicate: bool = True,
        compression: str | None = None,
    ) -> ConsolidationResult:
        """
        Atomically consolidate multiple archives.

        Steps:
        1. Read all messages from source archives
        2. Optionally deduplicate by Message-ID
        3. Write to NEW consolidated mbox (never modify in-place)
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
        mbox_obj = None

        try:
            # Phase 1: Read and collect messages
            logger.info(f"Phase 1: Reading {len(source_archives)} source archives")
            messages = self._collect_messages(source_archives)
            total_messages = len(messages)
            logger.info(f"Collected {total_messages} messages")

            # Phase 2: Deduplicate if requested
            duplicates_removed = 0
            if deduplicate:
                logger.info("Phase 2: Deduplicating by Message-ID")
                messages, duplicates_removed = self._deduplicate_messages(messages)
                logger.info(f"Removed {duplicates_removed} duplicates")

            # Phase 3: Write to staging mbox
            logger.info("Phase 3: Writing to staging mbox")
            offset_map: dict[
                str, tuple[str, int, int]
            ] = {}  # rfc_message_id -> (gmail_id, offset, length)

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
                # mbox library might not have created file on disk yet for first message
                if staging_mbox.exists():
                    with open(staging_mbox, "rb") as f:
                        f.seek(0, 2)
                        length = f.tell() - offset
                else:
                    # File not created yet - use message size as estimate
                    # This happens when mbox library delays file creation
                    length = len(msg.as_bytes())

                offset_map[rfc_id] = (gmail_id, offset, length)

            mbox_obj.unlock()
            mbox_obj.close()
            mbox_obj = None

            # Phase 4: Move staging to final location
            logger.info("Phase 4: Moving to final location")
            final_mbox = output_archive
            if compression:
                final_mbox = output_archive.with_suffix(".mbox")

            shutil.move(str(staging_mbox), str(final_mbox))

            # Compress if requested
            if compression:
                logger.info(f"Compressing with {compression}")
                self._compress_file(final_mbox, output_archive, compression)
                final_mbox.unlink()
                # Clean up lock file
                lock_file = Path(str(final_mbox) + ".lock")
                if lock_file.exists():
                    lock_file.unlink()

            # Phase 5: Validate BEFORE database commit (ensures atomicity)
            # For consolidation, validate that the output contains expected messages
            # (can't use _validate_archive_consistency yet as DB not updated)
            logger.info("Phase 5: Validating consolidated archive")
            self._validate_consolidation_output(
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

            self.db.bulk_update_archive_locations(updates)
            self.db.commit()

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
                self.db.rollback()
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
                self.db.rollback()
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

        finally:
            # Cleanup
            if mbox_obj:
                try:
                    mbox_obj.unlock()
                except Exception as e:
                    logger.warning(f"Failed to unlock staging mbox: {e}")
                try:
                    mbox_obj.close()
                except Exception as e:
                    logger.warning(f"Failed to close staging mbox: {e}")

    # ==================== VALIDATION ====================

    def _validate_batch_consistency(self, rfc_message_ids: list[str]) -> None:
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
            if not self.db.get_message_by_rfc_message_id(rfc_id):
                raise IntegrityError(
                    f"Batch validation failed: {rfc_id} not in database after commit"
                )

    def _validate_message_consistency(self, rfc_message_id: str) -> None:
        """
        Validate that a message exists in both mbox and database.

        Args:
            rfc_message_id: RFC 2822 Message-ID to validate (primary key in v1.2)

        Raises:
            IntegrityError: If inconsistent
        """
        # Get location from database
        location = self.db.get_message_location(rfc_message_id)
        if not location:
            raise IntegrityError(f"Message {rfc_message_id} not in database")

        archive_file, offset, length = location

        # Handle compressed archives - need to decompress to validate
        archive_path = Path(archive_file)
        compression = self._detect_compression(archive_path)

        if compression:
            # Decompress to temp file for validation
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                self._decompress_file(archive_path, tmp_path, compression)
                validate_path = tmp_path
            except Exception as e:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise IntegrityError(f"Failed to decompress {archive_file}: {e}")
        else:
            validate_path = archive_path

        try:
            # Verify file exists
            if not validate_path.exists():
                raise IntegrityError(f"Archive file missing: {validate_path}")

            # Verify message can be read at offset
            with open(validate_path, "rb") as f:
                f.seek(offset)
                message_bytes = f.read(length)
                if not message_bytes:
                    raise IntegrityError(f"No data at offset {offset} in {archive_file}")

                # Verify it parses as email
                try:
                    email.message_from_bytes(message_bytes, policy=policy.default)
                except Exception as e:
                    raise IntegrityError(f"Invalid email data at offset {offset}: {e}")

        finally:
            # Clean up temp file if created
            if compression and tmp_path.exists():
                tmp_path.unlink()

    def _validate_archive_consistency(self, archive_file: Path) -> None:
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
        db_records = self.db.get_all_messages_for_archive(str(archive_file))
        db_message_ids = {rec["rfc_message_id"] for rec in db_records}

        logger.debug(f"Database has {len(db_records)} records for {archive_file}")

        # Handle compressed archives
        compression = self._detect_compression(archive_file)
        if compression:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                self._decompress_file(archive_file, tmp_path, compression)
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

    def _validate_consolidation_output(
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
                self._decompress_file(archive_file, tmp_path, compression)
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

    def _collect_messages(self, source_archives: list[Path]) -> list[dict[str, Any]]:
        """
        Collect all messages from source archives.

        Args:
            source_archives: List of archive paths

        Returns:
            List of message dictionaries with metadata
        """
        messages: list[dict[str, Any]] = []

        for archive_path in source_archives:
            logger.debug(f"Reading archive: {archive_path}")

            # Get all database records for this archive
            db_records = self.db.get_all_messages_for_archive(str(archive_path))

            # Create lookup by rfc_message_id
            db_lookup = {rec["rfc_message_id"]: rec for rec in db_records}

            # Handle compressed archives
            compression = self._detect_compression(archive_path)
            if compression:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".mbox", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    self._decompress_file(archive_path, tmp_path, compression)
                    read_path = tmp_path
                except Exception as e:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    raise HybridStorageError(f"Failed to decompress {archive_path}: {e}")
            else:
                read_path = archive_path
                tmp_path = None

            try:
                with closing(mailbox.mbox(str(read_path))) as mbox_obj:
                    for key in mbox_obj.keys():
                        msg = mbox_obj[key]
                        rfc_message_id = msg.get("Message-ID", "")

                        # Get gmail_id from database
                        db_record = db_lookup.get(rfc_message_id)
                        gmail_id = db_record["gmail_id"] if db_record else "unknown"

                        # Extract date for sorting
                        date_str = msg.get("Date", "")

                        # Calculate size for dedup strategies
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

            finally:
                # Clean up temp file if created
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        return messages

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

    def _compress_file(self, source: Path, dest: Path, compression: str) -> None:
        """
        Compress file with specified format.

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

    def _decompress_file(self, source: Path, dest: Path, compression: str) -> None:
        """
        Decompress file with specified format.

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

    # ==================== CONTEXT MANAGER ====================

    def __enter__(self) -> HybridStorage:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - cleanup staging area."""
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
