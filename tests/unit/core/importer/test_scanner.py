"""Unit tests for importer FileScanner module.

Tests file discovery, glob pattern matching, and compression format detection.
All tests use mocks - no actual file I/O.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.importer._scanner import CompressionFormat, FileScanner


@pytest.mark.unit
class TestCompressionFormat:
    """Tests for compression format detection."""

    def test_from_path_gzip(self) -> None:
        """Test gzip format detection."""
        assert CompressionFormat.from_path(Path("test.mbox.gz")) == CompressionFormat.GZIP

    def test_from_path_lzma(self) -> None:
        """Test lzma format detection (.xz extension)."""
        assert CompressionFormat.from_path(Path("test.mbox.xz")) == CompressionFormat.LZMA

    def test_from_path_lzma_alt(self) -> None:
        """Test lzma format detection (.lzma extension)."""
        assert CompressionFormat.from_path(Path("test.mbox.lzma")) == CompressionFormat.LZMA

    def test_from_path_zstd(self) -> None:
        """Test zstd format detection."""
        assert CompressionFormat.from_path(Path("test.mbox.zst")) == CompressionFormat.ZSTD

    def test_from_path_none(self) -> None:
        """Test uncompressed mbox detection."""
        assert CompressionFormat.from_path(Path("test.mbox")) == CompressionFormat.NONE

    def test_from_path_case_insensitive(self) -> None:
        """Test case-insensitive extension detection."""
        assert CompressionFormat.from_path(Path("test.mbox.GZ")) == CompressionFormat.GZIP
        assert CompressionFormat.from_path(Path("test.mbox.XZ")) == CompressionFormat.LZMA

    def test_from_path_unknown_extension(self) -> None:
        """Test unknown extension defaults to NONE."""
        assert CompressionFormat.from_path(Path("test.mbox.unknown")) == CompressionFormat.NONE


@pytest.mark.unit
class TestFileScannerInit:
    """Tests for FileScanner initialization."""

    def test_init_default(self) -> None:
        """Test initialization with default parameters."""
        scanner = FileScanner()
        assert scanner is not None


@pytest.mark.unit
class TestFileScannerScanPattern:
    """Tests for glob pattern scanning."""

    @patch("gmailarchiver.core.importer._scanner.glob")
    def test_scan_pattern_single_file(self, mock_glob: Mock) -> None:
        """Test scanning pattern that matches single file."""
        mock_glob.return_value = ["/tmp/archive.mbox"]

        scanner = FileScanner()
        files = scanner.scan_pattern("/tmp/*.mbox")

        assert len(files) == 1
        assert files[0] == Path("/tmp/archive.mbox")
        mock_glob.assert_called_once_with("/tmp/*.mbox")

    @patch("gmailarchiver.core.importer._scanner.glob")
    def test_scan_pattern_multiple_files(self, mock_glob: Mock) -> None:
        """Test scanning pattern that matches multiple files."""
        mock_glob.return_value = ["/tmp/archive1.mbox", "/tmp/archive2.mbox.gz"]

        scanner = FileScanner()
        files = scanner.scan_pattern("/tmp/*.mbox*")

        assert len(files) == 2
        assert files[0] == Path("/tmp/archive1.mbox")
        assert files[1] == Path("/tmp/archive2.mbox.gz")

    @patch("gmailarchiver.core.importer._scanner.glob")
    def test_scan_pattern_no_matches(self, mock_glob: Mock) -> None:
        """Test scanning pattern with no matches."""
        mock_glob.return_value = []

        scanner = FileScanner()
        files = scanner.scan_pattern("/tmp/*.mbox")

        assert len(files) == 0


@pytest.mark.unit
class TestFileScannerDecompress:
    """Tests for decompression to temporary files."""

    @patch("gmailarchiver.core.importer._scanner.NamedTemporaryFile")
    @patch("gmailarchiver.core.importer._scanner.gzip.open")
    def test_decompress_gzip(self, mock_gzip_open: Mock, mock_temp: Mock) -> None:
        """Test gzip decompression."""
        # Setup mocks
        mock_compressed = Mock()
        mock_compressed.read.return_value = b"test data"
        mock_gzip_open.return_value.__enter__.return_value = mock_compressed

        mock_temp_file = Mock()
        mock_temp_file.name = "/tmp/temp.mbox"
        mock_temp.return_value = mock_temp_file

        scanner = FileScanner()
        temp_path, is_temp = scanner.decompress_to_temp(Path("test.mbox.gz"))

        assert temp_path == Path("/tmp/temp.mbox")
        assert is_temp is True
        mock_gzip_open.assert_called_once_with(Path("test.mbox.gz"), "rb")
        mock_temp_file.write.assert_called_once_with(b"test data")
        mock_temp_file.close.assert_called_once()

    @patch("gmailarchiver.core.importer._scanner.NamedTemporaryFile")
    @patch("gmailarchiver.core.importer._scanner.lzma.open")
    def test_decompress_lzma(self, mock_lzma_open: Mock, mock_temp: Mock) -> None:
        """Test lzma decompression."""
        # Setup mocks
        mock_compressed = Mock()
        mock_compressed.read.return_value = b"test data"
        mock_lzma_open.return_value.__enter__.return_value = mock_compressed

        mock_temp_file = Mock()
        mock_temp_file.name = "/tmp/temp.mbox"
        mock_temp.return_value = mock_temp_file

        scanner = FileScanner()
        temp_path, is_temp = scanner.decompress_to_temp(Path("test.mbox.xz"))

        assert temp_path == Path("/tmp/temp.mbox")
        assert is_temp is True
        mock_lzma_open.assert_called_once_with(Path("test.mbox.xz"), "rb")
        mock_temp_file.write.assert_called_once_with(b"test data")

    def test_decompress_uncompressed(self) -> None:
        """Test that uncompressed files are returned as-is."""
        scanner = FileScanner()
        temp_path, is_temp = scanner.decompress_to_temp(Path("test.mbox"))

        assert temp_path == Path("test.mbox")
        assert is_temp is False

    @patch("gmailarchiver.core.importer._scanner.NamedTemporaryFile")
    @patch("gmailarchiver.core.importer._scanner.gzip.open")
    @patch("gmailarchiver.core.importer._scanner.Path.exists")
    @patch("gmailarchiver.core.importer._scanner.Path.unlink")
    def test_decompress_error_cleanup(
        self,
        mock_unlink: Mock,
        mock_exists: Mock,
        mock_gzip_open: Mock,
        mock_temp: Mock,
    ) -> None:
        """Test that temporary file is cleaned up on decompression error."""
        # Setup mocks to raise error
        mock_gzip_open.side_effect = OSError("Decompression failed")

        mock_temp_file = Mock()
        mock_temp_file.name = "/tmp/temp.mbox"
        mock_temp.return_value = mock_temp_file
        mock_exists.return_value = True

        scanner = FileScanner()
        with pytest.raises(RuntimeError, match="Failed to decompress"):
            scanner.decompress_to_temp(Path("test.mbox.gz"))

        # Verify cleanup
        mock_temp_file.close.assert_called_once()
        # Note: Path.exists() and unlink() are called on the Path object
        # We need to verify the pattern, not the exact call


@pytest.mark.unit
class TestFileScannerCleanup:
    """Tests for temporary file cleanup."""

    @patch("gmailarchiver.core.importer._scanner.Path.exists")
    @patch("gmailarchiver.core.importer._scanner.Path.unlink")
    def test_cleanup_temp_file(self, mock_unlink: Mock, mock_exists: Mock) -> None:
        """Test cleanup of temporary file."""
        mock_exists.return_value = True

        scanner = FileScanner()
        scanner.cleanup_temp_file(Path("/tmp/temp.mbox"), is_temp=True)

        # Verify unlink was called (on the Path object, so we check the call happened)
        assert mock_unlink.call_count == 1

    def test_cleanup_non_temp_file(self) -> None:
        """Test that non-temp files are not deleted."""
        scanner = FileScanner()
        # Should not raise, should not delete
        scanner.cleanup_temp_file(Path("test.mbox"), is_temp=False)

    @patch("gmailarchiver.core.importer._scanner.Path.exists")
    def test_cleanup_missing_file(self, mock_exists: Mock) -> None:
        """Test cleanup when temp file doesn't exist."""
        mock_exists.return_value = False

        scanner = FileScanner()
        # Should not raise
        scanner.cleanup_temp_file(Path("/tmp/missing.mbox"), is_temp=True)
