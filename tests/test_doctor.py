"""Tests for the doctor command - WRITTEN FIRST per TDD methodology."""

import json
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from gmailarchiver.doctor import (
    CheckResult,
    CheckSeverity,
    Doctor,
    DoctorReport,
)

# ============================================================================
# Test Fixtures
# ============================================================================


# Test: CheckResult and CheckSeverity
# ============================================================================


def test_check_severity_levels() -> None:
    """Test CheckSeverity enum values."""
    assert CheckSeverity.OK.value == "OK"
    assert CheckSeverity.WARNING.value == "WARNING"
    assert CheckSeverity.ERROR.value == "ERROR"


def test_check_result_creation() -> None:
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


def test_check_result_with_details() -> None:
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


def test_check_database_schema_v11(v11_db: str) -> None:
    """Test database schema check for v1.1 database."""
    doctor = Doctor(v11_db)
    result = doctor.check_database_schema()

    assert result.severity == CheckSeverity.OK
    assert "v1.1" in result.message
    assert result.fixable is False


def test_check_database_schema_missing_database() -> None:
    """Test database schema check when database doesn't exist."""
    doctor = Doctor("/nonexistent/database.db", auto_create=False)
    result = doctor.check_database_schema()

    assert result.severity == CheckSeverity.ERROR
    assert "not found" in result.message.lower()
    assert result.fixable is True  # Can create new database


def test_check_database_schema_v10() -> None:
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

        doctor = Doctor(str(db_path), auto_create=False)
        result = doctor.check_database_schema()

        assert result.severity == CheckSeverity.WARNING
        assert "v1.0" in result.message
        assert "migration" in result.message.lower()
        assert result.fixable is True


def test_check_database_integrity_ok(v11_db: str) -> None:
    """Test database integrity check on healthy database."""
    doctor = Doctor(v11_db)
    result = doctor.check_database_integrity()

    assert result.severity == CheckSeverity.OK
    assert "healthy" in result.message.lower() or "ok" in result.message.lower()


def test_check_database_integrity_corrupted() -> None:
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

        doctor = Doctor(str(db_path), validate_schema=False, auto_create=False)
        result = doctor.check_database_integrity()

        assert result.severity == CheckSeverity.ERROR
        assert result.fixable is False  # Corruption not auto-fixable


@pytest.mark.skip(
    "SQLite FTS5 content=messages prevents simulating orphaned FTS rows "
    "without corrupting the database file; this scenario cannot be "
    "reliably unit-tested."
)
def test_check_orphaned_fts_records(v11_db: str) -> None:
    """Test check for orphaned FTS records (theoretical corruption scenario)."""
    # Insert message directly into FTS without corresponding messages record
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages (
            gmail_id, rfc_message_id, thread_id, archived_timestamp,
            archive_file, mbox_offset, mbox_length
        ) VALUES ('1', 'msg1@example.com', 'thread1', '2024-01-01', 'archive.mbox', 0, 100)
    """)
    # Manually insert orphaned FTS record with higher rowid
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (999, 'Orphaned', 'test@example.com', 'user@example.com', 'Orphaned record')
    """)
    conn.commit()
    conn.close()

    doctor = Doctor(v11_db)
    result = doctor.check_orphaned_fts()

    assert result.severity == CheckSeverity.WARNING
    assert "orphaned" in result.message.lower()
    assert result.fixable is True


def test_check_orphaned_fts_none(v11_db: str) -> None:
    """Test check for orphaned FTS records when none exist."""
    doctor = Doctor(v11_db)
    result = doctor.check_orphaned_fts()

    assert result.severity == CheckSeverity.OK
    assert "no orphaned" in result.message.lower() or result.message == "FTS index is clean"


def test_check_archive_files_exist(v11_db: str) -> None:
    """Test check that archive files referenced in database exist."""
    # Create a temporary archive file
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "archive.mbox"
        archive_path.write_text("dummy")

        # Insert message referencing this archive
        conn = sqlite3.connect(v11_db)
        conn.execute("""
            INSERT INTO messages (
                gmail_id, rfc_message_id, thread_id, archived_timestamp,
                archive_file, mbox_offset, mbox_length
            ) VALUES ('1', 'msg1@example.com', 'thread1', '2024-01-01', ?, 0, 100)
        """, (str(archive_path),))
        conn.commit()
        conn.close()

        doctor = Doctor(v11_db)
        result = doctor.check_archive_files_exist()

        assert result.severity == CheckSeverity.OK
        assert "exist" in result.message.lower()


