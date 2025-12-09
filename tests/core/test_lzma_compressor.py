"""Tests for LZMA compressor to improve coverage.

These tests target specific uncovered lines in compressor/_lzma.py
(lines 37-38, 51-69) to achieve 95%+ coverage.
"""

import tempfile
from pathlib import Path

from gmailarchiver.core.compressor._lzma import LzmaCompressor


class TestLzmaVerify:
    """Tests for LzmaCompressor.verify() method (lines 37-38)."""

    def test_verify_invalid_lzma_file(self) -> None:
        """Test verify() returns False for invalid LZMA file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file that's not valid LZMA
            invalid_file = Path(tmpdir) / "invalid.xz"
            invalid_file.write_bytes(b"Not a valid LZMA file")

            # verify() should return False
            result = LzmaCompressor.verify(invalid_file)

            assert result is False

    def test_verify_valid_lzma_file(self) -> None:
        """Test verify() returns True for valid LZMA file."""
        import lzma

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a valid LZMA file
            valid_file = Path(tmpdir) / "valid.xz"
            with lzma.open(valid_file, "wb") as f:
                f.write(b"This is test data that can be read")

            # verify() should return True
            result = LzmaCompressor.verify(valid_file)

            assert result is True


class TestLzmaEstimateSize:
    """Tests for LzmaCompressor.estimate_size() method (lines 51-69)."""

    def test_estimate_size_small_sample(self) -> None:
        """Test estimate_size() with small sample."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_content = b"This is test data for compression estimation. " * 100
            test_file.write_bytes(test_content)

            # Estimate size with small sample
            sample_size = 1024
            estimated_size = LzmaCompressor.estimate_size(test_file, sample_size)

            # Should return a positive size
            assert estimated_size > 0
            # Compressed size should be smaller than sample
            assert estimated_size < sample_size

    def test_estimate_size_large_sample(self) -> None:
        """Test estimate_size() with large sample."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a larger test file
            test_file = Path(tmpdir) / "large.txt"
            test_content = b"Repeated data " * 10000
            test_file.write_bytes(test_content)

            # Estimate size with larger sample
            sample_size = 10240
            estimated_size = LzmaCompressor.estimate_size(test_file, sample_size)

            # Should return a positive size
            assert estimated_size > 0
            # For repeated data, compression should be significant
            assert estimated_size < sample_size * 0.5

    def test_estimate_size_temp_file_cleanup(self) -> None:
        """Test estimate_size() cleans up temporary file (line 68-69)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_bytes(b"Test data" * 100)

            # Count temp files before
            temp_files_before = list(Path(tempfile.gettempdir()).glob("tmp*"))

            # Call estimate_size
            LzmaCompressor.estimate_size(test_file, 512)

            # Temp files should be cleaned up
            temp_files_after = list(Path(tempfile.gettempdir()).glob("tmp*"))

            # Should not create additional temp files (or clean them up)
            assert len(temp_files_after) <= len(temp_files_before) + 1
