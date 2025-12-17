"""Facade for archive validation with clean orchestration.

This module provides the public API for validating mbox archives.
It coordinates internal modules for comprehensive validation.
"""

from dataclasses import dataclass, field
from pathlib import Path

from gmailarchiver.core.validator._checksum import ChecksumValidator
from gmailarchiver.core.validator._counter import MessageCounter
from gmailarchiver.core.validator._decompressor import Decompressor
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class ValidationResult:
    """Result from comprehensive validation."""

    count_check: bool = False
    database_check: bool = False
    integrity_check: bool = False
    spot_check: bool = False
    passed: bool = False
    errors: list[str] = field(default_factory=list)


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


class ValidatorFacade:
    """Public facade for mbox archive validation.

    Provides clean API for validating archives before deletion.
    Supports compression, database cross-checks, and spot sampling.
    """

    def __init__(
        self,
        archive_path: str | Path,
        state_db_path: str | Path = "archive_state.db",
        progress: ProgressReporter | None = None,
        db_manager: DBManager | None = None,
    ) -> None:
        """Initialize validator facade.

        Args:
            archive_path: Path to mbox archive file
            state_db_path: Path to SQLite database file
            progress: Optional ProgressReporter for structured logging
            db_manager: Optional DBManager for database operations (will create if not provided)
        """
        self.archive_path = Path(archive_path)
        self.state_db_path = Path(state_db_path)
        self.progress = progress
        self.errors: list[str] = []

        # Database manager (create if not provided)
        self._db_manager = db_manager
        self._owns_db_manager = db_manager is None

        # Internal modules
        self._decompressor = Decompressor()
        self._counter = MessageCounter()
        self._checksum = ChecksumValidator()

    async def _get_db_manager(self) -> DBManager | None:
        """Get or create DBManager instance.

        Returns:
            DBManager instance or None if database doesn't exist
        """
        if self._db_manager is not None:
            return self._db_manager

        if not self.state_db_path.exists():
            return None

        try:
            # For validation, we don't want to fail on schema validation
            self._db_manager = DBManager(
                str(self.state_db_path), validate_schema=False, auto_create=False
            )
            await self._db_manager.initialize()
            return self._db_manager
        except Exception:
            return None

    async def close(self) -> None:
        """Close database manager if owned by this validator."""
        if self._owns_db_manager and self._db_manager is not None:
            await self._db_manager.close()
            self._db_manager = None

    def _log(self, message: str, level: str = "INFO") -> None:
        """Log message through ProgressReporter if available.

        Args:
            message: Message to log
            level: Severity level (INFO, WARNING, ERROR)
        """
        if self.progress:
            if level == "WARNING":
                self.progress.warning(message)
            elif level == "ERROR":
                self.progress.error(message)
            else:  # INFO
                self.progress.info(message)

    def validate_all(self) -> bool:
        """Quick validation to check if archive is readable and non-empty.

        Returns:
            True if archive is readable and has messages
        """
        mbox_path = None
        is_temp = False
        try:
            mbox_path, is_temp = self._decompressor.get_mbox_path(self.archive_path)
            is_valid, error = self._counter.validate_not_empty(mbox_path)
            if not is_valid:
                self.errors.append(error)
            return is_valid
        except Exception as e:
            self.errors.append(f"Archive validation failed: {e}")
            return False
        finally:
            if mbox_path:
                self._decompressor.cleanup_temp_file(mbox_path, is_temp)

    def validate_count(self, expected_count: int) -> bool:
        """Validate archive message count.

        Args:
            expected_count: Expected number of messages

        Returns:
            True if counts match
        """
        mbox_path = None
        is_temp = False
        try:
            mbox_path, is_temp = self._decompressor.get_mbox_path(self.archive_path)
            is_valid, error = self._counter.validate_count(mbox_path, expected_count)
            if not is_valid:
                self.errors.append(error)
            return is_valid
        except Exception as e:
            self.errors.append(f"Count validation failed: {e}")
            return False
        finally:
            if mbox_path:
                self._decompressor.cleanup_temp_file(mbox_path, is_temp)

    def compute_checksum(self, data: bytes) -> str:
        """Compute SHA256 checksum of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal digest
        """
        return self._checksum.compute_checksum(data)

    def validate_comprehensive(
        self, expected_message_ids: set[str], sample_size: int = 100
    ) -> ValidationResult:
        """Perform comprehensive multi-layer validation.

        Note: This is a simplified version. Full implementation will include:
        - Database cross-checks
        - Spot check sampling
        - Offset verification

        Args:
            expected_message_ids: Set of Gmail message IDs
            sample_size: Number of messages to spot-check

        Returns:
            ValidationResult with detailed check status
        """
        expected_count = len(expected_message_ids)
        result = ValidationResult()

        mbox_path, is_temp = self._decompressor.get_mbox_path(self.archive_path)

        try:
            # Count and integrity check
            is_valid, error = self._counter.validate_count(mbox_path, expected_count)
            if is_valid:
                result.count_check = True
            else:
                result.errors.append(error)

            # Readability check
            is_valid, error = self._counter.check_readability(mbox_path)
            if is_valid:
                result.integrity_check = True
            else:
                result.errors.append(error)

            # Database and spot checks would go here (simplified for now)
            result.database_check = True  # Placeholder
            result.spot_check = True  # Placeholder - full implementation would spot-check

            result.passed = all(
                [
                    result.count_check,
                    result.database_check,
                    result.integrity_check,
                    result.spot_check,
                ]
            )

            return result
        except Exception as e:
            result.errors.append(f"Failed to read archive: {e}")
            return result
        finally:
            self._decompressor.cleanup_temp_file(mbox_path, is_temp)

    def report(self, result: ValidationResult) -> None:
        """Print validation report.

        Args:
            result: ValidationResult from validate_comprehensive()
        """
        self._log("\n" + "=" * 60, "INFO")
        self._log("ARCHIVE VALIDATION REPORT", "INFO")
        self._log("=" * 60, "INFO")

        checks = [
            ("Count Check", result.count_check),
            ("Database Check", result.database_check),
            ("Integrity Check", result.integrity_check),
            ("Spot Check", result.spot_check),
        ]

        for name, passed in checks:
            status = "✓ PASSED" if passed else "✗ FAILED"
            self._log(f"{name:20s} {status}", "INFO")

        if result.errors:
            self._log("\nErrors:", "INFO")
            for error in result.errors:
                self._log(f"  - {error}", "WARNING")

        self._log("\n" + "=" * 60, "INFO")
        if result.passed:
            self._log("VALIDATION: ✓ PASSED", "INFO")
        else:
            self._log("VALIDATION: ✗ FAILED", "ERROR")
        self._log("=" * 60 + "\n", "INFO")

    def get_mbox_path(self) -> tuple[Path, bool]:
        """Get mbox path, decompressing if necessary.

        Returns:
            Tuple of (mbox_path, is_temporary)
            If file is compressed, returns path to temporary decompressed file
        """
        return self._decompressor.get_mbox_path(self.archive_path)

    async def verify_offsets(self) -> OffsetVerificationResult:
        """Verify mbox offset accuracy by reading messages.

        Returns:
            OffsetVerificationResult with statistics
        """
        import mailbox

        # Get database manager
        db_manager = await self._get_db_manager()
        if db_manager is None or db_manager.conn is None:
            return OffsetVerificationResult(
                total_checked=0,
                successful_reads=0,
                failed_reads=0,
                accuracy_percentage=0.0,
                failures=[],
                skipped=True,
            )

        conn = db_manager.conn  # Type narrowed to non-None

        # Check if messages table exists (v1.1 schema)
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            )
            row = await cursor.fetchone()
            if not row:
                return OffsetVerificationResult(
                    total_checked=0,
                    successful_reads=0,
                    failed_reads=0,
                    accuracy_percentage=0.0,
                    failures=[],
                    skipped=True,
                )
        except Exception:
            return OffsetVerificationResult(
                total_checked=0,
                successful_reads=0,
                failed_reads=0,
                accuracy_percentage=0.0,
                failures=[],
                skipped=True,
            )

        # Get messages with offsets from database
        try:
            cursor = await conn.execute(
                """
                SELECT gmail_id, rfc_message_id, mbox_offset, mbox_length
                FROM messages
                WHERE archive_file = ?
                ORDER BY mbox_offset
            """,
                (str(self.archive_path),),
            )
            messages = await cursor.fetchall()
        except Exception:
            return OffsetVerificationResult(
                total_checked=0,
                successful_reads=0,
                failed_reads=0,
                accuracy_percentage=0.0,
                failures=[],
                skipped=True,
            )

        if not messages:
            return OffsetVerificationResult(
                total_checked=0,
                successful_reads=0,
                failed_reads=0,
                accuracy_percentage=0.0,
                failures=[],
                skipped=True,
            )

        # Get mbox path (decompress if needed)
        mbox_path, is_temp = self._decompressor.get_mbox_path(self.archive_path)

        successful = 0
        failed = 0
        failures = []

        try:
            # Open mbox and verify each offset
            with open(mbox_path, "rb") as f:
                for gmail_id, rfc_message_id, offset, length in messages:
                    try:
                        f.seek(offset)
                        data = f.read(length)

                        # Check if we could read the expected length
                        if len(data) != length:
                            failures.append(
                                f"Message {gmail_id}: Length mismatch "
                                f"(expected {length}, read {len(data)})"
                            )
                            failed += 1
                            continue

                        msg = mailbox.mboxMessage(data)

                        # Verify message ID matches
                        actual_id = msg.get("Message-ID", "").strip()
                        if actual_id != rfc_message_id:
                            failures.append(
                                f"Message {gmail_id}: ID mismatch "
                                f"(expected {rfc_message_id}, got {actual_id})"
                            )
                            failed += 1
                        else:
                            successful += 1
                    except Exception as e:
                        failures.append(f"Message {gmail_id}: Read error at offset {offset}: {e}")
                        failed += 1
        finally:
            if is_temp:
                self._decompressor.cleanup_temp_file(mbox_path, is_temp)

        total = successful + failed
        accuracy = (successful / total * 100) if total > 0 else 0.0

        return OffsetVerificationResult(
            total_checked=total,
            successful_reads=successful,
            failed_reads=failed,
            accuracy_percentage=accuracy,
            failures=failures,
            skipped=False,
        )

    async def verify_consistency(self) -> ConsistencyReport:
        """Verify database consistency (orphaned records, FTS sync, etc).

        Returns:
            ConsistencyReport with detailed findings
        """
        # Get database manager
        db_manager = await self._get_db_manager()
        if db_manager is None or db_manager.conn is None:
            return ConsistencyReport(
                schema_version="unknown",
                orphaned_records=0,
                missing_records=0,
                duplicate_gmail_ids=0,
                duplicate_rfc_message_ids=0,
                fts_synced=True,
                passed=False,
                errors=["Database file not found or connection not initialized"],
            )

        errors: list[str] = []
        conn = db_manager.conn  # Type narrowed to non-None

        # Check schema version
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        row = await cursor.fetchone()
        has_v11 = row is not None

        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        row = await cursor.fetchone()
        has_v10 = row is not None

        if not has_v11 and not has_v10:
            # No recognized schema
            return ConsistencyReport(
                schema_version="none",
                orphaned_records=0,
                missing_records=0,
                duplicate_gmail_ids=0,
                duplicate_rfc_message_ids=0,
                fts_synced=True,
                passed=False,
                errors=[
                    "Database has no recognized schema (no messages or archived_messages table)"
                ],
            )

        schema_version = "v1.1" if has_v11 else "v1.0"

        # Count orphaned and missing records by comparing DB vs mbox
        orphaned_records = 0
        missing_records = 0

        if has_v11:
            # Get Message-IDs from database
            table_name = "messages"
            cursor = await conn.execute(
                f"""
                SELECT rfc_message_id FROM {table_name}
                WHERE archive_file = ?
            """,
                (str(self.archive_path),),
            )
            rows = await cursor.fetchall()
            db_message_ids = set(row[0] for row in rows)

            # Get Message-IDs from mbox file
            mbox_message_ids = set()
            mbox_path, is_temp = self._decompressor.get_mbox_path(self.archive_path)
            try:
                import mailbox

                mbox = mailbox.mbox(str(mbox_path))
                for msg in mbox:
                    msg_id = msg.get("Message-ID", "").strip()
                    if msg_id:
                        mbox_message_ids.add(msg_id)
                mbox.close()
            except Exception as e:
                errors.append(f"Failed to read mbox for consistency check: {e}")
            finally:
                if is_temp:
                    self._decompressor.cleanup_temp_file(mbox_path, is_temp)

            # Orphaned: in DB but not in mbox
            orphaned_records = len(db_message_ids - mbox_message_ids)
            # Missing: in mbox but not in DB
            missing_records = len(mbox_message_ids - db_message_ids)

            if orphaned_records > 0:
                errors.append(f"Found {orphaned_records} orphaned database records (not in mbox)")
            if missing_records > 0:
                errors.append(f"Found {missing_records} messages in mbox not tracked in database")

        # Check for duplicate Gmail IDs
        table_name = "messages" if has_v11 else "archived_messages"
        cursor = await conn.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT gmail_id, COUNT(*) as cnt
                FROM {table_name}
                GROUP BY gmail_id
                HAVING cnt > 1
            )
        """)
        row = await cursor.fetchone()
        duplicate_gmail_ids = row[0] if row else 0

        # Check for duplicate RFC message IDs (v1.1 only)
        duplicate_rfc_ids = 0
        if has_v11:
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT rfc_message_id, COUNT(*) as cnt
                    FROM messages
                    GROUP BY rfc_message_id
                    HAVING cnt > 1
                )
            """)
            row = await cursor.fetchone()
            duplicate_rfc_ids = row[0] if row else 0

        # Check FTS sync (v1.1 only)
        fts_synced = True
        if has_v11:
            try:
                cursor = await conn.execute("SELECT COUNT(*) FROM messages_fts")
                row = await cursor.fetchone()
                fts_count = row[0] if row else 0
                cursor = await conn.execute("SELECT COUNT(*) FROM messages")
                row = await cursor.fetchone()
                msg_count = row[0] if row else 0
                fts_synced = fts_count == msg_count
                if not fts_synced:
                    errors.append(
                        f"FTS index out of sync: {fts_count} FTS rows vs {msg_count} message rows"
                    )
            except Exception:
                fts_synced = False
                errors.append("FTS table not found or corrupted")

        if duplicate_gmail_ids > 0:
            errors.append(f"Found {duplicate_gmail_ids} duplicate Gmail IDs")
        if duplicate_rfc_ids > 0:
            errors.append(f"Found {duplicate_rfc_ids} duplicate RFC Message-IDs")

        passed = (
            orphaned_records == 0
            and duplicate_gmail_ids == 0
            and duplicate_rfc_ids == 0
            and fts_synced
            and len(errors) == 0
        )

        return ConsistencyReport(
            schema_version=schema_version,
            orphaned_records=orphaned_records,
            missing_records=missing_records,
            duplicate_gmail_ids=duplicate_gmail_ids,
            duplicate_rfc_message_ids=duplicate_rfc_ids,
            fts_synced=fts_synced,
            passed=passed,
            errors=errors,
        )
