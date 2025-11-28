"""Decompression handling for mbox archives.

Handles detection and decompression of compressed mbox files.
Supports: gzip (.gz), lzma (.xz), zstd (.zst), and uncompressed (.mbox).
"""

import gzip
import lzma
import os
import tempfile
from compression import zstd
from pathlib import Path


class Decompressor:
    """Handles decompression of mbox archives."""

    def get_mbox_path(self, archive_path: Path) -> tuple[Path, bool]:
        """Get path to mbox file, decompressing if necessary.

        Args:
            archive_path: Path to potentially compressed archive

        Returns:
            Tuple of (mbox_path, is_temporary)
            - mbox_path: Path to uncompressed mbox file
            - is_temporary: True if file should be cleaned up after use
        """
        suffix = archive_path.suffix.lower()

        # If uncompressed, return as-is
        if suffix == ".mbox":
            return (archive_path, False)

        # Need to decompress to temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix=".mbox", prefix="gmailarchive_")
        temp_mbox = Path(temp_path)

        try:
            if suffix == ".gz":
                with gzip.open(archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
                        f_out.write(f_in.read())
            elif suffix == ".xz":
                with lzma.open(archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
                        f_out.write(f_in.read())
            elif suffix == ".zst":
                with zstd.open(archive_path, "rb") as f_in:
                    with open(temp_mbox, "wb") as f_out:
                        f_out.write(f_in.read())
            else:
                # Unknown compression, try as-is
                os.close(temp_fd)
                temp_mbox.unlink()
                return (archive_path, False)

            return (temp_mbox, True)
        finally:
            # Close the file descriptor (only if not already closed)
            try:
                os.close(temp_fd)
            except OSError:
                # Already closed
                pass

    def cleanup_temp_file(self, mbox_path: Path, is_temp: bool) -> None:
        """Clean up temporary decompressed file.

        Args:
            mbox_path: Path to mbox file
            is_temp: Whether file is temporary
        """
        if is_temp and mbox_path.exists():
            mbox_path.unlink()
