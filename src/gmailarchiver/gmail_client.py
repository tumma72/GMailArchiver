"""Gmail API client wrapper with retry logic and batching."""

import base64
import random
import time
from collections.abc import Iterator
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .utils import chunk_list


class GmailClient:
    """Wrapper for Gmail API with rate limiting and batch operations."""

    # Batch size for fetching messages (reduced to avoid concurrent request limits)
    # Gmail has an undocumented per-user concurrent request limit
    BATCH_SIZE = 10
    # Max retries for rate limit errors
    MAX_RETRIES = 5
    # Delay between batch requests (seconds) to respect rate limits
    BATCH_DELAY = 1.0

    def __init__(self, credentials: Credentials) -> None:
        """
        Initialize Gmail API client.

        Args:
            credentials: Google OAuth2 credentials
        """
        self.service = build('gmail', 'v1', credentials=credentials)
        self.user_id = 'me'

    def list_messages(self, query: str) -> list[dict[str, str]]:
        """
        List all message IDs matching the query.

        Args:
            query: Gmail search query (e.g., 'before:2022/01/01')

        Returns:
            List of message dictionaries with 'id' and 'threadId'
        """
        messages: list[dict[str, str]] = []
        page_token: str | None = None

        while True:
            try:
                response = self._execute_with_retry(
                    self.service.users().messages().list(
                        userId=self.user_id,
                        q=query,
                        maxResults=100,
                        pageToken=page_token
                    )
                )

                if 'messages' in response:
                    messages.extend(response['messages'])

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except HttpError as error:
                if error.resp.status == 404:
                    # No messages found
                    break
                raise

        return messages

    def get_message(self, message_id: str, format: str = 'raw') -> dict[str, Any]:
        """
        Get a single message.

        Args:
            message_id: Gmail message ID
            format: Message format ('raw', 'full', 'minimal', 'metadata')

        Returns:
            Message dictionary
        """
        return self._execute_with_retry(
            self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format=format
            )
        )

    def get_messages_batch(
        self,
        message_ids: list[str],
        format: str = 'raw'
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
        for chunk in chunk_list(message_ids, self.BATCH_SIZE):
            batch = self.service.new_batch_http_request()
            results: list[dict[str, Any]] = []
            failed_ids: list[tuple[str, str]] = []  # (msg_id, error_reason)

            def callback(
                request_id: str,
                response: dict[str, Any],
                exception: Exception | None
            ) -> None:
                if exception is not None:
                    # Log error but don't raise - continue with other messages
                    error_msg = str(exception)
                    # Extract message ID from request_id if possible
                    msg_id = request_id.split('/')[-1] if '/' in request_id else request_id
                    failed_ids.append((msg_id, error_msg))
                else:
                    results.append(response)

            for msg_id in chunk:
                batch.add(
                    self.service.users().messages().get(
                        userId=self.user_id,
                        id=msg_id,
                        format=format
                    ),
                    callback=callback,
                    request_id=msg_id  # Pass message ID for error tracking
                )

            self._execute_with_retry(batch)

            # Log any failures (non-fatal)
            if failed_ids:
                import logging
                logger = logging.getLogger(__name__)
                for msg_id, error in failed_ids:
                    logger.warning(f"Failed to fetch message {msg_id}: {error}")

            yield from results

            # Add delay between batches to respect rate limits
            time.sleep(self.BATCH_DELAY)

    def decode_message_raw(self, message: dict[str, Any]) -> bytes:
        """
        Decode raw message from base64.

        Args:
            message: Message dictionary with 'raw' field

        Returns:
            Decoded message bytes (RFC822 format)
        """
        if 'raw' not in message:
            raise ValueError("Message does not contain 'raw' field")

        # Gmail uses URL-safe base64 encoding
        return base64.urlsafe_b64decode(message['raw'])

    def trash_messages(self, message_ids: list[str]) -> int:
        """
        Move messages to trash.

        Args:
            message_ids: List of message IDs to trash

        Returns:
            Number of messages trashed
        """
        count = 0
        for msg_id in message_ids:
            self._execute_with_retry(
                self.service.users().messages().trash(
                    userId=self.user_id,
                    id=msg_id
                )
            )
            count += 1
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
                self.service.users().messages().batchDelete(
                    userId=self.user_id,
                    body={'ids': chunk}
                )
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
        for attempt in range(self.MAX_RETRIES):
            try:
                return request.execute()
            except HttpError as error:
                # Rate limit error (429) or server error (5xx)
                if error.resp.status == 429 or error.resp.status >= 500:
                    if attempt < self.MAX_RETRIES - 1:
                        # For rate limit errors, use longer backoff
                        if error.resp.status == 429:
                            # Exponential backoff: 2, 4, 8, 16 seconds (+ jitter)
                            wait_time = (2 ** (attempt + 1)) + random.uniform(0, 1)
                        else:
                            # Server errors: shorter backoff
                            wait_time = (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(wait_time)
                        continue
                raise

        raise RuntimeError(f"Failed after {self.MAX_RETRIES} retries")
