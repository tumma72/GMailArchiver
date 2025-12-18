"""Tests for async Gmail client and adaptive rate limiter.

These tests use a FakeGmailClient subclass that overrides I/O at the HTTP
boundary. This approach:
1. Tests actual GmailClient behavior (not mock wiring)
2. Catches interface changes via mypy (subclass must match parent)
3. Avoids brittle patch() calls that break on refactoring
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from google.oauth2.credentials import Credentials

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.connectors.rate_limiter import AdaptiveRateLimiter

# =============================================================================
# Test Double: FakeGmailClient
# =============================================================================


@dataclass
class MockResponse:
    """Lightweight mock HTTP response for testing.

    Matches the httpx.Response interface used by GmailClient.
    """

    status_code: int = 200
    data: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        """Return response data as JSON."""
        return self.data

    def raise_for_status(self) -> None:
        """Raise HTTPStatusError for 4xx/5xx responses."""
        if 400 <= self.status_code < 600:
            request = httpx.Request("GET", "https://test.example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


@dataclass
class RecordedRequest:
    """Record of an HTTP request made by GmailClient."""

    method: str
    url: str
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = None


class FakeGmailClient(GmailClient):
    """Test double for GmailClient that captures HTTP calls.

    This subclass overrides I/O methods to return configured responses
    instead of making real HTTP calls. This approach:

    1. Tests actual GmailClient behavior (not mock wiring)
    2. mypy catches interface mismatches between parent and test double
    3. No fragile patch() paths that break on refactoring

    Usage:
        responses = [MockResponse(data={"messages": [...]})]
        async with FakeGmailClient(creds, responses=responses) as client:
            async for msg in client.list_messages("query"):
                ...
        # Check requests made
        assert client.requests[0].url == "expected_url"
    """

    def __init__(
        self,
        credentials: Credentials,
        responses: list[MockResponse] | None = None,
        batch_size: int = 10,
        max_retries: int = 5,
    ) -> None:
        """Initialize testable client with mock responses.

        Args:
            credentials: Google OAuth2 credentials (can be mock)
            responses: List of MockResponse to return in order
            batch_size: Messages per batch (passed to parent)
            max_retries: Max retries (passed to parent)
        """
        super().__init__(credentials, batch_size=batch_size, max_retries=max_retries)
        self._mock_responses = list(responses) if responses else []
        self.requests: list[RecordedRequest] = []

    async def __aenter__(self) -> FakeGmailClient:
        """Enter context - don't create real HTTP client."""
        # Skip parent's HTTP client creation
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context - nothing to close."""
        pass

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> MockResponse:  # type: ignore[override]
        """Override HTTP I/O to return mock responses.

        This is the single I/O boundary - all HTTP calls go through here.
        By overriding this, we test all other GmailClient logic.
        """
        # Record the request for assertions
        self.requests.append(
            RecordedRequest(
                method=method,
                url=url,
                params=kwargs.get("params"),
                json_body=kwargs.get("json"),
            )
        )

        if not self._mock_responses:
            raise RuntimeError(
                f"No mock responses configured for {method} {url}. "
                f"Requests made: {len(self.requests)}"
            )

        response = self._mock_responses.pop(0)

        # Simulate rate limiter behavior (we want to test this integration)
        await self._rate_limiter.acquire()

        if response.status_code == 200 or response.status_code == 204:
            self._rate_limiter.on_success()
            return response

        if response.status_code == 429:
            self._rate_limiter.on_rate_limit()
            # For 429, retry with next response
            return await self._request_with_retry(method, url, **kwargs)

        response.raise_for_status()
        return response  # Unreachable but makes mypy happy


def mock_credentials() -> MagicMock:
    """Create mock Google OAuth2 credentials for testing."""
    creds = MagicMock(spec=Credentials)
    creds.token = "test_token_12345"
    creds.expired = False
    creds.refresh_token = None
    return creds


# =============================================================================
# AdaptiveRateLimiter Tests
# =============================================================================


class TestAdaptiveRateLimiterInit:
    """Tests for AdaptiveRateLimiter initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default parameters."""
        limiter = AdaptiveRateLimiter()

        assert limiter.max_tokens == 20.0
        assert limiter.refill_rate == 10.0
        assert limiter.min_refill_rate == 1.0
        assert limiter.backoff_factor == 0.5
        assert limiter.recovery_threshold == 10

    def test_init_with_custom_params(self) -> None:
        """Test initialization with custom parameters."""
        limiter = AdaptiveRateLimiter(
            max_tokens=30.0,
            refill_rate=15.0,
            min_refill_rate=2.0,
            backoff_factor=0.3,
            recovery_threshold=5,
        )

        assert limiter.max_tokens == 30.0
        assert limiter.refill_rate == 15.0
        assert limiter.min_refill_rate == 2.0
        assert limiter.backoff_factor == 0.3
        assert limiter.recovery_threshold == 5


class TestAdaptiveRateLimiterAcquire:
    """Tests for AdaptiveRateLimiter.acquire() method."""

    @pytest.mark.asyncio
    async def test_acquire_with_available_tokens(self) -> None:
        """Test acquire returns immediately when tokens available."""
        limiter = AdaptiveRateLimiter(max_tokens=20.0)

        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.1  # Should be near-instant

    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self) -> None:
        """Test acquire decrements available tokens."""
        limiter = AdaptiveRateLimiter(max_tokens=5.0, refill_rate=0.0)

        # Consume all tokens
        for _ in range(5):
            await limiter.acquire()

        assert limiter.tokens <= 0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_no_tokens(self) -> None:
        """Test acquire waits when no tokens available."""
        limiter = AdaptiveRateLimiter(max_tokens=1.0, refill_rate=10.0)

        # Consume the only token
        await limiter.acquire()

        # Next acquire should wait for refill
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        # Should have waited ~0.1 sec for 1 token at 10/sec rate
        assert 0.05 < elapsed < 0.3


class TestAdaptiveRateLimiterOnSuccess:
    """Tests for AdaptiveRateLimiter.on_success() method."""

    def test_on_success_increments_counter(self) -> None:
        """Test on_success increments consecutive success counter."""
        limiter = AdaptiveRateLimiter()
        initial_count = limiter._consecutive_successes

        limiter.on_success()

        assert limiter._consecutive_successes == initial_count + 1

    def test_on_success_increases_rate_after_threshold(self) -> None:
        """Test rate increases after recovery_threshold successes."""
        limiter = AdaptiveRateLimiter(
            refill_rate=10.0,
            recovery_threshold=3,
        )

        # First reduce rate (simulating 429 error)
        limiter.on_rate_limit()
        reduced_rate = limiter.refill_rate
        assert reduced_rate < 10.0

        # Simulate successes to recover
        for _ in range(3):
            limiter.on_success()

        assert limiter.refill_rate > reduced_rate

    def test_on_success_respects_max_rate(self) -> None:
        """Test rate doesn't exceed baseline after recovery."""
        limiter = AdaptiveRateLimiter(
            refill_rate=10.0,
            recovery_threshold=1,
        )
        baseline = limiter.refill_rate

        for _ in range(100):
            limiter.on_success()

        assert limiter.refill_rate <= baseline


