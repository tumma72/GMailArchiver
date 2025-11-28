"""Unit tests for validator._decompressor module.

Tests compression/decompression handling for mbox archives.
All tests are fast (<1s) and use mocking for I/O.
"""

import gzip
import lzma
import tempfile
from compression import zstd
from pathlib import Path

import pytest


@pytest.mark.unit
class TestDecompressor:
    """Unit tests for Decompressor class."""

    def test_get_uncompressed_mbox_returns_as_is(self) -> None:
        """Test that uncompressed .mbox files are returned as-is."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        decompressor = Decompressor()
        archive_path = Path("/path/to/archive.mbox")

        mbox_path, is_temp = decompressor.get_mbox_path(archive_path)

        assert mbox_path == archive_path
        assert is_temp is False

    def test_get_gzip_compressed_decompresses_to_temp(self) -> None:
        """Test that .gz files are decompressed to temporary location."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as source:
            source_path = Path(source.name)
            source.write(b"From test@example.com\nSubject: Test\n\nBody")

        with tempfile.NamedTemporaryFile(suffix=".mbox.gz", delete=False) as gz_file:
            gz_path = Path(gz_file.name)

        try:
            # Compress the source
            with gzip.open(gz_path, "wb") as f_out:
                with open(source_path, "rb") as f_in:
                    f_out.write(f_in.read())

            decompressor = Decompressor()
            mbox_path, is_temp = decompressor.get_mbox_path(gz_path)

            assert is_temp is True
            assert mbox_path.exists()
            assert mbox_path.suffix == ".mbox"

            # Verify content
            with open(mbox_path, "rb") as f:
                content = f.read()
                assert b"From test@example.com" in content

            # Cleanup temp file
            if mbox_path.exists():
                mbox_path.unlink()
        finally:
            source_path.unlink()
            gz_path.unlink()

    def test_get_lzma_compressed_decompresses_to_temp(self) -> None:
        """Test that .xz files are decompressed to temporary location."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as source:
            source_path = Path(source.name)
            source.write(b"From test@example.com\nSubject: Test\n\nBody")

        with tempfile.NamedTemporaryFile(suffix=".mbox.xz", delete=False) as xz_file:
            xz_path = Path(xz_file.name)

        try:
            # Compress the source
            with lzma.open(xz_path, "wb") as f_out:
                with open(source_path, "rb") as f_in:
                    f_out.write(f_in.read())

            decompressor = Decompressor()
            mbox_path, is_temp = decompressor.get_mbox_path(xz_path)

            assert is_temp is True
            assert mbox_path.exists()
            assert mbox_path.suffix == ".mbox"

            # Cleanup temp file
            if mbox_path.exists():
                mbox_path.unlink()
        finally:
            source_path.unlink()
            xz_path.unlink()

    def test_get_zstd_compressed_decompresses_to_temp(self) -> None:
        """Test that .zst files are decompressed to temporary location."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as source:
            source_path = Path(source.name)
            source.write(b"From test@example.com\nSubject: Test\n\nBody")

        with tempfile.NamedTemporaryFile(suffix=".mbox.zst", delete=False) as zst_file:
            zst_path = Path(zst_file.name)

        try:
            # Compress the source
            with zstd.open(zst_path, "wb") as f_out:
                with open(source_path, "rb") as f_in:
                    f_out.write(f_in.read())

            decompressor = Decompressor()
            mbox_path, is_temp = decompressor.get_mbox_path(zst_path)

            assert is_temp is True
            assert mbox_path.exists()
            assert mbox_path.suffix == ".mbox"

            # Cleanup temp file
            if mbox_path.exists():
                mbox_path.unlink()
        finally:
            source_path.unlink()
            zst_path.unlink()

    def test_get_unknown_extension_returns_as_is(self) -> None:
        """Test that unknown extensions are returned as-is."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".unknown", delete=False) as unknown:
            unknown_path = Path(unknown.name)

        try:
            decompressor = Decompressor()
            mbox_path, is_temp = decompressor.get_mbox_path(unknown_path)

            assert mbox_path == unknown_path
            assert is_temp is False
        finally:
            unknown_path.unlink()

    def test_cleanup_temp_file_removes_file(self) -> None:
        """Test that cleanup removes temporary files."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as temp:
            temp_path = Path(temp.name)

        assert temp_path.exists()

        decompressor = Decompressor()
        decompressor.cleanup_temp_file(temp_path, is_temp=True)

        assert not temp_path.exists()

    def test_cleanup_non_temp_file_does_not_remove(self) -> None:
        """Test that cleanup does not remove non-temporary files."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as perm:
            perm_path = Path(perm.name)

        try:
            decompressor = Decompressor()
            decompressor.cleanup_temp_file(perm_path, is_temp=False)

            # Should still exist
            assert perm_path.exists()
        finally:
            perm_path.unlink()

    def test_cleanup_missing_file_does_not_raise(self) -> None:
        """Test that cleanup handles missing files gracefully."""
        from gmailarchiver.core.validator._decompressor import Decompressor

        missing_path = Path("/nonexistent/file.mbox")

        decompressor = Decompressor()
        # Should not raise
        decompressor.cleanup_temp_file(missing_path, is_temp=True)
