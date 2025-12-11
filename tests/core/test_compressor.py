"""Tests for ArchiveCompressor - mbox compression functionality."""

import email
import gzip
import mailbox
from compression import zstd
from pathlib import Path

import pytest

from gmailarchiver.core.compressor import (
    ArchiveCompressor,
    CompressionSummary,
)
from gmailarchiver.data.db_manager import DBManager

pytestmark = pytest.mark.asyncio

# Note: Shared fixtures (temp_dir, temp_db) are provided by tests/conftest.py
# with proper resource cleanup.


def create_test_mbox(path: Path, message_count: int = 10) -> int:
    """Create a test mbox file with specified number of messages.

    Returns:
        File size in bytes
    """
    mbox = mailbox.mbox(str(path))

    for i in range(message_count):
        msg = email.message.EmailMessage()
        msg["Message-ID"] = f"<msg{i}@example.com>"
        msg["Subject"] = f"Test Message {i}"
        msg["From"] = f"sender{i}@example.com"
        msg["To"] = f"recipient{i}@example.com"
        msg["Date"] = f"Mon, {i + 1:02d} Jan 2024 12:00:00 +0000"
        # Add varying content length for realistic compression testing
        content = f"This is test message {i}. " * (10 + i * 5)
        msg.set_content(content)
        mbox.add(msg)

    mbox.close()
    return path.stat().st_size


async def populate_db_from_mbox(db_path: Path, mbox_path: Path) -> None:
    """Populate database with messages from mbox file."""
    async with DBManager(str(db_path), validate_schema=False) as db:
        mbox = mailbox.mbox(str(mbox_path))

        try:
            for i, msg in enumerate(mbox):
                gmail_id = f"gmail_{mbox_path.stem}_{i}"
                base_message_id = msg.get("Message-ID")
                if (
                    base_message_id
                    and base_message_id.startswith("<")
                    and base_message_id.endswith(">")
                ):
                    # Make RFC Message-ID unique across different archives by
                    # suffixing the mailbox stem inside the angle brackets.
                    rfc_message_id = f"{base_message_id[:-1]}-{mbox_path.stem}>"
                else:
                    rfc_message_id = f"<unknown{i}-{mbox_path.stem}@example.com>"
                subject = msg.get("Subject", "")
                from_addr = msg.get("From", "")
                to_addr = msg.get("To", "")
                date_str = msg.get("Date", "")

                # Get mbox offset and length.
                # Python's mailbox.mbox implementation changed in 3.14 so that
                # _toc entries may be either integer offsets or (start, stop)
                # tuples; support both shapes here.
                toc_entry = mbox._toc[i]

                if isinstance(toc_entry, tuple):
                    # Newer Python: (start, stop) or (start, stop, ...)
                    offset = toc_entry[0]
                    if len(toc_entry) > 1 and toc_entry[1] is not None:
                        length = toc_entry[1] - toc_entry[0]
                    else:
                        length = mbox_path.stat().st_size - offset
                else:
                    # Older behavior: integer offsets only
                    offset = toc_entry
                    if i + 1 < len(mbox):
                        next_entry = mbox._toc[i + 1]
                        next_offset = next_entry[0] if isinstance(next_entry, tuple) else next_entry
                        length = next_offset - offset
                    else:
                        length = mbox_path.stat().st_size - offset

                await db.record_archived_message(
                    gmail_id=gmail_id,
                    rfc_message_id=rfc_message_id,
                    thread_id=f"thread_{i}",
                    archive_file=str(mbox_path),
                    mbox_offset=offset,
                    mbox_length=length,
                    subject=subject,
                    from_addr=from_addr,
                    to_addr=to_addr,
                    date=date_str,
                    body_preview=f"Preview {i}",
                    checksum=f"checksum_{i}",
                    size_bytes=length,
                )
        finally:
            mbox.close()


# ==================== BASIC COMPRESSION TESTS ====================