class TestAdaptiveRateLimiterOnRateLimit:
    """Tests for AdaptiveRateLimiter.on_rate_limit() method."""

    def test_on_rate_limit_reduces_rate(self) -> None:
        """Test rate is reduced on 429 error."""
        limiter = AdaptiveRateLimiter(refill_rate=10.0, backoff_factor=0.5)
        initial_rate = limiter.refill_rate

        limiter.on_rate_limit()

        assert limiter.refill_rate < initial_rate
        assert limiter.refill_rate == initial_rate * 0.5

    def test_on_rate_limit_respects_minimum(self) -> None:
        """Test rate doesn't go below minimum."""
        limiter = AdaptiveRateLimiter(
            refill_rate=2.0,
            min_refill_rate=1.0,
            backoff_factor=0.5,
        )

        for _ in range(10):
            limiter.on_rate_limit()

        assert limiter.refill_rate >= limiter.min_refill_rate

    def test_on_rate_limit_resets_success_counter(self) -> None:
        """Test success counter resets on rate limit."""
        limiter = AdaptiveRateLimiter()
        limiter.on_success()
        limiter.on_success()

        limiter.on_rate_limit()

        assert limiter._consecutive_successes == 0

    def test_on_rate_limit_returns_retry_after(self) -> None:
        """Test returns provided retry_after value."""
        limiter = AdaptiveRateLimiter()

        wait_time = limiter.on_rate_limit(retry_after=5.0)

        assert wait_time == 5.0

    def test_on_rate_limit_returns_backoff_when_no_retry_after(self) -> None:
        """Test returns exponential backoff when no retry_after."""
        limiter = AdaptiveRateLimiter()

        wait_time = limiter.on_rate_limit(retry_after=None)

        assert wait_time > 0


class TestAdaptiveRateLimiterOnServerError:
    """Tests for AdaptiveRateLimiter.on_server_error() method."""

    def test_on_server_error_does_not_reduce_rate(self) -> None:
        """Test server errors don't reduce rate (transient)."""
        limiter = AdaptiveRateLimiter(refill_rate=10.0)
        initial_rate = limiter.refill_rate

        limiter.on_server_error()

        assert limiter.refill_rate == initial_rate

    def test_on_server_error_returns_backoff(self) -> None:
        """Test returns backoff time for server errors."""
        limiter = AdaptiveRateLimiter()

        wait_time = limiter.on_server_error()

        assert wait_time > 0


