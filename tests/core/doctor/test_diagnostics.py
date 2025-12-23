"""Tests for DiagnosticsRunner - comprehensive coverage for missing lines."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity, DiagnosticsRunner
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.hybrid_storage import HybridStorage

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test: Database Schema Checks - Missing Lines
# ============================================================================


async def test_check_database_schema_no_storage(v11_db: str) -> None:
    """Test check_database_schema when storage is None (line 72)."""
    runner = DiagnosticsRunner(Path(v11_db), storage=None)
    result = await runner.check_database_schema()

    assert result.severity == CheckSeverity.ERROR
    assert "cannot connect" in result.message.lower()
    assert result.fixable is False


async def test_check_database_schema_no_connection(v11_db: str, db_manager: DBManager) -> None:
    """Test check_database_schema when connection is None (line 80)."""
    storage = HybridStorage(db_manager)

    # Close the connection to make it None
    await db_manager.close()

    runner = DiagnosticsRunner(Path(v11_db), storage=storage)
    result = await runner.check_database_schema()

    assert result.severity == CheckSeverity.ERROR
    # The actual error message varies - just check it's an error about connection
    assert "connection" in result.message.lower() or "failed" in result.message.lower()
    assert result.fixable is False


async def test_check_database_integrity_corruption_detected(v11_db: str) -> None:
    """Test check_database_integrity when corruption is detected (line 146)."""
    # Create a fresh DBManager for this test
    db_mgr = DBManager(v11_db)
    await db_mgr.initialize()
    storage = HybridStorage(db_mgr)
    runner = DiagnosticsRunner(Path(v11_db), storage=storage)

    # Create an async mock for the cursor
    async def mock_fetchone():
        return ("corruption detected",)

    mock_cursor = Mock()
    mock_cursor.fetchone = mock_fetchone

    # Create async mock for execute
    async def mock_execute(*args, **kwargs):
        return mock_cursor

    # Mock the execute method to return our mock cursor
    with patch.object(db_mgr._conn, "execute", side_effect=mock_execute):
        result = await runner.check_database_integrity()

        assert result.severity == CheckSeverity.ERROR
        assert "corruption" in result.message.lower()
        assert result.fixable is False

    await db_mgr.close()


async def test_check_archive_files_exist_empty_database(v11_db: str) -> None:
    """Test check_archive_files_exist when database has no messages (line 253)."""
    # Use v11_db which has messages table but no messages
    db_mgr = DBManager(v11_db)
    await db_mgr.initialize()
    storage = HybridStorage(db_mgr)

    runner = DiagnosticsRunner(Path(v11_db), storage=storage)
    result = await runner.check_archive_files_exist()

    assert result.severity == CheckSeverity.OK
    assert "no archive" in result.message.lower() or "no messages" in result.message.lower()
    await db_mgr.close()


# ============================================================================
# Test: Python Version Checks - Edge Cases (line 331)
# ============================================================================


@patch("sys.version_info", (3, 11, 5, "final", 0))
async def test_check_python_version_too_old(tmp_path: Path) -> None:
    """Test check_python_version with Python < 3.12 (line 331)."""
    fake_db = tmp_path / "test.db"
    runner = DiagnosticsRunner(fake_db, storage=None)
    result = runner.check_python_version()

    assert result.severity == CheckSeverity.ERROR
    assert "3.11" in result.message
    assert "requires: 3.12+" in result.message.lower()
    assert result.fixable is False


@patch("sys.version_info", (3, 14, 2))  # Tuple without named attributes
async def test_check_python_version_tuple_fallback(tmp_path: Path) -> None:
    """Test check_python_version with simple tuple version_info."""
    fake_db = tmp_path / "test.db"
    runner = DiagnosticsRunner(fake_db, storage=None)
    result = runner.check_python_version()

    assert result.severity == CheckSeverity.OK
    assert "3.14" in result.message


# ============================================================================
# Test: OAuth Token Checks - Error Paths (lines 408-416)
# ============================================================================


async def test_check_oauth_token_invalid_credentials() -> None:
    """Test check_oauth_token when credentials are invalid but not expired (lines 408-414)."""
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
                # Credentials that are neither valid nor expired (invalid state)
                mock_creds_instance = Mock()
                mock_creds_instance.valid = False
                mock_creds_instance.expired = False
                mock_creds.from_authorized_user_info.return_value = mock_creds_instance

                fake_db = Path(tmpdir) / "test.db"
                runner = DiagnosticsRunner(fake_db, storage=None)
                result = runner.check_oauth_token()

                assert result.severity == CheckSeverity.WARNING
                assert "invalid" in result.message.lower()
                assert result.fixable is True
                assert "auth-reset" in result.details.lower()


async def test_check_oauth_token_corrupted_json() -> None:
    """Test check_oauth_token with corrupted JSON (lines 415-422)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text("{invalid json")
        fake_db = Path(tmpdir) / "test.db"

        with patch(
            "gmailarchiver.core.doctor._diagnostics._get_default_token_path",
            return_value=token_path,
        ):
            runner = DiagnosticsRunner(fake_db, storage=None)
            result = runner.check_oauth_token()

            assert result.severity == CheckSeverity.WARNING
            assert "corrupted" in result.message.lower()
            assert result.fixable is True


