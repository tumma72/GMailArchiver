"""Unit tests for importer GmailLookup module.

Tests Gmail API lookups for real Gmail IDs during import.
All tests use mocks - no actual API calls.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from gmailarchiver.core.importer._gmail_lookup import GmailLookup, LookupResult


@pytest.mark.unit
class TestGmailLookupInit:
    """Tests for GmailLookup initialization."""

    def test_init_with_client(self) -> None:
        """Test initialization with Gmail client."""
        mock_client = Mock()
        lookup = GmailLookup(mock_client)
        assert lookup.client == mock_client

    def test_init_without_client(self) -> None:
        """Test initialization without Gmail client."""
        lookup = GmailLookup(None)
        assert lookup.client is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestGmailLookupLookupGmailId:
    """Tests for Gmail ID lookup."""

    async def test_lookup_gmail_id_found(self) -> None:
        """Test looking up Gmail ID when message exists."""
        mock_client = Mock()
        mock_client.search_by_rfc_message_id = AsyncMock(return_value="gmail123")

        lookup = GmailLookup(mock_client)
        result = await lookup.lookup_gmail_id("<test@example.com>")

        assert isinstance(result, LookupResult)
        assert result.gmail_id == "gmail123"
        assert result.found is True
        assert result.error is None
        mock_client.search_by_rfc_message_id.assert_called_once_with("<test@example.com>")

    async def test_lookup_gmail_id_not_found(self) -> None:
        """Test looking up Gmail ID when message doesn't exist."""
        mock_client = Mock()
        mock_client.search_by_rfc_message_id = AsyncMock(return_value=None)

        lookup = GmailLookup(mock_client)
        result = await lookup.lookup_gmail_id("<deleted@example.com>")

        assert result.gmail_id is None
        assert result.found is False
        assert result.error is None

    async def test_lookup_gmail_id_no_client(self) -> None:
        """Test lookup when no Gmail client is configured."""
        lookup = GmailLookup(None)
        result = await lookup.lookup_gmail_id("<test@example.com>")

        assert result.gmail_id is None
        assert result.found is False
        assert result.error is None

    async def test_lookup_gmail_id_api_error(self) -> None:
        """Test lookup when API raises exception."""
        mock_client = Mock()
        mock_client.search_by_rfc_message_id = AsyncMock(side_effect=Exception("API rate limit"))

        lookup = GmailLookup(mock_client)
        result = await lookup.lookup_gmail_id("<test@example.com>")

        assert result.gmail_id is None
        assert result.found is False
        assert result.error == "API rate limit"


@pytest.mark.unit
class TestGmailLookupIsEnabled:
    """Tests for checking if Gmail lookup is enabled."""

    def test_is_enabled_with_client(self) -> None:
        """Test is_enabled returns True when client is configured."""
        mock_client = Mock()
        lookup = GmailLookup(mock_client)
        assert lookup.is_enabled() is True

    def test_is_enabled_without_client(self) -> None:
        """Test is_enabled returns False when no client."""
        lookup = GmailLookup(None)
        assert lookup.is_enabled() is False


@pytest.mark.unit
class TestLookupResult:
    """Tests for LookupResult dataclass."""

    def test_lookup_result_found(self) -> None:
        """Test creating successful lookup result."""
        result = LookupResult(gmail_id="gmail123", found=True, error=None)
        assert result.gmail_id == "gmail123"
        assert result.found is True
        assert result.error is None

    def test_lookup_result_not_found(self) -> None:
        """Test creating not-found lookup result."""
        result = LookupResult(gmail_id=None, found=False, error=None)
        assert result.gmail_id is None
        assert result.found is False
        assert result.error is None

    def test_lookup_result_error(self) -> None:
        """Test creating error lookup result."""
        result = LookupResult(gmail_id=None, found=False, error="Connection timeout")
        assert result.gmail_id is None
        assert result.found is False
        assert result.error == "Connection timeout"
