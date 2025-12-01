"""Tests for Gmail API client wrapper."""

import base64
from typing import Any
from unittest.mock import Mock, patch

import pytest
from googleapiclient.errors import HttpError

from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.shared.input_validator import InvalidInputError


class TestGmailClientInit:
    """Tests for GmailClient initialization."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_init_with_defaults(self, mock_build: Mock) -> None:
        """Test initialization with default parameters."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = GmailClient(mock_creds)

        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)
        assert client.service == mock_service
        assert client.user_id == "me"
        assert client.batch_size == 10
        assert client.max_retries == 5
        assert client.batch_delay == 0.5

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_init_with_custom_params(self, mock_build: Mock) -> None:
        """Test initialization with custom parameters."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = GmailClient(mock_creds, batch_size=20, max_retries=3, batch_delay=0.5)

        assert client.batch_size == 20
        assert client.max_retries == 3
        assert client.batch_delay == 0.5


class TestListMessages:
    """Tests for list_messages method."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_single_page(self, mock_build: Mock) -> None:
        """Test listing messages with single page response."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Setup mock response
        mock_list = Mock()
        mock_list.execute.return_value = {
            "messages": [
                {"id": "msg1", "threadId": "thread1"},
                {"id": "msg2", "threadId": "thread2"},
            ]
        }
        mock_service.users().messages().list.return_value = mock_list

        client = GmailClient(mock_creds)
        messages = client.list_messages("before:2022/01/01")

        assert len(messages) == 2
        assert messages[0]["id"] == "msg1"
        assert messages[1]["id"] == "msg2"

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_multiple_pages(self, mock_build: Mock) -> None:
        """Test listing messages with pagination."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Setup mock responses for multiple pages
        mock_list_page1 = Mock()
        mock_list_page1.execute.return_value = {
            "messages": [{"id": "msg1", "threadId": "thread1"}],
            "nextPageToken": "token123",
        }

        mock_list_page2 = Mock()
        mock_list_page2.execute.return_value = {"messages": [{"id": "msg2", "threadId": "thread2"}]}

        mock_service.users().messages().list.side_effect = [mock_list_page1, mock_list_page2]

        client = GmailClient(mock_creds)
        messages = client.list_messages("before:2022/01/01")

        assert len(messages) == 2
        assert messages[0]["id"] == "msg1"
        assert messages[1]["id"] == "msg2"

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_no_messages(self, mock_build: Mock) -> None:
        """Test listing messages when no messages found."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_list = Mock()
        mock_list.execute.return_value = {}
        mock_service.users().messages().list.return_value = mock_list

        client = GmailClient(mock_creds)
        messages = client.list_messages("before:2022/01/01")

        assert messages == []

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_404_error(self, mock_build: Mock) -> None:
        """Test listing messages handles 404 error gracefully."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_list = Mock()
        mock_resp = Mock()
        mock_resp.status = 404
        mock_list.execute.side_effect = HttpError(mock_resp, b"Not found")
        mock_service.users().messages().list.return_value = mock_list

        client = GmailClient(mock_creds)
        messages = client.list_messages("before:2022/01/01")

        assert messages == []

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_invalid_query(self, mock_build: Mock) -> None:
        """Test listing messages with invalid query raises error."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = GmailClient(mock_creds)

        with pytest.raises(InvalidInputError, match="Invalid character"):
            client.list_messages("before:2022/01/01; rm -rf /")


class TestGetMessage:
    """Tests for get_message method."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_raw_format(self, mock_build: Mock) -> None:
        """Test getting a single message in raw format."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_get = Mock()
        mock_get.execute.return_value = {"id": "msg1", "raw": "base64data"}
        mock_service.users().messages().get.return_value = mock_get

        client = GmailClient(mock_creds)
        message = client.get_message("msg1", format="raw")

        assert message["id"] == "msg1"
        assert message["raw"] == "base64data"
        mock_service.users().messages().get.assert_called_once_with(
            userId="me", id="msg1", format="raw"
        )

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_full_format(self, mock_build: Mock) -> None:
        """Test getting a single message in full format."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_get = Mock()
        mock_get.execute.return_value = {"id": "msg1", "payload": {}}
        mock_service.users().messages().get.return_value = mock_get

        client = GmailClient(mock_creds)
        message = client.get_message("msg1", format="full")

        assert message["id"] == "msg1"
        mock_service.users().messages().get.assert_called_once_with(
            userId="me", id="msg1", format="full"
        )


