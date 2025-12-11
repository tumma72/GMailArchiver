"""Message location lookup for extraction."""

from typing import TypedDict

from gmailarchiver.data.db_manager import DBManager


class MessageLocation(TypedDict):
    """Message location information."""

    archive_file: str
    mbox_offset: int
    mbox_length: int


class MessageLocator:
    """Locate messages in archives using database."""

    def __init__(self, db: DBManager) -> None:
        """Initialize locator with database manager.

        Args:
            db: Database manager instance
        """
        self.db = db

    async def locate_by_gmail_id(self, gmail_id: str) -> MessageLocation | None:
        """Locate message by Gmail ID.

        Args:
            gmail_id: Gmail message ID

        Returns:
            MessageLocation or None if not found
        """
        result = await self.db.get_message_location_by_gmail_id(gmail_id)
        if not result:
            return None

        archive_file, mbox_offset, mbox_length = result
        return MessageLocation(
            archive_file=archive_file,
            mbox_offset=mbox_offset,
            mbox_length=mbox_length,
        )

    async def locate_by_rfc_message_id(self, rfc_message_id: str) -> MessageLocation | None:
        """Locate message by RFC 2822 Message-ID.

        Args:
            rfc_message_id: RFC 2822 Message-ID header value

        Returns:
            MessageLocation or None if not found
        """
        message = await self.db.get_message_by_rfc_message_id(rfc_message_id)
        if not message:
            return None

        return MessageLocation(
            archive_file=message["archive_file"],
            mbox_offset=message["mbox_offset"],
            mbox_length=message["mbox_length"],
        )
