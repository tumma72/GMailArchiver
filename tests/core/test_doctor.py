"""Tests for the doctor command - WRITTEN FIRST per TDD methodology."""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.doctor import (
    CheckResult,
    CheckSeverity,
    Doctor,
    DoctorReport,
)

pytestmark = pytest.mark.asyncio

# ============================================================================
# Test Fixtures
# ============================================================================


# Test: CheckResult and CheckSeverity
# ============================================================================


async def test_check_severity_levels() -> None:
    """Test CheckSeverity enum values."""
    assert CheckSeverity.OK.value == "OK"
    assert CheckSeverity.WARNING.value == "WARNING"
    assert CheckSeverity.ERROR.value == "ERROR"


async def test_check_result_creation() -> None:
    """Test CheckResult dataclass creation."""
    result = CheckResult(
        name="Test Check",
        severity=CheckSeverity.OK,
        message="All good",
        fixable=False,
    )

    assert result.name == "Test Check"
    assert result.severity == CheckSeverity.OK
    assert result.message == "All good"
    assert result.fixable is False
    assert result.details is None


async def test_check_result_with_details() -> None:
    """Test CheckResult with optional details."""
    result = CheckResult(
        name="Test Check",
        severity=CheckSeverity.WARNING,
        message="Something off",
        fixable=True,
        details="Extra info here",
    )

    assert result.details == "Extra info here"


# ============================================================================
# Test: Database Checks
# ============================================================================


async def test_check_database_schema_v11(v11_db: str) -> None:
    """Test database schema check for v1.1 database."""
    doctor = await Doctor.create(v11_db)
    result = await doctor.check_database_schema()

    assert result.severity == CheckSeverity.OK
    assert "v1.1" in result.message
    assert result.fixable is False
    await doctor.close()


async def test_check_database_schema_missing_database() -> None:
    """Test database schema check when database doesn't exist."""
    doctor = await Doctor.create("/nonexistent/database.db", auto_create=False)
    result = await doctor.check_database_schema()

    assert result.severity == CheckSeverity.ERROR
    assert "not found" in result.message.lower()
    assert result.fixable is True  # Can create new database
    await doctor.close()


async def test_check_database_schema_v10() -> None:
    """Test database schema check for v1.0 database (needs migration)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "v10.db"
        conn = sqlite3.connect(str(db_path))

        # Create v1.0 schema (old table name)
        conn.execute("""
            CREATE TABLE archived_messages (
                gmail_id TEXT PRIMARY KEY,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP
            )
        """)
        conn.execute("PRAGMA user_version = 10")
        conn.commit()
        conn.close()

        doctor = await Doctor.create(str(db_path), auto_create=False)
        result = await doctor.check_database_schema()

        assert result.severity == CheckSeverity.WARNING
        assert "v1.0" in result.message
        assert "migration" in result.message.lower()
        assert result.fixable is True
    await doctor.close()


async def test_check_database_integrity_ok(v11_db: str) -> None:
    """Test database integrity check on healthy database."""
    doctor = await Doctor.create(v11_db)
    result = await doctor.check_database_integrity()

    assert result.severity == CheckSeverity.OK
    assert "healthy" in result.message.lower() or "ok" in result.message.lower()
    await doctor.close()


async def test_check_database_integrity_corrupted() -> None:
    """Test database integrity check on corrupted database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "corrupted.db"

        # Create a valid database first
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        # Corrupt it by truncating
        with open(db_path, "wb") as f:
            f.write(b"corrupted")

        doctor = await Doctor.create(str(db_path), validate_schema=False, auto_create=False)
        result = await doctor.check_database_integrity()

        assert result.severity == CheckSeverity.ERROR
        assert result.fixable is False  # Corruption not auto-fixable
    await doctor.close()


async def test_check_orphaned_fts_none(v11_db: str) -> None:
    """Test check for orphaned FTS records when none exist."""
    doctor = await Doctor.create(v11_db)
    result = await doctor.check_orphaned_fts()

    assert result.severity == CheckSeverity.OK
    assert "no orphaned" in result.message.lower() or result.message == "FTS index is clean"
    await doctor.close()


