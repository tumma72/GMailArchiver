"""Unit tests for MessageLister (archiver package internal module).

This module contains fast, isolated unit tests with no I/O or external
dependencies. All external components (GmailClient, validation) are mocked.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.archiver._lister import MessageLister
from gmailarchiver.shared.input_validator import InvalidInputError


class TestMessageLister:
    """Unit tests for MessageLister internal module."""

    @pytest.fixture
    def mock_gmail_client(self):
        """Create mock Gmail client."""
        client = Mock()
        client.list_messages = Mock(
            return_value=[
                {"id": "msg001", "threadId": "thread001"},
                {"id": "msg002", "threadId": "thread001"},
            ]
        )
        return client

    @pytest.fixture
    def lister(self, mock_gmail_client):
        """Create MessageLister with mocked client."""
        return MessageLister(gmail_client=mock_gmail_client)

    @pytest.mark.unit
    def test_list_messages_with_valid_age_threshold(self, lister, mock_gmail_client):
        """Test listing messages with valid age threshold."""
        query, messages = lister.list_messages("3y")

        # Should parse age and create Gmail query
        assert "before:" in query
        assert len(messages) == 2
        assert messages[0]["id"] == "msg001"

        # Should call Gmail client with query
        mock_gmail_client.list_messages.assert_called_once()
        call_args = mock_gmail_client.list_messages.call_args
        assert "before:" in call_args[0][0]

    @pytest.mark.unit
    def test_list_messages_with_iso_date(self, lister, mock_gmail_client):
        """Test listing messages with ISO date format."""
        query, messages = lister.list_messages("2022-01-01")

        assert "before:2022/01/01" in query
        assert len(messages) == 2
        mock_gmail_client.list_messages.assert_called_once()

    @pytest.mark.unit
    def test_list_messages_with_invalid_age_format(self, lister):
        """Test error handling for invalid age threshold."""
        with pytest.raises(InvalidInputError):
            lister.list_messages("invalid")

    @pytest.mark.unit
    def test_list_messages_with_progress_callback(self, lister, mock_gmail_client):
        """Test that progress callback is passed to Gmail client."""
        progress_callback = Mock()

        lister.list_messages("3y", progress_callback=progress_callback)

        # Should pass callback to Gmail client
        mock_gmail_client.list_messages.assert_called_once()
        call_kwargs = mock_gmail_client.list_messages.call_args[1]
        assert call_kwargs["progress_callback"] == progress_callback

    @pytest.mark.unit
    def test_list_messages_with_months_threshold(self, lister, mock_gmail_client):
        """Test listing messages with months threshold."""
        query, messages = lister.list_messages("6m")

        assert "before:" in query
        assert len(messages) == 2
        mock_gmail_client.list_messages.assert_called_once()

    @pytest.mark.unit
    def test_list_messages_with_weeks_threshold(self, lister, mock_gmail_client):
        """Test listing messages with weeks threshold."""
        query, messages = lister.list_messages("2w")

        assert "before:" in query
        assert len(messages) == 2

    @pytest.mark.unit
    def test_list_messages_with_days_threshold(self, lister, mock_gmail_client):
        """Test listing messages with days threshold."""
        query, messages = lister.list_messages("30d")

        assert "before:" in query
        assert len(messages) == 2

    @pytest.mark.unit
    def test_list_messages_with_empty_result(self, lister, mock_gmail_client):
        """Test listing when no messages match."""
        mock_gmail_client.list_messages.return_value = []

        query, messages = lister.list_messages("3y")

        assert "before:" in query
        assert len(messages) == 0

    @pytest.mark.unit
    def test_query_format(self, lister, mock_gmail_client):
        """Test that query format matches Gmail syntax."""
        with patch("gmailarchiver.core.archiver._lister.parse_age") as mock_parse:
            mock_parse.return_value = datetime(2022, 1, 1)

            query, _ = lister.list_messages("3y")

            # Gmail query format: before:YYYY/MM/DD
            assert query == "before:2022/01/01"
