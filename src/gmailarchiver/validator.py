"""Archive validation module."""

import email
import gzip
import hashlib
import lzma
import mailbox
import random
import sqlite3
import tempfile
from compression import zstd
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OffsetVerificationResult:
    """Result from offset verification."""

    total_checked: int
    successful_reads: int
    failed_reads: int
    accuracy_percentage: float
    failures: list[str] = field(default_factory=list)
    skipped: bool = False


@dataclass
class ConsistencyReport:
    """Report from consistency checks."""

    schema_version: str
    orphaned_records: int
    missing_records: int
    duplicate_gmail_ids: int
    duplicate_rfc_message_ids: int
    fts_synced: bool
    passed: bool
    errors: list[str] = field(default_factory=list)


class ArchiveValidator:
    """Validate archive integrity before deletion."""

    def __init__(
        self, archive_path: str, state_db_path: str = "archive_state.db", output: Any | None = None
    ) -> None:
        """
        Initialize validator.

        Args:
            archive_path: Path to mbox archive file (compressed or uncompressed)
            state_db_path: Path to state database
            output: Optional OutputManager for structured logging
        """
        self.archive_path = Path(archive_path)
        self.state_db_path = Path(state_db_path)
        self.errors: list[str] = []
        self.output = output

    def _log(self, message: str, level: str = "INFO") -> None:
        """Log message through OutputManager if available, otherwise print.

        Args:
            message: Message to log
            level: Severity level (INFO, WARNING, ERROR, SUCCESS)
        """
        if self.output:
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

    def _get_mbox_path(self) -> tuple[Path, bool]:
        """
        Get path to mbox file, decompressing if necessary.

        Returns:
            Tuple of (mbox_path, is_temporary)
        """
        suffix = self.archive_path.suffix.lower()

        # If uncompressed, return as-is
        if suffix == ".mbox":
            return (self.archive_path, False)

        # Need to decompress to temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix=".mbox", prefix="gmailarchive_")
        temp_mbox = Path(temp_path)

        try:
            if suffix == ".gz":
                with gzip.open(self.archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
                        f_out.write(f_in.read())
            elif suffix == ".xz":
                with lzma.open(self.archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
                        f_out.write(f_in.read())
            elif suffix == ".zst":
                with zstd.open(self.archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
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
        self, expected_message_ids: set[str], sample_size: int = 100
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
            "count_check": False,
            "database_check": False,
            "integrity_check": False,
            "spot_check": False,
            "errors": [],
            "passed": False,
        }

        schema_version = self._detect_schema_version()

        # Decompress archive if needed
        mbox_path, is_temp = self._get_mbox_path()

        try:
            # 1. Count validation + basic integrity over the same mbox handle
            try:
                with closing(mailbox.mbox(str(mbox_path))) as mbox:
                    archive_count = len(mbox)
                    expected_count = len(expected_message_ids)

                    if archive_count == expected_count:
                        results["count_check"] = True
                    else:
                        results["errors"].append(
                            f"Count mismatch: {archive_count} in archive vs "
                            f"{expected_count} expected"
                        )

                    # 3. Content integrity check
                    try:
                        message_count = 0
                        for _msg in mbox:
                            message_count += 1

                        if message_count > 0:
                            results["integrity_check"] = True
                        else:
                            results["errors"].append("Archive contains no readable messages")
                    except Exception as e:
                        results["errors"].append(f"Integrity check failed: {e}")
            except Exception as e:
                results["errors"].append(f"Failed to read archive: {e}")
                return results

            # 2. Database cross-check
            if self.state_db_path.exists():
                try:
                    conn = sqlite3.connect(str(self.state_db_path))
                    db_count = 0

                    if schema_version == "1.1":
                        archive_str = str(self.archive_path)
                        archive_name = self.archive_path.name
                        cursor = conn.execute(
                            """
                            SELECT COUNT(*) FROM messages
                            WHERE archive_file = ? OR archive_file = ?
                            """,
                            (archive_str, archive_name),
                        )
                        row = cursor.fetchone()
                        db_count = row[0] if row else 0
                    else:
                        # v1.0 or unknown schema: fall back to archived_messages total
                        cursor = conn.execute("SELECT COUNT(*) FROM archived_messages")
                        row = cursor.fetchone()
                        db_count = row[0] if row else 0

                    conn.close()

                    if db_count == expected_count:
                        results["database_check"] = True
                    else:
                        results["errors"].append(
                            f"DB count mismatch: {db_count} in DB vs {expected_count} expected"
                        )
                except Exception as e:
                    results["errors"].append(f"Database check failed: {e}")
            else:
                results["errors"].append("State database not found")

            # 4. Spot check sampling
            if expected_message_ids and self.state_db_path.exists():
                try:
                    # Sample messages to verify
                    sample_count = min(sample_size, len(expected_message_ids))
                    sample_ids = random.sample(list(expected_message_ids), sample_count)

                    conn = sqlite3.connect(str(self.state_db_path))
                    found = 0

                    archive_str = str(self.archive_path)
                    archive_name = self.archive_path.name

                    for msg_id in sample_ids:
                        if schema_version == "1.1":
                            cursor = conn.execute(
                                """
                                SELECT 1 FROM messages
                                WHERE gmail_id = ?
                                  AND (archive_file = ? OR archive_file = ?)
                                """,
                                (msg_id, archive_str, archive_name),
                            )
                        else:
                            cursor = conn.execute(
                                "SELECT 1 FROM archived_messages WHERE gmail_id = ?",
                                (msg_id,),
                            )

                        if cursor.fetchone():
                            found += 1

                    conn.close()

                    if found == sample_count:
                        results["spot_check"] = True
                    else:
                        results["errors"].append(
                            f"Spot check: {found}/{sample_count} messages found in DB"
                        )
                except Exception as e:
                    results["errors"].append(f"Spot check failed: {e}")

            # Overall pass/fail
            results["passed"] = all(
                [
                    results["count_check"],
                    results["database_check"],
                    results["integrity_check"],
                    results["spot_check"] or not expected_message_ids,
                ]
            )

            return results
        finally:
            # Clean up temporary file if created
            if is_temp and mbox_path.exists():
                mbox_path.unlink()

    def validate_all(self) -> bool:
        """
        Quick validation to check if archive is readable and non-empty.

        Used for simple pre-deletion validation checks.
        Handles both compressed and uncompressed archives.

        Returns:
            True if archive is readable and has messages
        """
        try:
            # Get path to mbox file (decompress if necessary)
            mbox_path, is_temp = self._get_mbox_path()

            try:
                mbox = mailbox.mbox(str(mbox_path))
                try:
                    count = len(mbox)
                    if count == 0:
                        self.errors.append("Archive is empty")
                        return False
                    return True
                finally:
                    mbox.close()
            finally:
                # Clean up temporary file if created
                if is_temp and mbox_path.exists():
                    mbox_path.unlink()
        except Exception as e:
            self.errors.append(f"Archive validation failed: {e}")
            return False

    def validate_count(self, expected_count: int) -> bool:
        """
        Validate archive message count.

        Args:
            expected_count: Expected number of messages

        Returns:
            True if counts match
        """
        try:
            with closing(mailbox.mbox(str(self.archive_path))) as mbox:
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
        self._log("\n" + "=" * 60, "INFO")
        self._log("ARCHIVE VALIDATION REPORT", "INFO")
        self._log("=" * 60, "INFO")

        checks = [
            ("Count Check", results["count_check"]),
            ("Database Check", results["database_check"]),
            ("Integrity Check", results["integrity_check"]),
            ("Spot Check", results["spot_check"]),
        ]

        for name, passed in checks:
            status = "✓ PASSED" if passed else "✗ FAILED"
            self._log(f"{name:20s} {status}", "INFO")

        if results["errors"]:
            self._log("\nErrors:", "INFO")
            for error in results["errors"]:
                self._log(f"  - {error}", "WARNING")

        self._log("\n" + "=" * 60, "INFO")
        if results["passed"]:
            self._log("VALIDATION: ✓ PASSED", "SUCCESS")
        else:
            self._log("VALIDATION: ✗ FAILED", "ERROR")
        self._log("=" * 60 + "\n", "INFO")

    def _detect_schema_version(self) -> str:
        """
        Detect database schema version.

        Returns:
            Schema version: "1.0", "1.1", or "none"
        """
        if not self.state_db_path.exists():
            return "none"

        conn = sqlite3.connect(str(self.state_db_path))
        try:
            # Check for v1.1 messages table
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            )
            if cursor.fetchone():
                return "1.1"

            # Check for v1.0 archived_messages table
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
            )
            if cursor.fetchone():
                return "1.0"

            return "none"
        finally:
            conn.close()

    def verify_offsets(self) -> OffsetVerificationResult:
        """
        Verify mbox offset accuracy for v1.1 databases.

        Returns:
            Detailed verification result with accuracy statistics
        """
        schema_version = self._detect_schema_version()

        # Skip if not v1.1 schema
        if schema_version != "1.1":
            return OffsetVerificationResult(
                total_checked=0,
                successful_reads=0,
                failed_reads=0,
                accuracy_percentage=0.0,
                skipped=True,
            )

        archive_str = str(self.archive_path)
        archive_name = self.archive_path.name

        # Get mbox path (decompress if needed)
        mbox_path, is_temp = self._get_mbox_path()

        try:
            conn = sqlite3.connect(str(self.state_db_path))
            cursor = conn.execute(
                """
                SELECT gmail_id, rfc_message_id, mbox_offset, mbox_length
                FROM messages
                WHERE archive_file = ? OR archive_file = ?
                """,
                (archive_str, archive_name),
            )
            records = cursor.fetchall()
            conn.close()

            total_checked = len(records)
            successful_reads = 0
            failed_reads = 0
            failures = []

            with open(mbox_path, "rb") as f:
                for gmail_id, rfc_message_id, offset, length in records:
                    try:
                        # Seek to offset
                        f.seek(offset)
                        # Read expected length
                        data = f.read(length)

                        # First check if we read the expected amount of data
                        actual_length = len(data)
                        if actual_length != length:
                            failed_reads += 1
                            failures.append(
                                f"Length mismatch for {gmail_id}: expected "
                                f"{length}, got {actual_length}"
                            )
                            continue

                        # Parse as email message
                        msg = email.message_from_bytes(data)

                        # Extract Message-ID
                        actual_message_id = msg.get("Message-ID", "")

                        # Compare with database
                        if actual_message_id != rfc_message_id:
                            failed_reads += 1
                            failures.append(
                                f"Message-ID mismatch for {gmail_id}: expected "
                                f"{rfc_message_id}, got {actual_message_id}"
                            )
                        else:
                            successful_reads += 1

                    except Exception as e:
                        failed_reads += 1
                        failures.append(
                            f"Failed to read message {gmail_id} at offset {offset}: {e}"
                        )

            accuracy_percentage = (
                (successful_reads / total_checked * 100.0) if total_checked > 0 else 0.0
            )

            return OffsetVerificationResult(
                total_checked=total_checked,
                successful_reads=successful_reads,
                failed_reads=failed_reads,
                accuracy_percentage=accuracy_percentage,
                failures=failures,
            )

        finally:
            # Clean up temporary file if created
            if is_temp and mbox_path.exists():
                mbox_path.unlink()

    def verify_consistency(self) -> ConsistencyReport:
        """
        Deep database consistency checks.

        Returns:
            Detailed consistency report
        """
        schema_version = self._detect_schema_version()

        # Initialize report
        report = ConsistencyReport(
            schema_version=schema_version,
            orphaned_records=0,
            missing_records=0,
            duplicate_gmail_ids=0,
            duplicate_rfc_message_ids=0,
            fts_synced=True,
            passed=True,
        )

        # Skip if no database
        if schema_version == "none":
            report.passed = False
            report.errors.append("No database found")
            return report

        # Get mbox path (decompress if needed)
        mbox_path, is_temp = self._get_mbox_path()

        try:
            # Get all Message-IDs from mbox
            with closing(mailbox.mbox(str(mbox_path))) as mbox:
                mbox_message_ids = set()
                for msg in mbox:
                    msg_id = msg.get("Message-ID", "")
                    if msg_id:
                        mbox_message_ids.add(msg_id)

            # Get all Message-IDs from database
            conn = sqlite3.connect(str(self.state_db_path))

            if schema_version == "1.1":
                # v1.1 schema checks (per-archive)
                archive_str = str(self.archive_path)
                archive_name = self.archive_path.name

                cursor = conn.execute(
                    """
                    SELECT rfc_message_id FROM messages
                    WHERE archive_file = ? OR archive_file = ?
                    """,
                    (archive_str, archive_name),
                )
                db_message_ids = {row[0] for row in cursor.fetchall()}

                # Check for orphaned records (in DB but not in mbox)
                orphaned = db_message_ids - mbox_message_ids
                report.orphaned_records = len(orphaned)

                # Check for missing records (in mbox but not in DB)
                missing = mbox_message_ids - db_message_ids
                report.missing_records = len(missing)

                # Check for duplicate gmail_ids
                cursor = conn.execute(
                    """SELECT gmail_id, COUNT(*) as cnt FROM messages
                       GROUP BY gmail_id HAVING cnt > 1"""
                )
                report.duplicate_gmail_ids = len(cursor.fetchall())

                # Check for duplicate rfc_message_ids
                cursor = conn.execute(
                    """SELECT rfc_message_id, COUNT(*) as cnt FROM messages GROUP BY
                       rfc_message_id HAVING cnt > 1"""
                )
                report.duplicate_rfc_message_ids = len(cursor.fetchall())

                # Check FTS5 sync
                try:
                    cursor = conn.execute("SELECT COUNT(*) FROM messages")
                    messages_count = cursor.fetchone()[0]

                    cursor = conn.execute("SELECT COUNT(*) FROM messages_fts")
                    fts_count = cursor.fetchone()[0]

                    report.fts_synced = messages_count == fts_count
                except sqlite3.OperationalError:
                    # FTS5 table doesn't exist
                    report.fts_synced = False

            else:
                # v1.0 schema has limited checks
                # We can't verify Message-IDs easily since they're not stored
                report.fts_synced = True  # No FTS in v1.0

            conn.close()

            # Determine overall pass/fail
            report.passed = (
                report.orphaned_records == 0
                and report.missing_records == 0
                and report.duplicate_gmail_ids == 0
                and report.duplicate_rfc_message_ids == 0
                and report.fts_synced
            )

            return report

        finally:
            # Clean up temporary file if created
            if is_temp and mbox_path.exists():
                mbox_path.unlink()
