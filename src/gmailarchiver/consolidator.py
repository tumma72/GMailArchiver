"""Archive consolidation for merging multiple mbox files."""

import gzip
import lzma
import mailbox
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from gmailarchiver.state import ArchiveState


@dataclass
class ConsolidationResult:
    """Result of consolidating multiple archives."""

    output_file: str
    source_files: list[str]
    total_messages: int
    duplicates_removed: int
    messages_consolidated: int
    execution_time_ms: float
    sort_applied: bool
    compression_used: str | None


class ArchiveConsolidator:
    """Consolidate multiple mbox archives into a single archive."""

    def __init__(self, state_db_path: str) -> None:
        """Initialize consolidator with database path."""
        self.state_db_path = state_db_path

    def consolidate(
        self,
        source_archives: list[str | Path],
        output_archive: str | Path,
        sort_by_date: bool = True,
        deduplicate: bool = True,
        dedupe_strategy: str = 'newest',
        compress: str | None = None,
    ) -> ConsolidationResult:
        """
        Consolidate multiple archives into one.

        Args:
            source_archives: List of source archive paths to merge
            output_archive: Path to output consolidated archive
            sort_by_date: Sort messages chronologically by date
            deduplicate: Remove duplicate messages
            dedupe_strategy: Strategy for choosing which duplicate to keep
                ('newest', 'largest', 'first')
            compress: Compression format ('gzip', 'lzma', 'zstd', or None)

        Returns:
            ConsolidationResult with consolidation statistics

        Raises:
            ValueError: If source_archives is empty or dedupe_strategy is invalid
            FileNotFoundError: If any source archive doesn't exist
        """
        start_time = time.perf_counter()

        # Validate inputs
        if not source_archives:
            raise ValueError("source_archives cannot be empty")

        valid_strategies = ('newest', 'largest', 'first')
        if deduplicate and dedupe_strategy not in valid_strategies:
            raise ValueError(f"Invalid dedupe_strategy: {dedupe_strategy}. "
                           f"Must be one of {valid_strategies}")

        # Convert paths
        source_paths = [Path(p) for p in source_archives]
        output_path = Path(output_archive)

        # Verify source files exist
        for source_path in source_paths:
            if not source_path.exists():
                raise FileNotFoundError(f"Source archive not found: {source_path}")

        # Collect messages from all archives
        messages = self._collect_messages(source_paths)
        total_messages = len(messages)

        # Sort if requested
        if sort_by_date:
            messages = self._sort_messages(messages)

        # Deduplicate if requested
        duplicates_removed = 0
        if deduplicate:
            messages, duplicates_removed = self._deduplicate_messages(
                messages, dedupe_strategy
            )

        # Write consolidated archive
        offsets = self._write_consolidated_mbox(messages, output_path, compress)

        # Update database
        self._update_database(
            offsets,
            str(output_path),
            [str(p) for p in source_paths],
            duplicates_removed
        )

        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000

        return ConsolidationResult(
            output_file=str(output_path),
            source_files=[str(p) for p in source_paths],
            total_messages=total_messages,
            duplicates_removed=duplicates_removed,
            messages_consolidated=len(messages),
            execution_time_ms=execution_time_ms,
            sort_applied=sort_by_date,
            compression_used=compress,
        )

    def _collect_messages(self, source_archives: list[Path]) -> list[dict]:
        """Collect all messages from source archives."""
        messages = []

        for archive_path in source_archives:
            # Handle compressed archives
            if archive_path.suffix == '.gz':
                # Decompress to temporary file
                import tempfile
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.mbox', delete=False) as tmp:
                    with gzip.open(archive_path, 'rb') as gz:
                        tmp.write(gz.read())
                    tmp_path = tmp.name

                mbox = mailbox.mbox(tmp_path)
            else:
                mbox = mailbox.mbox(str(archive_path))

            try:
                for key in mbox.keys():
                    msg = mbox[key]

                    # Parse date for sorting
                    date_str = msg.get('Date', '')
                    date_timestamp = self._parse_date(date_str)

                    # Get Message-ID
                    rfc_message_id = msg.get('Message-ID', '')

                    messages.append({
                        'message': msg,
                        'rfc_message_id': rfc_message_id,
                        'date': date_timestamp,
                        'source_archive': str(archive_path),
                        'original_key': key,
                    })
            finally:
                mbox.close()

                # Clean up temp file if decompressed
                if archive_path.suffix == '.gz':
                    Path(tmp_path).unlink()

        return messages

    def _parse_date(self, date_str: str) -> float:
        """Parse email Date header to timestamp."""
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except (ValueError, TypeError):
            # Return epoch for invalid dates (sorts to beginning)
            return 0.0

    def _sort_messages(self, messages: list[dict]) -> list[dict]:
        """Sort messages by date timestamp."""
        return sorted(messages, key=lambda m: m['date'])

    def _deduplicate_messages(
        self, messages: list[dict], strategy: str
    ) -> tuple[list[dict], int]:
        """Remove duplicates using specified strategy."""
        # Group by Message-ID
        by_message_id: dict[str, list[dict]] = {}
        for msg_dict in messages:
            msg_id = msg_dict['rfc_message_id']
            if msg_id not in by_message_id:
                by_message_id[msg_id] = []
            by_message_id[msg_id].append(msg_dict)

        # Apply strategy to duplicates
        kept_messages = []
        duplicates_removed = 0

        for msg_id, msg_list in by_message_id.items():
            if len(msg_list) == 1:
                # No duplicates
                kept_messages.append(msg_list[0])
            else:
                # Apply strategy
                if strategy == 'newest':
                    kept = max(msg_list, key=lambda m: m['date'])
                elif strategy == 'largest':
                    kept = max(msg_list, key=lambda m: len(m['message'].as_bytes()))
                else:  # 'first'
                    kept = msg_list[0]

                kept_messages.append(kept)
                duplicates_removed += len(msg_list) - 1

        return kept_messages, duplicates_removed

    def _write_consolidated_mbox(
        self,
        messages: list[dict],
        output_path: Path,
        compress: str | None,
    ) -> dict[str, tuple[int, int]]:
        """Write messages to new mbox and track offsets."""
        offsets: dict[str, tuple[int, int]] = {}

        if compress == 'gzip':
            # Write to compressed file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.mbox', delete=False) as tmp:
                tmp_path = Path(tmp.name)

            # Write to temp mbox first
            mbox = mailbox.mbox(str(tmp_path))
            mbox.lock()

            try:
                for msg_dict in messages:
                    msg = msg_dict['message']
                    msg_id = msg_dict['rfc_message_id']

                    # Get offset before writing
                    with open(tmp_path, 'rb') as f:
                        f.seek(0, 2)  # End of file
                        offset = f.tell()

                    mbox.add(msg)
                    mbox.flush()

                    # Calculate length
                    with open(tmp_path, 'rb') as f:
                        f.seek(0, 2)
                        length = f.tell() - offset

                    offsets[msg_id] = (offset, length)
            finally:
                mbox.unlock()
                mbox.close()

            # Compress to output
            with open(tmp_path, 'rb') as f_in:
                with gzip.open(output_path, 'wb') as f_out:
                    f_out.write(f_in.read())

            # Clean up temp file
            tmp_path.unlink()

        else:
            # Write uncompressed
            mbox = mailbox.mbox(str(output_path))
            mbox.lock()

            try:
                for msg_dict in messages:
                    msg = msg_dict['message']
                    msg_id = msg_dict['rfc_message_id']

                    # Get offset before writing
                    with open(output_path, 'rb') as f:
                        f.seek(0, 2)  # End of file
                        offset = f.tell()

                    mbox.add(msg)
                    mbox.flush()

                    # Calculate length
                    with open(output_path, 'rb') as f:
                        f.seek(0, 2)
                        length = f.tell() - offset

                    offsets[msg_id] = (offset, length)
            finally:
                mbox.unlock()
                mbox.close()

        return offsets

    def _update_database(
        self,
        offsets: dict[str, tuple[int, int]],
        output_file: str,
        source_files: list[str],
        duplicates_removed: int,
    ) -> None:
        """Update database with new archive file and offsets."""
        with ArchiveState(self.state_db_path, validate_path=False) as state:
            # Get gmail_ids to remove (duplicates)
            gmail_ids_to_remove = []

            if duplicates_removed > 0:
                # Find duplicate entries (multiple gmail_ids with same rfc_message_id)
                for msg_id in offsets.keys():
                    cursor = state.conn.execute('''
                        SELECT gmail_id FROM messages
                        WHERE rfc_message_id = ?
                        ORDER BY archived_timestamp DESC
                    ''', (msg_id,))
                    rows = cursor.fetchall()

                    # Keep first (newest), remove rest
                    if len(rows) > 1:
                        gmail_ids_to_remove.extend([row[0] for row in rows[1:]])

                # Delete duplicate entries
                for gmail_id in gmail_ids_to_remove:
                    state.conn.execute('''
                        DELETE FROM messages WHERE gmail_id = ?
                    ''', (gmail_id,))

            # Update all messages with new archive_file and offsets
            for msg_id, (offset, length) in offsets.items():
                state.conn.execute('''
                    UPDATE messages
                    SET archive_file = ?,
                        mbox_offset = ?,
                        mbox_length = ?
                    WHERE rfc_message_id = ?
                ''', (output_file, offset, length, msg_id))

            state.conn.commit()
