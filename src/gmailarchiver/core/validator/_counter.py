"""Message counting for mbox archives.

Provides message counting and basic validation logic.
"""

import mailbox
from pathlib import Path


class MessageCounter:
    """Counts messages in mbox archives."""

    def count_messages(self, mbox_path: Path) -> int:
        """Count messages in an mbox file.

        Args:
            mbox_path: Path to uncompressed mbox file

        Returns:
            Number of messages in the archive

        Raises:
            Exception: If mbox cannot be read
        """
        mbox = mailbox.mbox(str(mbox_path))
        try:
            return len(mbox)
        finally:
            mbox.close()

    def validate_count(self, mbox_path: Path, expected_count: int) -> tuple[bool, str]:
        """Validate message count against expected.

        Args:
            mbox_path: Path to uncompressed mbox file
            expected_count: Expected number of messages

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            actual_count = self.count_messages(mbox_path)
            if actual_count == expected_count:
                return (True, "")
            msg = f"Count mismatch: {actual_count} in archive vs {expected_count} expected"
            return (False, msg)
        except Exception as e:
            return (False, f"Count validation failed: {e}")

    def validate_not_empty(self, mbox_path: Path) -> tuple[bool, str]:
        """Validate that archive is not empty.

        Args:
            mbox_path: Path to uncompressed mbox file

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            count = self.count_messages(mbox_path)
            if count == 0:
                return (False, "Archive is empty")
            return (True, "")
        except Exception as e:
            return (False, f"Archive validation failed: {e}")

    def check_readability(self, mbox_path: Path) -> tuple[bool, str]:
        """Check if messages in archive are readable.

        Args:
            mbox_path: Path to uncompressed mbox file

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            mbox = mailbox.mbox(str(mbox_path))
            try:
                message_count = 0
                for _ in mbox:
                    message_count += 1

                if message_count > 0:
                    return (True, "")
                return (False, "Archive contains no readable messages")
            finally:
                mbox.close()
        except Exception as e:
            return (False, f"Integrity check failed: {e}")