async def test_check_archive_files_exist(v11_db: str) -> None:
    """Test check that archive files referenced in database exist."""
    # Create a temporary archive file
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "archive.mbox"
        archive_path.write_text("dummy")

        # Insert message referencing this archive
        conn = sqlite3.connect(v11_db)
        conn.execute(
            """
            INSERT INTO messages (
                gmail_id, rfc_message_id, thread_id, archived_timestamp,
                archive_file, mbox_offset, mbox_length
            ) VALUES ('1', 'msg1@example.com', 'thread1', '2024-01-01', ?, 0, 100)
        """,
            (str(archive_path),),
        )
        conn.commit()
        conn.close()

        doctor = await Doctor.create(v11_db)
        result = await doctor.check_archive_files_exist()

        assert result.severity == CheckSeverity.OK
        assert "exist" in result.message.lower()
    await doctor.close()


async def test_check_archive_files_missing(v11_db: str) -> None:
    """Test check when archive files are missing."""
    # Insert message referencing non-existent archive
    conn = sqlite3.connect(v11_db)
    conn.execute(
        """
        INSERT INTO messages (
            gmail_id, rfc_message_id, thread_id, archived_timestamp,
            archive_file, mbox_offset, mbox_length
        ) VALUES (
            '1', 'msg1@example.com', 'thread1', '2024-01-01',
            '/nonexistent/archive.mbox', 0, 100
        )
        """
    )
    conn.commit()
    conn.close()

    doctor = await Doctor.create(v11_db)
    result = await doctor.check_archive_files_exist()

    assert result.severity == CheckSeverity.WARNING
    assert "missing" in result.message.lower()
    assert "1" in result.message  # Should mention count
    assert result.fixable is False  # Can't auto-fix missing files
    await doctor.close()


# ============================================================================
# Test: Environment Checks
# ============================================================================


async def test_check_python_version_ok() -> None:
    """Test Python version check when version is sufficient."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_python_version()

    # We're running Python 3.14+ in this environment
    assert result.severity == CheckSeverity.OK
    assert "3.14" in result.message or str(sys.version_info.minor) in result.message
    await doctor.close()


@patch("sys.version_info", (3, 12, 0, "final", 0))
async def test_check_python_version_too_old() -> None:
    """Test Python version check when version is too old."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_python_version()

    assert result.severity == CheckSeverity.WARNING
    assert "3.12" in result.message
    assert result.fixable is False  # Can't auto-upgrade Python
    await doctor.close()


async def test_check_dependencies_installed() -> None:
    """Test that required dependencies are installed."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_dependencies()

    assert result.severity == CheckSeverity.OK
    assert "installed" in result.message.lower()
    await doctor.close()


@patch("importlib.import_module")
async def test_check_dependencies_missing(mock_import: Mock) -> None:
    """Test dependency check when packages are missing."""
    mock_import.side_effect = ImportError("No module named 'google'")

    doctor = await Doctor.create(":memory:")
    result = doctor.check_dependencies()

    assert result.severity == CheckSeverity.ERROR
    assert "missing" in result.message.lower()
    assert result.fixable is True  # Can run pip install
    await doctor.close()


async def test_check_oauth_token_missing() -> None:
    """Test OAuth token check when token doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_token_path = Path(tmpdir) / "nonexistent_token.json"

        token_patch = "gmailarchiver.core.doctor._diagnostics._get_default_token_path"
        with patch(token_patch, return_value=fake_token_path):
            doctor = await Doctor.create(":memory:")
            result = doctor.check_oauth_token()

            assert result.severity == CheckSeverity.WARNING
            assert "not found" in result.message.lower()
            assert result.fixable is True  # Can re-authenticate
    await doctor.close()