async def test_check_oauth_token_missing_key() -> None:
    """Test check_oauth_token with missing required key (lines 415-422)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "token.json"
        token_path.write_text(json.dumps({"token": "fake_token"}))  # Missing required fields
        fake_db = Path(tmpdir) / "test.db"

        with patch(
            "gmailarchiver.core.doctor._diagnostics._get_default_token_path",
            return_value=token_path,
        ):
            runner = DiagnosticsRunner(fake_db, storage=None)
            result = runner.check_oauth_token()

            assert result.severity == CheckSeverity.WARNING
            assert "corrupted" in result.message.lower()


async def test_check_oauth_token_value_error() -> None:
    """Test check_oauth_token with ValueError from credentials (lines 415-422)."""
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
        fake_db = Path(tmpdir) / "test.db"

        with patch(
            "gmailarchiver.core.doctor._diagnostics._get_default_token_path",
            return_value=token_path,
        ):
            with patch(
                "gmailarchiver.connectors.auth.Credentials.from_authorized_user_info",
                side_effect=ValueError("Invalid credentials format"),
            ):
                runner = DiagnosticsRunner(fake_db, storage=None)
                result = runner.check_oauth_token()

                assert result.severity == CheckSeverity.WARNING
                assert "corrupted" in result.message.lower()


# ============================================================================
# Test: Credentials File Check - Exception Path (lines 445-446)
# ============================================================================


async def test_check_credentials_file_exception(tmp_path: Path) -> None:
    """Test check_credentials_file handles exceptions (lines 445-451)."""
    # Import the auth module to patch it
    import gmailarchiver.connectors.auth

    fake_db = tmp_path / "test.db"
    with patch.object(
        gmailarchiver.connectors.auth,
        "_get_bundled_credentials_path",
        side_effect=RuntimeError("Credentials path error"),
    ):
        runner = DiagnosticsRunner(fake_db, storage=None)
        result = runner.check_credentials_file()

        assert result.severity == CheckSeverity.ERROR
        assert "failed" in result.message.lower() or "error" in result.message.lower()
        assert result.fixable is False


# ============================================================================
# Test: Mbox Offsets Check - Comprehensive Coverage (lines 605-685)
# ============================================================================


async def test_check_mbox_offsets_no_storage(tmp_path: Path) -> None:
    """Test check_mbox_offsets when storage is None (lines 605-611)."""
    fake_db = tmp_path / "test.db"
    runner = DiagnosticsRunner(fake_db, storage=None)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.OK
    assert "skipped" in result.message.lower()
    assert result.fixable is False


async def test_check_mbox_offsets_no_db(tmp_path: Path) -> None:
    """Test check_mbox_offsets when db is None."""
    db_path = tmp_path / "test.db"
    db_manager = DBManager(str(db_path))
    await db_manager.initialize()
    storage = HybridStorage(db_manager)

    # Mock storage.db to be None
    storage.db = None

    runner = DiagnosticsRunner(db_path, storage=storage)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.OK
    assert "skipped" in result.message.lower()
    await db_manager.close()


async def test_check_mbox_offsets_closed_connection(v11_db: str) -> None:
    """Test check_mbox_offsets when connection is None after closing."""
    # Create a DBManager and close it
    db_manager = DBManager(v11_db)
    await db_manager.initialize()
    storage = HybridStorage(db_manager)
    await db_manager.close()  # Close connection to make it None

    runner = DiagnosticsRunner(Path(v11_db), storage=storage)
    result = await runner.check_mbox_offsets()

    # After close, connection is None which causes exception handled as WARNING
    assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]
    assert "skipped" in result.message.lower() or "failed" in result.message.lower()


async def test_check_mbox_offsets_empty_database(v11_db: str) -> None:
    """Test check_mbox_offsets when database has no messages (lines 661-667)."""
    # Use v11_db which has messages table but no messages
    db_mgr = DBManager(v11_db)
    await db_mgr.initialize()
    storage = HybridStorage(db_mgr)

    runner = DiagnosticsRunner(Path(v11_db), storage=storage)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.OK
    assert "no messages" in result.message.lower()
    await db_mgr.close()


async def test_check_mbox_offsets_with_archive_file(db_manager: DBManager) -> None:
    """Test check_mbox_offsets with specific archive file (lines 632-639)."""
    storage = HybridStorage(db_manager)

    # Insert test messages with invalid offsets for specific archive
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
        """,
        (
            "<test1@example.com>",
            "test1",
            "thread1",
            "Test 1",
            "from@example.com",
            "to@example.com",
            "2024-01-01T00:00:00",
            "archive1.mbox",
            -1,  # Invalid offset
            100,
            "default",
        ),
    )
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
        """,
        (
            "<test2@example.com>",
            "test2",
            "thread2",
            "Test 2",
            "from@example.com",
            "to@example.com",
            "2024-01-01T00:00:00",
            "archive2.mbox",
            0,  # Valid offset
            100,
            "default",
        ),
    )
    await db_manager.commit()

    runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
    result = await runner.check_mbox_offsets(archive_file="archive1.mbox")

    assert result.severity == CheckSeverity.WARNING
    assert "invalid" in result.message.lower()
    assert result.fixable is True


async def test_check_mbox_offsets_without_archive_file(db_manager: DBManager) -> None:
    """Test check_mbox_offsets without specific archive file (lines 641-646)."""
    storage = HybridStorage(db_manager)

    # Insert message with negative offset (invalid - mbox_offset can't be NULL per schema)
    if db_manager._conn:
        await db_manager._conn.execute(
            """
            INSERT INTO messages (
                rfc_message_id, gmail_id, thread_id, subject, from_addr,
                to_addr, date, archived_timestamp, archive_file,
                mbox_offset, mbox_length, account_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
            """,
            (
                "<test@example.com>",
                "test",
                "thread",
                "Test",
                "from@example.com",
                "to@example.com",
                "2024-01-01T00:00:00",
                "archive.mbox",
                -10,  # Negative offset (invalid)
                100,
                "default",
            ),
        )
        await db_manager.commit()

        runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
        result = await runner.check_mbox_offsets()

        assert result.severity == CheckSeverity.WARNING
        assert "invalid" in result.message.lower()


async def test_check_mbox_offsets_zero_messages(db_manager: DBManager) -> None:
    """Test check_mbox_offsets when total_count is 0 (lines 661-667)."""
    storage = HybridStorage(db_manager)

    runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.OK
    assert "no messages" in result.message.lower()
    assert result.fixable is False


async def test_check_mbox_offsets_all_valid(db_manager: DBManager) -> None:
    """Test check_mbox_offsets when all offsets are valid (lines 669-675)."""
    storage = HybridStorage(db_manager)

    # Insert message with valid offset
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
        """,
        (
            "<test@example.com>",
            "test",
            "thread",
            "Test",
            "from@example.com",
            "to@example.com",
            "2024-01-01T00:00:00",
            "archive.mbox",
            0,  # Valid offset
            100,
            "default",
        ),
    )
    await db_manager.commit()

    runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.OK
    assert "offsets are valid" in result.message.lower()
    assert result.fixable is False