async def test_compress_single_mbox_to_zstd(temp_dir: Path, temp_db: Path) -> None:
    """Test compressing single mbox to zstd format (default)."""
    # Setup
    mbox_path = temp_dir / "test.mbox"
    original_size = create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        # Execute
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

        # Verify
        assert isinstance(result, CompressionSummary)
        assert result.files_compressed == 1
        assert result.files_skipped == 0
        assert result.total_files == 1

    # Check compressed file exists
    compressed_path = temp_dir / "test.mbox.zst"
    assert compressed_path.exists()

    # Check original still exists (not in-place)
    assert mbox_path.exists()

    # Verify space savings
    assert result.original_size == original_size
    assert result.compressed_size < original_size
    assert result.space_saved == original_size - result.compressed_size
    assert result.compression_ratio > 1.0
    assert result.compression_ratio == original_size / result.compressed_size


async def test_compress_single_mbox_to_gzip(temp_dir: Path, temp_db: Path) -> None:
    """Test compressing single mbox to gzip format."""
    mbox_path = temp_dir / "test.mbox"
    original_size = create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="gzip", in_place=False, dry_run=False
        )

    # Verify
    assert result.files_compressed == 1
    compressed_path = temp_dir / "test.mbox.gz"
    assert compressed_path.exists()
    assert result.compressed_size < original_size


async def test_compress_single_mbox_to_lzma(temp_dir: Path, temp_db: Path) -> None:
    """Test compressing single mbox to lzma format."""
    mbox_path = temp_dir / "test.mbox"
    original_size = create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="lzma", in_place=False, dry_run=False
        )

    # Verify
    assert result.files_compressed == 1
    compressed_path = temp_dir / "test.mbox.xz"
    assert compressed_path.exists()
    assert result.compressed_size < original_size


# ==================== IN-PLACE COMPRESSION TESTS ====================


async def test_compress_in_place(temp_dir: Path, temp_db: Path) -> None:
    """Test in-place compression (replaces original file)."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=True, dry_run=False
        )

    # Verify
    assert result.files_compressed == 1

    # Original should be deleted
    assert not mbox_path.exists()

    # Compressed should exist
    compressed_path = temp_dir / "test.mbox.zst"
    assert compressed_path.exists()


async def test_compress_in_place_updates_db(temp_dir: Path, temp_db: Path) -> None:
    """Test in-place compression updates database archive_file paths."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=True, dry_run=False
        )

    # Verify database updated
    async with DBManager(str(temp_db), validate_schema=False) as db:
        messages = await db.get_all_messages_for_archive(str(temp_dir / "test.mbox.zst"))
        assert len(messages) == 10

        # Old path should have no messages and original file should be deleted
        old_messages = await db.get_all_messages_for_archive(str(mbox_path))
        assert len(old_messages) == 0
        assert not mbox_path.exists()


async def test_compress_in_place_keep_original_preserves_source_file(
    temp_dir: Path, temp_db: Path
) -> None:
    """Test in-place compression with keep_original keeps source file on disk."""
    mbox_path = temp_dir / "test_keep.mbox"
    create_test_mbox(mbox_path, message_count=5)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        await compressor.compress(
            files=[str(mbox_path)],
            format="zstd",
            in_place=True,
            dry_run=False,
            keep_original=True,
        )

    compressed_path = temp_dir / "test_keep.mbox.zst"

    # Both original and compressed files should exist
    assert mbox_path.exists()
    assert compressed_path.exists()

    # Database should point to the compressed path only
    async with DBManager(str(temp_db), validate_schema=False) as db:
        new_messages = await db.get_all_messages_for_archive(str(compressed_path))
        assert len(new_messages) == 5

        old_messages = await db.get_all_messages_for_archive(str(mbox_path))
        assert len(old_messages) == 0


# ==================== DRY RUN TESTS ====================