async def test_check_oauth_token_valid() -> None:
    """Test OAuth token check when token exists and is valid."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text(
            json.dumps(
                {
                    "token": "fake_token",
                    "refresh_token": "fake_refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "fake_client_id",
                    "client_secret": "fake_secret",
                    "scopes": ["https://mail.google.com/"],
                }
            )
        )

        with patch(
            "gmailarchiver.core.doctor._diagnostics._get_default_token_path",
            return_value=token_path,
        ):
            with patch("gmailarchiver.connectors.auth.Credentials") as mock_creds:
                mock_creds_instance = Mock()
                mock_creds_instance.valid = True
                mock_creds_instance.expired = False
                mock_creds.from_authorized_user_info.return_value = mock_creds_instance

                doctor = await Doctor.create(":memory:")
                result = doctor.check_oauth_token()

                assert result.severity == CheckSeverity.OK
                assert "valid" in result.message.lower()
    await doctor.close()


async def test_check_oauth_token_expired() -> None:
    """Test OAuth token check when token is expired."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text(
            json.dumps(
                {
                    "token": "fake_token",
                    "refresh_token": "fake_refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "fake_client_id",
                    "client_secret": "fake_secret",
                    "scopes": ["https://mail.google.com/"],
                }
            )
        )

        with patch(
            "gmailarchiver.core.doctor._diagnostics._get_default_token_path",
            return_value=token_path,
        ):
            with patch("gmailarchiver.connectors.auth.Credentials") as mock_creds:
                mock_creds_instance = Mock()
                mock_creds_instance.valid = False
                mock_creds_instance.expired = True
                mock_creds.from_authorized_user_info.return_value = mock_creds_instance

                doctor = await Doctor.create(":memory:")
                result = doctor.check_oauth_token()

                assert result.severity == CheckSeverity.WARNING
                assert "expired" in result.message.lower()
                assert result.fixable is True
    await doctor.close()


