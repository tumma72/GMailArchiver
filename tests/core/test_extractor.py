"""Tests for MessageExtractor class."""

import lzma
from pathlib import Path

import pytest

from gmailarchiver.core.extractor import ExtractorError, MessageExtractor
from gmailarchiver.data.db_manager import DBManager

pytestmark = pytest.mark.asyncio

# Note: Shared fixtures (temp_dir, temp_db, sample_message, uncompressed_mbox,
# compressed_mbox_gzip, compressed_mbox_lzma, populated_db, etc.) are provided
# by tests/conftest.py with proper resource cleanup.


# ============================================================================
# Tests: Initialization
# ============================================================================


async def test_init_with_existing_db(temp_db: Path) -> None:
    """Test initialization with existing database."""
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    extractor = MessageExtractor(db_manager)
    assert extractor.db_manager == db_manager
    await extractor.close()


async def test_init_with_missing_db(temp_dir: Path) -> None:
    """Test initialization with missing database."""
    missing_db = temp_dir / "nonexistent.db"
    # DBManager will raise FileNotFoundError when initialized with missing db
    with pytest.raises(FileNotFoundError):
        db_manager = DBManager(str(missing_db), auto_create=False)
        await db_manager.initialize()
        MessageExtractor(db_manager)


async def test_context_manager(temp_db: Path) -> None:
    """Test async context manager protocol."""
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        assert extractor.db_manager == db_manager
    # Database should be closed after context


# ============================================================================
# Tests: Extract by Gmail ID
# ============================================================================


async def test_extract_by_gmail_id_success(
    populated_db: Path, uncompressed_mbox: Path, sample_message: bytes
) -> None:
    """Test extracting message by Gmail ID."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_gmail_id("msg001", output_path=None)
        # Use the actual sample message length from the fixture (216 bytes)
        assert len(message_bytes) == 216
        assert b"From: alice@example.com" in message_bytes


async def test_extract_by_gmail_id_to_file(
    populated_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test extracting message to file."""
    output_file = temp_dir / "extracted.eml"

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        await extractor.extract_by_gmail_id("msg001", output_path=output_file)

    assert output_file.exists()
    # File content should match the sample message size
    assert output_file.stat().st_size == 216


async def test_extract_by_gmail_id_not_found(populated_db: Path, uncompressed_mbox: Path) -> None:
    """Test extracting non-existent message by Gmail ID."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        with pytest.raises(ExtractorError, match="Message not found"):
            await extractor.extract_by_gmail_id("nonexistent")


async def test_extract_by_gmail_id_missing_archive(populated_db: Path) -> None:
    """Test extracting when archive file is missing.

    We simulate a missing archive by deleting the underlying mbox file that the
    database record references.
    """
    # Determine the archive file path from the database and remove it
    db = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db.initialize()
    try:
        # v1.2: Use get_message_location_by_gmail_id for gmail_id lookup
        result = await db.get_message_location_by_gmail_id("msg001")
        archive_file, _offset, _length = result  # type: ignore[misc]
    finally:
        await db.close()

    archive_path = Path(archive_file)
    if archive_path.exists():
        archive_path.unlink()

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        with pytest.raises(ExtractorError, match="Archive file not found"):
            await extractor.extract_by_gmail_id("msg001")


# ============================================================================
# Tests: Extract by RFC Message-ID
# ============================================================================


async def test_extract_by_rfc_message_id_success(
    populated_db: Path, uncompressed_mbox: Path
) -> None:
    """Test extracting message by RFC Message-ID."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_rfc_message_id(
            "<test001@example.com>", output_path=None
        )
        assert len(message_bytes) == 216