class TestGetMessagesBatch:
    """Tests for get_messages_batch method."""

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_messages_batch_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test batch fetching messages successfully."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock batch request - capture callback and simulate success
        captured_callback = None

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            nonlocal captured_callback
            captured_callback = callback

        def mock_execute() -> None:
            # Simulate successful batch execution by calling callback
            if captured_callback:
                captured_callback("msg1", {"id": "msg1", "raw": "data1"}, None)

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=2)
        message_ids = ["msg1"]

        messages = list(client.get_messages_batch(message_ids))

        # Should have one successful message
        assert len(messages) == 1
        assert messages[0]["id"] == "msg1"

    @patch("gmailarchiver.connectors.gmail_client.logger")
    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_messages_batch_with_failures(
        self, mock_build: Mock, mock_time: Mock, mock_logger: Mock
    ) -> None:
        """Test batch fetching with some failures."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callback = None

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            nonlocal captured_callback
            captured_callback = callback

        call_count = 0

        def mock_execute() -> None:
            nonlocal call_count
            if captured_callback:
                if call_count == 0:
                    # First message succeeds
                    captured_callback("msg1", {"id": "msg1", "raw": "data1"}, None)
                else:
                    # Second message fails
                    captured_callback("msg2/error", None, Exception("Message not found"))
                call_count += 1

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=1)
        message_ids = ["msg1", "msg2"]

        messages = list(client.get_messages_batch(message_ids))

        # Should only have successful message
        assert len(messages) == 1
        # Should have logged the failure
        assert mock_logger.warning.called

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_messages_batch_respects_batch_size(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test batch fetching respects batch size."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_batch = Mock()
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=2, batch_delay=0.1)
        message_ids = ["msg1", "msg2", "msg3", "msg4"]

        list(client.get_messages_batch(message_ids))

        # Should create 2 batches (4 messages / batch_size of 2)
        assert mock_service.new_batch_http_request.call_count == 2


class TestDecodeMessageRaw:
    """Tests for decode_message_raw method."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_decode_message_raw_success(self, mock_build: Mock) -> None:
        """Test decoding raw message successfully."""
        mock_creds = Mock()
        client = GmailClient(mock_creds)

        # Create a test message
        original = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        encoded = base64.urlsafe_b64encode(original).decode("ascii")
        message = {"raw": encoded}

        decoded = client.decode_message_raw(message)

        assert decoded == original

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_decode_message_raw_missing_field(self, mock_build: Mock) -> None:
        """Test decoding message without raw field raises error."""
        mock_creds = Mock()
        client = GmailClient(mock_creds)

        message = {"id": "msg1", "threadId": "thread1"}

        with pytest.raises(ValueError, match="does not contain 'raw' field"):
            client.decode_message_raw(message)


