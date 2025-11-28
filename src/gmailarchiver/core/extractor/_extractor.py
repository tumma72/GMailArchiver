"""Message extraction from archives."""

import gzip
import lzma
import sys
from io import IOBase
from pathlib import Path


class ExtractorError(Exception):
    """Raised when extraction fails."""

    pass


class MessageExtractorCore:
    """Core extraction logic for messages."""

    @staticmethod
    def extract_from_archive(
        archive_file: str,
        mbox_offset: int,
        mbox_length: int,
        output_path: str | Path | None = None,
    ) -> bytes:
        """Extract message from archive at specified offset.

        Args:
            archive_file: Path to archive file
            mbox_offset: Byte offset in archive
            mbox_length: Message length in bytes
            output_path: Output file path (None = stdout)

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If extraction fails
        """
        archive_path = Path(archive_file)
        if not archive_path.exists():
            raise ExtractorError(f"Archive file not found: {archive_file}")

        # Detect compression format
        compression = MessageExtractorCore._get_compression_format(archive_path)

        try:
            if compression:
                # Decompress and extract
                message_bytes = MessageExtractorCore._extract_from_compressed(
                    archive_path, compression, mbox_offset, mbox_length
                )
            else:
                # Extract directly from uncompressed mbox
                with open(archive_path, "rb") as f:
                    f.seek(mbox_offset)
                    message_bytes = f.read(mbox_length)

            # Output to file or stdout
            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(message_bytes)
            else:
                # Write to stdout
                sys.stdout.buffer.write(message_bytes)

            return message_bytes

        except Exception as e:
            raise ExtractorError(f"Failed to extract message: {e}") from e

    @staticmethod
    def _extract_from_compressed(
        archive_path: Path, compression: str, offset: int, length: int
    ) -> bytes:
        """Extract message from compressed archive.

        Args:
            archive_path: Path to compressed archive
            compression: Compression format ('gzip', 'lzma', 'zstd')
            offset: Byte offset in decompressed data
            length: Message length in bytes

        Returns:
            Raw message bytes

        Raises:
            ExtractorError: If extraction fails
        """
        try:
            # Open compressed file
            f: IOBase
            if compression == "gzip":
                f = gzip.open(archive_path, "rb")
            elif compression == "lzma":
                f = lzma.open(archive_path, "rb")
            elif compression == "zstd":
                # Python 3.14+ has native zstd support
                try:
                    from compression import zstd

                    f = zstd.open(archive_path, "rb")
                except ImportError:
                    raise ExtractorError(
                        "zstd compression requires Python 3.14+ or 'zstandard' package"
                    )
            else:
                raise ExtractorError(f"Unsupported compression format: {compression}")

            # Seek to offset and read message
            with f:
                f.seek(offset)
                message_bytes = f.read(length)

            return message_bytes

        except Exception as e:
            raise ExtractorError(f"Failed to extract from compressed archive: {e}") from e

    @staticmethod
    def _get_compression_format(archive_path: Path) -> str | None:
        """Detect compression format from file extension.

        Args:
            archive_path: Path to archive file

        Returns:
            Compression format: 'gzip', 'lzma', 'zstd', or None
        """
        suffix = archive_path.suffix.lower()
        if suffix == ".gz":
            return "gzip"
        elif suffix in (".xz", ".lzma"):
            return "lzma"
        elif suffix == ".zst":
            return "zstd"
        return None
