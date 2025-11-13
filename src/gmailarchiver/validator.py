"""Archive validation module."""

import gzip
import hashlib
import lzma
import mailbox
import random
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import zstandard as zstd


class ArchiveValidator:
    """Validate archive integrity before deletion."""

    def __init__(self, archive_path: str, state_db_path: str = 'archive_state.db') -> None:
        """
        Initialize validator.

        Args:
            archive_path: Path to mbox archive file (compressed or uncompressed)
            state_db_path: Path to state database
        """
        self.archive_path = Path(archive_path)
        self.state_db_path = Path(state_db_path)
        self.errors: list[str] = []

    def _get_mbox_path(self) -> tuple[Path, bool]:
        """
        Get path to mbox file, decompressing if necessary.

        Returns:
            Tuple of (mbox_path, is_temporary)
        """
        suffix = self.archive_path.suffix.lower()

        # If uncompressed, return as-is
        if suffix == '.mbox':
            return (self.archive_path, False)

        # Need to decompress to temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.mbox', prefix='gmailarchive_')
        temp_mbox = Path(temp_path)

        try:
            if suffix == '.gz':
                with gzip.open(self.archive_path, 'rb') as f_in:
                    with open(temp_mbox, 'wb') as f_out:
                        f_out.write(f_in.read())
            elif suffix == '.xz':
                with lzma.open(self.archive_path, 'rb') as f_in:
                    with open(temp_mbox, 'wb') as f_out:
                        f_out.write(f_in.read())
            elif suffix == '.zst':
                with zstd.open(self.archive_path, 'rb') as f_in:
                    with open(temp_mbox, 'wb') as f_out:
                        f_out.write(f_in.read())
            else:
                # Unknown compression, try as-is
                return (self.archive_path, False)

            return (temp_mbox, True)
        finally:
            # Close the file descriptor
            import os
            os.close(temp_fd)

    def validate_comprehensive(
        self,
        expected_message_ids: set[str],
        sample_size: int = 100
    ) -> dict[str, Any]:
        """
        Perform comprehensive multi-layer validation.

        Args:
            expected_message_ids: Set of Gmail message IDs that should be archived
            sample_size: Number of messages to spot-check

        Returns:
            Validation results dictionary with passed/failed status
        """
        results: dict[str, Any] = {
            'count_check': False,
            'database_check': False,
            'integrity_check': False,
            'spot_check': False,
            'errors': [],
            'passed': False
        }

        # Decompress archive if needed
        mbox_path, is_temp = self._get_mbox_path()

        try:
            # 1. Count validation
            try:
                mbox = mailbox.mbox(str(mbox_path))
                archive_count = len(mbox)
                expected_count = len(expected_message_ids)

                if archive_count == expected_count:
                    results['count_check'] = True
                else:
                    results['errors'].append(
                        f"Count mismatch: {archive_count} in archive vs "
                        f"{expected_count} expected"
                    )
            except Exception as e:
                results['errors'].append(f"Failed to read archive: {e}")
                return results

            # 2. Database cross-check
            if self.state_db_path.exists():
                try:
                    conn = sqlite3.connect(str(self.state_db_path))
                    cursor = conn.execute('SELECT COUNT(*) FROM archived_messages')
                    db_count_result = cursor.fetchone()
                    db_count = db_count_result[0] if db_count_result else 0
                    conn.close()

                    if db_count >= expected_count:
                        results['database_check'] = True
                    else:
                        results['errors'].append(
                            f"DB count mismatch: {db_count} in DB vs {expected_count} expected"
                        )
                except Exception as e:
                    results['errors'].append(f"Database check failed: {e}")
            else:
                results['errors'].append("State database not found")

            # 3. Content integrity check
            try:
                message_count = 0
                for msg in mbox:
                    message_count += 1

                if message_count > 0:
                    results['integrity_check'] = True
                else:
                    results['errors'].append("Archive contains no readable messages")
            except Exception as e:
                results['errors'].append(f"Integrity check failed: {e}")

            # 4. Spot check sampling
            if expected_message_ids and self.state_db_path.exists():
                try:
                    # Sample messages to verify
                    sample_count = min(sample_size, len(expected_message_ids))
                    sample_ids = random.sample(list(expected_message_ids), sample_count)

                    conn = sqlite3.connect(str(self.state_db_path))
                    found = 0

                    for msg_id in sample_ids:
                        cursor = conn.execute(
                            'SELECT 1 FROM archived_messages WHERE gmail_id = ?',
                            (msg_id,)
                        )
                        if cursor.fetchone():
                            found += 1

                    conn.close()

                    if found == sample_count:
                        results['spot_check'] = True
                    else:
                        results['errors'].append(
                            f"Spot check: {found}/{sample_count} messages found in DB"
                        )
                except Exception as e:
                    results['errors'].append(f"Spot check failed: {e}")

            # Overall pass/fail
            results['passed'] = all([
                results['count_check'],
                results['database_check'],
                results['integrity_check'],
                results['spot_check'] or not expected_message_ids
            ])

            return results
        finally:
            # Clean up temporary file if created
            if is_temp and mbox_path.exists():
                mbox_path.unlink()

    def validate_count(self, expected_count: int) -> bool:
        """
        Validate archive message count.

        Args:
            expected_count: Expected number of messages

        Returns:
            True if counts match
        """
        try:
            mbox = mailbox.mbox(str(self.archive_path))
            actual_count = len(mbox)
            return actual_count == expected_count
        except Exception as e:
            self.errors.append(f"Count validation failed: {e}")
            return False

    def compute_checksum(self, data: bytes) -> str:
        """
        Compute SHA256 checksum of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal digest
        """
        return hashlib.sha256(data).hexdigest()

    def report(self, results: dict[str, Any]) -> None:
        """
        Print validation report.

        Args:
            results: Validation results from validate_comprehensive()
        """
        print("\n" + "="*60)
        print("ARCHIVE VALIDATION REPORT")
        print("="*60)

        checks = [
            ('Count Check', results['count_check']),
            ('Database Check', results['database_check']),
            ('Integrity Check', results['integrity_check']),
            ('Spot Check', results['spot_check'])
        ]

        for name, passed in checks:
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{name:20s} {status}")

        if results['errors']:
            print("\nErrors:")
            for error in results['errors']:
                print(f"  - {error}")

        print("\n" + "="*60)
        if results['passed']:
            print("VALIDATION: ✓ PASSED")
        else:
            print("VALIDATION: ✗ FAILED")
        print("="*60 + "\n")
