"""Gmail API client wrapper with retry logic and batching."""

import base64
import logging
import random
import time
from collections.abc import Callable, Iterator
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .input_validator import validate_gmail_query
from .utils import chunk_list

logger = logging.getLogger(__name__)


class GmailClient:
    """Wrapper for Gmail API with rate limiting and batch operations."""

    def __init__(
        self,
        credentials: Credentials,
        batch_size: int = 10,
        max_retries: int = 5,
        batch_delay: float = 1.0,
    ) -> None:
        """
        Initialize Gmail API client.

        Args:
            credentials: Google OAuth2 credentials
            batch_size: Number of messages to fetch per batch (default: 10)
            max_retries: Maximum number of retries for rate limit errors (default: 5)
            batch_delay: Delay between batch requests in seconds (default: 1.0)
        """
        self.service = build("gmail", "v1", credentials=credentials)
        self.user_id = "me"
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.batch_delay = batch_delay

    def list_messages(
        self,
        query: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, str]]:
        """
        List all message IDs matching the query.

        Args:
            query: Gmail search query (e.g., 'before:2022/01/01')
            progress_callback: Optional callback(messages_found, page_number) for progress

        Returns:
            List of message dictionaries with 'id' and 'threadId'

        Raises:
            InvalidInputError: If query contains dangerous patterns
        """
        # Validate query to prevent injection attacks
        query = validate_gmail_query(query)

        messages: list[dict[str, str]] = []
        page_token: str | None = None
        page_number = 0

        while True:
            try:
                response = self._execute_with_retry(
                    self.service.users()
                    .messages()
                    .list(userId=self.user_id, q=query, maxResults=100, pageToken=page_token)
                )

                if "messages" in response:
                    messages.extend(response["messages"])

                page_number += 1
                if progress_callback:
                    progress_callback(len(messages), page_number)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as error:
                if error.resp.status == 404:
                    # No messages found
                    break
                raise

        return messages

    def get_message(self, message_id: str, format: str = "raw") -> dict[str, Any]:
        """
        Get a single message.

        Args:
            message_id: Gmail message ID
            format: Message format ('raw', 'full', 'minimal', 'metadata')

        Returns:
            Message dictionary
        """
        return self._execute_with_retry(  # type: ignore[no-any-return]
            self.service.users().messages().get(userId=self.user_id, id=message_id, format=format)
        )

    def get_message_ids_batch(
        self,
        gmail_ids: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        batch_size: int = 100,
    ) -> dict[str, str]:
        """
        Fetch RFC Message-ID headers for multiple messages efficiently.

        Uses metadata format to get only headers (much faster than full/raw).
        This enables pre-filtering duplicates before downloading full content.

        Args:
            gmail_ids: List of Gmail message IDs
            progress_callback: Optional callback(processed, total) for progress
            batch_size: Messages per batch (default 100, max allowed by Gmail API)

        Returns:
            Dict mapping gmail_id -> rfc_message_id (or empty string if not found)
        """
        result: dict[str, str] = {}
        total = len(gmail_ids)

        for i, chunk in enumerate(chunk_list(gmail_ids, batch_size)):
            batch = self.service.new_batch_http_request()
            chunk_results: dict[str, str] = {}

            def make_callback(gid: str) -> Callable[[str, dict[str, Any], Exception | None], None]:
                def callback(
                    request_id: str, response: dict[str, Any], exception: Exception | None
                ) -> None:
                    if exception is not None:
                        chunk_results[gid] = ""  # Message unavailable
                    else:
                        # Extract Message-ID from headers
                        msg_id = ""
                        payload = response.get("payload", {})
                        headers = payload.get("headers", [])
                        for header in headers:
                            if header.get("name", "").lower() == "message-id":
                                msg_id = header.get("value", "")
                                break
                        chunk_results[gid] = msg_id

                return callback

            for gid in chunk:
                batch.add(
                    self.service.users()
                    .messages()
                    .get(
                        userId=self.user_id,
                        id=gid,
                        format="metadata",
                        metadataHeaders=["Message-ID"],
                    ),
                    callback=make_callback(gid),
                    request_id=gid,
                )

            self._execute_with_retry(batch)
            result.update(chunk_results)

            if progress_callback:
                progress_callback(len(result), total)

            # Short delay for metadata requests (lightweight, less rate limiting risk)
            time.sleep(0.1)

        return result

    def get_messages_batch(
        self, message_ids: list[str], format: str = "raw"
    ) -> Iterator[dict[str, Any]]:
        """
        Get multiple messages in batches with graceful error handling.

        Args:
            message_ids: List of Gmail message IDs
            format: Message format ('raw', 'full', 'minimal', 'metadata')

        Yields:
            Message dictionaries (only successful fetches)

        Note:
            Failed messages are logged but don't stop the batch.
            Common failures: message deleted/moved during fetch (400 errors)
        """
        for chunk in chunk_list(message_ids, self.batch_size):
            batch = self.service.new_batch_http_request()
            results: list[dict[str, Any]] = []
            failed_ids: list[tuple[str, str]] = []  # (msg_id, error_reason)

            def callback(
                request_id: str, response: dict[str, Any], exception: Exception | None
            ) -> None:
                if exception is not None:
                    # Log error but don't raise - continue with other messages
                    error_msg = str(exception)
                    # Extract message ID from request_id if possible
                    msg_id = request_id.split("/")[-1] if "/" in request_id else request_id
                    failed_ids.append((msg_id, error_msg))
                else:
                    results.append(response)

            for msg_id in chunk:
                batch.add(
                    self.service.users()
                    .messages()
                    .get(userId=self.user_id, id=msg_id, format=format),
                    callback=callback,
                    request_id=msg_id,  # Pass message ID for error tracking
                )

            self._execute_with_retry(batch)

            # Log any failures (non-fatal)
            if failed_ids:
                for msg_id, error in failed_ids:
                    logger.warning(f"Failed to fetch message {msg_id}: {error}")

            yield from results

            # Add delay between batches to respect rate limits
            time.sleep(self.batch_delay)

    def decode_message_raw(self, message: dict[str, Any]) -> bytes:
        """
        Decode raw message from base64.

        Args:
            message: Message dictionary with 'raw' field

        Returns:
            Decoded message bytes (RFC822 format)
        """
        if "raw" not in message:
            raise ValueError("Message does not contain 'raw' field")

        # Gmail uses URL-safe base64 encoding
        return base64.urlsafe_b64decode(message["raw"])

    def trash_messages(self, message_ids: list[str]) -> int:
        """
        Move messages to trash (batch operation).

        Args:
            message_ids: List of message IDs to trash

        Returns:
            Number of messages trashed
        """
        count = 0
        # Batch trash operations in chunks to avoid rate limits
        for chunk in chunk_list(message_ids, 100):
            batch = self.service.new_batch_http_request()

            def callback(
                request_id: str, response: dict[str, Any], exception: Exception | None
            ) -> None:
                if exception is not None:
                    logger.warning(f"Failed to trash message {request_id}: {exception}")

            for msg_id in chunk:
                batch.add(
                    self.service.users().messages().trash(userId=self.user_id, id=msg_id),
                    callback=callback,
                    request_id=msg_id,
                )

            self._execute_with_retry(batch)
            count += len(chunk)

            # Add delay between batches to respect rate limits
            time.sleep(self.batch_delay)

        return count

    def delete_messages_permanent(self, message_ids: list[str]) -> int:
        """
        Permanently delete messages (batch operation).

        Args:
            message_ids: List of message IDs to delete

        Returns:
            Number of messages deleted

        Warning:
            This is irreversible! Use trash_messages() for reversible deletion.
        """
        count = 0
        # Gmail API allows up to 1000 messages per batch delete
        for chunk in chunk_list(message_ids, 1000):
            self._execute_with_retry(
                self.service.users()
                .messages()
                .batchDelete(userId=self.user_id, body={"ids": chunk})
            )
            count += len(chunk)
        return count

    def _execute_with_retry(self, request: Any) -> Any:
        """
        Execute a request with exponential backoff for rate limits.

        Args:
            request: Google API request object

        Returns:
            Response from the API

        Raises:
            HttpError: If request fails after max retries
        """
        for attempt in range(self.max_retries):
            try:
                return request.execute()
            except HttpError as error:
                # Rate limit error (429) or server error (5xx)
                if error.resp.status == 429 or error.resp.status >= 500:
                    if attempt < self.max_retries - 1:
                        # For rate limit errors, use longer backoff
                        if error.resp.status == 429:
                            # Exponential backoff: 2, 4, 8, 16 seconds (+ jitter)
                            wait_time = (2 ** (attempt + 1)) + random.uniform(0, 1)
                        else:
                            # Server errors: shorter backoff
                            wait_time = (2**attempt) + random.uniform(0, 1)
                        time.sleep(wait_time)
                        continue
                raise

        raise RuntimeError(f"Failed after {self.max_retries} retries")