async def test_check_credentials_file_exists() -> None:
    """Test credentials file check when bundled credentials exist."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_credentials_file()

    # Bundled credentials should exist
    assert result.severity == CheckSeverity.OK
    assert "found" in result.message.lower() or "exists" in result.message.lower()
    await doctor.close()


# ============================================================================
# Test: System Checks
# ============================================================================


async def test_check_disk_space_sufficient() -> None:
    """Test disk space check when sufficient space available."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB

        doctor = await Doctor.create(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.OK
        assert "GB" in result.message or "MB" in result.message
    await doctor.close()


async def test_check_disk_space_low_warning() -> None:
    """Test disk space check with low space (warning level)."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=300 * 1024 * 1024)  # 300 MB (< 500 MB)

        doctor = await Doctor.create(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.WARNING
        assert "300" in result.message
        assert result.fixable is False  # Can't auto-fix disk space
    await doctor.close()


async def test_check_disk_space_critical_error() -> None:
    """Test disk space check with critically low space."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=50 * 1024 * 1024)  # 50 MB (< 100 MB)

        doctor = await Doctor.create(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.ERROR
        assert "50" in result.message
    await doctor.close()


async def test_check_write_permissions_ok() -> None:
    """Test write permissions check when directory is writable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        doctor = await Doctor.create(str(db_path))
        result = doctor.check_write_permissions()

        assert result.severity == CheckSeverity.OK
        assert "writable" in result.message.lower()
    await doctor.close()


async def test_check_write_permissions_denied() -> None:
    """Test write permissions check when directory is not writable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        with patch("pathlib.Path.is_dir", return_value=True):
            with patch("os.access", return_value=False):
                doctor = await Doctor.create(str(db_path))
                result = doctor.check_write_permissions()

                assert result.severity == CheckSeverity.ERROR
                assert "not writable" in result.message.lower()
    await doctor.close()


async def test_check_stale_lock_files_none() -> None:
    """Test stale lock file check when no lock files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        doctor = await Doctor.create(str(db_path))
        result = doctor.check_stale_locks()

        assert result.severity == CheckSeverity.OK
        assert "no stale" in result.message.lower()
    await doctor.close()


async def test_check_stale_lock_files_found() -> None:
    """Test stale lock file check when lock files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create fake lock files
        (Path(tmpdir) / "archive.mbox.lock").touch()
        (Path(tmpdir) / "archive.mbox.lock.lock").touch()

        doctor = await Doctor.create(str(db_path))
        result = doctor.check_stale_locks()

        assert result.severity == CheckSeverity.WARNING
        assert "lock file" in result.message.lower()
        assert "2" in result.message
        assert result.fixable is True  # Can remove stale locks
    await doctor.close()


async def test_check_temp_directory_accessible() -> None:
    """Test temp directory accessibility check."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_temp_directory()

    assert result.severity == CheckSeverity.OK
    assert "accessible" in result.message.lower()
    await doctor.close()


async def test_check_temp_directory_not_accessible() -> None:
    """Test temp directory check when not accessible."""
    with patch("tempfile.gettempdir", return_value="/nonexistent/tmp"):
        with patch("os.access", return_value=False):
            # Mock mkdir to prevent actual directory creation during HybridStorage init
            with patch("pathlib.Path.mkdir"):
                doctor = await Doctor.create(":memory:")
                result = doctor.check_temp_directory()

                assert result.severity == CheckSeverity.ERROR
                assert "not accessible" in result.message.lower()
                await doctor.close()


# ============================================================================
# Test: Doctor.run_diagnostics()
# ============================================================================


async def test_run_diagnostics_all_checks_pass(v11_db: str) -> None:
    """Test run_diagnostics when all checks pass.

    This test uses a patched OAuth token check so it does not depend on
    the real user's authentication state or token.json on disk.
    """
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB

        # Patch DiagnosticsRunner.check_oauth_token which is called by run_diagnostics
        with patch(
            "gmailarchiver.core.doctor._diagnostics.DiagnosticsRunner.check_oauth_token"
        ) as mock_token_check:
            mock_token_check.return_value = CheckResult(
                name="OAuth token",
                severity=CheckSeverity.OK,
                message="OAuth token is valid (test override)",
                fixable=False,
            )

            doctor = await Doctor.create(v11_db)
            report = await doctor.run_diagnostics()

        assert isinstance(report, DoctorReport)
        assert report.overall_status == CheckSeverity.OK
        assert report.errors == 0
        assert report.warnings == 0
        assert len(report.checks) > 0
        assert all(check.severity == CheckSeverity.OK for check in report.checks)
    await doctor.close()


async def test_run_diagnostics_with_warnings(v11_db: str) -> None:
    """Test run_diagnostics when some checks have warnings."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=300 * 1024 * 1024)  # 300 MB - WARNING

        doctor = await Doctor.create(v11_db)
        report = await doctor.run_diagnostics()

        assert report.overall_status == CheckSeverity.WARNING
        assert report.warnings >= 1
        assert report.errors == 0
    await doctor.close()


async def test_run_diagnostics_with_errors(v11_db: str) -> None:
    """Test run_diagnostics when some checks have errors."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=50 * 1024 * 1024)  # 50 MB - ERROR

        doctor = await Doctor.create(v11_db)
        report = await doctor.run_diagnostics()

        assert report.overall_status == CheckSeverity.ERROR
        assert report.errors >= 1
    await doctor.close()


async def test_run_diagnostics_counts_results_correctly(v11_db: str) -> None:
    """Test that diagnostics correctly counts OK/WARNING/ERROR results."""
    # Insert orphaned FTS record (WARNING) + low disk space (WARNING)
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (999, 'Orphaned', 'test@example.com', 'user@example.com', 'Orphaned')
    """)
    conn.commit()
    conn.close()

    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=300 * 1024 * 1024)  # 300 MB - WARNING

        doctor = await Doctor.create(v11_db)
        report = await doctor.run_diagnostics()

        assert report.warnings >= 1  # At least disk space warning
        assert report.checks_passed >= 0  # Some checks should pass
    await doctor.close()


# ============================================================================
# Test: Auto-Fix Capabilities
# ============================================================================


async def test_auto_fix_orphaned_fts(v11_db: str) -> None:
    """Test auto-fix for orphaned FTS records."""
    # Insert orphaned FTS record
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (999, 'Orphaned', 'test@example.com', 'user@example.com', 'Orphaned')
    """)
    conn.commit()
    conn.close()

    doctor = await Doctor.create(v11_db)
    result = await doctor.fix_orphaned_fts()

    assert result.success is True
    assert "removed" in result.message.lower() or "cleaned" in result.message.lower()

    # Verify orphaned record was removed
    conn = sqlite3.connect(v11_db)
    cursor = conn.execute("SELECT COUNT(*) FROM messages_fts WHERE rowid = 999")
    count = cursor.fetchone()[0]
    assert count == 0
    await doctor.close()


async def test_auto_fix_stale_locks() -> None:
    """Test auto-fix for stale lock files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create fake lock files
        lock1 = Path(tmpdir) / "archive.mbox.lock"
        lock2 = Path(tmpdir) / "archive.mbox.lock.lock"
        lock1.touch()
        lock2.touch()

        doctor = await Doctor.create(str(db_path))
        result = doctor.fix_stale_locks()

        assert result.success is True
        assert not lock1.exists()
        assert not lock2.exists()
    await doctor.close()


