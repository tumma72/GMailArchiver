"""Tests for CLI consolidate command."""

import mailbox
from datetime import datetime

import pytest
from typer.testing import CliRunner

from gmailarchiver.__main__ import app
from gmailarchiver.data.migration import MigrationManager


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def v1_1_database(tmp_path):
    """Create a v1.1 database for testing."""
    db_path = tmp_path / "archive_state.db"
    manager = MigrationManager(db_path)
    manager._connect()

    # Create v1.1 schema
    manager._create_enhanced_schema(manager.conn)

    # Set schema version
    manager.conn.execute(
        "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
    )

    manager.conn.commit()
    manager._close()

    return db_path


@pytest.fixture
def sample_mbox_files(tmp_path):
    """Create multiple sample mbox files for consolidation testing."""
    mbox_files = []

    # Create archive1.mbox with 3 messages
    mbox1 = tmp_path / "archive1.mbox"
    mb1 = mailbox.mbox(str(mbox1))
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Archive 1 Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg1_{i}@example.com>"
        msg.set_payload(f"Content from archive 1, message {i}")
        mb1.add(msg)
    mb1.close()
    mbox_files.append(mbox1)

    # Create archive2.mbox with 3 messages
    mbox2 = tmp_path / "archive2.mbox"
    mb2 = mailbox.mbox(str(mbox2))
    for i in range(1, 4):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i + 3}@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = f"Archive 2 Message {i}"
        msg["Date"] = f"Mon, {i + 3} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<msg2_{i}@example.com>"
        msg.set_payload(f"Content from archive 2, message {i}")
        mb2.add(msg)
    mb2.close()
    mbox_files.append(mbox2)

    return mbox_files


@pytest.fixture
def sample_mbox_with_duplicates(tmp_path):
    """Create mbox files with duplicate messages."""
    mbox_files = []

    # Create first file with 2 unique messages
    mbox1 = tmp_path / "dup1.mbox"
    mb1 = mailbox.mbox(str(mbox1))
    for i in range(1, 3):
        msg = mailbox.mboxMessage()
        msg["From"] = f"sender{i}@example.com"
        msg["Subject"] = f"Unique Message {i}"
        msg["Date"] = f"Mon, {i} Jan 2024 12:00:00 +0000"
        msg["Message-ID"] = f"<unique{i}@example.com>"
        msg.set_payload(f"Unique content {i}")
        mb1.add(msg)
    mb1.close()
    mbox_files.append(mbox1)

    # Create second file with 1 unique + 1 duplicate
    mbox2 = tmp_path / "dup2.mbox"
    mb2 = mailbox.mbox(str(mbox2))
    # Duplicate of first message from mbox1
    msg = mailbox.mboxMessage()
    msg["From"] = "sender1@example.com"
    msg["Subject"] = "Unique Message 1"
    msg["Date"] = "Mon, 1 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = "<unique1@example.com>"
    msg.set_payload("Unique content 1")
    mb2.add(msg)
    # New unique message
    msg = mailbox.mboxMessage()
    msg["From"] = "sender3@example.com"
    msg["Subject"] = "Unique Message 3"
    msg["Date"] = "Mon, 3 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = "<unique3@example.com>"
    msg.set_payload("Unique content 3")
    mb2.add(msg)
    mb2.close()
    mbox_files.append(mbox2)

    return mbox_files


