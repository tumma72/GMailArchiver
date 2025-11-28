"""Unit tests for ArchiverFacade (archiver package public API).

This module contains fast, isolated unit tests with no I/O or external
dependencies. All internal modules (MessageLister, MessageFilter, MessageWriter)
are mocked to test orchestration logic.
"""

from unittest.mock import Mock, patch

import pytest

from gmailarchiver.core.archiver.facade import ArchiverFacade


class TestArchiverFacadeInitialization:
    """Tests for ArchiverFacade initialization."""

    @pytest.mark.unit
    def test_facade_creation_with_gmail_client(self):
        """Test creating facade with gmail_client."""
        mock_gmail_client = Mock()

        facade = ArchiverFacade(gmail_client=mock_gmail_client)

        assert facade is not None

    @pytest.mark.unit
    def test_facade_creation_with_custom_state_db_path(self):
        """Test creating facade with custom state database path."""
        mock_gmail_client = Mock()
        custom_db_path = "/custom/path/archive.db"

        facade = ArchiverFacade(gmail_client=mock_gmail_client, state_db_path=custom_db_path)

        assert facade is not None

    @pytest.mark.unit
    def test_facade_creation_with_output_manager(self):
        """Test creating facade with output_manager."""
        mock_gmail_client = Mock()
        mock_output_manager = Mock()

        facade = ArchiverFacade(gmail_client=mock_gmail_client, output_manager=mock_output_manager)

        assert facade is not None

    @pytest.mark.unit
    @patch("gmailarchiver.core.archiver.facade.MessageLister")
    @patch("gmailarchiver.core.archiver.facade.MessageFilter")
    @patch("gmailarchiver.core.archiver.facade.MessageWriter")
    def test_facade_creates_internal_modules(
        self, mock_writer_class, mock_filter_class, mock_lister_class
    ):
        """Test that facade creates internal module instances."""
        mock_gmail_client = Mock()
        state_db_path = "/tmp/test.db"

        ArchiverFacade(gmail_client=mock_gmail_client, state_db_path=state_db_path)

        # Should create MessageLister with gmail_client
        mock_lister_class.assert_called_once_with(gmail_client=mock_gmail_client)

        # Should create MessageFilter with state_db_path
        mock_filter_class.assert_called_once_with(state_db_path=state_db_path)

        # Should create MessageWriter with gmail_client and state_db_path
        mock_writer_class.assert_called_once_with(
            gmail_client=mock_gmail_client, state_db_path=state_db_path
        )