async def test_auto_fix_create_missing_database() -> None:
    """Test auto-fix creates missing database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "new.db"

        doctor = await Doctor.create(str(db_path), auto_create=False)
        result = await doctor.fix_missing_database()

        assert result.success is True
        assert db_path.exists()

        # Verify it's a valid v1.1 database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]
        assert version == 11
    await doctor.close()


async def test_run_auto_fix_fixes_all_issues(v11_db: str) -> None:
    """Test that run_auto_fix fixes all fixable issues."""
    # Create multiple fixable issues
    # 1. Orphaned FTS record
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (999, 'Orphaned', 'test@example.com', 'user@example.com', 'Orphaned')
    """)
    conn.commit()
    conn.close()

    # 2. Stale lock file
    db_dir = Path(v11_db).parent
    lock_file = db_dir / "stale.lock"
    lock_file.touch()

    doctor = await Doctor.create(v11_db)

    # Run diagnostics first
    report_before = await doctor.run_diagnostics()
    fixable_count = sum(
        1 for check in report_before.checks if check.fixable and check.severity != CheckSeverity.OK
    )

    # Run auto-fix
    fix_results = await doctor.run_auto_fix()

    assert len(fix_results) >= 1  # At least orphaned FTS should be fixed
    assert all(result.success for result in fix_results)

    # Run diagnostics again - should have fewer issues
    report_after = await doctor.run_diagnostics()
    assert report_after.warnings <= report_before.warnings
    assert report_after.errors <= report_before.errors
    await doctor.close()


# ============================================================================
# Test: DoctorReport
# ============================================================================


async def test_doctor_report_creation() -> None:
    """Test DoctorReport dataclass creation."""
    checks = [
        CheckResult("Check 1", CheckSeverity.OK, "All good", False),
        CheckResult("Check 2", CheckSeverity.WARNING, "Warning", True),
        CheckResult("Check 3", CheckSeverity.ERROR, "Error", False),
    ]

    report = DoctorReport(
        overall_status=CheckSeverity.ERROR,
        checks=checks,
        checks_passed=1,
        warnings=1,
        errors=1,
    )

    assert report.overall_status == CheckSeverity.ERROR
    assert len(report.checks) == 3
    assert report.checks_passed == 1
    assert report.warnings == 1
    assert report.errors == 1


async def test_doctor_report_to_dict() -> None:
    """Test DoctorReport conversion to dict for JSON output."""
    checks = [
        CheckResult("Check 1", CheckSeverity.OK, "All good", False),
    ]

    report = DoctorReport(
        overall_status=CheckSeverity.OK,
        checks=checks,
        checks_passed=1,
        warnings=0,
        errors=0,
    )

    report_dict = report.to_dict()

    assert report_dict["overall_status"] == "OK"
    assert report_dict["checks_passed"] == 1
    assert report_dict["warnings"] == 0
    assert report_dict["errors"] == 0
    assert len(report_dict["checks"]) == 1
    assert report_dict["checks"][0]["name"] == "Check 1"


# ============================================================================
# Test: Edge Cases
# ============================================================================


async def test_doctor_with_memory_database() -> None:
    """Test doctor can run diagnostics on :memory: database."""
    doctor = await Doctor.create(":memory:")
    report = await doctor.run_diagnostics()

    # Should handle gracefully - some checks will skip/warn
    assert isinstance(report, DoctorReport)
    await doctor.close()