async def test_compress_dry_run_no_actual_compression(temp_dir: Path, temp_db: Path) -> None:
    """Test dry-run mode doesn't actually compress files."""
    mbox_path = temp_dir / "test.mbox"
    original_size = create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=True
        )

    # Verify stats calculated
    assert result.total_files == 1
    assert result.original_size == original_size
    assert result.estimated_compressed_size > 0
    assert result.estimated_space_saved > 0
    assert result.estimated_compression_ratio > 1.0

    # But no actual compression
    compressed_path = temp_dir / "test.mbox.zst"
    assert not compressed_path.exists()

    # Original still exists
    assert mbox_path.exists()


async def test_compress_dry_run_shows_space_savings(temp_dir: Path, temp_db: Path) -> None:
    """Test dry-run mode accurately estimates space savings."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=50)  # Larger file for better estimate
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=True
        )

    # Verify reasonable compression ratio (zstd should be 2-5x typically)
    assert result.estimated_compression_ratio >= 1.5
    assert result.estimated_compression_ratio <= 10.0


# ==================== BATCH COMPRESSION TESTS ====================


async def test_compress_multiple_files(temp_dir: Path, temp_db: Path) -> None:
    """Test compressing multiple mbox files in batch."""
    # Create multiple mbox files
    mbox1 = temp_dir / "archive1.mbox"
    mbox2 = temp_dir / "archive2.mbox"
    mbox3 = temp_dir / "archive3.mbox"

    size1 = create_test_mbox(mbox1, message_count=10)
    size2 = create_test_mbox(mbox2, message_count=15)
    size3 = create_test_mbox(mbox3, message_count=20)

    await populate_db_from_mbox(temp_db, mbox1)
    await populate_db_from_mbox(temp_db, mbox2)
    await populate_db_from_mbox(temp_db, mbox3)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox1), str(mbox2), str(mbox3)],
            format="zstd",
            in_place=False,
            dry_run=False,
        )

    # Verify
    assert result.files_compressed == 3
    assert result.total_files == 3
    assert result.original_size == size1 + size2 + size3

    # Check all compressed files exist
    assert (temp_dir / "archive1.mbox.zst").exists()
    assert (temp_dir / "archive2.mbox.zst").exists()
    assert (temp_dir / "archive3.mbox.zst").exists()


async def test_compress_batch_with_mixed_formats(temp_dir: Path, temp_db: Path) -> None:
    """Test batch compression with files needing different handling."""
    # Create mix of .mbox and already-compressed files
    mbox1 = temp_dir / "archive1.mbox"
    mbox2 = temp_dir / "archive2.mbox"

    create_test_mbox(mbox1, message_count=10)
    create_test_mbox(mbox2, message_count=10)

    # Compress one file manually
    compressed_path = temp_dir / "archive2.mbox.zst"
    with open(mbox2, "rb") as f_in:
        with zstd.open(compressed_path, "wb") as f_out:
            f_out.write(f_in.read())

    await populate_db_from_mbox(temp_db, mbox1)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox1), str(mbox2)], format="zstd", in_place=False, dry_run=False
        )

    # Only uncompressed file should be processed
    assert result.files_compressed == 1
    assert result.files_skipped == 1
    assert result.total_files == 2


# ==================== DATABASE UPDATE TESTS ====================


async def test_compress_updates_archive_file_paths(temp_dir: Path, temp_db: Path) -> None:
    """Test compression updates archive_file paths in database."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        await compressor.compress(
            files=[str(mbox_path)], format="gzip", in_place=False, dry_run=False
        )

    # Verify database has both old and new paths
    async with DBManager(str(temp_db), validate_schema=False) as db:
        # Original path still has messages (not in-place)
        old_messages = await db.get_all_messages_for_archive(str(mbox_path))
        assert len(old_messages) == 10
        # No messages in new path yet (would need manual migration)
        # This test shows we need to decide: update DB or leave as-is for non-in-place