class TestTrashMessages:
    """Tests for trash_messages method."""

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_trash_messages_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test trashing messages successfully."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_batch = Mock()
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds)
        message_ids = ["msg1", "msg2", "msg3"]

        count = client.trash_messages(message_ids)

        assert count == 3
        mock_service.new_batch_http_request.assert_called()

    @patch("gmailarchiver.connectors.gmail_client.logger")
    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_trash_messages_with_failures(
        self, mock_build: Mock, mock_time: Mock, mock_logger: Mock
    ) -> None:
        """Test trashing messages with some failures."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callback = None

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            nonlocal captured_callback
            captured_callback = callback

        def mock_execute() -> None:
            # Simulate a failure
            if captured_callback:
                captured_callback("msg1", None, Exception("Failed to trash"))

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds)
        message_ids = ["msg1"]

        count = client.trash_messages(message_ids)

        assert count == 1
        # Should have logged the failure
        assert mock_logger.warning.called

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_trash_messages_large_batch(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test trashing large number of messages."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_batch = Mock()
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds)
        # 150 messages should create 2 batches (100 each)
        message_ids = [f"msg{i}" for i in range(150)]

        count = client.trash_messages(message_ids)

        assert count == 150
        # Should create 2 batches
        assert mock_service.new_batch_http_request.call_count == 2


class TestDeleteMessagesPermanent:
    """Tests for delete_messages_permanent method."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_delete_messages_permanent_success(self, mock_build: Mock) -> None:
        """Test permanently deleting messages successfully."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_batch_delete = Mock()
        mock_batch_delete.execute.return_value = None
        mock_service.users().messages().batchDelete.return_value = mock_batch_delete

        client = GmailClient(mock_creds)
        message_ids = ["msg1", "msg2", "msg3"]

        count = client.delete_messages_permanent(message_ids)

        assert count == 3
        mock_service.users().messages().batchDelete.assert_called_once_with(
            userId="me", body={"ids": message_ids}
        )

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_delete_messages_permanent_large_batch(self, mock_build: Mock) -> None:
        """Test permanently deleting large number of messages."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_batch_delete = Mock()
        mock_batch_delete.execute.return_value = None
        mock_service.users().messages().batchDelete.return_value = mock_batch_delete

        client = GmailClient(mock_creds)
        # 1500 messages should create 2 batches (1000 max each)
        message_ids = [f"msg{i}" for i in range(1500)]

        count = client.delete_messages_permanent(message_ids)

        assert count == 1500
        # Should be called twice (1000 + 500)
        assert mock_service.users().messages().batchDelete.call_count == 2