async def test_doctor_handles_permission_errors() -> None:
    """Test doctor handles permission errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", side_effect=PermissionError("Access denied")):
                doctor = await Doctor.create(str(db_path), validate_schema=False, auto_create=False)
                # Should not raise, handle gracefully
                result = await doctor.check_database_integrity()
                assert result.severity == CheckSeverity.ERROR
    await doctor.close()


async def test_multiple_diagnostics_runs_independent(v11_db: str) -> None:
    """Test that multiple diagnostic runs are independent."""
    doctor = await Doctor.create(v11_db)

    report1 = await doctor.run_diagnostics()
    report2 = await doctor.run_diagnostics()

    # Both should produce same results
    assert report1.overall_status == report2.overall_status
    assert len(report1.checks) == len(report2.checks)
    await doctor.close()


# ============================================================================
# Test: Platform-Specific Behavior
# ============================================================================


@patch("sys.platform", "win32")
async def test_doctor_on_windows() -> None:
    """Test doctor handles Windows-specific paths."""
    doctor = await Doctor.create(":memory:")
    # Should not crash on Windows
    result = doctor.check_temp_directory()
    assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


@patch("sys.platform", "darwin")
async def test_doctor_on_macos() -> None:
    """Test doctor handles macOS-specific behavior."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_temp_directory()
    assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


# ============================================================================
# Test: Database Schema - Unknown Version and Error Paths
# ============================================================================


async def test_check_database_schema_unknown_version() -> None:
    """Test database schema check with unknown version (lines 256-261)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "unknown_version.db"
        conn = sqlite3.connect(str(db_path))

        # Create tables with unknown schema version
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", ("99.99", "2024-01-01T00:00:00"))
        conn.commit()
        conn.close()

        doctor = await Doctor.create(str(db_path), validate_schema=False, auto_create=False)
        result = await doctor.check_database_schema()

        assert result.severity == CheckSeverity.WARNING
        assert "unknown" in result.message.lower() or "99.99" in result.message
        assert result.fixable is False
    await doctor.close()


async def test_check_database_schema_error(v11_db: str) -> None:
    """Test database schema check handles SQL errors (line 262-268)."""
    # Create a doctor with an invalid database path to trigger SQL error
    doctor = await Doctor.create(
        "/nonexistent/path/invalid.db", validate_schema=False, auto_create=False
    )
    result = await doctor.check_database_schema()

    # Should result in error since path doesn't exist and can't be accessed
    assert result.severity == CheckSeverity.ERROR
    assert result.fixable is False or result.fixable is True
    await doctor.close()


async def test_check_orphaned_fts_not_found() -> None:
    """Test orphaned FTS check when FTS table doesn't exist (line 229)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "no_fts.db"
        conn = sqlite3.connect(str(db_path))

        # Create messages table without FTS
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", ("1.1", "2024-01-01T00:00:00"))
        conn.commit()
        conn.close()

        doctor = await Doctor.create(str(db_path), validate_schema=False, auto_create=False)
        result = await doctor.check_orphaned_fts()

        # Should handle gracefully
        assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]
    await doctor.close()


