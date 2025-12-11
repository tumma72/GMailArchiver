"""Archive compression facade for converting mbox files to compressed formats."""

import gzip
import logging
import lzma
import mailbox
import shutil
import tempfile
import time
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from gmailarchiver.core.compressor._gzip import GzipCompressor
from gmailarchiver.core.compressor._lzma import LzmaCompressor
from gmailarchiver.core.compressor._zstd import ZstdCompressor
from gmailarchiver.data.db_manager import DBManager

logger = logging.getLogger(__name__)


class CompressionHandler(Protocol):
    """Protocol for compression handler classes."""

    @staticmethod
    def compress(source: Path, dest: Path) -> None:
        """Compress file."""
        ...

    @staticmethod
    def verify(file_path: Path) -> bool:
        """Verify compressed file."""
        ...

    @staticmethod
    def estimate_size(file_path: Path, sample_size: int) -> int:
        """Estimate compressed size."""
        ...

    @staticmethod
    def get_extension() -> str:
        """Get file extension."""
        ...


@dataclass
class CompressionResult:
    """Result of compressing a single file."""

    source_file: str
    dest_file: str | None
    original_size: int
    compressed_size: int
    space_saved: int
    compression_ratio: float
    success: bool
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class CompressionSummary:
    """Summary of batch compression operation."""

    files_compressed: int
    files_skipped: int
    total_files: int
    original_size: int
    compressed_size: int = 0
    estimated_compressed_size: int = 0
    space_saved: int = 0
    estimated_space_saved: int = 0
    compression_ratio: float = 0.0
    estimated_compression_ratio: float = 0.0
    execution_time_ms: float = 0.0
    file_results: list[CompressionResult] = field(default_factory=list)
    verification_passed: bool = True


