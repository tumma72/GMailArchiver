"""Gzip compression handler."""

import gzip
import shutil
from pathlib import Path


class GzipCompressor:
    """Handle gzip compression operations."""

    @staticmethod
    def compress(source: Path, dest: Path) -> None:
        """Compress file using gzip.

        Args:
            source: Source file path
            dest: Destination compressed file path
        """
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

    @staticmethod
    def verify(file_path: Path) -> bool:
        """Verify gzip file can be decompressed.

        Args:
            file_path: Path to gzip file

        Returns:
            True if file is valid
        """
        try:
            with gzip.open(file_path, "rb") as f:
                f.read(1024)  # Read a small chunk
            return True
        except Exception:
            return False

    @staticmethod
    def estimate_size(file_path: Path, sample_size: int) -> int:
        """Estimate compressed size by sampling.

        Args:
            file_path: Path to source file
            sample_size: Number of bytes to sample

        Returns:
            Estimated compressed size
        """
        import tempfile

        # Read sample
        with open(file_path, "rb") as f:
            sample_data = f.read(sample_size)

        # Compress sample to temp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            with gzip.open(tmp_path, "wb", compresslevel=6) as f:
                f.write(sample_data)

            compressed_sample_size = tmp_path.stat().st_size
            return compressed_sample_size
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @staticmethod
    def get_extension() -> str:
        """Get file extension for this compression format."""
        return ".gz"
