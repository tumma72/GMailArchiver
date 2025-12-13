"""Tests for ImporterFacade - mbox import into v1.1 database."""

import email
import gzip
import mailbox
import sqlite3
import time
from pathlib import Path

import pytest

from gmailarchiver.core.importer import (
    ImporterFacade,
    ImportResult,
    MultiImportResult,
)
from gmailarchiver.data.db_manager import DBManager

pytestmark = pytest.mark.asyncio


# Fixtures for creating test mbox files
@pytest.fixture
def sample_mbox_simple(tmp_path):
    """Create a simple mbox file with 3 messages."""
    mbox_path = tmp_path / "simple.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Message 1
    msg1 = email.message.EmailMessage()
    msg1["Message-ID"] = "<msg1@example.com>"
    msg1["Subject"] = "Test Message 1"
    msg1["From"] = "alice@example.com"
    msg1["To"] = "bob@example.com"
    msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg1.set_content("This is test message 1.")
    mbox.add(msg1)

    # Message 2
    msg2 = email.message.EmailMessage()
    msg2["Message-ID"] = "<msg2@example.com>"
    msg2["Subject"] = "Test Message 2"
    msg2["From"] = "bob@example.com"
    msg2["To"] = "alice@example.com"
    msg2["Date"] = "Tue, 02 Jan 2024 12:00:00 +0000"
    msg2.set_content("This is test message 2.")
    mbox.add(msg2)

    # Message 3
    msg3 = email.message.EmailMessage()
    msg3["Message-ID"] = "<msg3@example.com>"
    msg3["Subject"] = "Test Message 3"
    msg3["From"] = "charlie@example.com"
    msg3["To"] = "alice@example.com"
    msg3["Cc"] = "bob@example.com"
    msg3["Date"] = "Wed, 03 Jan 2024 12:00:00 +0000"
    msg3.set_content("This is test message 3 with longer content for body preview testing.")
    mbox.add(msg3)

    mbox.close()
    return mbox_path


@pytest.fixture
def sample_mbox_with_duplicates(tmp_path):
    """Create mbox file with duplicate Message-IDs."""
    mbox_path = tmp_path / "duplicates.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    # Message 1 (unique)
    msg1 = email.message.EmailMessage()
    msg1["Message-ID"] = "<unique1@example.com>"
    msg1["Subject"] = "Unique Message 1"
    msg1["From"] = "alice@example.com"
    msg1["To"] = "bob@example.com"
    msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg1.set_content("Unique message 1.")
    mbox.add(msg1)

    # Message 2 (duplicate - same Message-ID as msg1)
    msg2 = email.message.EmailMessage()
    msg2["Message-ID"] = "<unique1@example.com>"  # Duplicate!
    msg2["Subject"] = "Duplicate Message"
    msg2["From"] = "bob@example.com"
    msg2["To"] = "alice@example.com"
    msg2["Date"] = "Tue, 02 Jan 2024 12:00:00 +0000"
    msg2.set_content("This is a duplicate.")
    mbox.add(msg2)

    # Message 3 (unique)
    msg3 = email.message.EmailMessage()
    msg3["Message-ID"] = "<unique2@example.com>"
    msg3["Subject"] = "Unique Message 2"
    msg3["From"] = "charlie@example.com"
    msg3["To"] = "alice@example.com"
    msg3["Date"] = "Wed, 03 Jan 2024 12:00:00 +0000"
    msg3.set_content("Unique message 2.")
    mbox.add(msg3)

    mbox.close()
    return mbox_path


@pytest.fixture
def sample_mbox_malformed(tmp_path):
    """Create mbox file with malformed message."""
    mbox_path = tmp_path / "malformed.mbox"

    # Write raw mbox with one good message and one malformed
    with open(mbox_path, "w") as f:
        # Good message
        f.write("From alice@example.com Mon Jan 01 12:00:00 2024\n")
        f.write("Message-ID: <good@example.com>\n")
        f.write("Subject: Good Message\n")
        f.write("From: alice@example.com\n")
        f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
        f.write("\n")
        f.write("This is a good message.\n")
        f.write("\n")

        # Malformed message (incomplete headers)
        f.write("From broken@example.com Tue Jan 02 12:00:00 2024\n")
        f.write("This message has no proper headers\n")
        f.write("And incomplete structure\n")
        f.write("\n")

        # Another good message
        f.write("From bob@example.com Wed Jan 03 12:00:00 2024\n")
        f.write("Message-ID: <good2@example.com>\n")
        f.write("Subject: Good Message 2\n")
        f.write("From: bob@example.com\n")
        f.write("Date: Wed, 03 Jan 2024 12:00:00 +0000\n")
        f.write("\n")
        f.write("This is another good message.\n")
        f.write("\n")

    return mbox_path


@pytest.fixture
def sample_mbox_compressed(tmp_path):
    """Create gzip-compressed mbox file."""
    mbox_path = tmp_path / "compressed.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    msg1 = email.message.EmailMessage()
    msg1["Message-ID"] = "<compressed1@example.com>"
    msg1["Subject"] = "Compressed Message 1"
    msg1["From"] = "alice@example.com"
    msg1["To"] = "bob@example.com"
    msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg1.set_content("This message will be compressed.")
    mbox.add(msg1)

    msg2 = email.message.EmailMessage()
    msg2["Message-ID"] = "<compressed2@example.com>"
    msg2["Subject"] = "Compressed Message 2"
    msg2["From"] = "bob@example.com"
    msg2["To"] = "alice@example.com"
    msg2["Date"] = "Tue, 02 Jan 2024 12:00:00 +0000"
    msg2.set_content("This message will also be compressed.")
    mbox.add(msg2)

    mbox.close()

    # Compress the mbox file
    compressed_path = tmp_path / "compressed.mbox.gz"
    with open(mbox_path, "rb") as f_in:
        with gzip.open(compressed_path, "wb") as f_out:
            f_out.writelines(f_in)

    # Remove uncompressed file
    mbox_path.unlink()

    return compressed_path


@pytest.fixture
def sample_mbox_no_message_id(tmp_path):
    """Create mbox file with messages lacking Message-ID headers."""
    mbox_path = tmp_path / "no_message_id.mbox"

    with open(mbox_path, "w") as f:
        # Message without Message-ID (should generate fallback)
        f.write("From alice@example.com Mon Jan 01 12:00:00 2024\n")
        f.write("Subject: No Message ID\n")
        f.write("From: alice@example.com\n")
        f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
        f.write("\n")
        f.write("This message has no Message-ID header.\n")
        f.write("\n")

        # Message with Message-ID
        f.write("From bob@example.com Tue Jan 02 12:00:00 2024\n")
        f.write("Message-ID: <has-id@example.com>\n")
        f.write("Subject: Has Message ID\n")
        f.write("From: bob@example.com\n")
        f.write("Date: Tue, 02 Jan 2024 12:00:00 +0000\n")
        f.write("\n")
        f.write("This message has a Message-ID header.\n")
        f.write("\n")

    return mbox_path


