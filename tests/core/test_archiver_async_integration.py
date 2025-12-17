"""Tests for ArchiverFacade integration with GmailClient.

These tests define expected behavior for the async migration Phase 3.
Since the architecture is now async-only, these tests verify GmailClient works.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.archiver import ArchiverFacade

pytestmark = pytest.mark.asyncio


class TestArchiverFacadeWithAsyncClient:
    """Tests for ArchiverFacade using GmailClient."""

    async def test_create_with_async_gmail_client(self) -> None:
        """Test ArchiverFacade can be created with GmailClient."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"

            # Should accept GmailClient
            archiver = await ArchiverFacade.create(async_client, str(db_path))

            assert archiver.gmail_client is async_client
            await archiver.close()

    async def test_list_messages_async(self) -> None:
        """Test list_messages_for_archive works with async client."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        # Create mock async client with mocked list_messages
        async_client = GmailClient(mock_creds)

        # Mock the list_messages async generator
        async def mock_list_messages(query: str, max_results: int = 100):
            yield {"id": "msg1", "threadId": "thread1"}
            yield {"id": "msg2", "threadId": "thread2"}

        async_client.list_messages = mock_list_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            archiver = await ArchiverFacade.create(async_client, str(db_path))

            # Now async-only: use list_messages_for_archive directly
            query, messages = await archiver.list_messages_for_archive("3y")

            assert "before:" in query
            assert len(messages) == 2
            assert messages[0]["id"] == "msg1"

            await archiver.close()

    async def test_delete_archived_messages_async(self) -> None:
        """Test delete_archived_messages works with async client."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        # Mock trash_messages
        async_client.trash_messages = AsyncMock(return_value=2)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            archiver = await ArchiverFacade.create(async_client, str(db_path))

            # Now async-only: use delete_archived_messages directly
            count = await archiver.delete_archived_messages(["msg1", "msg2"], permanent=False)

            assert count == 2
            async_client.trash_messages.assert_called_once_with(["msg1", "msg2"])

            await archiver.close()

    async def test_delete_permanent_async(self) -> None:
        """Test permanent deletion works with async client."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        # Mock delete_messages_permanent
        async_client.delete_messages_permanent = AsyncMock(return_value=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            archiver = await ArchiverFacade.create(async_client, str(db_path))

            # Now async-only: use delete_archived_messages directly
            count = await archiver.delete_archived_messages(
                ["msg1", "msg2", "msg3"], permanent=True
            )

            assert count == 3
            async_client.delete_messages_permanent.assert_called_once_with(["msg1", "msg2", "msg3"])

            await archiver.close()


class TestArchiverFacadeAsyncArchiveWorkflow:
    """Tests for full async archive workflow."""

    async def test_archive_with_async_client(self) -> None:
        """Test full archive workflow with GmailClient."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        # Mock list_messages async generator
        async def mock_list_messages(query: str, max_results: int = 100):
            yield {"id": "msg1", "threadId": "thread1"}
            yield {"id": "msg2", "threadId": "thread2"}

        async_client.list_messages = mock_list_messages

        # Mock get_message for fetching full messages
        async_client.get_message = AsyncMock(
            return_value={
                "id": "msg1",
                "raw": "VGVzdCBtZXNzYWdl",  # base64 "Test message"
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            mbox_path = Path(tmpdir) / "test.mbox"

            archiver = await ArchiverFacade.create(async_client, str(db_path))

            # Full archive workflow should work with async client
            result = await archiver.archive(
                age_threshold="3y",
                output_file=str(mbox_path),
                incremental=True,
                dry_run=True,  # Dry run to avoid needing full mbox write
            )

            assert "found_count" in result
            assert result["found_count"] == 2

            await archiver.close()

    async def test_archive_no_messages_async(self) -> None:
        """Test archive with no matching messages using async client."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        # Mock empty list_messages
        async def mock_list_messages(query: str, max_results: int = 100):
            return
            yield  # noqa: PLE0117 - unreachable but makes it a generator

        async_client.list_messages = mock_list_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"

            archiver = await ArchiverFacade.create(async_client, str(db_path))

            result = await archiver.archive(
                age_threshold="3y",
                output_file="test.mbox",
                dry_run=True,
            )

            assert result["found_count"] == 0
            assert result["archived_count"] == 0

            await archiver.close()


class TestAsyncClientUsage:
    """Tests for async client usage patterns."""

    async def test_gmail_client_is_async_gmail_client(self) -> None:
        """Test facade stores GmailClient correctly."""
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_creds.expired = False

        async_client = GmailClient(mock_creds)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_state.db"
            archiver = await ArchiverFacade.create(async_client, str(db_path))

            # Facade stores the async client
            assert isinstance(archiver.gmail_client, GmailClient)

            await archiver.close()
