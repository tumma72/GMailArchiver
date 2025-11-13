"""Core archiving logic for Gmail messages."""

import email
import gzip
import lzma
import mailbox
import shutil
from email import policy
from pathlib import Path
from typing import Any

import zstandard as zstd
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .gmail_client import GmailClient
from .input_validator import validate_age_expression, validate_compression_format
from .state import ArchiveState
from .utils import datetime_to_gmail_query, format_bytes, parse_age
from .validator import ArchiveValidator


class GmailArchiver:
    """Main archiving orchestrator."""

    def __init__(
        self,
        gmail_client: GmailClient,
        state_db_path: str = 'archive_state.db'
    ) -> None:
        """
        Initialize archiver.

        Args:
            gmail_client: Gmail API client
            state_db_path: Path to state database
        """
        self.client = gmail_client
        self.state_db_path = state_db_path

    def archive(
        self,
        age_threshold: str,
        output_file: str,
        compress: str | None = None,
        incremental: bool = True,
        dry_run: bool = False
    ) -> dict[str, Any]:
        """
        Archive emails older than threshold to mbox file.

        Args:
            age_threshold: Age expression (e.g., '3y', '6m')
            output_file: Output mbox file path
            compress: Compression format ('gzip', 'lzma', 'zstd', None)
            incremental: Skip already-archived messages
            dry_run: Preview without actually archiving

        Returns:
            Dictionary with archive statistics

        Raises:
            InvalidInputError: If age_threshold or compress format is invalid
        """
        # Validate and parse age threshold
        age_threshold = validate_age_expression(age_threshold)
        compress = validate_compression_format(compress)

        cutoff_date = parse_age(age_threshold)
        query = f"before:{datetime_to_gmail_query(cutoff_date)}"

        print(f"Searching for emails older than {age_threshold} ({cutoff_date.date()})")
        print(f"Query: {query}")

        # List messages
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            task = progress.add_task("Listing messages...", total=None)
            message_list = self.client.list_messages(query)
            progress.update(task, completed=True)

        if not message_list:
            print("No messages found matching criteria")
            return {
                'messages_found': 0,
                'messages_archived': 0,
                'skipped': 0,
                'archive_file': None
            }

        print(f"Found {len(message_list)} messages")

        # Filter out already-archived messages if incremental
        message_ids = [msg['id'] for msg in message_list]
        if incremental:
            with ArchiveState(self.state_db_path) as state:
                archived_ids = state.get_archived_message_ids()
                original_count = len(message_ids)
                message_ids = [mid for mid in message_ids if mid not in archived_ids]
                skipped_count = original_count - len(message_ids)

                if skipped_count > 0:
                    print(f"Skipping {skipped_count} already-archived messages")

        if not message_ids:
            print("All messages already archived")
            return {
                'messages_found': len(message_list),
                'messages_archived': 0,
                'skipped': len(message_list),
                'archive_file': output_file
            }

        if dry_run:
            print(f"\nDRY RUN: Would archive {len(message_ids)} messages to {output_file}")
            if compress:
                print(f"          With {compress} compression")
            return {
                'messages_found': len(message_list),
                'messages_to_archive': len(message_ids),
                'dry_run': True
            }

        # Fetch and archive messages
        archive_result = self._archive_messages(
            message_ids,
            output_file,
            compress
        )

        # Record run in state
        with ArchiveState(self.state_db_path) as state:
            state.record_archive_run(
                query=query,
                messages_archived=archive_result['archived'],
                archive_file=output_file
            )

        return {
            'messages_found': len(message_list),
            'messages_archived': archive_result['archived'],
            'messages_failed': archive_result['failed'],
            'skipped': len(message_list) - len(message_ids),
            'archive_file': output_file
        }

    def _archive_messages(
        self,
        message_ids: list[str],
        output_file: str,
        compress: str | None = None
    ) -> dict[str, Any]:
        """
        Fetch messages and write to mbox archive.

        Args:
            message_ids: List of Gmail message IDs
            output_file: Output file path
            compress: Compression format

        Returns:
            Dict with archived count and failed count
        """
        output_path = Path(output_file)
        temp_mbox_path = output_path if not compress else output_path.with_suffix('.mbox')

        # Clean up any orphaned lock files from previous runs
        lock_file = Path(str(temp_mbox_path) + '.lock')
        if lock_file.exists():
            print(f"Warning: Removing orphaned lock file: {lock_file}")
            lock_file.unlink()

        # Create mbox file
        mbox = mailbox.mbox(str(temp_mbox_path))
        mbox.lock()

        try:
            archived_count = 0
            validator = ArchiveValidator(str(output_path), self.state_db_path)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task(
                    "Archiving messages...",
                    total=len(message_ids)
                )

                # Fetch messages in batches
                with ArchiveState(self.state_db_path) as state:
                    for message in self.client.get_messages_batch(message_ids):
                        # Decode raw message
                        raw_email = self.client.decode_message_raw(message)

                        # Parse email
                        msg = email.message_from_bytes(raw_email, policy=policy.default)

                        # Add to mbox
                        mbox.add(msg)

                        # Track in database
                        checksum = validator.compute_checksum(raw_email)

                        state.mark_archived(
                            gmail_id=message['id'],
                            archive_file=output_file,
                            subject=msg.get('Subject'),
                            from_addr=msg.get('From'),
                            message_date=msg.get('Date'),
                            checksum=checksum
                        )

                        archived_count += 1
                        progress.advance(task)

            mbox.flush()

        finally:
            # Ensure mbox is properly unlocked and closed
            try:
                mbox.unlock()
            except Exception as e:
                print(f"Warning: Failed to unlock mbox: {e}")
            try:
                mbox.close()
            except Exception as e:
                print(f"Warning: Failed to close mbox: {e}")

        # Compress if requested
        if compress:
            self._compress_archive(temp_mbox_path, output_path, compress)
            # Remove uncompressed file AND its lock file
            temp_mbox_path.unlink()
            lock_file = Path(str(temp_mbox_path) + '.lock')
            if lock_file.exists():
                lock_file.unlink()

        # Calculate stats
        attempted = len(message_ids)
        failed = attempted - archived_count

        # Print summary
        final_path = output_path
        file_size = final_path.stat().st_size if final_path.exists() else 0
        print(f"\n✓ Archived {archived_count} messages")
        if failed > 0:
            print(f"  ⚠ Failed: {failed} messages (deleted/moved during archiving)")
        print(f"  File: {final_path}")
        print(f"  Size: {format_bytes(file_size)}")

        return {
            'archived': archived_count,
            'failed': failed,
            'attempted': attempted
        }

    def _compress_archive(
        self,
        source_path: Path,
        dest_path: Path,
        compress_format: str
    ) -> None:
        """
        Compress mbox archive.

        Args:
            source_path: Source mbox file
            dest_path: Destination compressed file
            compress_format: Compression format ('gzip', 'lzma', or 'zstd')
        """
        print(f"\nCompressing with {compress_format}...")

        if compress_format == 'gzip':
            with open(source_path, 'rb') as f_in:
                with gzip.open(dest_path, 'wb', compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compress_format == 'lzma':
            with open(source_path, 'rb') as f_in:
                with lzma.open(dest_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        elif compress_format == 'zstd':
            # Zstandard: fast compression with excellent ratios (Python 3.14+ stdlib)
            # Level 3 is default (good balance), max is 22
            with open(source_path, 'rb') as f_in:
                with zstd.open(dest_path, 'wb', level=3) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            raise ValueError(
                f"Unsupported compression format: {compress_format}. "
                "Supported: gzip, lzma, zstd"
            )

    def validate_archive(
        self,
        archive_file: str,
        expected_message_ids: set[str]
    ) -> bool:
        """
        Validate archive integrity.

        Args:
            archive_file: Path to archive file
            expected_message_ids: Set of expected message IDs

        Returns:
            True if validation passes
        """
        validator = ArchiveValidator(archive_file, self.state_db_path)
        results = validator.validate_comprehensive(expected_message_ids)
        validator.report(results)
        return results['passed']  # type: ignore[no-any-return]

    def delete_archived_messages(
        self,
        message_ids: list[str],
        permanent: bool = False
    ) -> int:
        """
        Delete messages (trash or permanent).

        Args:
            message_ids: List of message IDs to delete
            permanent: If True, permanently delete; otherwise move to trash

        Returns:
            Number of messages deleted
        """
        if permanent:
            print(f"Permanently deleting {len(message_ids)} messages...")
            count = self.client.delete_messages_permanent(message_ids)
            print(f"✓ Permanently deleted {count} messages")
        else:
            print(f"Moving {len(message_ids)} messages to trash...")
            count = self.client.trash_messages(message_ids)
            print(f"✓ Moved {count} messages to trash (30-day recovery)")

        return count