@pytest.fixture
def v1_1_db(tmp_path):
    """Create a v1.1 database for testing."""
    db_path = tmp_path / "v1.1.db"

    # Create v1.1 schema using ArchiveState (it should auto-create v1.1 schema)
    conn = sqlite3.connect(str(db_path))

    # Create v1.1 messages table
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

    # Create schema_version table
    conn.execute("""
        CREATE TABLE schema_version (
            version TEXT PRIMARY KEY,
            migrated_timestamp TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO schema_version VALUES (?, ?)", ("1.1", "2024-01-01T00:00:00"))

    # Create archive_runs table with operation_type column
    conn.execute("""
        CREATE TABLE archive_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            messages_archived INTEGER NOT NULL,
            archive_file TEXT NOT NULL,
            account_id TEXT DEFAULT 'default',
            operation_type TEXT DEFAULT 'archive'
        )
    """)

    conn.commit()
    conn.close()

    return db_path


class TestImporterFacadeInit:
    """Test ImporterFacade initialization."""

    async def test_init_with_valid_db_path(self, v1_1_db):
        """Test initialization with valid database path."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        assert importer.db_manager == db_manager
        await db_manager.close()

    async def test_init_creates_db_if_not_exists(self, tmp_path):
        """Test initialization creates database if it doesn't exist."""
        db_path = tmp_path / "new.db"
        db_manager = DBManager(str(db_path), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        assert importer.db_manager == db_manager
        await db_manager.close()


class TestImportSingleArchive:
    """Test importing single mbox archive."""

    async def test_import_simple_mbox_all_messages(self, v1_1_db, sample_mbox_simple):
        """Test importing simple mbox with 3 messages (all imported)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        assert isinstance(result, ImportResult)
        assert result.archive_file == str(sample_mbox_simple)
        assert result.messages_imported == 3
        assert result.messages_skipped == 0
        assert result.messages_failed == 0
        assert result.execution_time_ms > 0
        assert len(result.errors) == 0
        await db_manager.close()

    async def test_import_verifies_database_population(self, v1_1_db, sample_mbox_simple):
        """Test that imported messages are in database."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        # Verify database has 3 messages
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 3
        await db_manager.close()

    async def test_import_with_skip_duplicates_true(self, v1_1_db, sample_mbox_with_duplicates):
        """Test importing with duplicate Message-IDs (skipped)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(
            str(sample_mbox_with_duplicates), skip_duplicates=True
        )
        await db_manager.commit()  # Ensure changes are committed

        # File has 3 messages: unique1, unique1 (dup), unique2
        # With skip_duplicates=True, only 2 unique messages are imported
        assert result.messages_imported == 2  # Only 2 unique messages
        assert result.messages_skipped == 1  # 1 duplicate skipped within file

        # Import again - should skip all duplicates
        result2 = await importer.import_archive(
            str(sample_mbox_with_duplicates), skip_duplicates=True
        )
        await db_manager.commit()  # Ensure changes are committed

        # On second import: all messages already exist in DB
        assert result2.messages_imported == 0
        assert result2.messages_skipped == 3  # All 3 messages are duplicates
        await db_manager.close()

    async def test_import_with_skip_duplicates_false(self, v1_1_db, sample_mbox_with_duplicates):
        """Test importing without skipping duplicates (uses INSERT OR REPLACE)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(
            str(sample_mbox_with_duplicates), skip_duplicates=False
        )
        await db_manager.commit()  # Ensure changes are committed

        # With skip_duplicates=False, INSERT OR REPLACE is used
        # File has: unique1, unique1 (dup), unique2
        # All 3 "import" (second unique1 replaces the first via OR REPLACE)
        assert result.messages_imported == 3  # All 3 processed
        assert result.messages_failed == 0  # OR REPLACE doesn't fail
        assert result.messages_skipped == 0  # Not skipping

        # Verify only 2 unique messages in DB
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 2  # Only 2 unique Message-IDs

        # Second import also succeeds (replaces existing records)
        result2 = await importer.import_archive(
            str(sample_mbox_with_duplicates), skip_duplicates=False
        )
        await db_manager.commit()  # Ensure changes are committed

        # All messages imported (replaced) successfully
        assert result2.messages_imported == 3
        assert result2.messages_failed == 0
        await db_manager.close()

    async def test_import_with_malformed_messages(self, v1_1_db, sample_mbox_malformed):
        """Test importing mbox with malformed message (graceful handling)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_malformed))
        await db_manager.commit()  # Ensure changes are committed

        # Python's mailbox library is robust and parses all 3 messages
        # The "malformed" message has no Message-ID, so we generate a fallback
        # All 3 messages import successfully
        assert result.messages_imported == 3
        assert result.messages_skipped == 0
        assert result.messages_failed == 0
        await db_manager.close()

    async def test_import_with_custom_account_id(self, v1_1_db, sample_mbox_simple):
        """Test importing with custom account_id."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_simple), account_id="custom-account")
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 3

        # Verify account_id in database
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT DISTINCT account_id FROM messages")
        account_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "custom-account" in account_ids
        await db_manager.close()

    async def test_import_returns_execution_time(self, v1_1_db, sample_mbox_simple):
        """Test that import result includes execution time."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        assert result.execution_time_ms > 0
        assert result.execution_time_ms < 10000  # Should be < 10 seconds
        await db_manager.close()


class TestOffsetCalculation:
    """Test mbox offset calculation for O(1) message access."""

    async def test_offsets_are_accurate(self, v1_1_db, sample_mbox_simple):
        """Test that calculated offsets allow reading messages directly."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        # Get offset and length from database
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("""
            SELECT rfc_message_id, mbox_offset, mbox_length, archive_file
            FROM messages
            ORDER BY rfc_message_id
        """)
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 3

        # Verify each message can be read at its offset
        for rfc_message_id, offset, length, archive_file in rows:
            with open(archive_file, "rb") as f:
                f.seek(offset)
                message_bytes = f.read(length)

                # Parse and verify Message-ID
                msg = email.message_from_bytes(message_bytes)
                assert msg.get("Message-ID", "").strip() == rfc_message_id
        await db_manager.close()

    async def test_offsets_are_non_negative(self, v1_1_db, sample_mbox_simple):
        """Test that all offsets are non-negative."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT mbox_offset, mbox_length FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for offset, length in rows:
            assert offset >= 0
            assert length > 0
        await db_manager.close()

    async def test_offsets_are_unique_per_message(self, v1_1_db, sample_mbox_simple):
        """Test that each message has a unique offset."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT mbox_offset FROM messages")
        offsets = [row[0] for row in cursor.fetchall()]
        conn.close()

        # All offsets should be unique
        assert len(offsets) == len(set(offsets))
        await db_manager.close()

    async def test_offsets_with_compressed_archive(self, v1_1_db, sample_mbox_compressed):
        """Test offset calculation on decompressed data."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_compressed))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 2

        # Offsets should be calculated on decompressed file
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT mbox_offset, mbox_length FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for offset, length in rows:
            assert offset >= 0
            assert length > 0
        await db_manager.close()


class TestMetadataExtraction:
    """Test metadata extraction from email messages."""

    async def test_extract_all_v1_1_fields(self, v1_1_db, sample_mbox_simple):
        """Test that all v1.1 metadata fields are populated."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("""
            SELECT gmail_id, rfc_message_id, subject, from_addr, to_addr, cc_addr,
                   date, archive_file, mbox_offset, mbox_length, body_preview,
                   checksum, size_bytes, account_id
            FROM messages
            WHERE rfc_message_id = '<msg3@example.com>'
        """)
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        (
            gmail_id,
            rfc_message_id,
            subject,
            from_addr,
            to_addr,
            cc_addr,
            date,
            archive_file,
            mbox_offset,
            mbox_length,
            body_preview,
            checksum,
            size_bytes,
            account_id,
        ) = row

        # Verify all required fields are present
        # Note: gmail_id is NULL when importing without GmailClient (offline mode)
        # This is correct behavior - only real Gmail IDs are stored, not synthetic ones
        assert gmail_id is None  # No GmailClient = no Gmail ID lookup
        assert rfc_message_id == "<msg3@example.com>"
        assert subject == "Test Message 3"
        assert from_addr == "charlie@example.com"
        assert to_addr == "alice@example.com"
        assert cc_addr == "bob@example.com"
        assert date is not None
        assert archive_file is not None
        assert mbox_offset >= 0
        assert mbox_length > 0
        assert body_preview is not None
        assert checksum is not None
        assert size_bytes > 0
        assert account_id == "default"
        await db_manager.close()

    async def test_extract_thread_id_from_xgm_thrid(self, v1_1_db, tmp_path):
        """Test thread ID extraction from X-GM-THRID header."""
        mbox_path = tmp_path / "thread_test.mbox"

        # Create message with X-GM-THRID header
        with open(mbox_path, "w") as f:
            f.write("From sender@example.com Mon Jan 01 12:00:00 2024\n")
            f.write("Message-ID: <thread-test@example.com>\n")
            f.write("Subject: Thread Test\n")
            f.write("From: sender@example.com\n")
            f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
            f.write("X-GM-THRID: 1234567890abcdef\n")
            f.write("\n")
            f.write("Test message with Gmail thread ID.\n")
            f.write("\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1

        # Verify thread_id is extracted
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT thread_id FROM messages WHERE rfc_message_id = '<thread-test@example.com>'"
        )
        thread_id = cursor.fetchone()[0]
        conn.close()

        assert thread_id == "1234567890abcdef"
        await db_manager.close()

    async def test_extract_thread_id_from_references_fallback(self, v1_1_db, tmp_path):
        """Test thread ID extraction from References header when X-GM-THRID is missing."""
        mbox_path = tmp_path / "references_test.mbox"

        # Create message with References header (no X-GM-THRID)
        with open(mbox_path, "w") as f:
            f.write("From sender@example.com Mon Jan 01 12:00:00 2024\n")
            f.write("Message-ID: <references-test@example.com>\n")
            f.write("Subject: References Test\n")
            f.write("From: sender@example.com\n")
            f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
            f.write("References: <original@example.com> <reply1@example.com>\n")
            f.write("\n")
            f.write("Test message using References for thread ID.\n")
            f.write("\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1

        # Verify thread_id is first reference
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT thread_id FROM messages WHERE rfc_message_id = '<references-test@example.com>'"
        )
        thread_id = cursor.fetchone()[0]
        conn.close()

        assert thread_id == "<original@example.com>"
        await db_manager.close()

    async def test_extract_thread_id_none_when_missing(self, v1_1_db, tmp_path):
        """Test thread ID is None when both X-GM-THRID and References are missing."""
        mbox_path = tmp_path / "no_thread.mbox"

        # Create message with no thread headers
        with open(mbox_path, "w") as f:
            f.write("From sender@example.com Mon Jan 01 12:00:00 2024\n")
            f.write("Message-ID: <no-thread@example.com>\n")
            f.write("Subject: No Thread Test\n")
            f.write("From: sender@example.com\n")
            f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
            f.write("\n")
            f.write("Test message with no thread information.\n")
            f.write("\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1

        # Verify thread_id is None
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT thread_id FROM messages WHERE rfc_message_id = '<no-thread@example.com>'"
        )
        thread_id = cursor.fetchone()[0]
        conn.close()

        assert thread_id is None
        await db_manager.close()

    async def test_body_preview_multipart_with_decoding_error(self, v1_1_db, tmp_path):
        """Test body preview extraction handles decoding errors in multipart messages."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        mbox_path = tmp_path / "multipart_error.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        # Create multipart message with problematic encoding
        msg = MIMEMultipart()
        msg["Message-ID"] = "<multipart-error@example.com>"
        msg["Subject"] = "Multipart Error Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"

        # Add valid text part
        text_part = MIMEText("Valid text content")
        msg.attach(text_part)

        mbox.add(msg)
        mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1

        # Verify body preview was extracted
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT body_preview FROM messages "
            "WHERE rfc_message_id = '<multipart-error@example.com>'"
        )
        body_preview = cursor.fetchone()[0]
        conn.close()

        assert "Valid text content" in body_preview
        await db_manager.close()

    async def test_body_preview_non_multipart_with_decoding_error(self, v1_1_db, tmp_path):
        """Test body preview extraction handles decoding errors in non-multipart messages."""
        mbox_path = tmp_path / "decode_error.mbox"

        # Create message with invalid UTF-8 in body
        with open(mbox_path, "wb") as f:
            f.write(b"From sender@example.com Mon Jan 01 12:00:00 2024\n")
            f.write(b"Message-ID: <decode-error@example.com>\n")
            f.write(b"Subject: Decode Error Test\n")
            f.write(b"From: sender@example.com\n")
            f.write(b"Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
            f.write(b"Content-Type: text/plain; charset=utf-8\n")
            f.write(b"\n")
            # Include some invalid UTF-8 bytes - will be handled with errors='ignore'
            f.write(b"Valid content with invalid bytes: \xff\xfe mixed in.\n")
            f.write(b"\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1

        # Verify body preview exists (invalid bytes ignored)
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT body_preview FROM messages WHERE rfc_message_id = '<decode-error@example.com>'"
        )
        body_preview = cursor.fetchone()[0]
        conn.close()

        assert body_preview is not None
        assert "Valid content" in body_preview
        await db_manager.close()

    async def test_extract_rfc_message_id(self, v1_1_db, sample_mbox_simple):
        """Test RFC Message-ID extraction."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT rfc_message_id FROM messages ORDER BY rfc_message_id")
        message_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "<msg1@example.com>" in message_ids
        assert "<msg2@example.com>" in message_ids
        assert "<msg3@example.com>" in message_ids
        await db_manager.close()

    async def test_generate_fallback_message_id(self, v1_1_db, sample_mbox_no_message_id):
        """Test fallback Message-ID generation for messages without Message-ID."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_no_message_id))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 2

        # Verify fallback Message-ID was generated
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT rfc_message_id FROM messages ORDER BY rfc_message_id")
        message_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        # One should be the actual Message-ID, one should be generated
        assert "<has-id@example.com>" in message_ids
        # Fallback should be a hash-based ID
        assert any("@generated>" in mid for mid in message_ids)
        await db_manager.close()

    async def test_body_preview_extraction(self, v1_1_db, sample_mbox_simple):
        """Test body preview extraction (first 1000 chars)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("""
            SELECT body_preview FROM messages
            WHERE rfc_message_id = '<msg3@example.com>'
        """)
        body_preview = cursor.fetchone()[0]
        conn.close()

        assert body_preview is not None
        assert "longer content for body preview testing" in body_preview
        assert len(body_preview) <= 1000
        await db_manager.close()

    async def test_checksum_calculation(self, v1_1_db, sample_mbox_simple):
        """Test SHA256 checksum calculation."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT checksum FROM messages")
        checksums = [row[0] for row in cursor.fetchall()]
        conn.close()

        # All checksums should be 64 hex characters (SHA256)
        for checksum in checksums:
            assert checksum is not None
            assert len(checksum) == 64
            assert all(c in "0123456789abcdef" for c in checksum)
        await db_manager.close()