class TestArchiverFacadeDelegationMethods:
    """Tests for facade delegation to internal modules."""

    @pytest.fixture
    def mock_lister(self):
        """Create mock MessageLister."""
        lister = Mock()
        lister.list_messages.return_value = (
            "before:2022/01/01",
            [{"id": "msg001"}, {"id": "msg002"}],
        )
        return lister

    @pytest.fixture
    def mock_filter(self):
        """Create mock MessageFilter."""
        filter_module = Mock()
        filter_module.filter_archived.return_value = (["msg002"], 1)
        return filter_module

    @pytest.fixture
    def mock_writer(self):
        """Create mock MessageWriter."""
        writer = Mock()
        writer.archive_messages.return_value = {
            "archived_count": 1,
            "failed_count": 0,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox",
        }
        return writer

    @pytest.fixture
    def facade(self, mock_lister, mock_filter, mock_writer):
        """Create facade with mocked internal modules."""
        with patch("gmailarchiver.core.archiver.facade.MessageLister", return_value=mock_lister):
            with patch(
                "gmailarchiver.core.archiver.facade.MessageFilter",
                return_value=mock_filter,
            ):
                with patch(
                    "gmailarchiver.core.archiver.facade.MessageWriter",
                    return_value=mock_writer,
                ):
                    return ArchiverFacade(gmail_client=Mock())

    @pytest.mark.unit
    def test_list_messages_for_archive_delegates_to_lister(self, facade, mock_lister):
        """Test that list_messages_for_archive delegates to MessageLister."""
        query, messages = facade.list_messages_for_archive("3y")

        # Should call MessageLister.list_messages with age threshold
        mock_lister.list_messages.assert_called_once_with("3y", progress_callback=None)

        # Should return query and messages from lister
        assert query == "before:2022/01/01"
        assert len(messages) == 2
        assert messages[0]["id"] == "msg001"

    @pytest.mark.unit
    def test_list_messages_with_progress_callback(self, facade, mock_lister):
        """Test that progress callback is passed to MessageLister."""
        progress_callback = Mock()

        facade.list_messages_for_archive("3y", progress_callback=progress_callback)

        # Should pass callback to lister
        mock_lister.list_messages.assert_called_once_with("3y", progress_callback=progress_callback)

    @pytest.mark.unit
    def test_filter_already_archived_delegates_to_filter(self, facade, mock_filter):
        """Test that filter_already_archived delegates to MessageFilter."""
        message_ids = ["msg001", "msg002"]

        filtered, skipped = facade.filter_already_archived(message_ids, incremental=True)

        # Should call MessageFilter.filter_archived with message IDs
        mock_filter.filter_archived.assert_called_once_with(message_ids, incremental=True)

        # Should return filtered list and skipped count
        assert filtered == ["msg002"]
        assert skipped == 1

    @pytest.mark.unit
    def test_filter_with_incremental_false(self, facade, mock_filter):
        """Test filtering with incremental=False."""
        message_ids = ["msg001", "msg002"]

        facade.filter_already_archived(message_ids, incremental=False)

        # Should pass incremental flag to filter
        mock_filter.filter_archived.assert_called_once_with(message_ids, incremental=False)

    @pytest.mark.unit
    def test_archive_messages_delegates_to_writer(self, facade, mock_writer):
        """Test that archive_messages delegates to MessageWriter."""
        message_ids = ["msg001", "msg002"]
        output_file = "/tmp/archive.mbox"

        result = facade.archive_messages(message_ids, output_file)

        # Should call MessageWriter.archive_messages
        mock_writer.archive_messages.assert_called_once_with(
            message_ids, output_file, compress=None, operation=None
        )

        # Should return result from writer
        assert result["archived_count"] == 1
        assert result["failed_count"] == 0
        assert result["interrupted"] is False

    @pytest.mark.unit
    def test_archive_messages_with_compression(self, facade, mock_writer):
        """Test archive_messages with compression parameter."""
        message_ids = ["msg001"]
        output_file = "/tmp/archive.mbox"

        facade.archive_messages(message_ids, output_file, compress="gzip")

        # Should pass compression to writer
        mock_writer.archive_messages.assert_called_once_with(
            message_ids, output_file, compress="gzip", operation=None
        )

    @pytest.mark.unit
    def test_archive_messages_with_operation_handle(self, facade, mock_writer):
        """Test archive_messages with operation handle."""
        message_ids = ["msg001"]
        output_file = "/tmp/archive.mbox"
        mock_operation = Mock()

        facade.archive_messages(message_ids, output_file, operation=mock_operation)

        # Should pass operation handle to writer
        mock_writer.archive_messages.assert_called_once_with(
            message_ids, output_file, compress=None, operation=mock_operation
        )


