"""MessageWriter - Internal module for writing messages to mbox archives.

This is an internal implementation detail of the archiver package.
DO NOT import or use this module outside of the archiver package.
Public API is exposed through GmailArchiver class.

Phase 1.6 - Extracted from archiver_legacy.py for clean architecture.
"""

import email
import json
import signal
import threading
import uuid
from email import policy
from pathlib import Path
from typing import Any

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.data.hybrid_storage import HybridStorage
from gmailarchiver.shared.input_validator import validate_compression_format
from gmailarchiver.shared.protocols import TaskHandle
from gmailarchiver.shared.utils import format_bytes


class MessageWriter:
    """Write Gmail messages to mbox archive with hybrid storage.

    Internal module - not part of public API.
    Handles the write phase of archiving workflow.
    """

    def __init__(self, gmail_client: GmailClient, storage: HybridStorage) -> None:
        """Initialize MessageWriter with Gmail client and hybrid storage.

        Args:
            gmail_client: Async Gmail API client for fetching messages
            storage: HybridStorage instance for atomic mbox+database operations
        """
        self.client = gmail_client
        self.storage = storage
        self._interrupted = threading.Event()
        self._original_sigint_handler: Any = None

    async def archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        task: TaskHandle | None = None,
        gmail_query: str | None = None,
    ) -> dict[str, Any]:
        """Archive messages to mbox file with hybrid storage.

        Args:
            message_ids: List of Gmail message IDs to archive
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            task: Optional task handle for progress tracking
            gmail_query: The Gmail search query used (for session tracking/resume)

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

        # Create session for tracking progress
        # Use the actual Gmail query if provided, otherwise generate a generic one
        session_id = str(uuid.uuid4())
        query = gmail_query or f"archive_messages({len(message_ids)} messages)"
        await self.storage.db.create_session(
            session_id=session_id,
            target_file=output_file,
            query=query,
            message_ids=message_ids,
            compression=compress,
        )

        # Archive messages using helper method
        result = await self._archive_messages(
            message_ids,
            output_file,
            compress,
            task,
            session_id=session_id,
        )

        # Map helper result to expected output format
        return {
            "archived_count": result.get("archived", 0),
            "failed_count": result.get("failed", 0),
            "interrupted": result.get("interrupted", False),
            "actual_file": result.get("actual_file", output_file),
        }

    async def _archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None,
        task: TaskHandle | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Archive messages using HybridStorage batch operation.

        This method uses batch archiving for O(n) performance instead of O(n²).
        The batch method opens the mbox file once and does a single fsync at the end.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path (final destination)
            compress: Compression format
            task: Optional task handle for progress tracking
            session_id: Optional session ID for resumable operations

        Returns:
            Dict with keys: archived, failed, interrupted, actual_file
        """
        output_path = Path(output_file)
        fetch_failed_count = 0

        # Install SIGINT handler for graceful Ctrl+C
        self._install_sigint_handler()

        # Phase 1: Fetch all messages from Gmail and prepare batch
        # This is I/O bound (network) so we do it first
        batch_messages: list[tuple[email.message.Message, str, str | None, str | None]] = []

        try:
            async for message in self.client.get_messages_batch(message_ids):
                # Check for interrupt during fetch
                if self._interrupted.is_set():
                    self._log("Interrupt during fetch - archiving fetched messages...")
                    break

                try:
                    # Decode raw message
                    raw_email = self.client.decode_message_raw(message)

                    # Parse email
                    msg = email.message_from_bytes(raw_email, policy=policy.default)

                    # Extract Gmail labels as JSON
                    labels = None
                    if "labelIds" in message:
                        labels = json.dumps(message["labelIds"])

                    # Add to batch: (email_message, gmail_id, thread_id, labels)
                    batch_messages.append(
                        (
                            msg,
                            message["id"],
                            message.get("threadId"),
                            labels,
                        )
                    )

                    # Update progress for fetch phase
                    if task:
                        task.advance(1)

                except Exception as e:
                    # Log error but continue fetching
                    msg_id = message.get("id", "unknown")
                    error_msg = f"Failed to fetch/parse message {msg_id}: {e}"
                    self._log(f"Warning: {error_msg}")
                    fetch_failed_count += 1
                    # Still advance progress even on failure
                    if task:
                        task.advance(1)

        except KeyboardInterrupt:
            self._log("Interrupt during fetch - archiving fetched messages...")

        # Phase 2: Archive all messages in a single batch operation
        # This is the performance-critical part - O(n) instead of O(n²)
        def progress_callback(gmail_id: str, subject: str, status: str) -> None:
            """Report progress for each message with Log Window pattern."""
            if task:
                # Map status to log level for Log Window (UI_UX_CLI.md Section 7.4)
                # HybridStorage sends: "success", "skipped", "error"
                truncated_subject = (subject[:50] + "...") if len(subject) > 50 else subject
                if status == "success":
                    task.log(f"Archived: {truncated_subject}", "SUCCESS")
                elif status == "skipped":
                    task.log(f"Skipped (duplicate): {truncated_subject}", "WARNING")
                elif status == "error" or status == "failed":
                    task.log(f"Failed: {truncated_subject}", "ERROR")
                else:
                    task.log(f"{status}: {truncated_subject}", "INFO")

        try:
            result = await self.storage.archive_messages_batch(
                messages=batch_messages,
                archive_file=output_path,
                compression=compress,
                commit_interval=100,
                progress_callback=progress_callback,
                interrupt_event=self._interrupted,
                session_id=session_id,
            )

            archived_count = result["archived"]
            skipped_count = result["skipped"]
            failed_count = result["failed"] + fetch_failed_count
            interrupted = result["interrupted"]
            final_path = Path(result["actual_file"])

            # Handle interrupted state
            if interrupted:
                self._log(f"Progress saved: {archived_count}/{len(batch_messages)} messages")
                self._log("Run the same command again to resume")

        except KeyboardInterrupt:
            # Handle KeyboardInterrupt at outer level
            self._log("Interrupt received - saving progress...")
            return {
                "archived": 0,
                "failed": fetch_failed_count,
                "attempted": len(message_ids),
                "interrupted": True,
                "actual_file": str(output_path),
            }

        finally:
            # Restore original SIGINT handler
            self._restore_sigint_handler()

        # Print summary
        file_size = final_path.stat().st_size if final_path.exists() else 0
        self._log(f"Archived {archived_count} messages")
        if skipped_count > 0:
            self._log(f"Skipped: {skipped_count} duplicates")
        if failed_count > 0:
            self._log(f"Failed: {failed_count} messages (errors during archiving)")
        self._log(f"File: {final_path}")
        self._log(f"Size: {format_bytes(file_size)}")

        return {
            "archived": archived_count,
            "failed": failed_count,
            "attempted": len(message_ids),
            "interrupted": interrupted,
            "actual_file": str(final_path),
        }

    def _log(self, message: str) -> None:
        """Log a message to stdout."""
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