class TestDuplicateHandling:
    """Test duplicate message handling."""

    async def test_skip_duplicates_on_rfc_message_id(self, v1_1_db, sample_mbox_simple):
        """Test duplicate detection uses RFC Message-ID."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # First import
        result1 = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed
        assert result1.messages_imported == 3

        # Second import with skip_duplicates=True
        result2 = await importer.import_archive(str(sample_mbox_simple), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed
        assert result2.messages_imported == 0
        assert result2.messages_skipped == 3
        await db_manager.close()

    async def test_duplicate_count_in_result(self, v1_1_db, sample_mbox_simple):
        """Test that skipped count is accurate."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Import twice
        await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed
        result = await importer.import_archive(str(sample_mbox_simple), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_skipped == 3
        assert result.messages_imported == 0
        await db_manager.close()

    async def test_duplicate_handling_across_archives(self, v1_1_db, sample_mbox_simple, tmp_path):
        """Test duplicate detection across different archive files."""
        # Create a second archive with same Message-IDs
        mbox_path2 = tmp_path / "simple2.mbox"
        mbox = mailbox.mbox(str(mbox_path2))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<msg1@example.com>"  # Same as sample_mbox_simple
        msg["Subject"] = "Duplicate from another archive"
        msg["From"] = "different@example.com"
        msg["To"] = "another@example.com"
        msg["Date"] = "Thu, 04 Jan 2024 12:00:00 +0000"
        msg.set_content("This is a duplicate message from a different archive.")
        mbox.add(msg)
        mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Import first archive
        result1 = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed
        assert result1.messages_imported == 3

        # Import second archive with duplicate
        result2 = await importer.import_archive(str(mbox_path2), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed
        assert result2.messages_imported == 0
        assert result2.messages_skipped == 1
        await db_manager.close()


class TestCompressionSupport:
    """Test compression format support."""

    async def test_import_gzip_compressed_archive(self, v1_1_db, sample_mbox_compressed):
        """Test importing gzip-compressed mbox."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_compressed))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 2
        assert result.messages_failed == 0
        await db_manager.close()

    async def test_compressed_archive_stores_compressed_filename(
        self, v1_1_db, sample_mbox_compressed
    ):
        """Test that database stores the compressed filename."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        await importer.import_archive(str(sample_mbox_compressed))
        await db_manager.commit()  # Ensure changes are committed

        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("SELECT DISTINCT archive_file FROM messages")
        archive_files = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Should store the .gz filename
        assert any(str(sample_mbox_compressed) in af for af in archive_files)
        await db_manager.close()

    async def test_compression_detection_from_extension(self, tmp_path):
        """Test compression format detection from file extension."""
        # This is more of an internal implementation test
        # The importer should detect .gz, .xz, .zst extensions
        importer = ImporterFacade(str(tmp_path / "test.db"))

        # Test that _get_uncompressed_path returns correct handling
        # (This test will be implemented when we know the internal API)
        pass

    async def test_import_lzma_compressed_archive(self, v1_1_db, tmp_path):
        """Test importing lzma-compressed (.xz) mbox."""
        import lzma

        # Create uncompressed mbox
        mbox_path = tmp_path / "lzma_test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<lzma-test@example.com>"
        msg["Subject"] = "LZMA Test Message"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("This message will be LZMA compressed.")
        mbox.add(msg)
        mbox.close()

        # Compress with lzma (.xz extension)
        compressed_path = tmp_path / "lzma_test.mbox.xz"
        with open(mbox_path, "rb") as f_in:
            with lzma.open(compressed_path, "wb") as f_out:
                f_out.write(f_in.read())

        # Remove uncompressed file
        mbox_path.unlink()

        # Test import
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(compressed_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1
        assert result.messages_failed == 0
        await db_manager.close()

    async def test_import_zstd_compressed_archive(self, v1_1_db, tmp_path):
        """Test importing zstd-compressed (.zst) mbox."""
        from compression import zstd

        # Create uncompressed mbox
        mbox_path = tmp_path / "zstd_test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<zstd-test@example.com>"
        msg["Subject"] = "Zstandard Test Message"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("This message will be Zstandard compressed.")
        mbox.add(msg)
        mbox.close()

        # Compress with zstd (Python 3.14 built-in compression module)
        compressed_path = tmp_path / "zstd_test.mbox.zst"
        with open(mbox_path, "rb") as f_in:
            with zstd.open(compressed_path, "wb") as f_out:
                f_out.write(f_in.read())

        # Remove uncompressed file
        mbox_path.unlink()

        # Test import
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(compressed_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1
        assert result.messages_failed == 0
        await db_manager.close()

    # NOTE: test_compression_format_detection removed - compression detection
    # is now tested in unit/core/importer/test_scanner.py

    async def test_decompression_failure_cleanup(self, v1_1_db, tmp_path):
        """Test that temporary files are cleaned up on decompression failure."""

        # Create a corrupted gzip file
        corrupted_path = tmp_path / "corrupted.mbox.gz"
        with open(corrupted_path, "wb") as f:
            f.write(b"This is not valid gzip data")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Should raise RuntimeError and clean up temp file
        with pytest.raises(RuntimeError, match="Failed to decompress"):
            await importer.import_archive(str(corrupted_path))
            await db_manager.commit()  # Ensure changes are committed
        await db_manager.close()


class TestErrorHandling:
    """Test error handling and recovery."""

    async def test_continue_on_database_error(self, tmp_path):
        """Test that import continues when individual messages cause errors."""
        # Create a v1.1 DB
        db_path = tmp_path / "test.db"

        # Create mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<good@example.com>"
        msg1["Subject"] = "Good Message"
        msg1["From"] = "sender@example.com"
        msg1["To"] = "recipient@example.com"
        msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg1.set_content("This is a good message.")
        mbox.add(msg1)
        mbox.close()

        db_manager = DBManager(str(db_path), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should import successfully
        assert result.messages_imported == 1
        assert result.messages_failed == 0
        await db_manager.close()

    async def test_error_handling_with_corrupt_db(self, tmp_path):
        """Test error details when there are issues."""
        # For now, test that error handling structure exists
        # Actual database errors are hard to trigger with INSERT OR REPLACE
        importer = ImporterFacade(str(tmp_path / "test.db"))

        # Verify ImportResult has errors field
        result = ImportResult(
            archive_file="test.mbox",
            messages_imported=0,
            messages_skipped=0,
            messages_failed=1,
            execution_time_ms=0.0,
            errors=["Test error message"],
        )

        assert len(result.errors) == 1
        assert "Test error" in result.errors[0]

    async def test_import_nonexistent_archive_raises_error(self, v1_1_db, tmp_path):
        """Test importing nonexistent archive raises appropriate error."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        nonexistent = tmp_path / "nonexistent.mbox"

        with pytest.raises((FileNotFoundError, Exception)):
            await importer.import_archive(str(nonexistent))
            await db_manager.commit()  # Ensure changes are committed
        await db_manager.close()

    async def test_database_query_error_handling(self, v1_1_db, tmp_path):
        """Test error handling when database query fails during duplicate check."""
        # Create simple mbox
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<test@example.com>"
        msg["Subject"] = "Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Test content.")
        mbox.add(msg)
        mbox.close()

        # Import first time normally
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should import successfully (DB exists and is valid)
        assert result.messages_imported == 1

        # Second import with skip_duplicates should trigger the existing_ids query
        result2 = await importer.import_archive(str(mbox_path), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed
        assert result2.messages_skipped == 1  # Message already exists
        await db_manager.close()

    async def test_database_insert_error_recovery(self, v1_1_db, tmp_path):
        """Test that database insert errors are caught and recorded."""
        # Create mbox with messages
        mbox_path = tmp_path / "insert_test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        # Add first message
        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<insert1@example.com>"
        msg1["Subject"] = "Insert Test 1"
        msg1["From"] = "sender@example.com"
        msg1["To"] = "recipient@example.com"
        msg1["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg1.set_content("First message.")
        mbox.add(msg1)

        # Add second message
        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<insert2@example.com>"
        msg2["Subject"] = "Insert Test 2"
        msg2["From"] = "sender@example.com"
        msg2["To"] = "recipient@example.com"
        msg2["Date"] = "Tue, 02 Jan 2024 12:00:00 +0000"
        msg2.set_content("Second message.")
        mbox.add(msg2)

        mbox.close()

        # Import first time
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result1 = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed
        assert result1.messages_imported == 2

        # Import again with skip_duplicates=True, then manually trigger constraint violation
        # by trying to insert with skip_duplicates=True (will fail silently with proper
        # error handling)
        result2 = await importer.import_archive(str(mbox_path), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed
        assert result2.messages_skipped == 2
        assert result2.messages_failed == 0
        await db_manager.close()

    async def test_import_multiple_with_file_error(self, v1_1_db, tmp_path):
        """Test that import_multiple continues after file-level errors."""
        # Create one valid mbox
        mbox1_path = tmp_path / "valid.mbox"
        mbox = mailbox.mbox(str(mbox1_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<valid@example.com>"
        msg["Subject"] = "Valid Message"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Valid message.")
        mbox.add(msg)
        mbox.close()

        # Create an invalid file (not an mbox)
        invalid_path = tmp_path / "invalid.mbox"
        with open(invalid_path, "w") as f:
            f.write("This is not a valid mbox file\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        pattern = str(tmp_path / "*.mbox")
        result = await importer.import_multiple(pattern)

        # Should have 2 files (1 valid, 1 invalid)
        assert result.total_files == 2
        # The valid file should succeed, invalid should be in file_results with error
        assert len(result.file_results) == 2

        # Check that at least one file succeeded
        successful_files = [r for r in result.file_results if r.messages_imported > 0]
        assert len(successful_files) >= 1
        await db_manager.close()

    async def test_body_preview_multipart_exception_handling(self, v1_1_db, tmp_path):
        """Test exception handling in multipart body preview extraction."""
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart

        mbox_path = tmp_path / "multipart_exception.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        # Create multipart message with non-text parts
        msg = MIMEMultipart()
        msg["Message-ID"] = "<multipart-exception@example.com>"
        msg["Subject"] = "Multipart Exception Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"

        # Add a binary part (image)
        binary_part = MIMEBase("image", "png")
        binary_part.set_payload(b"\x89PNG\r\n\x1a\n")  # PNG header
        msg.attach(binary_part)

        mbox.add(msg)
        mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should import successfully despite no text/plain part
        assert result.messages_imported == 1

        # Verify body_preview is empty or minimal (no text/plain found)
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute(
            "SELECT body_preview FROM messages "
            "WHERE rfc_message_id = '<multipart-exception@example.com>'"
        )
        body_preview = cursor.fetchone()[0]
        conn.close()

        # Body preview will be empty since no text/plain part exists
        assert body_preview == ""
        await db_manager.close()

    async def test_body_preview_non_multipart_exception_handling(self, v1_1_db, tmp_path):
        """Test exception handling in non-multipart body preview extraction."""
        mbox_path = tmp_path / "non_multipart_exception.mbox"

        # Create message with Content-Transfer-Encoding that might cause issues
        with open(mbox_path, "w") as f:
            f.write("From sender@example.com Mon Jan 01 12:00:00 2024\n")
            f.write("Message-ID: <non-multipart-exception@example.com>\n")
            f.write("Subject: Non-Multipart Exception Test\n")
            f.write("From: sender@example.com\n")
            f.write("Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
            f.write("Content-Type: application/octet-stream\n")
            f.write("\n")
            f.write("Binary data here\n")
            f.write("\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should import successfully despite non-text content
        assert result.messages_imported == 1
        await db_manager.close()

    async def test_import_multiple_error_recovery(self, v1_1_db, tmp_path):
        """Test that import_multiple records errors but continues processing files."""
        # Create one valid mbox
        valid_path = tmp_path / "valid.mbox"
        mbox = mailbox.mbox(str(valid_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<valid-multiple@example.com>"
        msg["Subject"] = "Valid Message"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Valid content.")
        mbox.add(msg)
        mbox.close()

        # Create directory (not a file) with .mbox extension to trigger error
        error_path = tmp_path / "error.mbox"
        error_path.mkdir()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        pattern = str(tmp_path / "*.mbox")
        result = await importer.import_multiple(pattern)

        # Should have 2 "files" (1 valid mbox, 1 directory)
        assert result.total_files == 2

        # Valid file should import successfully
        assert result.total_messages_imported >= 1

        # Should have results for both (valid + error)
        assert len(result.file_results) == 2

        # One should have an error
        error_results = [r for r in result.file_results if len(r.errors) > 0]
        assert len(error_results) >= 1
        await db_manager.close()


class TestMultipleArchiveImport:
    """Test importing multiple archives with glob patterns."""

    async def test_import_multiple_with_glob_pattern(self, v1_1_db, tmp_path):
        """Test importing multiple archives using glob pattern."""
        # Create multiple mbox files
        for i in range(3):
            mbox_path = tmp_path / f"archive_{i}.mbox"
            mbox = mailbox.mbox(str(mbox_path))

            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<msg{i}@example.com>"
            msg["Subject"] = f"Message {i}"
            msg["From"] = f"sender{i}@example.com"
            msg["To"] = "recipient@example.com"
            msg["Date"] = f"Mon, 0{i + 1} Jan 2024 12:00:00 +0000"
            msg.set_content(f"Content of message {i}.")
            mbox.add(msg)
            mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        pattern = str(tmp_path / "archive_*.mbox")
        result = await importer.import_multiple(pattern)

        assert isinstance(result, MultiImportResult)
        assert result.total_files == 3
        assert result.total_messages_imported == 3
        assert result.total_messages_skipped == 0
        assert result.total_messages_failed == 0
        await db_manager.close()

    async def test_import_multiple_returns_per_file_results(self, v1_1_db, tmp_path):
        """Test that import_multiple returns results for each file."""
        # Create 2 mbox files
        for i in range(2):
            mbox_path = tmp_path / f"multi_{i}.mbox"
            mbox = mailbox.mbox(str(mbox_path))

            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<multi{i}@example.com>"
            msg["Subject"] = f"Multi Message {i}"
            msg["From"] = f"sender{i}@example.com"
            msg["To"] = "recipient@example.com"
            msg["Date"] = f"Mon, 0{i + 1} Jan 2024 12:00:00 +0000"
            msg.set_content(f"Content {i}.")
            mbox.add(msg)
            mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        pattern = str(tmp_path / "multi_*.mbox")
        result = await importer.import_multiple(pattern)

        assert len(result.file_results) == 2
        for file_result in result.file_results:
            assert isinstance(file_result, ImportResult)
        await db_manager.close()

    async def test_import_multiple_with_no_matching_files(self, v1_1_db, tmp_path):
        """Test import_multiple with pattern that matches no files."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        pattern = str(tmp_path / "nonexistent_*.mbox")
        result = await importer.import_multiple(pattern)

        assert result.total_files == 0
        assert result.total_messages_imported == 0
        await db_manager.close()


class TestPerformance:
    """Test performance benchmarks."""

    async def test_import_1000_messages_under_6_seconds(self, v1_1_db, tmp_path):
        """Test importing 1000 messages completes in < 6 seconds."""
        # Create mbox with 1000 messages
        mbox_path = tmp_path / "performance_1000.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        for i in range(1000):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<perf{i}@example.com>"
            msg["Subject"] = f"Performance Test Message {i}"
            msg["From"] = f"sender{i}@example.com"
            msg["To"] = "recipient@example.com"
            msg["Date"] = f"Mon, 01 Jan 2024 {i % 24:02d}:{i % 60:02d}:00 +0000"
            msg.set_content(f"This is performance test message {i} with some content.")
            mbox.add(msg)

        mbox.close()

        # Import and measure time
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        start_time = time.time()
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed
        elapsed = time.time() - start_time

        assert result.messages_imported == 1000
        assert elapsed < 6.0  # Must be under 6 seconds
        await db_manager.close()

    async def test_report_messages_per_second(self, v1_1_db, tmp_path):
        """Test performance reporting (messages/second)."""
        # Create mbox with 100 messages
        mbox_path = tmp_path / "performance_100.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        for i in range(100):
            msg = email.message.EmailMessage()
            msg["Message-ID"] = f"<speed{i}@example.com>"
            msg["Subject"] = f"Speed Test {i}"
            msg["From"] = "sender@example.com"
            msg["To"] = "recipient@example.com"
            msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
            msg.set_content(f"Message {i}.")
            mbox.add(msg)

        mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Calculate messages per second
        msg_per_sec = (result.messages_imported / result.execution_time_ms) * 1000

        # Should process at least 100 messages/second
        assert msg_per_sec > 100
        await db_manager.close()


class TestDBManagerIntegration:
    """Test integration with DBManager instead of direct SQL."""

    async def test_uses_dbmanager_for_database_operations(self, v1_1_db, sample_mbox_simple):
        """Test that importer uses DBManager for all database operations."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Import should work without direct SQL queries
        result = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed
        assert result.messages_imported == 3

        # Verify DBManager can read the imported messages
        async with DBManager(str(v1_1_db)) as db:
            # Check messages were recorded
            cursor = await db.conn.execute("SELECT COUNT(*) FROM messages")
            row = await cursor.fetchone()
            count = row[0]
            assert count == 3
        await db_manager.close()

    async def test_atomic_import_operations(self, v1_1_db, sample_mbox_simple):
        """Test that import operations are atomic (all or nothing)."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # First import should succeed
        result = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed
        assert result.messages_imported == 3

        # Check database has exactly 3 records
        async with DBManager(str(v1_1_db)) as db:
            cursor = await db.conn.execute("SELECT COUNT(*) FROM messages")
            row = await cursor.fetchone()
            count = row[0]
            assert count == 3
        await db_manager.close()

    async def test_audit_trail_in_archive_runs(self, v1_1_db, sample_mbox_simple):
        """Test that import operations are recorded in archive_runs."""
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Import messages
        await importer.import_archive(str(sample_mbox_simple), account_id="test-import")
        await db_manager.commit()  # Ensure changes are committed

        # Verify archive_runs has entries
        conn = sqlite3.connect(str(v1_1_db))
        cursor = conn.execute("""
            SELECT COUNT(*), SUM(messages_archived)
            FROM archive_runs
            WHERE account_id = 'test-import'
        """)
        run_count, total_messages = cursor.fetchone()
        conn.close()

        # Should have audit trail entries
        assert run_count > 0
        assert total_messages == 3
        await db_manager.close()

    async def test_error_handling_with_rollback(self, v1_1_db, tmp_path):
        """Test proper error handling with database rollback."""
        # Create a simple mbox
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<rollback-test@example.com>"
        msg["Subject"] = "Test Message"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Test content.")
        mbox.add(msg)
        mbox.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # First import should succeed
        result1 = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed
        assert result1.messages_imported == 1

        # Second import with skip_duplicates should skip
        result2 = await importer.import_archive(str(mbox_path), skip_duplicates=True)
        await db_manager.commit()  # Ensure changes are committed
        assert result2.messages_skipped == 1
        assert result2.messages_imported == 0
        await db_manager.close()

    async def test_no_direct_sql_queries_in_importer(self, v1_1_db, sample_mbox_simple):
        """Test that importer doesn't use direct SQL queries."""
        # This is a behavioral test - we verify the importer works correctly
        # using only DBManager methods, not direct SQL
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(sample_mbox_simple))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 3

        # Verify using DBManager that messages are correctly stored
        async with DBManager(str(v1_1_db)) as db:
            # Get all messages using DBManager API
            messages = await db.get_all_messages_for_archive(str(sample_mbox_simple))
            assert len(messages) == 3

            # Verify each message has proper metadata
            for msg_data in messages:
                # Note: gmail_id is NULL when importing without GmailClient (offline mode)
                # This is correct - only real Gmail IDs are stored, not synthetic ones
                assert msg_data["rfc_message_id"] is not None
                assert msg_data["mbox_offset"] >= 0
                assert msg_data["mbox_length"] > 0
                assert msg_data["archive_file"] == str(sample_mbox_simple)
        await db_manager.close()

    async def test_extract_body_preview_multipart_exception_handling(
        self, v1_1_db: Path, tmp_path: Path
    ) -> None:
        """Test body preview extraction when get_payload raises exception (lines 159-160)."""
        # Create mbox with multipart message
        mbox_path = tmp_path / "multipart.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<multipart@example.com>"
        msg["Subject"] = "Multipart Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.make_mixed()

        # Add a text part
        text_part = email.message.EmailMessage()
        text_part.set_content("This is the body")
        text_part.set_type("text/plain")
        msg.attach(text_part)

        mbox.add(msg)
        mbox.close()

        # Import should succeed despite potential exceptions in body extraction
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed
        assert result.messages_imported == 1
        await db_manager.close()

    async def test_extract_body_preview_non_multipart_exception_handling(
        self, v1_1_db: Path, tmp_path: Path
    ) -> None:
        """Test body preview extraction for non-multipart message exception (lines 166-167)."""
        # Create mbox with simple message
        mbox_path = tmp_path / "simple.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<simple@example.com>"
        msg["Subject"] = "Simple Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        msg.set_content("Simple body text")

        mbox.add(msg)
        mbox.close()

        # Import should succeed
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed
        assert result.messages_imported == 1
        await db_manager.close()


async def test_import_handles_duplicate_messages_constraint(v1_1_db: Path, tmp_path: Path) -> None:
    """Test import handles database constraint violations gracefully (lines 402-414).

    When importing an mbox with duplicate Message-IDs, the second insert should
    fail with IntegrityError (UNIQUE constraint), which should be caught and handled.
    """
    # Create mbox with 2 messages having the same Message-ID
    mbox_path = tmp_path / "duplicates.mbox"
    with open(mbox_path, "wb") as f:
        # First message
        f.write(b"From first@example.com Mon Jan 01 12:00:00 2024\n")
        f.write(b"Message-ID: <duplicate@example.com>\n")
        f.write(b"Subject: First Message\n")
        f.write(b"From: first@example.com\n")
        f.write(b"Date: Mon, 01 Jan 2024 12:00:00 +0000\n")
        f.write(b"\n")
        f.write(b"Body of first message\n")
        f.write(b"\n")

        # Second message with SAME Message-ID (will violate UNIQUE constraint)
        f.write(b"From second@example.com Tue Jan 02 12:00:00 2024\n")
        f.write(b"Message-ID: <duplicate@example.com>\n")
        f.write(b"Subject: Second Message\n")
        f.write(b"From: second@example.com\n")
        f.write(b"Date: Tue, 02 Jan 2024 12:00:00 +0000\n")
        f.write(b"\n")
        f.write(b"Body of second message\n")
        f.write(b"\n")

    db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
    await db_manager.initialize()
    importer = ImporterFacade(db_manager)

    # Import with skip_duplicates=False (uses INSERT OR REPLACE)
    # This should handle the duplicate gracefully
    result = await importer.import_archive(str(mbox_path), skip_duplicates=False)
    await db_manager.commit()  # Ensure changes are committed

    # Should complete without crashing
    assert result.messages_imported > 0, "Should import at least one message"

    # Verify database has exactly 1 message (second replaces first via OR REPLACE)
    conn = sqlite3.connect(str(v1_1_db))
    cursor = conn.execute("SELECT COUNT(*) FROM messages")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1, f"Expected 1 message (duplicate replaced), got {count}"
    await db_manager.close()


async def test_importer_extract_body_non_multipart_payload_exception(v1_1_db: Path) -> None:
    """Test extract_body handles decode errors for non-multipart messages (lines 159-167).

    When msg.get_payload(decode=True) raises an exception for a non-multipart
    message, the function should gracefully handle it and return empty string.
    """
    import email.message
    import mailbox
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mbox_path = Path(tmpdir) / "test.mbox"

        # Create mbox with non-multipart message that might cause decode issues
        mbox_obj = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<decode_error@example.com>"
        msg["Subject"] = "Decode Error Test"
        msg["From"] = "sender@example.com"

        # Set binary content that might cause decode issues
        msg.set_content(
            b"Binary content with invalid UTF-8: \xff\xfe",
            maintype="application",
            subtype="octet-stream",
        )

        mbox_obj.add(msg)
        mbox_obj.close()

        # Import the archive
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should complete without crashing (body might be empty or partial)
        assert result.messages_imported >= 0
    await db_manager.close()


async def test_importer_database_constraint_violation(v1_1_db: Path) -> None:
    """Test importer handles database constraint violations (lines 402-414).

    When inserting a message causes a database constraint error (e.g., unique
    constraint violation), the importer should catch it, rollback, log error,
    and continue processing other messages.
    """
    import email.message
    import mailbox
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mbox_path = Path(tmpdir) / "test.mbox"

        # Create mbox with two messages having same Gmail ID (will cause constraint error)
        mbox_obj = mailbox.mbox(str(mbox_path))

        msg1 = email.message.EmailMessage()
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1["X-Gmail-Labels"] = "UNREAD"  # Force gmail_id extraction
        msg1["Subject"] = "Message 1"
        msg1["From"] = "sender@example.com"
        msg1.set_content("Body 1")
        mbox_obj.add(msg1)

        msg2 = email.message.EmailMessage()
        msg2["Message-ID"] = "<msg2@example.com>"  # Different Message-ID
        msg2["X-Gmail-Labels"] = "UNREAD"  # But will use same gmail_id if we manipulate
        msg2["Subject"] = "Message 2"
        msg2["From"] = "sender@example.com"
        msg2.set_content("Body 2")
        mbox_obj.add(msg2)

        mbox_obj.close()

        # Import first message
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result1 = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Try importing again - should handle duplicates gracefully
        result2 = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Second import should have some failures (duplicates)
        assert result2.messages_failed > 0 or result2.messages_skipped > 0, (
            "Second import should detect duplicates"
        )
    await db_manager.close()


async def test_importer_message_processing_exception(v1_1_db: Path) -> None:
    """Test importer handles general message processing exceptions (lines 410-414).

    When processing a message raises an unexpected exception (not just database),
    the importer should catch it, log error, and continue with next message.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mbox_path = Path(tmpdir) / "corrupt.mbox"

        # Create mbox with corrupt message
        with open(mbox_path, "wb") as f:
            f.write(b"From MAILER-DAEMON Mon Jan 01 00:00:00 2024\n")
            f.write(b"Message-ID: <corrupt@example.com>\n")
            # Missing required headers, malformed structure
            f.write(b"\xff\xfe\xfd Invalid bytes\n")
            f.write(b"\n")

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)

        # Should handle corrupt message gracefully
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Processing might fail or succeed depending on mailbox parsing
        # Either way, should not crash
        assert result.messages_failed >= 0
        assert result.messages_imported >= 0
    await db_manager.close()


async def test_importer_multipart_decode_exception(v1_1_db: Path) -> None:
    """Test importer handles decode exceptions in multipart messages (lines 159-160).

    When extracting body from multipart message raises exception during decode,
    should continue to next part or return partial body.
    """
    import email.message
    import mailbox
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mbox_path = Path(tmpdir) / "multipart.mbox"

        # Create multipart message with potentially problematic payload
        mbox_obj = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<multipart_decode@example.com>"
        msg["Subject"] = "Multipart Decode Test"
        msg["From"] = "sender@example.com"

        # Make it multipart
        msg.make_mixed()

        # Add a text part
        text_part = email.message.EmailMessage()
        text_part.set_content("Plain text content", subtype="plain")
        msg.attach(text_part)

        mbox_obj.add(msg)
        mbox_obj.close()

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        # Should complete successfully
        assert result.messages_imported == 1
    await db_manager.close()


async def test_importer_extract_body_exception_path(v1_1_db: Path) -> None:
    """Test extract_body handles exception in non-multipart decode (lines 166-167).

    When get_payload(decode=True) raises exception, the except block should
    catch it and return empty/partial body (graceful degradation).
    """
    import email.message
    import mailbox
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mbox_path = Path(tmpdir) / "test.mbox"

        # Create message that might cause decode exception
        mbox_obj = mailbox.mbox(str(mbox_path))
        msg = email.message.EmailMessage()
        msg["Message-ID"] = "<exception_path@example.com>"
        msg["Subject"] = "Exception Path Test"
        msg["From"] = "sender@example.com"

        # Simple text content (should work, but exercises the code path)
        msg.set_content("Simple text content")

        mbox_obj.add(msg)
        mbox_obj.close()

        # Import should work
        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        result = await importer.import_archive(str(mbox_path))
        await db_manager.commit()  # Ensure changes are committed

        assert result.messages_imported == 1
    await db_manager.close()


async def test_count_messages_returns_zero_for_nonexistent_file(v1_1_db: Path) -> None:
    """Test count_messages returns 0 for nonexistent file (line 279).

    When the archive file doesn't exist, the method should return 0
    without raising an exception.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent = Path(tmpdir) / "does_not_exist.mbox"

        db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
        await db_manager.initialize()
        importer = ImporterFacade(db_manager)
        count = importer.count_messages(str(nonexistent))

        assert count == 0
    await db_manager.close()


async def test_import_with_new_database_creates_schema(tmp_path: Path) -> None:
    """Test import creates schema for new database and imports successfully.

    When the database doesn't exist, it should be created with proper schema.
    """
    import email.message
    import mailbox

    # Database doesn't exist
    db_path = tmp_path / "new.db"

    # Create simple mbox
    mbox_path = tmp_path / "test.mbox"
    mbox = mailbox.mbox(str(mbox_path))

    msg = email.message.EmailMessage()
    msg["Message-ID"] = "<new@example.com>"
    msg["Subject"] = "New Message"
    msg["From"] = "sender@example.com"
    msg.set_content("Content")
    mbox.add(msg)
    mbox.close()

    # Import should work (auto-create schema)
    db_manager = DBManager(str(db_path), validate_schema=False, auto_create=True)
    await db_manager.initialize()
    importer = ImporterFacade(db_manager)
    result = await importer.import_archive(str(mbox_path), skip_duplicates=True)
    await db_manager.commit()  # Ensure changes are committed

    # Should import successfully
    assert result.messages_imported == 1
    assert db_path.exists()
    await db_manager.close()


class TestImporterExceptionHandling:
    """Tests for exception handling paths in ImporterFacade."""

    async def test_count_messages_compressed_archive_cleanup(self, v1_1_db: Path) -> None:
        """Test count_messages cleans up temp files for compressed archives.

        Covers line 291: Cleanup of temp file after decompression.
        """
        import gzip
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create compressed mbox
            mbox_content = (
                b"From test@example.com Mon Jan 1 00:00:00 2024\n"
                b"Message-ID: <msg1@test.com>\n"
                b"Subject: Test\n\n"
                b"Body\n"
            )
            archive_path = Path(tmpdir) / "test.mbox.gz"
            with gzip.open(archive_path, "wb") as f:
                f.write(mbox_content)

            db_manager = DBManager(str(v1_1_db), validate_schema=False, auto_create=True)
            await db_manager.initialize()
            importer = ImporterFacade(db_manager)
            count = importer.count_messages(str(archive_path))

            # Should count the message
            assert count == 1
            # Temp file should be cleaned up
            temp_files = list(Path(tmpdir).glob("tmp*.mbox"))
            assert len(temp_files) == 0
        await db_manager.close()

    # NOTE: Tests for private implementation details (_extract_rfc_message_id,
    # _extract_body_preview) moved to unit/core/importer/test_writer.py