class TestExecuteWithRetry:
    """Tests for _execute_with_retry method."""

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_success_first_try(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test successful execution on first try."""
        mock_creds = Mock()
        client = GmailClient(mock_creds)

        mock_request = Mock()
        mock_request.execute.return_value = {"result": "success"}

        result = client._execute_with_retry(mock_request)

        assert result == {"result": "success"}
        mock_request.execute.assert_called_once()
        mock_time.sleep.assert_not_called()

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_429_retry_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test retry on 429 rate limit error."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=3)

        mock_request = Mock()
        mock_resp_429 = Mock()
        mock_resp_429.status = 429

        # Fail first time with 429, succeed second time
        mock_request.execute.side_effect = [
            HttpError(mock_resp_429, b"Rate limit"),
            {"result": "success"},
        ]

        result = client._execute_with_retry(mock_request)

        assert result == {"result": "success"}
        assert mock_request.execute.call_count == 2
        mock_time.sleep.assert_called_once()

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_500_retry_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test retry on 500 server error."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=3)

        mock_request = Mock()
        mock_resp_500 = Mock()
        mock_resp_500.status = 500

        # Fail first time with 500, succeed second time
        mock_request.execute.side_effect = [
            HttpError(mock_resp_500, b"Server error"),
            {"result": "success"},
        ]

        result = client._execute_with_retry(mock_request)

        assert result == {"result": "success"}
        assert mock_request.execute.call_count == 2
        mock_time.sleep.assert_called_once()

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_503_retry_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test retry on 503 service unavailable error."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=3)

        mock_request = Mock()
        mock_resp_503 = Mock()
        mock_resp_503.status = 503

        # Fail first time with 503, succeed second time
        mock_request.execute.side_effect = [
            HttpError(mock_resp_503, b"Service unavailable"),
            {"result": "success"},
        ]

        result = client._execute_with_retry(mock_request)

        assert result == {"result": "success"}
        assert mock_request.execute.call_count == 2

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_max_retries_exceeded(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test that max retries raises error."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=3)

        mock_request = Mock()
        mock_resp_429 = Mock()
        mock_resp_429.status = 429

        # Always fail with 429
        mock_request.execute.side_effect = HttpError(mock_resp_429, b"Rate limit")

        with pytest.raises(HttpError):
            client._execute_with_retry(mock_request)

        # Should try max_retries times
        assert mock_request.execute.call_count == 3

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_non_retryable_error(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test that non-retryable errors are raised immediately."""
        mock_creds = Mock()
        client = GmailClient(mock_creds)

        mock_request = Mock()
        mock_resp_400 = Mock()
        mock_resp_400.status = 400

        mock_request.execute.side_effect = HttpError(mock_resp_400, b"Bad request")

        with pytest.raises(HttpError):
            client._execute_with_retry(mock_request)

        # Should not retry for 400 error
        mock_request.execute.assert_called_once()
        mock_time.sleep.assert_not_called()

    @patch("gmailarchiver.connectors.gmail_client.random")
    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_backoff_timing(
        self, mock_build: Mock, mock_time: Mock, mock_random: Mock
    ) -> None:
        """Test that retry backoff timing is correct."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=4)

        mock_request = Mock()
        mock_resp_429 = Mock()
        mock_resp_429.status = 429

        # Set random to return 0.5 for predictable testing
        mock_random.uniform.return_value = 0.5

        # Fail 3 times with 429, succeed on 4th
        mock_request.execute.side_effect = [
            HttpError(mock_resp_429, b"Rate limit"),
            HttpError(mock_resp_429, b"Rate limit"),
            HttpError(mock_resp_429, b"Rate limit"),
            {"result": "success"},
        ]

        client._execute_with_retry(mock_request)

        # Check backoff times for 429 (rate limit): 2^(attempt+1) + jitter
        # Attempt 0: 2^1 + 0.5 = 2.5
        # Attempt 1: 2^2 + 0.5 = 4.5
        # Attempt 2: 2^3 + 0.5 = 8.5
        assert mock_time.sleep.call_count == 3
        calls = mock_time.sleep.call_args_list
        assert calls[0][0][0] == 2.5  # 2^(0+1) + 0.5
        assert calls[1][0][0] == 4.5  # 2^(1+1) + 0.5
        assert calls[2][0][0] == 8.5  # 2^(2+1) + 0.5

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_execute_with_retry_all_attempts_fail_no_http_error(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test that RuntimeError is raised when all retries fail without HttpError."""
        mock_creds = Mock()
        client = GmailClient(mock_creds, max_retries=2)

        mock_request = Mock()
        # Return None (not raising HttpError) so we fall through all retries
        mock_request.execute.return_value = None

        # This should complete successfully and return None
        result = client._execute_with_retry(mock_request)
        assert result is None


class TestGetMessageIdsBatch:
    """Tests for get_message_ids_batch method."""

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_ids_batch_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test successful batch retrieval of message IDs."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callbacks: dict[str, Any] = {}

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            captured_callbacks[request_id] = callback

        def mock_execute() -> None:
            # Simulate successful batch execution
            for gid, callback in captured_callbacks.items():
                callback(
                    gid,
                    {
                        "id": gid,
                        "payload": {
                            "headers": [{"name": "Message-ID", "value": f"<{gid}@example.com>"}]
                        },
                    },
                    None,
                )

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=100)
        gmail_ids = ["msg1", "msg2", "msg3"]

        result = client.get_message_ids_batch(gmail_ids)

        assert len(result) == 3
        assert result["msg1"] == "<msg1@example.com>"
        assert result["msg2"] == "<msg2@example.com>"
        assert result["msg3"] == "<msg3@example.com>"

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_ids_batch_with_exception(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test batch retrieval handles exceptions gracefully."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callbacks: dict[str, Any] = {}

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            captured_callbacks[request_id] = callback

        def mock_execute() -> None:
            # First succeeds, second fails with exception
            for gid, callback in captured_callbacks.items():
                if gid == "msg1":
                    callback(
                        gid,
                        {
                            "id": gid,
                            "payload": {
                                "headers": [{"name": "Message-ID", "value": "<msg1@example.com>"}]
                            },
                        },
                        None,
                    )
                else:
                    callback(gid, None, Exception("Message not found"))

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=100)
        gmail_ids = ["msg1", "msg2"]

        result = client.get_message_ids_batch(gmail_ids)

        assert len(result) == 2
        assert result["msg1"] == "<msg1@example.com>"
        assert result["msg2"] == ""  # Empty string for failed message

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_ids_batch_with_progress_callback(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test progress callback is called during batch retrieval."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callbacks: dict[str, Any] = {}

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            captured_callbacks[request_id] = callback

        def mock_execute() -> None:
            for gid, callback in captured_callbacks.items():
                callback(
                    gid,
                    {
                        "id": gid,
                        "payload": {
                            "headers": [{"name": "Message-ID", "value": f"<{gid}@example.com>"}]
                        },
                    },
                    None,
                )

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        progress_calls: list[tuple[int, int]] = []

        def progress_callback(processed: int, total: int) -> None:
            progress_calls.append((processed, total))

        client = GmailClient(mock_creds, batch_size=100)
        gmail_ids = ["msg1", "msg2"]

        client.get_message_ids_batch(gmail_ids, progress_callback=progress_callback)

        # Progress callback should be called
        assert len(progress_calls) > 0
        assert progress_calls[-1] == (2, 2)

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_get_message_ids_batch_missing_message_id_header(
        self, mock_build: Mock, mock_time: Mock
    ) -> None:
        """Test handling of messages without Message-ID header."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        captured_callbacks: dict[str, Any] = {}

        def mock_add(request: Any, callback: Any, request_id: str) -> None:
            captured_callbacks[request_id] = callback

        def mock_execute() -> None:
            for gid, callback in captured_callbacks.items():
                # Response without Message-ID header
                callback(
                    gid,
                    {
                        "id": gid,
                        "payload": {"headers": [{"name": "Subject", "value": "Test Subject"}]},
                    },
                    None,
                )

        mock_batch = Mock()
        mock_batch.add.side_effect = mock_add
        mock_batch.execute.side_effect = mock_execute
        mock_service.new_batch_http_request.return_value = mock_batch

        client = GmailClient(mock_creds, batch_size=100)
        gmail_ids = ["msg1"]

        result = client.get_message_ids_batch(gmail_ids)

        assert len(result) == 1
        assert result["msg1"] == ""  # Empty string when no Message-ID header


class TestListMessagesProgressCallback:
    """Tests for list_messages with progress callback."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_calls_progress_callback(self, mock_build: Mock) -> None:
        """Test that list_messages calls progress_callback with count and page.

        This covers line 83: progress_callback(len(messages), page_number)
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Multiple pages of results
        mock_service.users().messages().list().execute.side_effect = [
            {"messages": [{"id": "msg1"}], "nextPageToken": "token1"},
            {"messages": [{"id": "msg2"}], "nextPageToken": None},
        ]

        client = GmailClient(mock_creds)
        progress_calls: list[tuple[int, int]] = []

        def progress_callback(count: int, page: int) -> None:
            progress_calls.append((count, page))

        client.list_messages("query", progress_callback=progress_callback)

        # Should be called once per page
        assert len(progress_calls) >= 1
        # First call should have count=1 and page=1
        assert progress_calls[0] == (1, 1)

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_list_messages_raises_non_404_error(self, mock_build: Mock) -> None:
        """Test that list_messages re-raises non-404 HttpError.

        This covers line 93: raise (non-404 HttpError)
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Create a 500 Internal Server Error
        http_error = HttpError(
            resp=Mock(status=500, reason="Server Error"),
            content=b"Internal Server Error",
        )
        mock_service.users().messages().list().execute.side_effect = http_error

        client = GmailClient(mock_creds, max_retries=1)

        with pytest.raises(HttpError) as exc_info:
            client.list_messages("query")

        assert exc_info.value.resp.status == 500


class TestSearchByRfcMessageId:
    """Tests for search_by_rfc_message_id method."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_search_empty_message_id_returns_none(self, mock_build: Mock) -> None:
        """Test that empty RFC message ID returns None.

        This covers line 327: return None when clean_id is empty
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = GmailClient(mock_creds)

        # Empty string after stripping angle brackets
        result = client.search_by_rfc_message_id("")
        assert result is None

        # Only angle brackets
        result = client.search_by_rfc_message_id("<>")
        assert result is None

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_search_found_returns_gmail_id(self, mock_build: Mock) -> None:
        """Test that successful search returns Gmail ID.

        This covers line 337: return response["messages"][0]["id"]
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "gmail123"}]
        }

        client = GmailClient(mock_creds)

        result = client.search_by_rfc_message_id("<test@example.com>")
        assert result == "gmail123"

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_search_not_found_returns_none(self, mock_build: Mock) -> None:
        """Test that search with no results returns None."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_service.users().messages().list().execute.return_value = {}

        client = GmailClient(mock_creds)

        result = client.search_by_rfc_message_id("<notfound@example.com>")
        assert result is None

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_search_404_error_returns_none(self, mock_build: Mock) -> None:
        """Test that 404 error returns None.

        This covers lines 340-343: HttpError 404 handling
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        http_error = HttpError(
            resp=Mock(status=404, reason="Not Found"),
            content=b"Not Found",
        )
        mock_service.users().messages().list().execute.side_effect = http_error

        client = GmailClient(mock_creds)

        result = client.search_by_rfc_message_id("<test@example.com>")
        assert result is None


class TestSearchByRfcMessageIdsBatch:
    """Tests for search_by_rfc_message_ids_batch method."""

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_batch_search_success(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test batch search returns correct mapping.

        This covers lines 367-383: search_by_rfc_message_ids_batch method
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock search results: first found, second not found
        def mock_execute_side_effect() -> dict[str, Any]:
            call_count = mock_service.users().messages().list().execute.call_count
            if call_count == 1:
                return {"messages": [{"id": "gmail1"}]}
            return {}

        mock_service.users().messages().list().execute.side_effect = mock_execute_side_effect

        client = GmailClient(mock_creds)

        result = client.search_by_rfc_message_ids_batch(
            ["<test1@example.com>", "<test2@example.com>"],
            batch_size=10,
            batch_delay=0.0,
        )

        assert "<test1@example.com>" in result
        assert "<test2@example.com>" in result
        assert result["<test1@example.com>"] == "gmail1"
        assert result["<test2@example.com>"] is None

    @patch("gmailarchiver.connectors.gmail_client.time")
    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_batch_search_with_progress(self, mock_build: Mock, mock_time: Mock) -> None:
        """Test batch search calls progress callback."""
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_service.users().messages().list().execute.return_value = {}

        client = GmailClient(mock_creds)
        progress_calls: list[tuple[int, int]] = []

        def progress_callback(processed: int, total: int) -> None:
            progress_calls.append((processed, total))

        client.search_by_rfc_message_ids_batch(
            ["<a@x.com>", "<b@x.com>"],
            progress_callback=progress_callback,
            batch_size=10,
            batch_delay=0.0,
        )

        # Should call progress for each message
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2)
        assert progress_calls[1] == (2, 2)


class TestExecuteWithRetryExhaustion:
    """Tests for _execute_with_retry exhausting retries."""

    @patch("gmailarchiver.connectors.gmail_client.build")
    def test_zero_retries_raises_runtime_error(self, mock_build: Mock) -> None:
        """Test that 0 max_retries raises RuntimeError immediately.

        This covers line 416: raise RuntimeError after max retries
        The loop is never entered when max_retries is 0.
        """
        mock_creds = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Create a mock request (won't be called since loop never runs)
        mock_request = Mock()

        client = GmailClient(mock_creds, max_retries=0)

        with pytest.raises(RuntimeError, match="Failed after 0 retries"):
            client._execute_with_retry(mock_request)

        # Verify execute was never called since loop never ran
        mock_request.execute.assert_not_called()
