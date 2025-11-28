"""Core archiving logic for Gmail messages."""

import email
import gzip
import lzma
import shutil
import signal
import threading
from collections.abc import Callable
from compression import zstd
from email import policy
from pathlib import Path
from typing import Any

from gmailarchiver.cli.output import OperationHandle
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.input_validator import (
    validate_age_expression,
    validate_compression_format,
)
from gmailarchiver.shared.utils import datetime_to_gmail_query, format_bytes, parse_age

from .validator import ArchiveValidator


class GmailArchiver:
    """Main archiving orchestrator."""

    def __init__(
        self,
        gmail_client: GmailClient,
        state_db_path: str = "archive_state.db",
        output: Any | None = None,
    ) -> None:
        """
        Initialize archiver.

        Args:
            gmail_client: Gmail API client
            state_db_path: Path to state database
            output: Optional OutputManager for structured logging (v1.3.1+)
        """
        self.client = gmail_client
        self.state_db_path = state_db_path
        self.output = output
        self.db_manager: DBManager | None = None
        self.hybrid_storage: HybridStorage | None = None
        # Interrupt handling for graceful Ctrl+C
        self._interrupted = threading.Event()
        self._original_sigint_handler: Any = None

    def _log(
        self, message: str, level: str = "INFO", operation: OperationHandle | None = None
    ) -> None:
        """Log message through operation handle or OutputManager.

        Args:
            message: Message to log
            level: Severity level (INFO, WARNING, ERROR, SUCCESS)
            operation: Optional operation handle for live layout (v1.3.3+)
        """
        # Priority: operation handle (live layout) > OutputManager > print fallback
        if operation:
            # Use operation handle for live layout display
            operation.log(message, level)
        elif self.output:
            # Use OutputManager's methods
            if level == "WARNING":
                self.output.warning(message)
            elif level == "ERROR":
                self.output.error(message, exit_code=0)
            elif level == "SUCCESS":
                self.output.success(message)
            else:  # INFO
                self.output.info(message)
        else:
            # Fallback to print for backward compatibility
            print(message)

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        """Handle SIGINT (Ctrl+C) for graceful interruption.

        Sets the interrupted flag to allow the current message to finish
        processing before exiting. The partial archive and session remain
        intact for resumption.

        Args:
            signum: Signal number (unused)
            frame: Current stack frame (unused)
        """
        self._interrupted.set()

    def _install_sigint_handler(self) -> None:
        """Install SIGINT handler for graceful interruption."""
        self._interrupted.clear()
        self._original_sigint_handler = signal.signal(signal.SIGINT, self._handle_sigint)

    def _restore_sigint_handler(self) -> None:
        """Restore original SIGINT handler."""
        if self._original_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._original_sigint_handler)
            self._original_sigint_handler = None

    # =========================================================================
    # Phase-based API (v1.4.3+)
    # These methods allow command to control UI for each phase separately
    # =========================================================================

    def list_messages_for_archive(
        self,
        age_threshold: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """List messages from Gmail matching age threshold.

        Phase 1 of archive operation. Lists messages from Gmail API without
        any database filtering or archiving.

        Args:
            age_threshold: Age expression (e.g., '3y', '6m') or ISO date
            progress_callback: Optional callback(count, page) for progress updates

        Returns:
            Tuple of (gmail_query, message_list) where message_list contains
            dicts with 'id' and 'threadId' keys

        Raises:
            InvalidInputError: If age_threshold format is invalid
        """
        # Validate age threshold
        age_threshold = validate_age_expression(age_threshold)

        # Parse to date and build query
        cutoff_date = parse_age(age_threshold)
        query = f"before:{datetime_to_gmail_query(cutoff_date)}"

        # List messages from Gmail API with progress callback
        message_list = self.client.list_messages(query, progress_callback=progress_callback)

        return query, message_list

    def filter_already_archived(
        self,
        message_ids: list[str],
        incremental: bool = True,
    ) -> tuple[list[str], int]:
        """Filter out already-archived messages.

        Phase 2 of archive operation. Checks database for existing messages
        and returns filtered list.

        Args:
            message_ids: List of Gmail message IDs to filter
            incremental: If True, filter out already archived (default: True)

        Returns:
            Tuple of (filtered_message_ids, skipped_count)
        """
        if not incremental:
            return message_ids, 0

        # Check database for existing messages
        db_path = Path(self.state_db_path)
        try:
            db = DBManager(str(db_path), validate_schema=False, auto_create=True)
            # Get only non-NULL gmail_ids (NULL means message deleted from Gmail)
            cursor = db.conn.execute("SELECT gmail_id FROM messages WHERE gmail_id IS NOT NULL")
            archived_ids = {row[0] for row in cursor.fetchall()}
            db.close()
        except Exception:
            # If query fails, database might be empty or table doesn't exist yet
            archived_ids = set()

        # Filter out already-archived
        filtered_ids = [mid for mid in message_ids if mid not in archived_ids]
        skipped_count = len(message_ids) - len(filtered_ids)

        return filtered_ids, skipped_count

    def archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
    ) -> dict[str, Any]:
        """Archive a list of messages to mbox file.

        Phase 3 of archive operation. Archives the messages with progress
        tracking and log streaming.

        Args:
            message_ids: List of Gmail message IDs to archive
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            operation: Optional operation handle for live progress/logging

        Returns:
            Dict with 'archived_count', 'failed_count', 'interrupted', 'actual_file'
        """
        import uuid

        if not message_ids:
            return {
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
                "actual_file": output_file,
            }

        # Validate compression format
        compress = validate_compression_format(compress)

        # Initialize storage managers
        self.db_manager = DBManager(
            str(self.state_db_path), validate_schema=False, auto_create=True
        )
        self.hybrid_storage = HybridStorage(self.db_manager)

        # Create session
        session_id = str(uuid.uuid4())
        query = f"archive_messages({len(message_ids)} messages)"
        self.db_manager.create_session(
            session_id=session_id,
            target_file=output_file,
            query=query,
            message_ids=message_ids,
            compression=compress,
        )

        try:
            # Archive messages
            result = self._archive_messages(
                message_ids,
                output_file,
                compress,
                operation,
                session_id=session_id,
            )

            # Clean up
            self.db_manager.close()

            return {
                "archived_count": result.get("archived", 0),
                "failed_count": result.get("failed", 0),
                "interrupted": result.get("interrupted", False),
                "actual_file": result.get("actual_file", output_file),
            }

        except Exception:
            # Clean up on error
            if self.db_manager:
                self.db_manager.close()
            raise

    # =========================================================================
    # Original API (preserved for backward compatibility)
    # =========================================================================

    def archive(
        self,
        age_threshold: str,
        output_file: str,
        compress: str | None = None,
        incremental: bool = True,
        dry_run: bool = False,
        operation: OperationHandle | None = None,
        resume: bool = True,
    ) -> dict[str, Any]:
        """
        Archive emails older than threshold to mbox file.

        Supports resumable operations: if interrupted, the archive can be resumed
        from where it left off. Progress is saved in the database.

        Args:
            age_threshold: Age expression (e.g., '3y', '6m') or ISO date
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            incremental: Skip already-archived messages
            dry_run: Preview without actually archiving
            operation: Optional operation handle for live progress tracking (v1.3.2+)
            resume: Whether to check for and resume partial archives (default: True)

        Returns:
            Dictionary with archive statistics

        Raises:
            InvalidInputError: If age_threshold or compress format is invalid
        """
        import uuid

        # Validate and parse age threshold
        age_threshold = validate_age_expression(age_threshold)
        compress = validate_compression_format(compress)

        # Check for existing partial archive session
        partial_file = Path(str(output_file) + ".partial")
        session_id: str | None = None
        resuming = False

        if resume and not dry_run:
            db = DBManager(str(self.state_db_path), validate_schema=False, auto_create=True)
            existing_session = db.get_session_by_file(output_file)

            if existing_session and partial_file.exists():
                # Found partial archive - we'll resume from it
                resuming = True
                session_id = existing_session["session_id"]
                processed = existing_session["processed_count"]
                total = existing_session["total_count"]
                self._log(
                    f"Resuming partial archive: {processed}/{total} messages", operation=operation
                )
            db.close()

        cutoff_date = parse_age(age_threshold)
        query = f"before:{datetime_to_gmail_query(cutoff_date)}"

        self._log(
            f"Searching for emails older than {age_threshold} ({cutoff_date.date()})",
            operation=operation,
        )
        self._log(f"Query: {query}", operation=operation)

        # List messages from Gmail API with progress updates
        # Define progress callback to update the log with message count
        def list_progress(messages_found: int, page_number: int) -> None:
            if operation:
                msg = f"Listing messages... {messages_found:,} found (page {page_number})"
                operation.log(msg, "INFO")

        if operation:
            operation.log("Listing messages from Gmail...", "INFO")

        message_list: list[dict[str, Any]] = self.client.list_messages(
            query, progress_callback=list_progress if operation else None
        )

        # Log final result
        if message_list:
            msg = f"Found {len(message_list):,} messages"
            if operation:
                operation.log(f"✓ {msg}", "SUCCESS")
            else:
                self._log(msg, operation=operation)
        else:
            msg = "No messages found matching criteria"
            if operation:
                operation.log(f"⚠ {msg}", "WARNING")
            else:
                self._log(msg, operation=operation)

        if not message_list:
            if not operation:
                self._log("No messages found matching criteria", operation=operation)
            return {"messages_found": 0, "messages_archived": 0, "skipped": 0, "archive_file": None}

        # Filter out already-archived messages if incremental
        # Uses instant set difference - O(n) with no API calls
        # Only checks non-NULL gmail_ids (NULL = deleted from Gmail = can't be duplicate)
        message_ids = [msg["id"] for msg in message_list]
        if incremental:
            # DBManager will auto-create v1.1 database if it doesn't exist
            # We use validate_schema=False to allow working with v1.0 databases too
            db_path = Path(self.state_db_path)
            try:
                db = DBManager(str(db_path), validate_schema=False, auto_create=True)
                # Get only non-NULL gmail_ids (NULL means message deleted from Gmail)
                cursor = db.conn.execute("SELECT gmail_id FROM messages WHERE gmail_id IS NOT NULL")
                archived_ids = {row[0] for row in cursor.fetchall()}
                db.close()
            except Exception:
                # If query fails, database might be empty or table doesn't exist yet
                archived_ids = set()

            original_count = len(message_ids)
            message_ids = [mid for mid in message_ids if mid not in archived_ids]
            skipped_count = original_count - len(message_ids)

            if skipped_count > 0:
                self._log(
                    f"Skipping {skipped_count} already-archived messages (by gmail_id)",
                    operation=operation,
                )

        # Note: Phase 2 (RFC Message-ID checking) has been removed in v1.4.0
        # With proper Gmail ID capture during import:
        # - Messages with real Gmail IDs are caught by the filter above
        # - Messages with NULL gmail_id were deleted from Gmail, so cannot be duplicates
        # This provides instant O(n) deduplication with zero API calls

        if not message_ids:
            self._log("All messages already archived", operation=operation)
            return {
                "messages_found": len(message_list),
                "messages_archived": 0,
                "skipped": len(message_list),
                "archive_file": output_file,
            }

        if dry_run:
            msg = f"DRY RUN: Would archive {len(message_ids)} messages to {output_file}"
            self._log(msg, operation=operation)
            if compress:
                self._log(f"With {compress} compression", operation=operation)
            return {
                "messages_found": len(message_list),
                "messages_to_archive": len(message_ids),
                "dry_run": True,
            }

        # Create session if not resuming
        if not resuming:
            session_id = str(uuid.uuid4())
            db = DBManager(str(self.state_db_path), validate_schema=False, auto_create=True)
            db.create_session(
                session_id=session_id,
                target_file=output_file,
                query=query,
                message_ids=message_ids,
                compression=compress,
            )
            db.close()
            msg = f"Created archive session: {len(message_ids)} messages to process"
            self._log(msg, operation=operation)

        # Fetch and archive messages
        archive_result = self._archive_messages(
            message_ids,
            output_file,
            compress,
            operation,
            session_id=session_id,
        )

        # Record run in state
        # DBManager already recorded this via _record_archive_run during each message
        # for v1.1 schema, so nothing more to do here

        return {
            "messages_found": len(message_list),
            "messages_archived": archive_result["archived"],
            "messages_failed": archive_result["failed"],
            "skipped": len(message_list) - len(message_ids),
            "archive_file": output_file,
            "actual_file": archive_result.get("actual_file", output_file),
            "interrupted": archive_result.get("interrupted", False),
        }

    def _archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch messages and write to mbox archive using HybridStorage.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path
            compress: Compression format
            operation: Optional operation handle for live progress tracking (v1.3.2+)
            session_id: Optional session ID for resumable operations (v1.3.6+)

        Returns:
            Dict with archived count and failed count
        """
        # Initialize DBManager and HybridStorage
        # DBManager will auto-create v1.1 database if it doesn't exist
        try:
            # Initialize DBManager - auto-creates v1.1 schema if needed
            self.db_manager = DBManager(
                str(self.state_db_path),
                validate_schema=False,  # Don't validate to allow migration from v1.0
                auto_create=True,
            )
            self.hybrid_storage = HybridStorage(self.db_manager)
            return self._archive_messages_hybrid_storage(
                message_ids, output_file, compress, operation, session_id
            )
        except Exception as e:
            # If DBManager fails completely, we have a serious issue
            raise RuntimeError(f"Failed to initialize database: {e}") from e

    def _archive_messages_hybrid_storage(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Archive messages using HybridStorage for atomic operations.

        Uses a .partial file during operation to support resumable archives.
        The partial file is renamed to the final file on successful completion.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path (final destination)
            compress: Compression format
            operation: Optional operation handle for live progress tracking (v1.3.2+)
            session_id: Optional session ID for resumable operations (v1.3.6+)

        Returns:
            Dict with archived count and failed count
        """
        output_path = Path(output_file)
        # Use partial file during operation for resumability
        partial_path = Path(str(output_file) + ".partial")
        archived_count = 0
        failed_count = 0

        assert self.hybrid_storage is not None, "HybridStorage not initialized"
        assert self.db_manager is not None, "DBManager not initialized"

        # Log initial status if operation handle provided
        if operation:
            operation.log(f"Processing {len(message_ids)} messages", "INFO")
            # Set total for progress tracking now that we know the count
            operation.set_total(len(message_ids), "Archiving messages")

        # Install SIGINT handler for graceful Ctrl+C
        self._install_sigint_handler()
        interrupted = False

        # Fetch messages in batches
        try:
            for i, message in enumerate(self.client.get_messages_batch(message_ids), 1):
                # Check for interrupt BEFORE processing (handles signal between iterations)
                if self._interrupted.is_set():
                    interrupted = True
                    self._log(
                        "Interrupt received - saving progress...", "WARNING", operation=operation
                    )
                    break

                try:
                    # Decode raw message
                    raw_email = self.client.decode_message_raw(message)

                    # Parse email
                    msg = email.message_from_bytes(raw_email, policy=policy.default)

                    # Extract subject for logging
                    subject = msg.get("Subject", "No Subject")

                    # Extract Gmail labels as JSON
                    labels = None
                    if "labelIds" in message:
                        import json

                        labels = json.dumps(message["labelIds"])

                    # Archive using HybridStorage to PARTIAL file (atomic operation)
                    # Note: We archive to partial_path but store output_file in DB
                    # so resume logic can find the right session
                    result = self.hybrid_storage.archive_message(
                        email_message=msg,
                        gmail_id=message["id"],
                        archive_file=partial_path,
                        thread_id=message.get("threadId"),
                        labels=labels,
                        compression=None,  # No compression during partial - compress at end
                    )

                    # Check if message was actually archived or skipped as duplicate
                    if result is None:
                        # Message was skipped (duplicate rfc_message_id)
                        if operation:
                            truncated_subject = subject[:60] if len(subject) > 60 else subject
                            operation.log(f"Skipped (duplicate): {truncated_subject}", "WARNING")
                            operation.update_progress(1)
                        continue

                    archived_count += 1

                    # Log success to operation handle
                    if operation:
                        # Truncate subject to 60 chars for readability
                        truncated_subject = subject[:60] if len(subject) > 60 else subject
                        operation.log(f"Archived: {truncated_subject}", "SUCCESS")
                        operation.update_progress(1)

                    # Update session progress every 100 messages
                    if session_id and archived_count % 100 == 0:
                        self.db_manager.update_session_progress(session_id, archived_count)

                except KeyboardInterrupt:
                    # Ctrl+C pressed - exit loop gracefully
                    interrupted = True
                    self._log(
                        "Interrupt received - saving progress...", "WARNING", operation=operation
                    )
                    break

                except Exception as e:
                    # Log error but continue with next message
                    msg_id = message["id"]
                    error_msg = f"Failed to archive message {msg_id}: {e}"

                    # Log to operation handle if available
                    if operation:
                        operation.log(error_msg, "ERROR")
                    else:
                        self._log(f"Warning: {error_msg}", "WARNING")

                    failed_count += 1

                # Check for Ctrl+C interrupt via signal handler - exit loop gracefully
                if self._interrupted.is_set():
                    interrupted = True
                    self._log(
                        "Interrupt received - saving progress...", "WARNING", operation=operation
                    )
                    break

            # Update progress regardless of interrupt status
            if archived_count > 0 and session_id:
                self.db_manager.update_session_progress(session_id, archived_count)

            # Only finalize (rename/compress) if NOT interrupted
            if archived_count > 0 and not interrupted:
                # Compress if requested
                if compress:
                    self._log(f"Compressing with {compress}...", operation=operation)
                    # Compress from partial file if it exists, otherwise from output
                    source_path = partial_path if partial_path.exists() else output_path
                    if source_path.exists():
                        self._compress_archive(source_path, output_path, compress)
                        # Remove uncompressed source file (if it's the partial)
                        if partial_path.exists():
                            partial_path.unlink(missing_ok=True)
                    final_path = output_path
                else:
                    # Rename partial to final (only if partial exists)
                    if partial_path.exists():
                        partial_path.rename(output_path)
                        final_path = output_path
                    elif output_path.exists():
                        # File was written directly to output_path (e.g., in tests)
                        final_path = output_path
                    else:
                        # Neither file exists - unexpected state
                        final_path = output_path

                # Mark session as complete
                if session_id:
                    self.db_manager.complete_session(session_id)

                # Update archive_file in messages table to point to final file
                # (messages were recorded with partial_path)
                self.db_manager.conn.execute(
                    "UPDATE messages SET archive_file = ? WHERE archive_file = ?",
                    (str(final_path), str(partial_path)),
                )
                self.db_manager.commit()
            elif interrupted:
                # Interrupted - keep partial file for resumption
                final_path = partial_path
                self._log(
                    f"Progress saved: {archived_count}/{len(message_ids)} messages",
                    "INFO",
                    operation=operation,
                )
                self._log("Run the same command again to resume", "INFO", operation=operation)
            else:
                final_path = partial_path

        except KeyboardInterrupt:
            # Handle KeyboardInterrupt at outer level (during batch fetch)
            interrupted = True
            final_path = partial_path
            self._log("Interrupt received - saving progress...", "WARNING", operation=operation)
            if archived_count > 0 and session_id and self.db_manager:
                self.db_manager.update_session_progress(session_id, archived_count)

        finally:
            # Restore original SIGINT handler
            self._restore_sigint_handler()
            # Close DBManager to prevent resource warnings
            if self.db_manager:
                self.db_manager.close()

        # Print summary (route through operation handle if available)
        file_size = final_path.stat().st_size if final_path.exists() else 0
        self._log(f"Archived {archived_count} messages", "SUCCESS", operation=operation)
        if failed_count > 0:
            fail_msg = f"Failed: {failed_count} messages (errors during archiving)"
            self._log(fail_msg, "WARNING", operation=operation)
        self._log(f"File: {final_path}", operation=operation)
        self._log(f"Size: {format_bytes(file_size)}", operation=operation)

        return {
            "archived": archived_count,
            "failed": failed_count,
            "attempted": len(message_ids),
            "interrupted": interrupted,
            "actual_file": str(final_path),  # The actual file where data was written
        }

    def _compress_archive(self, source_path: Path, dest_path: Path, compress_format: str) -> None:
        """
        Compress mbox archive.

        Args:
            source_path: Source mbox file
            dest_path: Destination compressed file
            compress_format: Compression format ('gzip', 'lzma', or 'zstd')
        """
        self._log(f"\nCompressing with {compress_format}...", "INFO")

        if compress_format == "gzip":
            with open(source_path, "rb") as f_in:
                with gzip.open(dest_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compress_format == "lzma":
            with open(source_path, "rb") as f_in:
                with lzma.open(dest_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compress_format == "zstd":
            # Zstandard: fast compression with excellent ratios (Python 3.14+ stdlib)
            # Level 3 is default (good balance), max is 22
            with open(source_path, "rb") as f_in:
                with zstd.open(dest_path, "wb", level=3) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            raise ValueError(
                f"Unsupported compression format: {compress_format}. Supported: gzip, lzma, zstd"
            )

    def validate_archive(self, archive_file: str, expected_message_ids: set[str]) -> dict[str, Any]:
        """
        Validate archive integrity.

        Args:
            archive_file: Path to archive file
            expected_message_ids: Set of expected message IDs

        Returns:
            Validation results dict with 'passed' key and check details
        """
        validator = ArchiveValidator(archive_file, self.state_db_path, output=self.output)
        results = validator.validate_comprehensive(expected_message_ids)
        # Don't call validator.report() - let caller handle display
        return results

    def _extract_rfc_message_id(self, msg: email.message.Message) -> str:
        """
        Extract RFC 2822 Message-ID from email message.

        Args:
            msg: Email message

        Returns:
            Message-ID header value (or generated fallback)
        """
        import hashlib

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

    def delete_archived_messages(self, message_ids: list[str], permanent: bool = False) -> int:
        """
        Delete messages (trash or permanent).

        Args:
            message_ids: List of message IDs to delete
            permanent: If True, permanently delete; otherwise move to trash

        Returns:
            Number of messages deleted
        """
        if permanent:
            self._log(f"Permanently deleting {len(message_ids)} messages...", "INFO")
            count = self.client.delete_messages_permanent(message_ids)
            self._log(f"✓ Permanently deleted {count} messages", "SUCCESS")
        else:
            self._log(f"Moving {len(message_ids)} messages to trash...", "INFO")
            count = self.client.trash_messages(message_ids)
            self._log(f"✓ Moved {count} messages to trash (30-day recovery)", "SUCCESS")

        return count