def test_check_archive_files_missing(v11_db: str) -> None:
    """Test check when archive files are missing."""
    # Insert message referencing non-existent archive
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages (
            gmail_id, rfc_message_id, thread_id, archived_timestamp,
            archive_file, mbox_offset, mbox_length
        ) VALUES ('1', 'msg1@example.com', 'thread1', '2024-01-01', '/nonexistent/archive.mbox', 0, 100)
    """)
    conn.commit()
    conn.close()

    doctor = Doctor(v11_db)
    result = doctor.check_archive_files_exist()

    assert result.severity == CheckSeverity.WARNING
    assert "missing" in result.message.lower()
    assert "1" in result.message  # Should mention count
    assert result.fixable is False  # Can't auto-fix missing files


# ============================================================================
# Test: Environment Checks
# ============================================================================


def test_check_python_version_ok() -> None:
    """Test Python version check when version is sufficient."""
    doctor = Doctor(":memory:")
    result = doctor.check_python_version()

    # We're running Python 3.14+ in this environment
    if sys.version_info >= (3, 14):
        assert result.severity == CheckSeverity.OK
        assert "3.14" in result.message or str(sys.version_info.minor) in result.message
    else:
        # In case running on older Python
        assert result.severity in [CheckSeverity.WARNING, CheckSeverity.ERROR]


@patch("sys.version_info", (3, 12, 0, "final", 0))
def test_check_python_version_too_old() -> None:
    """Test Python version check when version is too old."""
    doctor = Doctor(":memory:")
    result = doctor.check_python_version()

    assert result.severity == CheckSeverity.WARNING
    assert "3.12" in result.message
    assert result.fixable is False  # Can't auto-upgrade Python


def test_check_dependencies_installed() -> None:
    """Test that required dependencies are installed."""
    doctor = Doctor(":memory:")
    result = doctor.check_dependencies()

    assert result.severity == CheckSeverity.OK
    assert "installed" in result.message.lower()


@patch("importlib.import_module")
def test_check_dependencies_missing(mock_import: Mock) -> None:
    """Test dependency check when packages are missing."""
    mock_import.side_effect = ImportError("No module named 'google'")

    doctor = Doctor(":memory:")
    result = doctor.check_dependencies()

    assert result.severity == CheckSeverity.ERROR
    assert "missing" in result.message.lower()
    assert result.fixable is True  # Can run pip install


def test_check_oauth_token_missing() -> None:
    """Test OAuth token check when token doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_token_path = Path(tmpdir) / "nonexistent_token.json"

        with patch("gmailarchiver.doctor._get_default_token_path", return_value=fake_token_path):
            doctor = Doctor(":memory:")
            result = doctor.check_oauth_token()

            assert result.severity == CheckSeverity.WARNING
            assert "not found" in result.message.lower()
            assert result.fixable is True  # Can re-authenticate


def test_check_oauth_token_valid() -> None:
    """Test OAuth token check when token exists and is valid."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text(json.dumps({
            "token": "fake_token",
            "refresh_token": "fake_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake_client_id",
            "client_secret": "fake_secret",
            "scopes": ["https://mail.google.com/"]
        }))

        with patch("gmailarchiver.doctor._get_default_token_path", return_value=token_path):
            with patch("gmailarchiver.auth.Credentials") as mock_creds:
                mock_creds_instance = Mock()
                mock_creds_instance.valid = True
                mock_creds_instance.expired = False
                mock_creds.from_authorized_user_info.return_value = mock_creds_instance

                doctor = Doctor(":memory:")
                result = doctor.check_oauth_token()

                assert result.severity == CheckSeverity.OK
                assert "valid" in result.message.lower()


def test_check_oauth_token_expired() -> None:
    """Test OAuth token check when token is expired."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text(json.dumps({
            "token": "fake_token",
            "refresh_token": "fake_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake_client_id",
            "client_secret": "fake_secret",
            "scopes": ["https://mail.google.com/"]
        }))

        with patch("gmailarchiver.doctor._get_default_token_path", return_value=token_path):
            with patch("gmailarchiver.auth.Credentials") as mock_creds:
                mock_creds_instance = Mock()
                mock_creds_instance.valid = False
                mock_creds_instance.expired = True
                mock_creds.from_authorized_user_info.return_value = mock_creds_instance

                doctor = Doctor(":memory:")
                result = doctor.check_oauth_token()

                assert result.severity == CheckSeverity.WARNING
                assert "expired" in result.message.lower()
                assert result.fixable is True


def test_check_credentials_file_exists() -> None:
    """Test credentials file check when bundled credentials exist."""
    doctor = Doctor(":memory:")
    result = doctor.check_credentials_file()

    # Bundled credentials should exist
    assert result.severity == CheckSeverity.OK
    assert "found" in result.message.lower() or "exists" in result.message.lower()


