"""MessageWriter - Internal module for writing messages to mbox archives.

This is an internal implementation detail of the archiver package.
DO NOT import or use this module outside of the archiver package.
Public API is exposed through GmailArchiver class.

Phase 1.6 - Extracted from archiver_legacy.py for clean architecture.
"""

import email
import gzip
import json
import lzma
import shutil
import signal
import threading
import uuid
from compression import zstd
from email import policy
from pathlib import Path
from typing import Any

from gmailarchiver.cli.output import OperationHandle
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.input_validator import validate_compression_format
from gmailarchiver.shared.utils import format_bytes


class MessageWriter:
    """Write Gmail messages to mbox archive with hybrid storage.

    Internal module - not part of public API.
    Handles the write phase of archiving workflow.
    """

    def __init__(self, gmail_client: GmailClient, state_db_path: str) -> None:
        """Initialize MessageWriter with Gmail client and database path.

        Args:
            gmail_client: Gmail API client for fetching messages
            state_db_path: Path to state database for metadata tracking
        """
        self.client = gmail_client
        self.state_db_path = state_db_path
        self.db_manager: DBManager | None = None
        self.hybrid_storage: HybridStorage | None = None
        self._interrupted = threading.Event()
        self._original_sigint_handler: Any = None

    def archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
    ) -> dict[str, Any]:
        """Archive messages to mbox file with hybrid storage.

        Args:
            message_ids: List of Gmail message IDs to archive
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            operation: Optional operation handle for progress tracking

        Returns:
            Dict with keys:
                - archived_count: Number of successfully archived messages
                - failed_count: Number of failed messages
                - interrupted: Whether operation was interrupted
                - actual_file: Actual file path where messages were written
        """
        # Validate compression format first (raises InvalidInputError if invalid)
        compress = validate_compression_format(compress)

        # Return early if no messages to archive
        if not message_ids:
            return {
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
                "actual_file": output_file,
            }

        # Initialize storage managers
        self.db_manager = DBManager(self.state_db_path, validate_schema=False, auto_create=True)
        self.hybrid_storage = HybridStorage(self.db_manager)

        # Create session for tracking progress
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
            # Archive messages using helper method
            result = self._archive_messages(
                message_ids,
                output_file,
                compress,
                operation,
                session_id=session_id,
            )

            # Clean up database connection
            self.db_manager.close()

            # Map helper result to expected output format
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

    def _archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        operation: OperationHandle | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Archive messages using HybridStorage for atomic operations.

        Uses a .partial file during operation to support resumable archives.
        The partial file is renamed to the final file on successful completion.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path (final destination)
            compress: Compression format
            operation: Optional operation handle for progress tracking
            session_id: Optional session ID for resumable operations

        Returns:
            Dict with keys: archived, failed, interrupted, actual_file
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
        """Compress mbox archive.

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

    def _log(
        self, message: str, level: str = "INFO", operation: OperationHandle | None = None
    ) -> None:
        """Log a message either through operation handle or print."""
        if operation:
            operation.log(message, level)
        else:
            print(message)

    def _install_sigint_handler(self) -> None:
        """Install SIGINT handler for graceful interruption."""

        def sigint_handler(signum: int, frame: Any) -> None:
            self._interrupted.set()

        self._original_sigint_handler = signal.signal(signal.SIGINT, sigint_handler)

    def _restore_sigint_handler(self) -> None:
        """Restore original SIGINT handler."""
        if self._original_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._original_sigint_handler)