async def test_check_mbox_offsets_with_invalid(db_manager: DBManager) -> None:
    """Test check_mbox_offsets with invalid offsets (lines 676-683)."""
    storage = HybridStorage(db_manager)

    # Insert messages with invalid offsets
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
        """,
        (
            "<test1@example.com>",
            "test1",
            "thread1",
            "Test 1",
            "from@example.com",
            "to@example.com",
            "2024-01-01T00:00:00",
            "archive.mbox",
            -5,  # Invalid offset
            100,
            "default",
        ),
    )
    await db_manager._conn.execute(
        """
        INSERT INTO messages (
            rfc_message_id, gmail_id, thread_id, subject, from_addr,
            to_addr, date, archived_timestamp, archive_file,
            mbox_offset, mbox_length, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
        """,
        (
            "<test2@example.com>",
            "test2",
            "thread2",
            "Test 2",
            "from@example.com",
            "to@example.com",
            "2024-01-01T00:00:00",
            "archive.mbox",
            0,  # Valid offset
            100,
            "default",
        ),
    )
    await db_manager.commit()

    runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
    result = await runner.check_mbox_offsets()

    assert result.severity == CheckSeverity.WARNING
    assert "invalid" in result.message.lower()
    assert result.fixable is True
    assert "repair --backfill" in result.details.lower()


async def test_check_mbox_offsets_exception(db_manager: DBManager) -> None:
    """Test check_mbox_offsets handles exceptions (lines 684-690)."""
    storage = HybridStorage(db_manager)

    # Mock execute to raise exception
    with patch.object(
        db_manager._conn,
        "execute",
        side_effect=Exception("Database error"),
    ):
        runner = DiagnosticsRunner(Path(db_manager.db_path), storage=storage)
        result = await runner.check_mbox_offsets()

        assert result.severity == CheckSeverity.WARNING
        assert "failed" in result.message.lower()
        assert result.fixable is False


# ============================================================================
# Test: Integration - DiagnosticsRunner with Real Scenarios
# ============================================================================


async def test_diagnostics_runner_all_checks_pass(v11_db: str, db_manager: DBManager) -> None:
    """Test DiagnosticsRunner with all checks passing."""
    storage = HybridStorage(db_manager)
    runner = DiagnosticsRunner(Path(v11_db), storage=storage)

    # Run all check methods
    schema_result = await runner.check_database_schema()
    integrity_result = await runner.check_database_integrity()
    fts_result = await runner.check_orphaned_fts()
    archives_result = await runner.check_archive_files_exist()
    python_result = runner.check_python_version()
    deps_result = runner.check_dependencies()
    disk_result = runner.check_disk_space()
    perms_result = runner.check_write_permissions()
    locks_result = runner.check_stale_locks()
    temp_result = runner.check_temp_directory()

    # All should be OK or WARNING (not ERROR)
    results = [
        schema_result,
        integrity_result,
        fts_result,
        archives_result,
        python_result,
        deps_result,
        disk_result,
        perms_result,
        locks_result,
        temp_result,
    ]

    for result in results:
        assert isinstance(result, CheckResult)
        assert result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]


async def test_diagnostics_runner_no_storage(tmp_path: Path) -> None:
    """Test DiagnosticsRunner without storage (graceful handling)."""
    fake_db = tmp_path / "test.db"
    runner = DiagnosticsRunner(fake_db, storage=None)

    # Should handle missing storage gracefully
    schema_result = await runner.check_database_schema()
    disk_result = runner.check_disk_space()
    perms_result = runner.check_write_permissions()

    # Schema check should report cannot connect since storage is None
    assert schema_result.severity in [CheckSeverity.OK, CheckSeverity.ERROR]
    assert disk_result.severity in [CheckSeverity.OK, CheckSeverity.WARNING]
    assert perms_result.severity == CheckSeverity.OK