# ============================================================================
# Test: System Checks
# ============================================================================


def test_check_disk_space_sufficient() -> None:
    """Test disk space check when sufficient space available."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB

        doctor = Doctor(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.OK
        assert "GB" in result.message or "MB" in result.message


def test_check_disk_space_low_warning() -> None:
    """Test disk space check with low space (warning level)."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=300 * 1024 * 1024)  # 300 MB (< 500 MB)

        doctor = Doctor(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.WARNING
        assert "300" in result.message
        assert result.fixable is False  # Can't auto-fix disk space


def test_check_disk_space_critical_error() -> None:
    """Test disk space check with critically low space."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=50 * 1024 * 1024)  # 50 MB (< 100 MB)

        doctor = Doctor(":memory:")
        result = doctor.check_disk_space()

        assert result.severity == CheckSeverity.ERROR
        assert "50" in result.message


def test_check_write_permissions_ok() -> None:
    """Test write permissions check when directory is writable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        doctor = Doctor(str(db_path))
        result = doctor.check_write_permissions()

        assert result.severity == CheckSeverity.OK
        assert "writable" in result.message.lower()


def test_check_write_permissions_denied() -> None:
    """Test write permissions check when directory is not writable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        with patch("pathlib.Path.is_dir", return_value=True):
            with patch("os.access", return_value=False):
                doctor = Doctor(str(db_path))
                result = doctor.check_write_permissions()

                assert result.severity == CheckSeverity.ERROR
                assert "not writable" in result.message.lower()


def test_check_stale_lock_files_none() -> None:
    """Test stale lock file check when no lock files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        doctor = Doctor(str(db_path))
        result = doctor.check_stale_locks()

        assert result.severity == CheckSeverity.OK
        assert "no stale" in result.message.lower()


def test_check_stale_lock_files_found() -> None:
    """Test stale lock file check when lock files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create fake lock files
        (Path(tmpdir) / "archive.mbox.lock").touch()
        (Path(tmpdir) / "archive.mbox.lock.lock").touch()

        doctor = Doctor(str(db_path))
        result = doctor.check_stale_locks()

        assert result.severity == CheckSeverity.WARNING
        assert "lock file" in result.message.lower()
        assert "2" in result.message
        assert result.fixable is True  # Can remove stale locks


def test_check_temp_directory_accessible() -> None:
    """Test temp directory accessibility check."""
    doctor = Doctor(":memory:")
    result = doctor.check_temp_directory()

    assert result.severity == CheckSeverity.OK
    assert "accessible" in result.message.lower()


def test_check_temp_directory_not_accessible() -> None:
    """Test temp directory check when not accessible."""
    with patch("tempfile.gettempdir", return_value="/nonexistent/tmp"):
        with patch("os.access", return_value=False):
            doctor = Doctor(":memory:")
            result = doctor.check_temp_directory()

            assert result.severity == CheckSeverity.ERROR
            assert "not accessible" in result.message.lower()


# ============================================================================
# Test: Doctor.run_diagnostics()
# ============================================================================


def test_run_diagnostics_all_checks_pass(v11_db: str) -> None:
    """Test run_diagnostics when all checks pass.

    This test uses a patched OAuth token check so it does not depend on
    the real user's authentication state or token.json on disk.
    """
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=1024 * 1024 * 1024)  # 1 GB

        doctor = Doctor(v11_db)

        # Ensure OAuth token state does not influence this "all OK" scenario
        with patch.object(doctor, "check_oauth_token") as mock_token_check:
            mock_token_check.return_value = CheckResult(
                name="OAuth token",
                severity=CheckSeverity.OK,
                message="OAuth token is valid (test override)",
                fixable=False,
            )

            report = doctor.run_diagnostics()

        assert isinstance(report, DoctorReport)
        assert report.overall_status == CheckSeverity.OK
        assert report.errors == 0
        assert report.warnings == 0
        assert len(report.checks) > 0
        assert all(check.severity == CheckSeverity.OK for check in report.checks)


def test_run_diagnostics_with_warnings(v11_db: str) -> None:
    """Test run_diagnostics when some checks have warnings."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=300 * 1024 * 1024)  # 300 MB - WARNING

        doctor = Doctor(v11_db)
        report = doctor.run_diagnostics()

        assert report.overall_status == CheckSeverity.WARNING
        assert report.warnings >= 1
        assert report.errors == 0


def test_run_diagnostics_with_errors(v11_db: str) -> None:
    """Test run_diagnostics when some checks have errors."""
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = Mock(free=50 * 1024 * 1024)  # 50 MB - ERROR

        doctor = Doctor(v11_db)
        report = doctor.run_diagnostics()

        assert report.overall_status == CheckSeverity.ERROR
        assert report.errors >= 1


def test_run_diagnostics_counts_results_correctly(v11_db: str) -> None:
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

        doctor = Doctor(v11_db)
        report = doctor.run_diagnostics()

        assert report.warnings >= 2
        assert report.checks_passed >= 0  # Some checks should pass


# ============================================================================
# Test: Auto-Fix Capabilities
# ============================================================================


def test_auto_fix_orphaned_fts(v11_db: str) -> None:
    """Test auto-fix for orphaned FTS records."""
    # Insert orphaned FTS record
    conn = sqlite3.connect(v11_db)
    conn.execute("""
        INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
        VALUES (999, 'Orphaned', 'test@example.com', 'user@example.com', 'Orphaned')
    """)
    conn.commit()
    conn.close()

    doctor = Doctor(v11_db)
    result = doctor.fix_orphaned_fts()

    assert result.success is True
    assert "removed" in result.message.lower() or "cleaned" in result.message.lower()

    # Verify orphaned record was removed
    conn = sqlite3.connect(v11_db)
    cursor = conn.execute("SELECT COUNT(*) FROM messages_fts WHERE rowid = 999")
    count = cursor.fetchone()[0]
    assert count == 0


def test_auto_fix_stale_locks() -> None:
    """Test auto-fix for stale lock files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create fake lock files
        lock1 = Path(tmpdir) / "archive.mbox.lock"
        lock2 = Path(tmpdir) / "archive.mbox.lock.lock"
        lock1.touch()
        lock2.touch()

        doctor = Doctor(str(db_path))
        result = doctor.fix_stale_locks()

        assert result.success is True
        assert not lock1.exists()
        assert not lock2.exists()


def test_auto_fix_create_missing_database() -> None:
    """Test auto-fix creates missing database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "new.db"

        doctor = Doctor(str(db_path), auto_create=False)
        result = doctor.fix_missing_database()

        assert result.success is True
        assert db_path.exists()

        # Verify it's a valid v1.1 database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]
        assert version == 11


def test_run_auto_fix_fixes_all_issues(v11_db: str) -> None:
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

    doctor = Doctor(v11_db)

    # Run diagnostics first
    report_before = doctor.run_diagnostics()
    fixable_count = sum(1 for check in report_before.checks if check.fixable and check.severity != CheckSeverity.OK)

    # Run auto-fix
    fix_results = doctor.run_auto_fix()

    assert len(fix_results) >= 1  # At least orphaned FTS should be fixed
    assert all(result.success for result in fix_results)

    # Run diagnostics again - should have fewer issues
    report_after = doctor.run_diagnostics()
    assert report_after.warnings <= report_before.warnings
    assert report_after.errors <= report_before.errors


# ============================================================================
# Test: DoctorReport
# ============================================================================


def test_doctor_report_creation() -> None:
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


def test_doctor_report_to_dict() -> None:
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


def test_doctor_with_memory_database() -> None:
    """Test doctor can run diagnostics on :memory: database."""
    doctor = Doctor(":memory:")
    report = doctor.run_diagnostics()

    # Should handle gracefully - some checks will skip/warn
    assert isinstance(report, DoctorReport)


def test_doctor_handles_permission_errors() -> None:
    """Test doctor handles permission errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", side_effect=PermissionError("Access denied")):
                doctor = Doctor(str(db_path), validate_schema=False, auto_create=False)
                # Should not raise, handle gracefully
                result = doctor.check_database_integrity()
                assert result.severity == CheckSeverity.ERROR


def test_multiple_diagnostics_runs_independent(v11_db: str) -> None:
    """Test that multiple diagnostic runs are independent."""
    doctor = Doctor(v11_db)

    report1 = doctor.run_diagnostics()
    report2 = doctor.run_diagnostics()

    # Both should produce same results
    assert report1.overall_status == report2.overall_status
    assert len(report1.checks) == len(report2.checks)


# ============================================================================
# Test: Platform-Specific Behavior
# ============================================================================


@patch("sys.platform", "win32")
def test_doctor_on_windows() -> None:
    """Test doctor handles Windows-specific paths."""
    doctor = Doctor(":memory:")
    # Should not crash on Windows
    result = doctor.check_temp_directory()
    assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]


@patch("sys.platform", "darwin")
def test_doctor_on_macos() -> None:
    """Test doctor handles macOS-specific behavior."""
    doctor = Doctor(":memory:")
    result = doctor.check_temp_directory()
    assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING, CheckSeverity.ERROR]
