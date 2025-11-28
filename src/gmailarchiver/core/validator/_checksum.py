"""Checksum computation for mbox messages.

Provides SHA256 checksum computation for integrity validation.
"""

import hashlib


class ChecksumValidator:
    """Computes and validates checksums for mbox messages."""

    def compute_checksum(self, data: bytes) -> str:
        """Compute SHA256 checksum of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal digest string
        """
        return hashlib.sha256(data).hexdigest()