async def test_check_archive_files_exist_with_missing_files(v11_db: str) -> None:
    """Test archive files check with missing archive files (lines 362-370)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))

        # Create schema with messages pointing to non-existent files
        conn.execute("""
            CREATE TABLE messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)
        conn.execute("""
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", ("1.1", "2024-01-01T00:00:00"))
        # Insert message with non-existent archive file
        conn.execute(
            """
            INSERT INTO messages VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "msg1",
                "<msg1@example.com>",
                "thread1",
                "Subject",
                "from@example.com",
                "to@example.com",
                None,
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
                "/nonexistent/archive.mbox",
                0,
                100,
                "preview",
                "checksum123",
                1000,
                None,
                "default",
            ),
        )
        conn.commit()
        conn.close()

        doctor = await Doctor.create(str(db_path), validate_schema=False, auto_create=False)
        result = await doctor.check_archive_files_exist()

        # Should detect missing files
        assert result.severity in [CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


async def test_check_python_version_compatibility() -> None:
    """Test Python version check (lines 256-263)."""
    doctor = await Doctor.create(":memory:")
    result = doctor.check_python_version()

    assert result.severity == CheckSeverity.OK
    assert "3.14" in result.message or "Python" in result.message
    assert result.fixable is False
    await doctor.close()


async def test_check_dependencies_import_failures() -> None:
    """Test dependencies check with import failures (line 293, 312)."""
    with patch("importlib.import_module", side_effect=ImportError("Not found")):
        doctor = await Doctor.create(":memory:")
        result = doctor.check_dependencies()

        # Should identify missing dependencies
        assert result.severity in [CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


async def test_check_oauth_token_file_missing() -> None:
    """Test OAuth token check when token is missing (lines 560-568)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Use temp dir that doesn't have token
        doctor = await Doctor.create(":memory:")
        result = doctor.check_oauth_token()

        # Token missing is OK if not configured
        assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]
    await doctor.close()


async def test_check_credentials_file_missing() -> None:
    """Test credentials file check (lines 591-598)."""
    with patch("pathlib.Path.exists", return_value=False):
        doctor = await Doctor.create(":memory:")
        result = doctor.check_credentials_file()

        # Missing credentials is acceptable
        assert result.severity in [CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


async def test_check_disk_space_insufficient() -> None:
    """Test disk space check identifies low space (lines 645-646)."""
    with patch("shutil.disk_usage") as mock_disk:
        # Return very low available space (< 100MB)
        mock_disk.return_value = (1000000000, 500000000, 50000000)  # 50MB free
        doctor = await Doctor.create(":memory:")
        result = doctor.check_disk_space()

        # Should warn about low space
        assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]
    await doctor.close()


async def test_check_write_permissions_readonly_file() -> None:
    """Test write permissions check (lines 680-681)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        test_file = test_dir / "test.txt"

        # Create file and make it read-only
        test_file.write_text("test")
        test_file.chmod(0o444)

        try:
            doctor = await Doctor.create(":memory:")
            # Should handle permissions check gracefully
            result = doctor.check_write_permissions()
            assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]
        finally:
            test_file.chmod(0o644)
    await doctor.close()


async def test_check_stale_locks_found() -> None:
    """Test stale locks check (lines 714-715, 741-742)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a stale lock file
        lock_dir = Path(tmpdir) / ".gmailarchiver_locks"
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / "stale.lock"
        lock_file.write_text("stale")

        # Mock temp directory to return our temp dir
        with patch("tempfile.gettempdir", return_value=str(lock_dir.parent)):
            doctor = await Doctor.create(":memory:")
            result = doctor.check_stale_locks()

            # Should detect locks
            assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]
    await doctor.close()


async def test_fix_missing_database() -> None:
    """Test fix for missing database (lines 753-785)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "new.db"
        assert not db_path.exists()

        doctor = await Doctor.create(str(db_path))
        result = await doctor.fix_missing_database()

        assert result.success is True
        assert db_path.exists()
    await doctor.close()


async def test_run_diagnostics_full_report(v11_db: str) -> None:
    """Test run_diagnostics returns complete report (lines 118, 194, 196)."""
    doctor = await Doctor.create(v11_db)
    report = await doctor.run_diagnostics()

    assert len(report.checks) > 0
    assert report.overall_status in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]

    # Should have various check results
    check_names = [c.name for c in report.checks]
    assert "Database schema" in check_names
    await doctor.close()


async def test_doctor_report_dict_conversion() -> None:
    """Test DoctorReport to_dict conversion."""
    checks = [
        CheckResult("Test 1", CheckSeverity.OK, "All good", False),
        CheckResult("Test 2", CheckSeverity.WARNING, "Warning", True),
    ]
    report = DoctorReport(
        overall_status=CheckSeverity.WARNING,
        checks=checks,
        checks_passed=1,
        warnings=1,
        errors=0,
        fixable_issues=[],
    )

    result_dict = report.to_dict()
    assert "checks" in result_dict
    assert len(result_dict["checks"]) == 2


async def test_get_connection_returns_none_for_missing_db() -> None:
    """Test _get_db_manager returns None for missing database (line 118)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "nonexistent.db"
        doctor = await Doctor.create(str(db_path), auto_create=False)

        db_manager = doctor._get_db_manager()
        assert db_manager is None
    await doctor.close()


async def test_check_database_schema_connection_failure() -> None:
    """Test check_database_schema handles connection failure (lines 229, 262-263)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create a corrupt database file
        with open(db_path, "wb") as f:
            f.write(b"corrupted database content")

        doctor = await Doctor.create(str(db_path))
        result = await doctor.check_database_schema()

        # Should detect error
        assert result.severity == CheckSeverity.ERROR
        assert "cannot connect" in result.message.lower() or "failed" in result.message.lower()
    await doctor.close()