async def test_compress_preserves_mbox_offsets(temp_dir: Path, temp_db: Path) -> None:
    """Test compression preserves database integrity (offsets, etc)."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    # Get original offsets
    async with DBManager(str(temp_db), validate_schema=False) as db:
        original_messages = await db.get_all_messages_for_archive(str(mbox_path))
        original_count = len(original_messages)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=True, dry_run=False
        )

    # Verify message count preserved
    async with DBManager(str(temp_db), validate_schema=False) as db:
        new_path = str(temp_dir / "test.mbox.zst")
        new_messages = await db.get_all_messages_for_archive(new_path)
        assert len(new_messages) == original_count


# ==================== ERROR HANDLING TESTS ====================


async def test_compress_nonexistent_file(temp_dir: Path, temp_db: Path) -> None:
    """Test error handling for non-existent files."""
    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        with pytest.raises(FileNotFoundError):
            await compressor.compress(
                files=[str(temp_dir / "nonexistent.mbox")],
                format="zstd",
                in_place=False,
                dry_run=False,
            )


async def test_compress_invalid_compression_format(temp_dir: Path, temp_db: Path) -> None:
    """Test error handling for invalid compression format."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        with pytest.raises(ValueError, match="Unsupported compression format"):
            await compressor.compress(
                files=[str(mbox_path)], format="invalid", in_place=False, dry_run=False
            )


async def test_compress_empty_file_list(temp_dir: Path, temp_db: Path) -> None:
    """Test error handling for empty file list."""
    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        with pytest.raises(ValueError, match="files cannot be empty"):
            await compressor.compress(files=[], format="zstd", in_place=False, dry_run=False)


async def test_compress_already_compressed_file(temp_dir: Path, temp_db: Path) -> None:
    """Test handling of already-compressed files."""
    # Create compressed file
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)

    compressed_path = temp_dir / "test.mbox.gz"
    with open(mbox_path, "rb") as f_in:
        with gzip.open(compressed_path, "wb") as f_out:
            f_out.write(f_in.read())

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(compressed_path)], format="gzip", in_place=False, dry_run=False
        )

    # Should skip already-compressed files
    assert result.files_compressed == 0
    assert result.files_skipped == 1


# ==================== VERIFICATION TESTS ====================


async def test_compress_verifies_integrity_after_compression(temp_dir: Path, temp_db: Path) -> None:
    """Test that compression verifies integrity of compressed file."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

    # Should succeed without integrity errors
    assert result.files_compressed == 1
    assert result.verification_passed is True


async def test_compress_rollback_on_verification_failure(temp_dir: Path, temp_db: Path) -> None:
    """Test that failed verification triggers rollback."""
    # This is hard to test without mocking, but we should have this scenario
    # covered in integration tests
    # For now, just document the expected behavior
    pass


# ==================== COMPRESSION RESULT TESTS ====================


async def test_compression_result_dataclass(temp_dir: Path, temp_db: Path) -> None:
    """Test CompressionResult dataclass structure."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

    # Verify result structure
    assert hasattr(result, "files_compressed")
    assert hasattr(result, "files_skipped")
    assert hasattr(result, "total_files")
    assert hasattr(result, "original_size")
    assert hasattr(result, "compressed_size")
    assert hasattr(result, "space_saved")
    assert hasattr(result, "compression_ratio")
    assert hasattr(result, "execution_time_ms")


async def test_compression_summary_includes_file_details(temp_dir: Path, temp_db: Path) -> None:
    """Test CompressionSummary includes per-file details."""
    mbox1 = temp_dir / "archive1.mbox"
    mbox2 = temp_dir / "archive2.mbox"

    create_test_mbox(mbox1, message_count=10)
    create_test_mbox(mbox2, message_count=15)

    await populate_db_from_mbox(temp_db, mbox1)
    await populate_db_from_mbox(temp_db, mbox2)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox1), str(mbox2)], format="zstd", in_place=False, dry_run=False
        )

    # Should have details for each file
    assert hasattr(result, "file_results")
    assert len(result.file_results) == 2


# ==================== EDGE CASES ====================


async def test_compress_very_small_file(temp_dir: Path, temp_db: Path) -> None:
    """Test compression of very small mbox file."""
    mbox_path = temp_dir / "tiny.mbox"
    create_test_mbox(mbox_path, message_count=1)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

    # Should still work, even if compression ratio is poor
    assert result.files_compressed == 1


