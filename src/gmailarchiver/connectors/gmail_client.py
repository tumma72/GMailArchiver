"""Async Gmail API client with HTTP/2 and adaptive rate limiting.

This module provides an async-native Gmail client using httpx for HTTP/2 support
and AdaptiveRateLimiter for intelligent rate limiting.
"""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

import httpx
from google.oauth2.credentials import Credentials

if TYPE_CHECKING:
    from gmailarchiver.connectors.auth import GmailAuthenticator

from gmailarchiver.connectors.rate_limiter import AdaptiveRateLimiter
from gmailarchiver.shared.input_validator import validate_gmail_query
from gmailarchiver.shared.utils import chunk_list

logger = logging.getLogger(__name__)

# Gmail API base URL
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailClient:
    """Async Gmail API client with HTTP/2 and adaptive rate limiting.

    Uses httpx for HTTP/2 multiplexing and AdaptiveRateLimiter for
    intelligent rate limiting that adapts to API responses.

    Example:
        >>> async with GmailClient(credentials) as client:
        ...     async for msg in client.list_messages("before:2022/01/01"):
        ...         print(msg["id"])
    """

    def __init__(
        self,
        credentials: Credentials,
        batch_size: int = 10,
        max_retries: int = 5,
    ) -> None:
        """Initialize async Gmail client.

        Args:
            credentials: Google OAuth2 credentials
            batch_size: Messages per batch (default: 10, max: 100)
            max_retries: Maximum retries for failed requests (default: 5)
        """
        self._credentials = credentials
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.user_id = "me"

        # Will be initialized in connect() or __aenter__
        self._http_client: httpx.AsyncClient | None = None
        self._rate_limiter = AdaptiveRateLimiter()

        # Lock for thread-safe token refresh (prevents concurrent refresh attempts)
        self._refresh_lock: asyncio.Lock | None = None

        # Optional authenticator (set by create() factory method)
        self._authenticator: GmailAuthenticator | None = None

    @classmethod
    async def create(
        cls,
        credentials_file: str | None = None,
        batch_size: int = 10,
        max_retries: int = 5,
        output: Any | None = None,
    ) -> GmailClient:
        """Create and authenticate a GmailClient instance.

        This factory method handles authentication automatically and returns
        a ready-to-use client. This is the recommended way to create a
        GmailClient for most use cases.

        Args:
            credentials_file: Optional custom OAuth2 credentials file path.
                If None (default), uses bundled application credentials.
            batch_size: Messages per batch (default: 10, max: 100)
            max_retries: Maximum retries for failed requests (default: 5)
            output: Optional OutputManager for structured logging during auth

        Returns:
            Authenticated and connected GmailClient instance

        Raises:
            FileNotFoundError: If bundled credentials are missing
            Exception: If OAuth flow fails
        """
        from gmailarchiver.connectors.auth import GmailAuthenticator

        authenticator = GmailAuthenticator(
            credentials_file=credentials_file,
            output=output,
        )
        creds = await authenticator.authenticate_async()

        instance = cls(
            credentials=creds,
            batch_size=batch_size,
            max_retries=max_retries,
        )
        instance._authenticator = authenticator
        await instance.connect()

        return instance

    async def connect(self) -> GmailClient:
        """Initialize HTTP client for making API requests.

        This method provides explicit lifecycle management as an alternative
        to using the async context manager pattern. Call close() when done.

        Returns:
            Self, for method chaining

        Example (explicit lifecycle):
            client = GmailClient(credentials)
            await client.connect()
            try:
                async for msg in client.list_messages(...):
                    ...
            finally:
                await client.close()

        Example (context manager - preferred):
            async with GmailClient(credentials) as client:
                async for msg in client.list_messages(...):
                    ...
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self

    async def __aenter__(self) -> GmailClient:
        """Async context manager entry."""
        return await self.connect()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _get_headers(self) -> dict[str, str]:
        """Get authorization headers with current token.

        Note: Token refresh is handled by _ensure_valid_token() before requests.
        This method only constructs headers using the current token.
        """
        return {
            "Authorization": f"Bearer {self._credentials.token}",
            "Content-Type": "application/json",
        }

    async def _ensure_valid_token(self) -> None:
        """Ensure credentials are valid, refreshing if needed.

        This method handles token refresh asynchronously using asyncio.to_thread()
        to avoid blocking the event loop during the HTTP request to Google's
        token endpoint.

        Uses a lock to prevent concurrent refresh attempts, which could cause
        race conditions or redundant network requests.
        """
        if not self._credentials.expired:
            return

        if not self._credentials.refresh_token:
            return

        if self._refresh_lock is None:
            # Fallback if connect() wasn't called (shouldn't happen)
            self._refresh_lock = asyncio.Lock()

        async with self._refresh_lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self._credentials.expired and self._credentials.refresh_token:
                await asyncio.to_thread(self._refresh_token_sync)

    def _refresh_token_sync(self) -> None:
        """Sync helper: Refresh the OAuth token.

        Called via asyncio.to_thread() from _ensure_valid_token().
        """
        from google.auth.transport.requests import Request

        self._credentials.refresh(Request())  # type: ignore[no-untyped-call]

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make HTTP request with retry logic and rate limiting.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            **kwargs: Additional arguments for httpx request

        Returns:
            HTTP response

        Raises:
            httpx.HTTPStatusError: If request fails after all retries
        """
        if self._http_client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        # Ensure token is valid before making request (async refresh if needed)
        await self._ensure_valid_token()

        for attempt in range(self.max_retries):
            await self._rate_limiter.acquire()

            try:
                response = await self._http_client.request(
                    method,
                    url,
                    headers=self._get_headers(),
                    **kwargs,
                )

                if response.status_code == 200 or response.status_code == 204:
                    self._rate_limiter.on_success()
                    return response

                if response.status_code == 429:
                    # Rate limited - get Retry-After header
                    retry_after = response.headers.get("Retry-After")
                    wait_time = self._rate_limiter.on_rate_limit(
                        float(retry_after) if retry_after else None
                    )
                    logger.warning(f"Rate limited. Waiting {wait_time:.1f}s before retry.")
                    await asyncio.sleep(wait_time)
                    continue

                if response.status_code >= 500:
                    # Server error - transient
                    wait_time = self._rate_limiter.on_server_error()
                    logger.warning(
                        f"Server error {response.status_code}. Waiting {wait_time:.1f}s."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # Other errors (4xx except 429) - don't retry
                response.raise_for_status()

            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    wait_time = self._rate_limiter.on_server_error()
                    logger.warning(f"Timeout. Waiting {wait_time:.1f}s before retry.")
                    await asyncio.sleep(wait_time)
                    continue
                raise

        # All retries exhausted
        raise RuntimeError(f"Failed after {self.max_retries} retries")

    async def list_messages(
        self,
        query: str,
        max_results: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """List messages matching query.

        Args:
            query: Gmail search query (e.g., 'before:2022/01/01')
            max_results: Maximum messages per page (default: 100)

        Yields:
            Message dictionaries with 'id' and 'threadId'
        """
        # Validate query
        query = validate_gmail_query(query)

        page_token: str | None = None
        url = f"{GMAIL_API_BASE}/users/{self.user_id}/messages"

        while True:
            params: dict[str, Any] = {
                "q": query,
                "maxResults": max_results,
            }
            if page_token:
                params["pageToken"] = page_token

            response = await self._request_with_retry("GET", url, params=params)
            data = response.json()

            messages = data.get("messages", [])
            for msg in messages:
                yield msg

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    async def get_message(
        self,
        message_id: str,
        format: str = "raw",
    ) -> dict[str, Any]:
        """Get a single message.

        Args:
            message_id: Gmail message ID
            format: Message format ('raw', 'full', 'minimal', 'metadata')

        Returns:
            Message dictionary
        """
        url = f"{GMAIL_API_BASE}/users/{self.user_id}/messages/{message_id}"
        response = await self._request_with_retry("GET", url, params={"format": format})
        result: dict[str, Any] = response.json()
        return result

    async def get_messages_batch(
        self,
        message_ids: list[str],
        format: str = "raw",
    ) -> AsyncIterator[dict[str, Any]]:
        """Get multiple messages with rate limiting.

        Args:
            message_ids: List of Gmail message IDs
            format: Message format ('raw', 'full', 'minimal', 'metadata')

        Yields:
            Message dictionaries (only successful fetches)

        Note:
            Failed messages are logged but don't stop iteration.
        """
        for chunk in chunk_list(message_ids, self.batch_size):
            for msg_id in chunk:
                try:
                    msg = await self.get_message(msg_id, format=format)
                    yield msg
                except Exception as e:
                    logger.warning(f"Failed to fetch message {msg_id}: {e}")
                    continue

    def decode_message_raw(self, message: dict[str, Any]) -> bytes:
        """Decode raw message from base64.

        Args:
            message: Message dictionary with 'raw' field

        Returns:
            Decoded message bytes (RFC822 format)

        Raises:
            ValueError: If message doesn't contain 'raw' field
        """
        if "raw" not in message:
            raise ValueError("Message does not contain 'raw' field")

        # Gmail uses URL-safe base64 encoding
        return base64.urlsafe_b64decode(message["raw"])

    async def trash_messages(
        self,
        message_ids: list[str],
        progress_callback: Callable[[int], None] | None = None,
    ) -> int:
        """Move messages to trash.

        Args:
            message_ids: List of message IDs to trash
            progress_callback: Optional callback called after each message (receives count)

        Returns:
            Number of messages trashed
        """
        count = 0
        for msg_id in message_ids:
            try:
                url = f"{GMAIL_API_BASE}/users/{self.user_id}/messages/{msg_id}/trash"
                await self._request_with_retry("POST", url)
                count += 1
                if progress_callback:
                    progress_callback(count)
            except Exception as e:
                logger.warning(f"Failed to trash message {msg_id}: {e}")

        return count

    async def delete_messages_permanent(
        self,
        message_ids: list[str],
        progress_callback: Callable[[int], None] | None = None,
    ) -> int:
        """Permanently delete messages.

        Args:
            message_ids: List of message IDs to delete
            progress_callback: Optional callback called after each batch (receives count)

        Returns:
            Number of messages deleted

        Warning:
            This is irreversible! Use trash_messages() for reversible deletion.
        """
        count = 0

        # Gmail API allows batch delete up to 1000 messages
        for chunk in chunk_list(message_ids, 1000):
            try:
                url = f"{GMAIL_API_BASE}/users/{self.user_id}/messages/batchDelete"
                await self._request_with_retry("POST", url, json={"ids": chunk})
                count += len(chunk)
                if progress_callback:
                    progress_callback(count)
            except Exception as e:
                logger.warning(f"Failed to delete messages batch: {e}")

        return count

    async def search_by_rfc_message_id(self, rfc_message_id: str) -> str | None:
        """Search for a Gmail message by its RFC Message-ID header.

        Args:
            rfc_message_id: RFC 2822 Message-ID (with or without angle brackets)

        Returns:
            Gmail message ID if found, None if not found
        """
        # Strip angle brackets if present
        clean_id = rfc_message_id.strip("<>")
        if not clean_id:
            return None

        query = f"rfc822msgid:{clean_id}"

        try:
            url = f"{GMAIL_API_BASE}/users/{self.user_id}/messages"
            response = await self._request_with_retry(
                "GET", url, params={"q": query, "maxResults": 1}
            )
            data = response.json()

            if "messages" in data and data["messages"]:
                return data["messages"][0]["id"]  # type: ignore[no-any-return]
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def search_by_rfc_message_ids_batch(
        self,
        rfc_message_ids: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        batch_size: int = 50,
    ) -> dict[str, str | None]:
        """Search for Gmail message IDs by RFC Message-IDs in batches.

        Args:
            rfc_message_ids: List of RFC 2822 Message-IDs (with or without angle brackets)
            progress_callback: Optional callback(processed, total) for progress
            batch_size: Messages per batch (default 50 for rate limit safety)

        Returns:
            Dict mapping rfc_message_id -> gmail_id (or None if not found)
        """
        result: dict[str, str | None] = {}
        total = len(rfc_message_ids)

        for chunk in chunk_list(rfc_message_ids, batch_size):
            for rfc_id in chunk:
                gmail_id = await self.search_by_rfc_message_id(rfc_id)
                result[rfc_id] = gmail_id

                # Update progress after each message for responsiveness
                if progress_callback:
                    progress_callback(len(result), total)

        return result