class TestArchiverFacadeOrchestration:
    """Tests for facade orchestration (archive() method)."""

    @pytest.fixture
    def mock_lister(self):
        """Create mock MessageLister."""
        lister = Mock()
        lister.list_messages.return_value = (
            "before:2022/01/01",
            [{"id": "msg001"}, {"id": "msg002"}, {"id": "msg003"}],
        )
        return lister

    @pytest.fixture
    def mock_filter(self):
        """Create mock MessageFilter."""
        filter_module = Mock()
        filter_module.filter_archived.return_value = (
            ["msg002", "msg003"],
            1,
        )  # msg001 already archived
        return filter_module

    @pytest.fixture
    def mock_writer(self):
        """Create mock MessageWriter."""
        writer = Mock()
        writer.archive_messages.return_value = {
            "archived_count": 2,
            "failed_count": 0,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox",
        }
        return writer

    @pytest.fixture
    def facade(self, mock_lister, mock_filter, mock_writer):
        """Create facade with mocked internal modules."""
        with patch("gmailarchiver.core.archiver.facade.MessageLister", return_value=mock_lister):
            with patch(
                "gmailarchiver.core.archiver.facade.MessageFilter",
                return_value=mock_filter,
            ):
                with patch(
                    "gmailarchiver.core.archiver.facade.MessageWriter",
                    return_value=mock_writer,
                ):
                    return ArchiverFacade(gmail_client=Mock())

    @pytest.mark.unit
    def test_archive_orchestrates_full_workflow(
        self, facade, mock_lister, mock_filter, mock_writer
    ):
        """Test that archive() orchestrates list → filter → archive workflow."""
        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            compress=None,
            incremental=True,
            dry_run=False,
        )

        # Should call lister
        mock_lister.list_messages.assert_called_once_with("3y", progress_callback=None)

        # Should call filter with message IDs from lister
        mock_filter.filter_archived.assert_called_once_with(
            ["msg001", "msg002", "msg003"], incremental=True
        )

        # Should call writer with filtered IDs
        mock_writer.archive_messages.assert_called_once_with(
            ["msg002", "msg003"], "/tmp/archive.mbox", compress=None, operation=None
        )

        # Should return result with all data
        assert result["query"] == "before:2022/01/01"
        assert result["found_count"] == 3
        assert result["skipped_count"] == 1
        assert result["archived_count"] == 2
        assert result["failed_count"] == 0
        assert result["interrupted"] is False
        assert result["actual_file"] == "/tmp/archive.mbox"

    @pytest.mark.unit
    def test_archive_with_dry_run_mode(self, facade, mock_lister, mock_filter, mock_writer):
        """Test that dry-run mode skips archiving."""
        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=True,
            incremental=True,
        )

        # Should call lister
        mock_lister.list_messages.assert_called_once()

        # Should call filter
        mock_filter.filter_archived.assert_called_once()

        # Should NOT call writer in dry-run mode
        mock_writer.archive_messages.assert_not_called()

        # Should return preview data
        assert result["query"] == "before:2022/01/01"
        assert result["found_count"] == 3
        assert result["skipped_count"] == 1
        assert result["archived_count"] == 0  # No archiving in dry-run
        assert result["failed_count"] == 0
        assert result["interrupted"] is False

    @pytest.mark.unit
    def test_archive_with_incremental_false(self, facade, mock_lister, mock_filter, mock_writer):
        """Test archive with incremental=False (no filtering)."""
        # Configure filter to return all messages when incremental=False
        mock_filter.filter_archived.return_value = (
            ["msg001", "msg002", "msg003"],
            0,
        )

        facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            incremental=False,
            dry_run=False,
        )

        # Should call filter with incremental=False
        mock_filter.filter_archived.assert_called_once_with(
            ["msg001", "msg002", "msg003"], incremental=False
        )

    @pytest.mark.unit
    def test_archive_with_empty_message_list(self, facade, mock_lister, mock_filter, mock_writer):
        """Test archive when no messages are found."""
        # Configure lister to return no messages
        mock_lister.list_messages.return_value = ("before:2022/01/01", [])

        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            incremental=True,
            dry_run=False,
        )

        # Should call lister
        mock_lister.list_messages.assert_called_once()

        # Should NOT call filter (no messages to filter)
        mock_filter.filter_archived.assert_not_called()

        # Should NOT call writer (no messages to archive)
        mock_writer.archive_messages.assert_not_called()

        # Should return zero counts
        assert result["found_count"] == 0
        assert result["skipped_count"] == 0
        assert result["archived_count"] == 0
        assert result["failed_count"] == 0

    @pytest.mark.unit
    def test_archive_with_all_messages_filtered(
        self, facade, mock_lister, mock_filter, mock_writer
    ):
        """Test archive when all messages are already archived."""
        # Configure filter to return empty list (all filtered)
        mock_filter.filter_archived.return_value = ([], 3)

        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            incremental=True,
            dry_run=False,
        )

        # Should call lister and filter
        mock_lister.list_messages.assert_called_once()
        mock_filter.filter_archived.assert_called_once()

        # Should NOT call writer (no messages left after filtering)
        mock_writer.archive_messages.assert_not_called()

        # Should return correct counts
        assert result["found_count"] == 3
        assert result["skipped_count"] == 3
        assert result["archived_count"] == 0

    @pytest.mark.unit
    def test_archive_with_progress_callback(self, facade, mock_lister):
        """Test that progress callback is passed to lister."""
        progress_callback = Mock()

        facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=True,
            operation=Mock(progress_callback=progress_callback),
        )

        # Should pass progress callback from operation handle
        call_kwargs = mock_lister.list_messages.call_args[1]
        assert call_kwargs["progress_callback"] == progress_callback

    @pytest.mark.unit
    def test_archive_with_operation_handle(self, facade, mock_lister, mock_filter, mock_writer):
        """Test that operation handle is passed to writer."""
        mock_operation = Mock()
        mock_operation.progress_callback = None

        facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=False,
            operation=mock_operation,
        )

        # Should pass operation handle to writer
        mock_writer.archive_messages.assert_called_once()
        call_kwargs = mock_writer.archive_messages.call_args[1]
        assert call_kwargs["operation"] == mock_operation

    @pytest.mark.unit
    def test_archive_with_compression_format(self, facade, mock_writer):
        """Test archive with compression parameter."""
        facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            compress="gzip",
            dry_run=False,
        )

        # Should pass compression to writer
        call_kwargs = mock_writer.archive_messages.call_args[1]
        assert call_kwargs["compress"] == "gzip"

    @pytest.mark.unit
    def test_archive_result_dict_structure(self, facade):
        """Test that archive() returns dict with all required keys."""
        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=False,
        )

        # Should have all required keys
        required_keys = [
            "query",
            "found_count",
            "skipped_count",
            "archived_count",
            "failed_count",
            "interrupted",
        ]
        for key in required_keys:
            assert key in result

    @pytest.mark.unit
    def test_archive_extracts_message_ids_from_list_result(self, facade, mock_lister, mock_filter):
        """Test that archive extracts message IDs from lister result."""
        # Lister returns list of message dicts
        mock_lister.list_messages.return_value = (
            "before:2022/01/01",
            [
                {"id": "msg001", "threadId": "thread1"},
                {"id": "msg002", "threadId": "thread1"},
            ],
        )

        facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=True,
        )

        # Should extract IDs and pass to filter
        mock_filter.filter_archived.assert_called_once_with(["msg001", "msg002"], incremental=True)

    @pytest.mark.unit
    def test_archive_with_partial_failure(self, facade, mock_lister, mock_filter, mock_writer):
        """Test archive with some messages failing."""
        # Configure writer to report partial failure
        mock_writer.archive_messages.return_value = {
            "archived_count": 1,
            "failed_count": 1,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox",
        }

        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=False,
        )

        # Should return failure info from writer
        assert result["archived_count"] == 1
        assert result["failed_count"] == 1
        assert result["interrupted"] is False

    @pytest.mark.unit
    def test_archive_with_interruption(self, facade, mock_lister, mock_filter, mock_writer):
        """Test archive with interrupted archiving."""
        # Configure writer to report interruption
        mock_writer.archive_messages.return_value = {
            "archived_count": 1,
            "failed_count": 0,
            "interrupted": True,
            "actual_file": "/tmp/archive.mbox",
        }

        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",
            dry_run=False,
        )

        # Should return interrupted flag from writer
        assert result["interrupted"] is True
        assert result["archived_count"] == 1

    @pytest.mark.unit
    def test_archive_passes_actual_file_from_writer(
        self, facade, mock_lister, mock_filter, mock_writer
    ):
        """Test that actual_file from writer is returned."""
        # Writer might modify file extension (e.g., add .gz)
        mock_writer.archive_messages.return_value = {
            "archived_count": 2,
            "failed_count": 0,
            "interrupted": False,
            "actual_file": "/tmp/archive.mbox.gz",  # Modified by writer
        }

        result = facade.archive(
            age_threshold="3y",
            output_file="/tmp/archive.mbox",  # Original request
            compress="gzip",
            dry_run=False,
        )

        # Should return actual file from writer
        assert result["actual_file"] == "/tmp/archive.mbox.gz"


class TestArchiverFacadeEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def facade(self):
        """Create basic facade for edge case testing."""
        with patch("gmailarchiver.core.archiver.facade.MessageLister"):
            with patch("gmailarchiver.core.archiver.facade.MessageFilter"):
                with patch("gmailarchiver.core.archiver.facade.MessageWriter"):
                    return ArchiverFacade(gmail_client=Mock())

    @pytest.mark.unit
    def test_archive_with_none_operation_handle(self, facade):
        """Test archive with operation=None (default)."""
        with patch.object(facade._lister, "list_messages", return_value=("query", [])):
            result = facade.archive(
                age_threshold="3y",
                output_file="/tmp/archive.mbox",
                operation=None,
            )

        # Should handle None operation gracefully
        assert "found_count" in result

    @pytest.mark.unit
    def test_list_messages_with_none_progress_callback(self, facade):
        """Test list_messages with progress_callback=None (default)."""
        with patch.object(
            facade._lister,
            "list_messages",
            return_value=("query", [{"id": "msg001"}]),
        ):
            query, messages = facade.list_messages_for_archive("3y", progress_callback=None)

        # Should pass None callback to lister
        assert query is not None
        assert len(messages) == 1

    @pytest.mark.unit
    def test_archive_messages_with_empty_list(self, facade):
        """Test archive_messages with empty message list."""
        with patch.object(
            facade._writer,
            "archive_messages",
            return_value={
                "archived_count": 0,
                "failed_count": 0,
                "interrupted": False,
                "actual_file": "/tmp/archive.mbox",
            },
        ):
            result = facade.archive_messages([], "/tmp/archive.mbox")

        # Should delegate to writer even with empty list
        assert result["archived_count"] == 0

    @pytest.mark.unit
    def test_filter_with_empty_list(self, facade):
        """Test filter_already_archived with empty message list."""
        with patch.object(facade._filter, "filter_archived", return_value=([], 0)):
            filtered, skipped = facade.filter_already_archived([], incremental=True)

        # Should return empty results
        assert filtered == []
        assert skipped == 0