async def test_extract_by_rfc_message_id_not_found(
    populated_db: Path, uncompressed_mbox: Path
) -> None:
    """Test extracting non-existent message by RFC Message-ID."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        with pytest.raises(ExtractorError, match="Message not found"):
            await extractor.extract_by_rfc_message_id("<nonexistent@example.com>")


# ============================================================================
# Tests: Compressed Archives
# ============================================================================


async def test_extract_from_gzip(populated_db: Path, compressed_mbox_gzip: Path) -> None:
    """Test extracting from gzip-compressed archive."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_gmail_id("msg003", output_path=None)
        # gzip-compressed archive stores the same logical message content but with
        # a different envelope From line, so the total length is 220 bytes.
        assert len(message_bytes) == 220
        assert b"From: charlie@example.com" in message_bytes


async def test_extract_from_lzma(populated_db: Path, temp_dir: Path, sample_message: bytes) -> None:
    """Test extracting from lzma-compressed archive."""
    # Create lzma archive and add to database
    mbox_path = temp_dir / "archive.mbox.xz"
    msg = sample_message.replace(b"test001", b"test004")

    with lzma.open(mbox_path, "wb") as f:
        f.write(msg)

    # Add message to database using context manager (auto-commits on exit)
    async with DBManager(str(populated_db), auto_create=False, validate_schema=False) as db:
        await db.record_archived_message(
            gmail_id="msg004",
            rfc_message_id="<test004@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=0,
            mbox_length=len(msg),
            record_run=False,
        )

    # Extract
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_gmail_id("msg004", output_path=None)
        assert len(message_bytes) == len(msg)


async def test_compression_format_detection(populated_db: Path) -> None:
    """Test compression format detection."""
    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        assert extractor._get_compression_format(Path("test.mbox.gz")) == "gzip"
        assert extractor._get_compression_format(Path("test.mbox.xz")) == "lzma"
        assert extractor._get_compression_format(Path("test.mbox.lzma")) == "lzma"
        assert extractor._get_compression_format(Path("test.mbox.zst")) == "zstd"
        assert extractor._get_compression_format(Path("test.mbox")) is None


# ============================================================================
# Tests: Batch Extraction
# ============================================================================