# =============================================================================
# GmailClient Tests (using FakeGmailClient)
# =============================================================================


class TestGmailClientInit:
    """Tests for GmailClient initialization."""

    def test_init_stores_credentials(self) -> None:
        """Test initialization stores credentials."""
        creds = mock_credentials()
        client = GmailClient(creds)

        assert client._credentials is creds
        assert client.batch_size == 10  # default
        assert client.max_retries == 5  # default

    def test_init_with_custom_params(self) -> None:
        """Test initialization with custom batch_size and max_retries."""
        creds = mock_credentials()
        client = GmailClient(creds, batch_size=50, max_retries=3)

        assert client.batch_size == 50
        assert client.max_retries == 3

    def test_init_creates_rate_limiter(self) -> None:
        """Test initialization creates adaptive rate limiter."""
        creds = mock_credentials()
        client = GmailClient(creds)

        assert isinstance(client._rate_limiter, AdaptiveRateLimiter)


class TestGmailClientListMessages:
    """Tests for GmailClient.list_messages() method."""

    @pytest.mark.asyncio
    async def test_list_messages_yields_all_messages(self) -> None:
        """Test list_messages yields all messages from response."""
        responses = [
            MockResponse(data={"messages": [{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}]})
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            messages = [msg async for msg in client.list_messages("before:2022/01/01")]

        assert len(messages) == 3
        assert messages[0]["id"] == "msg1"
        assert messages[1]["id"] == "msg2"
        assert messages[2]["id"] == "msg3"

    @pytest.mark.asyncio
    async def test_list_messages_handles_pagination(self) -> None:
        """Test list_messages follows nextPageToken across pages."""
        responses = [
            MockResponse(data={"messages": [{"id": "msg1"}], "nextPageToken": "page2_token"}),
            MockResponse(data={"messages": [{"id": "msg2"}], "nextPageToken": "page3_token"}),
            MockResponse(data={"messages": [{"id": "msg3"}]}),
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            messages = [msg async for msg in client.list_messages("before:2022/01/01")]

        assert len(messages) == 3
        assert [m["id"] for m in messages] == ["msg1", "msg2", "msg3"]

        # Verify pagination tokens were used
        assert client.requests[1].params["pageToken"] == "page2_token"
        assert client.requests[2].params["pageToken"] == "page3_token"

    @pytest.mark.asyncio
    async def test_list_messages_handles_empty_response(self) -> None:
        """Test list_messages handles no matching messages."""
        responses = [MockResponse(data={})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            messages = [msg async for msg in client.list_messages("label:nonexistent")]

        assert messages == []

    @pytest.mark.asyncio
    async def test_list_messages_builds_correct_url(self) -> None:
        """Test list_messages calls correct Gmail API endpoint."""
        responses = [MockResponse(data={"messages": []})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            _ = [msg async for msg in client.list_messages("before:2022/01/01")]

        assert len(client.requests) == 1
        assert "/users/me/messages" in client.requests[0].url
        assert client.requests[0].params["q"] == "before:2022/01/01"


class TestGmailClientGetMessage:
    """Tests for GmailClient.get_message() method."""

    @pytest.mark.asyncio
    async def test_get_message_returns_message_data(self) -> None:
        """Test get_message returns full message dictionary."""
        responses = [
            MockResponse(
                data={
                    "id": "msg123",
                    "raw": "VGVzdCBtZXNzYWdl",
                    "threadId": "thread456",
                }
            )
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            msg = await client.get_message("msg123")

        assert msg["id"] == "msg123"
        assert msg["raw"] == "VGVzdCBtZXNzYWdl"
        assert msg["threadId"] == "thread456"

    @pytest.mark.asyncio
    async def test_get_message_uses_raw_format_by_default(self) -> None:
        """Test get_message defaults to raw format."""
        responses = [MockResponse(data={"id": "msg1", "raw": "data"})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.get_message("msg1")

        assert client.requests[0].params["format"] == "raw"

    @pytest.mark.asyncio
    async def test_get_message_accepts_format_parameter(self) -> None:
        """Test get_message accepts custom format parameter."""
        responses = [MockResponse(data={"id": "msg1"})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.get_message("msg1", format="metadata")

        assert client.requests[0].params["format"] == "metadata"


class TestGmailClientGetMessagesBatch:
    """Tests for GmailClient.get_messages_batch() method."""

    @pytest.mark.asyncio
    async def test_get_messages_batch_yields_all_messages(self) -> None:
        """Test batch fetch yields all requested messages."""
        responses = [
            MockResponse(data={"id": "msg1", "raw": "data1"}),
            MockResponse(data={"id": "msg2", "raw": "data2"}),
            MockResponse(data={"id": "msg3", "raw": "data3"}),
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            messages = [msg async for msg in client.get_messages_batch(["msg1", "msg2", "msg3"])]

        assert len(messages) == 3
        assert [m["id"] for m in messages] == ["msg1", "msg2", "msg3"]

    @pytest.mark.asyncio
    async def test_get_messages_batch_respects_batch_size(self) -> None:
        """Test batch fetch respects configured batch_size."""
        # With batch_size=2, should process in chunks of 2
        responses = [MockResponse(data={"id": f"msg{i}", "raw": f"data{i}"}) for i in range(5)]

        async with FakeGmailClient(mock_credentials(), responses, batch_size=2) as client:
            messages = [
                msg
                async for msg in client.get_messages_batch(["msg0", "msg1", "msg2", "msg3", "msg4"])
            ]

        assert len(messages) == 5


class TestGmailClientDecodeMessage:
    """Tests for GmailClient.decode_message_raw() method."""

    def test_decode_message_raw_decodes_base64(self) -> None:
        """Test decode_message_raw decodes URL-safe base64."""
        client = GmailClient(mock_credentials())
        # "Hello, World!" in URL-safe base64
        message = {"raw": "SGVsbG8sIFdvcmxkIQ=="}

        decoded = client.decode_message_raw(message)

        assert decoded == b"Hello, World!"

    def test_decode_message_raw_raises_on_missing_raw(self) -> None:
        """Test decode_message_raw raises ValueError if no raw field."""
        client = GmailClient(mock_credentials())
        message = {"id": "msg1"}  # No 'raw' field

        with pytest.raises(ValueError, match="does not contain 'raw' field"):
            client.decode_message_raw(message)


class TestGmailClientTrashMessages:
    """Tests for GmailClient.trash_messages() method."""

    @pytest.mark.asyncio
    async def test_trash_messages_returns_count(self) -> None:
        """Test trash_messages returns count of trashed messages."""
        responses = [
            MockResponse(status_code=200),
            MockResponse(status_code=200),
            MockResponse(status_code=200),
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            count = await client.trash_messages(["msg1", "msg2", "msg3"])

        assert count == 3

    @pytest.mark.asyncio
    async def test_trash_messages_calls_correct_endpoint(self) -> None:
        """Test trash_messages calls POST to /messages/{id}/trash."""
        responses = [MockResponse(status_code=200)]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.trash_messages(["msg123"])

        assert len(client.requests) == 1
        assert client.requests[0].method == "POST"
        assert "/messages/msg123/trash" in client.requests[0].url


class TestGmailClientDeleteMessagesPermanent:
    """Tests for GmailClient.delete_messages_permanent() method."""

    @pytest.mark.asyncio
    async def test_delete_permanent_returns_count(self) -> None:
        """Test delete_messages_permanent returns count of deleted messages."""
        responses = [MockResponse(status_code=204)]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            count = await client.delete_messages_permanent(["msg1", "msg2"])

        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_permanent_uses_batch_delete_endpoint(self) -> None:
        """Test delete_permanent calls batchDelete endpoint."""
        responses = [MockResponse(status_code=204)]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.delete_messages_permanent(["msg1", "msg2"])

        assert len(client.requests) == 1
        assert client.requests[0].method == "POST"
        assert "/messages/batchDelete" in client.requests[0].url
        assert client.requests[0].json_body == {"ids": ["msg1", "msg2"]}


class TestGmailClientSearchByRfcMessageId:
    """Tests for GmailClient.search_by_rfc_message_id() method."""

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_found(self) -> None:
        """Test search returns Gmail ID when message found."""
        responses = [MockResponse(data={"messages": [{"id": "gmail123"}]})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            gmail_id = await client.search_by_rfc_message_id("<test@example.com>")

        assert gmail_id == "gmail123"

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_not_found(self) -> None:
        """Test search returns None when message not found."""
        responses = [MockResponse(data={})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            gmail_id = await client.search_by_rfc_message_id("<missing@example.com>")

        assert gmail_id is None

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_strips_brackets(self) -> None:
        """Test search strips angle brackets from Message-ID."""
        responses = [MockResponse(data={"messages": [{"id": "gmail123"}]})]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.search_by_rfc_message_id("<test@example.com>")

        # Query should use rfc822msgid: without brackets
        assert "rfc822msgid:test@example.com" in client.requests[0].params["q"]

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_handles_empty(self) -> None:
        """Test search returns None for empty Message-ID."""
        async with FakeGmailClient(mock_credentials(), []) as client:
            gmail_id = await client.search_by_rfc_message_id("")

        assert gmail_id is None
        assert len(client.requests) == 0  # Should not make request


# =============================================================================
# GmailClient.create() Factory Method Tests
# =============================================================================


class TestGmailClientCreate:
    """Tests for GmailClient.create() factory method.

    These tests verify that the factory method correctly:
    1. Creates a GmailAuthenticator instance
    2. Calls authenticate_async() to get credentials
    3. Creates a GmailClient with those credentials
    4. Calls connect() to initialize the HTTP client
    5. Returns a usable client as an async context manager
    """

    @pytest.mark.asyncio
    async def test_create_returns_authenticated_client(self) -> None:
        """Test factory creates working client with authentication."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            client = await GmailClient.create()
            try:
                # Verify client was created with credentials
                assert client is not None
                assert client._credentials == mock_creds
                # Verify authentication was called
                mock_auth.authenticate_async.assert_called_once()
                # Verify HTTP client was initialized
                assert client._http_client is not None
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_create_uses_default_credentials(self) -> None:
        """Test factory uses bundled credentials when none specified."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            await GmailClient.create()

            # Verify authenticator was created with default parameters
            mock_auth_cls.assert_called_once()
            call_kwargs = mock_auth_cls.call_args[1]
            assert "credentials_file" not in call_kwargs or call_kwargs["credentials_file"] is None

    @pytest.mark.asyncio
    async def test_create_with_custom_credentials_file(self) -> None:
        """Test factory passes credentials_file to authenticator."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()
        custom_file = "/path/to/custom_oauth.json"

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            client = await GmailClient.create(credentials_file=custom_file)
            try:
                # Verify authenticator was created with custom credentials file
                mock_auth_cls.assert_called_once()
                call_kwargs = mock_auth_cls.call_args[1]
                assert call_kwargs["credentials_file"] == custom_file
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_create_propagates_auth_failure(self) -> None:
        """Test factory propagates authentication errors."""
        from unittest.mock import AsyncMock, patch

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(
                side_effect=FileNotFoundError("Credentials not found")
            )

            with pytest.raises(FileNotFoundError, match="Credentials not found"):
                await GmailClient.create()

    @pytest.mark.asyncio
    async def test_create_client_is_connected(self) -> None:
        """Test factory returns client with initialized HTTP client."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            client = await GmailClient.create()
            try:
                # Verify HTTP client is initialized (connect() was called)
                assert client._http_client is not None
                # Verify refresh lock is initialized
                assert client._refresh_lock is not None
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_create_with_custom_batch_size(self) -> None:
        """Test factory respects custom batch_size parameter."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            client = await GmailClient.create(batch_size=50)
            try:
                # Verify custom batch size was set
                assert client.batch_size == 50
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_create_client_usable_as_context_manager(self) -> None:
        """Test factory returns client usable with async with."""
        from unittest.mock import AsyncMock, patch

        mock_creds = mock_credentials()

        with patch("gmailarchiver.connectors.auth.GmailAuthenticator") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.authenticate_async = AsyncMock(return_value=mock_creds)

            # Create and use as context manager
            client = await GmailClient.create()

            # Should support async context manager protocol
            assert hasattr(client, "__aenter__")
            assert hasattr(client, "__aexit__")

            # Verify we can enter/exit context (idempotent since already connected)
            async with client:
                assert client._http_client is not None


# =============================================================================
# Additional Coverage Tests for Missing Lines
# =============================================================================


class TestGmailClientGetHeaders:
    """Tests for GmailClient._get_headers() method (line 172)."""

    def test_get_headers_returns_authorization_header(self) -> None:
        """Test _get_headers returns Authorization header with token."""
        creds = mock_credentials()
        creds.token = "test_token_abc123"
        client = GmailClient(creds)

        headers = client._get_headers()

        assert headers["Authorization"] == "Bearer test_token_abc123"
        assert headers["Content-Type"] == "application/json"


class TestGmailClientEnsureValidToken:
    """Tests for GmailClient._ensure_valid_token() method (lines 187-200)."""

    @pytest.mark.asyncio
    async def test_ensure_valid_token_returns_immediately_if_not_expired(self) -> None:
        """Test _ensure_valid_token returns immediately when token is valid."""
        creds = mock_credentials()
        creds.expired = False
        client = GmailClient(creds)

        # Should complete without blocking (no refresh needed)
        await client._ensure_valid_token()

        # Token should still be the same
        assert creds.token == "test_token_12345"

    @pytest.mark.asyncio
    async def test_ensure_valid_token_returns_if_no_refresh_token(self) -> None:
        """Test _ensure_valid_token returns immediately if no refresh_token available."""
        creds = mock_credentials()
        creds.expired = True
        creds.refresh_token = None

        client = GmailClient(creds)

        # Should complete without attempting refresh
        await client._ensure_valid_token()

        # Should not raise error despite expired token
        assert creds.expired is True

    @pytest.mark.asyncio
    async def test_ensure_valid_token_initializes_lock_if_missing(self) -> None:
        """Test _ensure_valid_token creates lock if not initialized (line 193-195)."""
        from unittest.mock import patch

        creds = mock_credentials()
        creds.expired = True
        creds.refresh_token = "refresh_token_value"

        client = GmailClient(creds)
        # Simulate lock not being initialized (connect() not called)
        client._refresh_lock = None

        with patch.object(client, "_refresh_token_sync", new_callable=MagicMock) as mock_refresh:
            await client._ensure_valid_token()

            # Lock should have been created (line 195)
            assert client._refresh_lock is not None

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refreshes_expired_token(self) -> None:
        """Test _ensure_valid_token refreshes expired token with refresh_token."""
        from unittest.mock import patch

        creds = mock_credentials()
        creds.expired = True
        creds.refresh_token = "refresh_token_value"

        client = GmailClient(creds)
        client._refresh_lock = asyncio.Lock()

        with patch.object(client, "_refresh_token_sync", new_callable=MagicMock) as mock_refresh:
            await client._ensure_valid_token()

            # Should have called refresh (line 200)
            mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_avoids_concurrent_refresh(self) -> None:
        """Test _ensure_valid_token prevents concurrent refresh attempts."""
        from unittest.mock import patch

        creds = mock_credentials()
        creds.expired = True
        creds.refresh_token = "refresh_token_value"

        client = GmailClient(creds)
        await client.connect()

        refresh_call_count = 0

        def sync_refresh():
            """Simulate slow refresh that marks token as not expired."""
            nonlocal refresh_call_count
            refresh_call_count += 1
            import time

            time.sleep(0.05)
            creds.expired = False

        with patch.object(client, "_refresh_token_sync", side_effect=sync_refresh):
            # Launch two concurrent refresh attempts
            task1 = asyncio.create_task(client._ensure_valid_token())
            task2 = asyncio.create_task(client._ensure_valid_token())

            await asyncio.gather(task1, task2)

            # Only one refresh should have happened (lock prevents concurrent)
            assert refresh_call_count == 1


class TestGmailClientRefreshTokenSync:
    """Tests for GmailClient._refresh_token_sync() method (lines 207-209)."""

    def test_refresh_token_sync_calls_credentials_refresh(self) -> None:
        """Test _refresh_token_sync calls credentials.refresh() with Request."""
        from unittest.mock import MagicMock, patch

        creds = mock_credentials()
        creds.refresh = MagicMock()

        client = GmailClient(creds)

        with patch("google.auth.transport.requests.Request") as mock_request_cls:
            mock_request = MagicMock()
            mock_request_cls.return_value = mock_request

            client._refresh_token_sync()

            # Should have created Request and called refresh
            mock_request_cls.assert_called_once()
            creds.refresh.assert_called_once_with(mock_request)


class TestGmailClientRequestWithRetry:
    """Tests for GmailClient._request_with_retry() error handling (lines 230-282)."""

    @pytest.mark.asyncio
    async def test_request_with_retry_raises_if_client_not_initialized(self) -> None:
        """Test _request_with_retry raises if HTTP client not initialized (line 230-231)."""
        creds = mock_credentials()
        client = GmailClient(creds)
        # Don't call connect() - leave _http_client as None

        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client._request_with_retry("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_request_with_retry_handles_429_rate_limit(self) -> None:
        """Test _request_with_retry handles 429 rate limit with retry (lines 251-259)."""
        from unittest.mock import AsyncMock, MagicMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=3)
        await client.connect()

        # First request returns 429, second succeeds
        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: rate limited
                response = MagicMock()
                response.status_code = 429
                response.headers = {"Retry-After": "0.01"}
                return response
            else:
                # Second call: success
                response = MagicMock()
                response.status_code = 200
                response.json.return_value = {"success": True}
                return response

        client._http_client.request = AsyncMock(side_effect=mock_request)

        result = await client._request_with_retry("GET", "https://example.com")

        assert result.status_code == 200
        assert call_count == 2  # Should have retried

    @pytest.mark.asyncio
    async def test_request_with_retry_handles_500_server_error(self) -> None:
        """Test _request_with_retry handles 500 server error with retry (lines 261-268)."""
        from unittest.mock import AsyncMock, MagicMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=3)
        await client.connect()

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: server error
                response = MagicMock()
                response.status_code = 503
                return response
            else:
                # Second call: success
                response = MagicMock()
                response.status_code = 200
                response.json.return_value = {"success": True}
                return response

        client._http_client.request = AsyncMock(side_effect=mock_request)

        result = await client._request_with_retry("GET", "https://example.com")

        assert result.status_code == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_request_with_retry_raises_for_4xx_errors(self) -> None:
        """Test _request_with_retry raises for 4xx errors without retry (line 271)."""
        from unittest.mock import AsyncMock, MagicMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=3)
        await client.connect()

        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.status_code = 404
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(404, request=httpx.Request("GET", "https://example.com")),
            )
            return response

        client._http_client.request = AsyncMock(side_effect=mock_request)

        with pytest.raises(httpx.HTTPStatusError):
            await client._request_with_retry("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_request_with_retry_handles_timeout(self) -> None:
        """Test _request_with_retry handles timeout with retry (lines 273-279)."""
        from unittest.mock import AsyncMock, MagicMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=3)
        await client.connect()

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: timeout
                raise httpx.TimeoutException("Request timeout")
            else:
                # Second call: success
                response = MagicMock()
                response.status_code = 200
                response.json.return_value = {"success": True}
                return response

        client._http_client.request = AsyncMock(side_effect=mock_request)

        result = await client._request_with_retry("GET", "https://example.com")

        assert result.status_code == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_request_with_retry_raises_timeout_after_all_retries(self) -> None:
        """Test _request_with_retry raises timeout after max retries exhausted."""
        from unittest.mock import AsyncMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=2)
        await client.connect()

        # All requests timeout
        client._http_client.request = AsyncMock(
            side_effect=httpx.TimeoutException("Request timeout")
        )

        with pytest.raises(httpx.TimeoutException):
            await client._request_with_retry("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_request_with_retry_raises_after_all_retries_exhausted(self) -> None:
        """Test _request_with_retry raises RuntimeError after max retries (line 282)."""
        from unittest.mock import AsyncMock, MagicMock

        creds = mock_credentials()
        creds.expired = False

        client = GmailClient(creds, max_retries=2)
        await client.connect()

        # All requests return 503
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.status_code = 503
            return response

        client._http_client.request = AsyncMock(side_effect=mock_request)

        with pytest.raises(RuntimeError, match="Failed after 2 retries"):
            await client._request_with_retry("GET", "https://example.com")


class TestGmailClientGetMessagesBatchErrorHandling:
    """Tests for GmailClient.get_messages_batch() exception handling (lines 364-366)."""

    @pytest.mark.asyncio
    async def test_get_messages_batch_continues_on_fetch_failure(self) -> None:
        """Test batch fetch continues when individual message fetch fails."""
        responses = [
            MockResponse(data={"id": "msg1", "raw": "data1"}),
            # msg2 will fail (no response)
            MockResponse(data={"id": "msg3", "raw": "data3"}),
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            # Override to simulate failure for msg2
            original_get = client.get_message

            async def get_with_failure(msg_id: str, format: str = "raw"):
                if msg_id == "msg2":
                    raise Exception("Network error fetching msg2")
                return await original_get(msg_id, format)

            client.get_message = get_with_failure

            messages = [msg async for msg in client.get_messages_batch(["msg1", "msg2", "msg3"])]

        # Should get msg1 and msg3, skip msg2
        assert len(messages) == 2
        assert messages[0]["id"] == "msg1"
        assert messages[1]["id"] == "msg3"


class TestGmailClientTrashMessagesErrorHandling:
    """Tests for GmailClient.trash_messages() exception handling (lines 401-402)."""

    @pytest.mark.asyncio
    async def test_trash_messages_continues_on_individual_failure(self) -> None:
        """Test trash_messages continues when individual message trash fails."""
        responses = [
            MockResponse(status_code=200),  # msg1 succeeds
            # msg2 will fail (no response)
            MockResponse(status_code=200),  # msg3 succeeds
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            # Override to simulate failure for msg2
            original_request = client._request_with_retry

            async def request_with_failure(method: str, url: str, **kwargs):
                if "msg2" in url:
                    raise Exception("Network error trashing msg2")
                return await original_request(method, url, **kwargs)

            client._request_with_retry = request_with_failure

            count = await client.trash_messages(["msg1", "msg2", "msg3"])

        # Should have trashed 2 out of 3
        assert count == 2


class TestGmailClientDeleteMessagesErrorHandling:
    """Tests for GmailClient.delete_messages_permanent() exception handling (lines 426-427)."""

    @pytest.mark.asyncio
    async def test_delete_permanent_continues_on_batch_failure(self) -> None:
        """Test delete_permanent continues when batch delete fails."""
        # Note: delete_permanent uses chunk_list with size 1000, so we need 1001+ messages
        # to create multiple batches. For testing, we'll just verify exception handling
        # by having the single batch fail
        responses = []

        async with FakeGmailClient(mock_credentials(), responses) as client:
            # Override to simulate failure
            async def request_with_failure(method: str, url: str, **kwargs):
                raise Exception("Network error on batch delete")

            client._request_with_retry = request_with_failure

            # Try to delete messages (single batch will fail)
            count = await client.delete_messages_permanent(["msg1", "msg2"])

        # Should have caught exception and returned 0
        assert count == 0


class TestGmailClientSearchByRfcMessageId404:
    """Tests for GmailClient.search_by_rfc_message_id() 404 handling (lines 458-461)."""

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_returns_none_on_404(self) -> None:
        """Test search returns None on 404 error."""
        async with FakeGmailClient(mock_credentials(), []) as client:
            # Override to raise 404
            async def request_with_404(*args, **kwargs):
                raise httpx.HTTPStatusError(
                    "404 Not Found",
                    request=httpx.Request("GET", "https://example.com"),
                    response=httpx.Response(
                        404, request=httpx.Request("GET", "https://example.com")
                    ),
                )

            client._request_with_retry = request_with_404

            result = await client.search_by_rfc_message_id("<test@example.com>")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_by_rfc_message_id_raises_on_other_http_errors(self) -> None:
        """Test search raises HTTPStatusError for non-404 errors."""
        async with FakeGmailClient(mock_credentials(), []) as client:
            # Override to raise 500
            async def request_with_500(*args, **kwargs):
                raise httpx.HTTPStatusError(
                    "500 Server Error",
                    request=httpx.Request("GET", "https://example.com"),
                    response=httpx.Response(
                        500, request=httpx.Request("GET", "https://example.com")
                    ),
                )

            client._request_with_retry = request_with_500

            with pytest.raises(httpx.HTTPStatusError):
                await client.search_by_rfc_message_id("<test@example.com>")


class TestGmailClientSearchByRfcMessageIdsBatch:
    """Tests for GmailClient.search_by_rfc_message_ids_batch() (lines 479-491)."""

    @pytest.mark.asyncio
    async def test_search_batch_returns_mapping(self) -> None:
        """Test batch search returns dict mapping RFC IDs to Gmail IDs."""
        responses = [
            MockResponse(data={"messages": [{"id": "gmail1"}]}),
            MockResponse(data={"messages": [{"id": "gmail2"}]}),
            MockResponse(data={}),  # Third message not found
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            result = await client.search_by_rfc_message_ids_batch(
                ["<msg1@example.com>", "<msg2@example.com>", "<msg3@example.com>"]
            )

        assert result == {
            "<msg1@example.com>": "gmail1",
            "<msg2@example.com>": "gmail2",
            "<msg3@example.com>": None,
        }

    @pytest.mark.asyncio
    async def test_search_batch_calls_progress_callback(self) -> None:
        """Test batch search calls progress callback after each message (line 488-489)."""
        responses = [
            MockResponse(data={"messages": [{"id": "gmail1"}]}),
            MockResponse(data={"messages": [{"id": "gmail2"}]}),
        ]

        progress_calls = []

        def progress_callback(processed: int, total: int) -> None:
            progress_calls.append((processed, total))

        async with FakeGmailClient(mock_credentials(), responses) as client:
            await client.search_by_rfc_message_ids_batch(
                ["<msg1@example.com>", "<msg2@example.com>"],
                progress_callback=progress_callback,
            )

        # Should have been called twice (once per message)
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2)
        assert progress_calls[1] == (2, 2)

    @pytest.mark.asyncio
    async def test_search_batch_respects_batch_size(self) -> None:
        """Test batch search chunks requests by batch_size."""
        # 5 messages with batch_size=2 should make 5 individual searches
        # (batch_size only affects chunking, not the number of API calls)
        responses = [MockResponse(data={"messages": [{"id": f"gmail{i}"}]}) for i in range(5)]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            result = await client.search_by_rfc_message_ids_batch(
                [f"<msg{i}@example.com>" for i in range(5)],
                batch_size=2,
            )

        assert len(result) == 5
        assert all(result[f"<msg{i}@example.com>"] == f"gmail{i}" for i in range(5))

    @pytest.mark.asyncio
    async def test_search_batch_without_progress_callback(self) -> None:
        """Test batch search works without progress callback (line 488 condition)."""
        responses = [
            MockResponse(data={"messages": [{"id": "gmail1"}]}),
        ]

        async with FakeGmailClient(mock_credentials(), responses) as client:
            result = await client.search_by_rfc_message_ids_batch(
                ["<msg1@example.com>"],
                progress_callback=None,
            )

        assert result == {"<msg1@example.com>": "gmail1"}