class ArchiveCompressor:
    """Compress mbox archives to save disk space."""

    def __init__(self, db_manager: DBManager) -> None:
        """Initialize compressor with database manager.

        Args:
            db_manager: Database manager for state operations
        """
        self.db_manager = db_manager
        self._compressors: dict[str, type[CompressionHandler]] = {
            "gzip": GzipCompressor,
            "lzma": LzmaCompressor,
            "zstd": ZstdCompressor,
        }

    async def compress(
        self,
        files: list[str],
        format: str = "zstd",
        in_place: bool = False,
        dry_run: bool = False,
        keep_original: bool = False,
    ) -> CompressionSummary:
        """Compress mbox archive files.

        Args:
            files: List of mbox file paths to compress
            format: Compression format ('gzip', 'lzma', 'zstd')
            in_place: Replace original file with compressed version
            dry_run: Preview compression without actually compressing
            keep_original: Keep original file after compression

        Returns:
            CompressionSummary with compression statistics

        Raises:
            ValueError: If files is empty or format is invalid
            FileNotFoundError: If any file doesn't exist
        """
        start_time = time.perf_counter()

        # Validate inputs
        if not files:
            raise ValueError("files cannot be empty")

        if format not in self._compressors:
            valid_formats = tuple(self._compressors.keys())
            raise ValueError(
                f"Unsupported compression format: {format}. Must be one of {valid_formats}"
            )

        # Convert to paths and verify existence
        file_paths = [Path(f) for f in files]
        for file_path in file_paths:
            if not file_path.exists():
                raise FileNotFoundError(f"Archive file not found: {file_path}")

        # Process each file
        file_results: list[CompressionResult] = []
        total_original_size = 0
        total_compressed_size = 0
        total_estimated_compressed_size = 0
        files_compressed = 0
        files_skipped = 0

        try:
            for file_path in file_paths:
                result = await self._compress_file(
                    file_path,
                    format,
                    in_place,
                    dry_run,
                    keep_original,
                )
                file_results.append(result)

                total_original_size += result.original_size

                if result.skipped:
                    files_skipped += 1
                else:
                    files_compressed += 1
                    if dry_run:
                        total_estimated_compressed_size += result.compressed_size
                    else:
                        total_compressed_size += result.compressed_size

            # Commit database changes if not dry run
            if not dry_run:
                await self.db_manager.commit()
            else:
                await self.db_manager.rollback()

            end_time = time.perf_counter()
            execution_time_ms = (end_time - start_time) * 1000

            # Calculate summary statistics
            if dry_run:
                space_saved = total_original_size - total_estimated_compressed_size
                compression_ratio = (
                    total_original_size / total_estimated_compressed_size
                    if total_estimated_compressed_size > 0
                    else 0.0
                )
                return CompressionSummary(
                    files_compressed=0,
                    files_skipped=files_skipped,
                    total_files=len(files),
                    original_size=total_original_size,
                    estimated_compressed_size=total_estimated_compressed_size,
                    estimated_space_saved=space_saved,
                    estimated_compression_ratio=compression_ratio,
                    execution_time_ms=execution_time_ms,
                    file_results=file_results,
                )
            else:
                space_saved = total_original_size - total_compressed_size
                compression_ratio = (
                    total_original_size / total_compressed_size
                    if total_compressed_size > 0
                    else 0.0
                )
                return CompressionSummary(
                    files_compressed=files_compressed,
                    files_skipped=files_skipped,
                    total_files=len(files),
                    original_size=total_original_size,
                    compressed_size=total_compressed_size,
                    space_saved=space_saved,
                    compression_ratio=compression_ratio,
                    execution_time_ms=execution_time_ms,
                    file_results=file_results,
                )

        except Exception:
            await self.db_manager.rollback()
            raise

    async def _compress_file(
        self,
        file_path: Path,
        format: str,
        in_place: bool,
        dry_run: bool,
        keep_original: bool,
    ) -> CompressionResult:
        """Compress a single file.

        Args:
            file_path: Path to file to compress
            format: Compression format
            in_place: Replace original file
            dry_run: Preview only
            keep_original: Keep original file

        Returns:
            CompressionResult for this file
        """
        original_size = file_path.stat().st_size

        # Check if already compressed
        if self._is_compressed(file_path):
            logger.info(f"Skipping already-compressed file: {file_path}")
            return CompressionResult(
                source_file=str(file_path),
                dest_file=None,
                original_size=original_size,
                compressed_size=0,
                space_saved=0,
                compression_ratio=0.0,
                success=False,
                skipped=True,
                skip_reason="Already compressed",
            )

        # Determine output path
        compressor = self._compressors[format]
        extension = compressor.get_extension()
        dest_path = file_path.with_suffix(file_path.suffix + extension)

        if dry_run:
            # Estimate compression size by sampling
            estimated_size = self._estimate_compressed_size(file_path, format)
            space_saved = original_size - estimated_size
            compression_ratio = original_size / estimated_size if estimated_size > 0 else 0.0

            return CompressionResult(
                source_file=str(file_path),
                dest_file=str(dest_path),
                original_size=original_size,
                compressed_size=estimated_size,
                space_saved=space_saved,
                compression_ratio=compression_ratio,
                success=True,
            )

        # Actual compression
        try:
            compressor.compress(file_path, dest_path)
            compressed_size = dest_path.stat().st_size

            # Verify compressed file can be read
            if not self._verify_compressed_file(dest_path, format):
                # Cleanup and raise error
                dest_path.unlink()
                raise ValueError(f"Verification failed for {dest_path}")

            # Update database if in_place
            if in_place:
                await self._update_database_paths(str(file_path), str(dest_path))
                # Remove original file unless the caller requested to keep it
                if not keep_original:
                    file_path.unlink()

            space_saved = original_size - compressed_size
            compression_ratio = original_size / compressed_size if compressed_size > 0 else 0.0

            return CompressionResult(
                source_file=str(file_path),
                dest_file=str(dest_path),
                original_size=original_size,
                compressed_size=compressed_size,
                space_saved=space_saved,
                compression_ratio=compression_ratio,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to compress {file_path}: {e}")
            # Cleanup partial file
            if dest_path.exists():
                dest_path.unlink()
            raise

    def _is_compressed(self, file_path: Path) -> bool:
        """Check if file is already compressed or has a compressed sibling."""
        # Directly compressed file
        if file_path.suffix in (".gz", ".xz", ".lzma", ".zst"):
            return True

        # If a compressed sibling already exists (same base name), skip
        for ext in (".gz", ".xz", ".lzma", ".zst"):
            sibling = file_path.with_suffix(file_path.suffix + ext)
            if sibling.exists():
                return True

        return False

    def _estimate_compressed_size(self, file_path: Path, format: str) -> int:
        """Estimate compressed size by compressing a sample.

        Args:
            file_path: Path to file
            format: Compression format

        Returns:
            Estimated compressed size in bytes
        """
        # Read first 10% of file (or 1MB, whichever is smaller)
        original_size = file_path.stat().st_size
        sample_size = min(original_size // 10, 1024 * 1024)

        if sample_size == 0:
            sample_size = original_size

        # Get compressor and estimate
        compressor = self._compressors[format]
        compressed_sample_size = compressor.estimate_size(file_path, sample_size)

        # Extrapolate to full file size with clamping
        raw_ratio = compressed_sample_size / sample_size if sample_size > 0 else 1.0
        # Clamp to minimum of 0.1 to avoid unrealistic compression ratios
        ratio = max(raw_ratio, 0.1)
        # Ensure we never estimate smaller than 1/10th of original
        min_estimated_size = max(1, (original_size + 9) // 10)
        estimated_size = max(int(original_size * ratio), min_estimated_size)

        return estimated_size

    def _verify_compressed_file(self, file_path: Path, format: str) -> bool:
        """Verify compressed file can be read.

        Args:
            file_path: Path to compressed file
            format: Compression format

        Returns:
            True if file can be decompressed successfully
        """
        try:
            # Try to open and read first few bytes
            compressor = self._compressors[format]
            if not compressor.verify(file_path):
                return False

            # Also verify it's a valid mbox by trying to open with mailbox
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                # Decompress to temp file
                if format == "gzip":
                    with gzip.open(file_path, "rb") as f_in:
                        with open(tmp_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                elif format == "lzma":
                    with lzma.open(file_path, "rb") as f_in:
                        with open(tmp_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                elif format == "zstd":
                    with zstd.open(file_path, "rb") as f_in:
                        with open(tmp_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)

                # Verify it's a valid mbox
                mbox = mailbox.mbox(str(tmp_path))
                # Just check it can be opened
                _ = len(mbox)
                mbox.close()

                return True
            finally:
                # Cleanup temp file
                if tmp_path.exists():
                    tmp_path.unlink()

        except Exception as e:
            logger.error(f"Verification failed for {file_path}: {e}")
            return False

    async def _update_database_paths(self, old_path: str, new_path: str) -> None:
        """Update database to point to new compressed file.

        Args:
            old_path: Old archive file path
            new_path: New compressed file path
        """
        # Get all messages for the old archive
        messages = await self.db_manager.get_all_messages_for_archive(old_path)

        if not messages:
            logger.warning(f"No messages found for archive: {old_path}")
            return

        # Update each message's archive_file path
        # Note: mbox_offset and mbox_length remain the same!
        updates = [
            {
                "gmail_id": msg["gmail_id"],
                "archive_file": new_path,
                "mbox_offset": msg["mbox_offset"],
                "mbox_length": msg["mbox_length"],
            }
            for msg in messages
        ]

        await self.db_manager.bulk_update_archive_locations(updates)
        logger.info(f"Updated {len(updates)} messages from {old_path} to {new_path}")