async def test_batch_extract_success(
    populated_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction of multiple messages."""
    output_dir = temp_dir / "extracted"

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        stats = await extractor.batch_extract(["msg001", "msg002"], output_dir)

    assert stats["extracted"] == 2
    assert stats["failed"] == 0
    assert len(stats["errors"]) == 0

    # Check files were created
    assert (output_dir / "msg001.eml").exists()
    assert (output_dir / "msg002.eml").exists()


async def test_batch_extract_partial_failure(
    populated_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction with some failures."""
    output_dir = temp_dir / "extracted"

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        stats = await extractor.batch_extract(["msg001", "nonexistent", "msg002"], output_dir)

    assert stats["extracted"] == 2
    assert stats["failed"] == 1
    assert len(stats["errors"]) == 1
    assert "nonexistent" in stats["errors"][0]


async def test_batch_extract_creates_directory(
    populated_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction creates output directory if it doesn't exist."""
    output_dir = temp_dir / "new" / "nested" / "dir"

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        stats = await extractor.batch_extract(["msg001"], output_dir)

    assert output_dir.exists()
    assert stats["extracted"] == 1


# ============================================================================
# Tests: Error Handling
# ============================================================================


async def test_extract_with_invalid_offset(temp_db: Path, temp_dir: Path) -> None:
    """Test extraction with invalid offset (beyond file size)."""
    # Create small mbox file
    mbox_path = temp_dir / "small.mbox"
    with open(mbox_path, "wb") as f:
        f.write(b"Small content")

    # Add message with offset beyond file size using context manager (auto-commits)
    async with DBManager(str(temp_db), auto_create=False, validate_schema=False) as db:
        await db.record_archived_message(
            gmail_id="msg_invalid",
            rfc_message_id="<invalid@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=10000,  # Way beyond file size
            mbox_length=100,
            record_run=False,
        )

    # Try to extract - should fail or return partial data
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        # This may not raise an error but will return less data than expected
        message_bytes = await extractor.extract_by_gmail_id("msg_invalid", output_path=None)
        assert len(message_bytes) < 100  # Won't get full 100 bytes


async def test_extract_from_corrupted_gzip(temp_db: Path, temp_dir: Path) -> None:
    """Test extraction from corrupted gzip file."""
    # Create corrupted gzip file
    corrupted_path = temp_dir / "corrupted.mbox.gz"
    with open(corrupted_path, "wb") as f:
        f.write(b"This is not a valid gzip file")

    # Add to database using context manager (auto-commits)
    async with DBManager(str(temp_db), auto_create=False, validate_schema=False) as db:
        await db.record_archived_message(
            gmail_id="msg_corrupted",
            rfc_message_id="<corrupted@example.com>",
            archive_file=str(corrupted_path),
            mbox_offset=0,
            mbox_length=100,
            record_run=False,
        )

    # Try to extract - should raise ExtractorError
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        with pytest.raises(ExtractorError, match="Failed to extract"):
            await extractor.extract_by_gmail_id("msg_corrupted")


# ============================================================================
# Tests: Edge Cases
# ============================================================================


async def test_extract_empty_message(temp_db: Path, temp_dir: Path) -> None:
    """Test extracting message with zero length."""
    # Create mbox with content
    mbox_path = temp_dir / "archive.mbox"
    with open(mbox_path, "wb") as f:
        f.write(b"Some content here")

    # Add message with zero length using context manager (auto-commits)
    async with DBManager(str(temp_db), auto_create=False, validate_schema=False) as db:
        await db.record_archived_message(
            gmail_id="msg_empty",
            rfc_message_id="<empty@example.com>",
            archive_file=str(mbox_path),
            mbox_offset=0,
            mbox_length=0,
            record_run=False,
        )

    # Extract
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_gmail_id("msg_empty", output_path=None)
        assert len(message_bytes) == 0


async def test_extract_with_special_characters_in_path(populated_db: Path, temp_dir: Path) -> None:
    """Test extraction when output path has special characters.

    We reuse the populated_db fixture so that msg001 already exists in the
    database, and simply verify that writing to a path with spaces and
    special characters succeeds.
    """
    output_file = temp_dir / "test file [with] (special) chars.eml"

    db_manager = DBManager(str(populated_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        await extractor.extract_by_gmail_id("msg001", output_path=output_file)

    assert output_file.exists()


async def test_extract_from_zstd_compressed_archive(temp_db: Path, temp_dir: Path) -> None:
    """Test extracting message from zstd-compressed archive.

    This tests the zstd decompression path in _open_compressed_archive.
    """
    from compression import zstd

    # Create a simple mbox content
    msg_content = b"From test@example.com Mon Jan 1 00:00:00 2024\nSubject: Test\n\nBody"

    # Compress to zstd
    zst_path = temp_dir / "archive.mbox.zst"
    with zstd.open(zst_path, "wb") as f:
        f.write(msg_content)

    # Add message to database using context manager (auto-commits)
    async with DBManager(str(temp_db), auto_create=False, validate_schema=False) as db:
        await db.record_archived_message(
            gmail_id="msg_zst",
            rfc_message_id="<zst@example.com>",
            archive_file=str(zst_path),
            mbox_offset=0,
            mbox_length=len(msg_content),
            record_run=False,
        )

    # Extract
    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        message_bytes = await extractor.extract_by_gmail_id("msg_zst", output_path=None)
        assert message_bytes == msg_content


async def test_extract_from_compressed_with_invalid_format_raises_error(
    temp_db: Path, temp_dir: Path
) -> None:
    """Test that _extract_from_compressed raises error for invalid format.

    This tests the defensive error handling when an invalid compression
    format string is passed to the internal method.
    """
    # Create a test file
    test_path = temp_dir / "archive.mbox"
    test_path.write_bytes(b"test content")

    db_manager = DBManager(str(temp_db), auto_create=False, validate_schema=False)
    await db_manager.initialize()
    async with MessageExtractor(db_manager) as extractor:
        with pytest.raises(ExtractorError, match="Unsupported compression format"):
            # Call private method directly with invalid format
            extractor._extract_from_compressed(test_path, "bz2", 0, 10)