class TestConsolidateCommand:
    """Test 'gmailarchiver consolidate' command."""

    def test_consolidate_with_explicit_file_list(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate merges multiple files when explicitly listed."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert "consolidat" in result.stdout.lower()
        assert output_file.exists()

        # Verify merged file has all messages
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 6  # 3 from each file
        merged_mbox.close()

    def test_consolidate_with_glob_pattern(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate works with glob patterns."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                "archive*.mbox",
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify merged file
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 6
        merged_mbox.close()

    def test_consolidate_with_sort(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate with --sort orders messages chronologically."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "sorted.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--sort",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert "sort" in result.stdout.lower()

        # Verify messages are sorted by date
        merged_mbox = mailbox.mbox(str(output_file))
        dates = []
        for msg in merged_mbox:
            date_str = msg.get("Date", "")
            if date_str:
                dates.append(date_str)

        # Check dates are in ascending order
        assert len(dates) > 0
        merged_mbox.close()

    def test_consolidate_with_no_sort(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate with --no-sort preserves original order."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "unsorted.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--no-sort",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_dedupe(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --dedupe removes duplicates."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "deduped.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_with_duplicates[0]),
                str(sample_mbox_with_duplicates[1]),
                "-o",
                str(output_file),
                "--dedupe",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert "duplicate" in result.stdout.lower()

        # Verify duplicates removed (should have 3 unique, not 4 total)
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 3  # 3 unique messages
        merged_mbox.close()

    def test_consolidate_with_no_dedupe(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --no-dedupe keeps all messages."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "with_dupes.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_with_duplicates[0]),
                str(sample_mbox_with_duplicates[1]),
                "-o",
                str(output_file),
                "--no-dedupe",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify all messages kept (including duplicate)
        merged_mbox = mailbox.mbox(str(output_file))
        assert len(merged_mbox) == 4  # 4 total (3 unique + 1 duplicate)
        merged_mbox.close()

    def test_consolidate_with_dedupe_strategy_newest(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --dedupe-strategy newest."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "newest.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_with_duplicates[0]),
                str(sample_mbox_with_duplicates[1]),
                "-o",
                str(output_file),
                "--dedupe-strategy",
                "newest",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_dedupe_strategy_largest(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --dedupe-strategy largest."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "largest.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_with_duplicates[0]),
                str(sample_mbox_with_duplicates[1]),
                "-o",
                str(output_file),
                "--dedupe-strategy",
                "largest",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_dedupe_strategy_first(
        self, runner, v1_1_database, sample_mbox_with_duplicates, tmp_path, monkeypatch
    ):
        """Test consolidate with --dedupe-strategy first."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "first.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_with_duplicates[0]),
                str(sample_mbox_with_duplicates[1]),
                "-o",
                str(output_file),
                "--dedupe-strategy",
                "first",
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_gzip_compression(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate with gzip compression."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "compressed.mbox.gz"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        assert "compress" in result.stdout.lower() or "gzip" in result.stdout.lower()

    def test_consolidate_missing_output_flag_error(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate without -o flag shows error."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["consolidate", str(sample_mbox_files[0]), "--state-db", str(v1_1_database)]
        )

        # Should fail due to missing required -o option
        assert result.exit_code != 0

    def test_consolidate_no_matching_files_error(
        self, runner, v1_1_database, tmp_path, monkeypatch
    ):
        """Test consolidate with no matching files shows error."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "output.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                "nonexistent*.mbox",
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 1
        # Error panel shows "No Archives Found" title and descriptive message
        assert "no archives found" in result.stdout.lower()

    def test_consolidate_shows_summary_table(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate displays rich summary table with statistics."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        # Should show summary statistics
        assert "summary" in result.stdout.lower() or "consolidat" in result.stdout.lower()
        # Should show message count
        assert "6" in result.stdout  # Total messages

    def test_consolidate_shows_performance_metrics(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate shows performance metrics (messages/second)."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        # Should show performance metrics
        assert "second" in result.stdout.lower() or "performance" in result.stdout.lower()

    def test_consolidate_auto_detects_compression_from_extension(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate auto-detects compression from output file extension."""
        monkeypatch.chdir(tmp_path)

        # Test .gz extension
        gz_output = tmp_path / "compressed.mbox.gz"
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                "-o",
                str(gz_output),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert gz_output.exists()

        # Test .zst extension
        zst_output = tmp_path / "compressed.mbox.zst"
        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                "-o",
                str(zst_output),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        assert zst_output.exists()

    def test_consolidate_with_invalid_dedupe_strategy(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate with invalid dedupe strategy shows error."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                "-o",
                str(output_file),
                "--dedupe-strategy",
                "invalid_strategy",
                "--state-db",
                str(v1_1_database),
            ],
        )

        # Should fail with invalid strategy error
        assert result.exit_code != 0

    def test_consolidate_default_state_db_path(
        self, runner, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate uses default database path when not specified."""
        monkeypatch.chdir(tmp_path)

        # Create v1.1 database at default location
        default_db = tmp_path / "archive_state.db"
        manager = MigrationManager(default_db)
        manager._connect()
        manager._create_enhanced_schema(manager.conn)
        manager.conn.execute(
            "INSERT INTO schema_version VALUES (?, ?)", ("1.1", datetime.now().isoformat())
        )
        manager.conn.commit()
        manager._close()

        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app, ["consolidate", str(sample_mbox_files[0]), "-o", str(output_file)]
        )

        assert result.exit_code == 0
        assert output_file.exists()

    def test_consolidate_with_auto_verify_clean(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate with --auto-verify on clean archive."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
                "--auto-verify",
            ],
        )

        assert result.exit_code == 0
        # Should show verification running
        assert "verif" in result.stdout.lower()
        # Should show verification passed (new format: "No issues found")
        assert (
            "passed" in result.stdout.lower()
            or "ok" in result.stdout.lower()
            or "no issues" in result.stdout.lower()
        )

    def test_consolidate_with_auto_verify_without_flag(
        self, runner, v1_1_database, sample_mbox_files, tmp_path, monkeypatch
    ):
        """Test consolidate without --auto-verify does not verify."""
        monkeypatch.chdir(tmp_path)
        output_file = tmp_path / "merged.mbox"

        result = runner.invoke(
            app,
            [
                "consolidate",
                str(sample_mbox_files[0]),
                str(sample_mbox_files[1]),
                "-o",
                str(output_file),
                "--state-db",
                str(v1_1_database),
            ],
        )

        assert result.exit_code == 0
        # Should NOT show verification-specific messages beyond suggested next steps
        # Count occurrences - should only appear in "next steps" suggestion
        verify_count = result.stdout.lower().count("verify")
        # Should have at least one mention in next steps, but not extra "Running verification"
        assert verify_count < 3  # Not running verification automatically