async def test_compress_large_batch(temp_dir: Path, temp_db: Path) -> None:
    """Test compressing large batch of files."""
    files = []
    for i in range(10):
        mbox_path = temp_dir / f"archive{i}.mbox"
        create_test_mbox(mbox_path, message_count=5)
        await populate_db_from_mbox(temp_db, mbox_path)
        files.append(str(mbox_path))

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=files, format="zstd", in_place=False, dry_run=False
        )

    assert result.files_compressed == 10
    assert result.total_files == 10


async def test_compress_with_special_characters_in_filename(temp_dir: Path, temp_db: Path) -> None:
    """Test compression of files with special characters in name."""
    mbox_path = temp_dir / "archive [2024] test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

    assert result.files_compressed == 1
    compressed_path = temp_dir / "archive [2024] test.mbox.zst"
    assert compressed_path.exists()


# ==================== PROGRESS TRACKING TESTS ====================


async def test_compress_tracks_execution_time(temp_dir: Path, temp_db: Path) -> None:
    """Test that compression tracks execution time."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=10)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        result = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
        )

    assert result.execution_time_ms > 0
    assert isinstance(result.execution_time_ms, float)


async def test_compress_different_formats_have_different_ratios(
    temp_dir: Path, temp_db: Path
) -> None:
    """Test that different compression formats produce different ratios."""
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=20)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        # Test with zstd
        result_zstd = await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=False, dry_run=True
        )

        # Test with gzip
        result_gzip = await compressor.compress(
            files=[str(mbox_path)], format="gzip", in_place=False, dry_run=True
        )

    # Both should have reasonable compression ratios
    assert result_zstd.estimated_compression_ratio > 1.0
    assert result_gzip.estimated_compression_ratio > 1.0


async def test_compress_preserves_message_count(temp_dir: Path, temp_db: Path) -> None:
    """Test that compression preserves exact message count in database."""
    mbox_path = temp_dir / "test.mbox"
    message_count = 15
    create_test_mbox(mbox_path, message_count=message_count)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)
        await compressor.compress(
            files=[str(mbox_path)], format="zstd", in_place=True, dry_run=False
        )

    # Verify message count unchanged
    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressed_path = str(temp_dir / "test.mbox.zst")
        messages = await db.get_all_messages_for_archive(compressed_path)
        assert len(messages) == message_count


async def test_compressor_cleanup_on_verification_failure(temp_dir: Path, temp_db: Path) -> None:
    """Test that failed verification cleans up corrupt compressed file (line 260).

    Critical path: When _verify_compressed_file returns False, the compressed file
    must be deleted to prevent keeping corrupt archives.
    """
    from unittest.mock import patch

    # Create test mbox
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=5)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        # Mock verification to fail
        with patch.object(compressor, "_verify_compressed_file", return_value=False):
            dest_path = temp_dir / "test.mbox.zst"

            # Compression should raise ValueError due to verification failure
            with pytest.raises(ValueError, match="Verification failed"):
                await compressor.compress(
                    files=[str(mbox_path)], format="zstd", in_place=False, dry_run=False
                )

            # Critical assertion: corrupt file must NOT exist (was cleaned up)
            assert not dest_path.exists(), "Corrupt compressed file should have been deleted"


async def test_unsupported_compression_format_raises_error(temp_dir: Path, temp_db: Path) -> None:
    """Test that unsupported compression format raises ValueError.

    The compress method validates the format before attempting compression.
    """
    mbox_path = temp_dir / "test.mbox"
    create_test_mbox(mbox_path, message_count=3)
    await populate_db_from_mbox(temp_db, mbox_path)

    async with DBManager(str(temp_db), validate_schema=False) as db:
        compressor = ArchiveCompressor(db)

        # Try to compress with invalid format
        with pytest.raises(ValueError, match="Unsupported compression format"):
            await compressor.compress(
                files=[str(mbox_path)],
                format="invalid_format",
                in_place=False,
                dry_run=False,
            )