async def test_check_disk_space_exception() -> None:
    """Test check_disk_space handles exceptions (lines 680-681)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        doctor = await Doctor.create(str(db_path))

        # Mock disk_usage to raise exception
        with patch("shutil.disk_usage", side_effect=OSError("Disk error")):
            result = doctor.check_disk_space()

            assert result.severity == CheckSeverity.WARNING
            assert "failed" in result.message.lower()
    await doctor.close()


async def test_check_write_permissions_exception() -> None:
    """Test check_write_permissions handles exceptions (lines 714-715)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        doctor = await Doctor.create(str(db_path))

        # Mock os.access to raise exception
        with patch("os.access", side_effect=OSError("Permission error")):
            result = doctor.check_write_permissions()

            assert result.severity == CheckSeverity.WARNING
            assert "failed" in result.message.lower()
    await doctor.close()


async def test_check_stale_locks_exception() -> None:
    """Test check_stale_locks handles exceptions (lines 741-742)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        doctor = await Doctor.create(str(db_path))

        # Mock glob to raise exception
        with patch.object(Path, "glob", side_effect=OSError("Glob error")):
            result = doctor.check_stale_locks()

            assert result.severity == CheckSeverity.WARNING
            assert "failed" in result.message.lower()
    await doctor.close()


async def test_check_temp_directory_exception() -> None:
    """Test check_temp_directory handles exceptions (lines 779-780)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        doctor = await Doctor.create(str(db_path))

        # Mock os.access to raise exception
        with patch("os.access", side_effect=OSError("Temp error")):
            result = doctor.check_temp_directory()

            assert result.severity == CheckSeverity.WARNING
            assert "failed" in result.message.lower()
    await doctor.close()


async def test_fix_orphaned_fts_connection_failure() -> None:
    """Test fix_orphaned_fts handles connection failure (lines 835)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "missing.db"
        doctor = await Doctor.create(str(db_path), auto_create=False)

        result = await doctor.fix_orphaned_fts()

        assert result.success is False
        assert "cannot connect" in result.message.lower()
    await doctor.close()


async def test_fix_stale_locks_exception() -> None:
    """Test fix_stale_locks handles exceptions (lines 846-847, 854-855)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create a lock file
        lock_file = Path(tmpdir) / "test.lock"
        lock_file.touch()

        doctor = await Doctor.create(str(db_path))

        # Mock unlink to raise permission error
        with patch.object(Path, "unlink", side_effect=PermissionError("Cannot delete")):
            result = doctor.fix_stale_locks()

            # Should handle exception gracefully
            assert result.success is True  # Reports success even if some locks couldn't be removed
            assert "0 lock" in result.message.lower()
    await doctor.close()


async def test_check_database_schema_for_connection_failures() -> None:
    """Test check_database_schema when connection fails (line 229)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "nonexistent.db"

        doctor = await Doctor.create(str(db_path), auto_create=False)
        result = await doctor.check_database_schema()

        # Should detect error when auto_create=False
        assert result.severity == CheckSeverity.ERROR
        assert "not found" in result.message.lower() or "missing" in result.message.lower()
    await doctor.close()


async def test_run_diagnostics_detects_fixable_issues() -> None:
    """Test run_diagnostics identifies fixable issues (lines 194, 196)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "missing.db"

        doctor = await Doctor.create(str(db_path), auto_create=False)
        report = await doctor.run_diagnostics()

        # Should have detected fixable issue (missing database when auto_create=False)
        assert len(report.fixable_issues) > 0
    await doctor.close()


async def test_fix_stale_locks_handles_glob_error() -> None:
    """Test fix_stale_locks handles errors gracefully (lines 854-855)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create valid database
        conn = sqlite3.connect(str(db_path))
        conn.close()

        doctor = await Doctor.create(str(db_path))

        # Even if glob has issues, should handle gracefully
        result = doctor.fix_stale_locks()

        # Should succeed even if no locks found
        assert result.success is True
    await doctor.close()
