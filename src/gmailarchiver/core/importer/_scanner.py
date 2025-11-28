"""Internal module for file scanning and compression handling.

This module handles file discovery via glob patterns and compression format
detection/decompression. Part of importer package's internal implementation.
"""

import gzip
import lzma
from enum import Enum
from glob import glob
from pathlib import Path
from tempfile import NamedTemporaryFile


class CompressionFormat(Enum):
    """Compression format enumeration."""

    NONE = "none"
    GZIP = "gzip"
    LZMA = "lzma"
    ZSTD = "zstd"

    @classmethod
    def from_path(cls, path: Path) -> CompressionFormat:
        """Detect compression format from file extension.

        Args:
            path: Path to archive file

        Returns:
            CompressionFormat enum value
        """
        suffix = path.suffix.lower()
        if suffix == ".gz":
            return cls.GZIP
        elif suffix in (".xz", ".lzma"):
            return cls.LZMA
        elif suffix == ".zst":
            return cls.ZSTD
        return cls.NONE


class FileScanner:
    """Internal helper for file discovery and compression handling.

    Handles glob pattern matching, compression format detection, and
    decompression to temporary files. This is an internal implementation
    detail - use ImporterFacade for public API.
    """

    def scan_pattern(self, pattern: str) -> list[Path]:
        """Scan filesystem for files matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., "archives/*.mbox*")

        Returns:
            List of matching file paths
        """
        return [Path(p) for p in glob(pattern)]

    def decompress_to_temp(self, archive_path: Path) -> tuple[Path, bool]:
        """Decompress archive to temporary file if needed.

        Args:
            archive_path: Path to archive file

        Returns:
            Tuple of (uncompressed_path, is_temporary)
            - If file is uncompressed, returns (original_path, False)
            - If compressed, returns (temp_path, True)

        Raises:
            RuntimeError: If decompression fails
        """
        compression = CompressionFormat.from_path(archive_path)

        if compression == CompressionFormat.NONE:
            return archive_path, False

        # Create temporary file for decompressed data
        temp = NamedTemporaryFile(mode="wb", delete=False, suffix=".mbox")
        temp_path = Path(temp.name)

        try:
            if compression == CompressionFormat.GZIP:
                with gzip.open(archive_path, "rb") as f_in:
                    temp.write(f_in.read())
            elif compression == CompressionFormat.LZMA:
                with lzma.open(archive_path, "rb") as f_in:
                    temp.write(f_in.read())
            elif compression == CompressionFormat.ZSTD:
                # Python 3.14+ has native zstd support
                from compression import zstd

                with zstd.open(archive_path, "rb") as f_in:
                    temp.write(f_in.read())

            temp.close()
            return temp_path, True

        except Exception as e:
            temp.close()
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"Failed to decompress {archive_path}: {e}") from e

    def cleanup_temp_file(self, path: Path, is_temp: bool) -> None:
        """Clean up temporary file if needed.

        Args:
            path: Path to file
            is_temp: Whether file is temporary (should be deleted)
        """
        if is_temp and path.exists():
            path.unlink()
