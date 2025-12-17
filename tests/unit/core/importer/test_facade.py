"""Unit tests for ImporterFacade.

Tests the facade orchestration layer that coordinates all importer modules.
Uses mocks for all dependencies.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gmailarchiver.core.importer.facade import ImporterFacade, ImportResult


@pytest.mark.unit
class TestImporterFacadeInit:
    """Tests for ImporterFacade initialization."""

    def test_init_minimal(self) -> None:
        """Test initialization with minimal parameters."""
        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        assert facade.db_manager == mock_db
        assert facade.gmail_client is None

    def test_init_with_gmail_client(self) -> None:
        """Test initialization with Gmail client."""
        mock_db = Mock()
        mock_client = Mock()
        facade = ImporterFacade(db_manager=mock_db, gmail_client=mock_client)
        assert facade.gmail_client == mock_client


@pytest.mark.unit
class TestImporterFacadeCountMessages:
    """Tests for count_messages method."""

    @patch("gmailarchiver.core.importer.facade.FileScanner")
    @patch("gmailarchiver.core.importer.facade.MboxReader")
    @patch("gmailarchiver.core.importer.facade.Path.exists")
    def test_count_messages_uncompressed(
        self, mock_exists: Mock, mock_reader_class: Mock, mock_scanner_class: Mock
    ) -> None:
        """Test counting messages in uncompressed mbox."""
        # Mock Path.exists()
        mock_exists.return_value = True

        # Setup mocks
        mock_scanner = Mock()
        mock_scanner.decompress_to_temp.return_value = (Path("/tmp/test.mbox"), False)
        mock_scanner_class.return_value = mock_scanner

        mock_reader = Mock()
        mock_reader.count_messages.return_value = 42
        mock_reader_class.return_value = mock_reader

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        count = facade.count_messages("/tmp/test.mbox")

        assert count == 42
        mock_scanner.decompress_to_temp.assert_called_once()
        mock_reader.count_messages.assert_called_once()
        mock_scanner.cleanup_temp_file.assert_called_once()

    @patch("gmailarchiver.core.importer.facade.FileScanner")
    @patch("gmailarchiver.core.importer.facade.MboxReader")
    @patch("gmailarchiver.core.importer.facade.Path.exists")
    def test_count_messages_compressed(
        self, mock_exists: Mock, mock_reader_class: Mock, mock_scanner_class: Mock
    ) -> None:
        """Test counting messages in compressed mbox."""
        # Mock Path.exists()
        mock_exists.return_value = True

        mock_scanner = Mock()
        mock_scanner.decompress_to_temp.return_value = (Path("/tmp/temp.mbox"), True)
        mock_scanner_class.return_value = mock_scanner

        mock_reader = Mock()
        mock_reader.count_messages.return_value = 10
        mock_reader_class.return_value = mock_reader

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        count = facade.count_messages("/tmp/test.mbox.gz")

        assert count == 10
        mock_scanner.cleanup_temp_file.assert_called_once()

    @patch("gmailarchiver.core.importer.facade.Path.exists")
    def test_count_messages_file_not_found(self, mock_exists: Mock) -> None:
        """Test counting when file doesn't exist."""
        mock_exists.return_value = False

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        count = facade.count_messages("/tmp/missing.mbox")

        assert count == 0


@pytest.mark.unit
class TestImporterFacadeImportArchive:
    """Tests for import_archive method."""

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.importer.facade.FileScanner")
    @patch("gmailarchiver.core.importer.facade.MboxReader")
    @patch("gmailarchiver.core.importer.facade.DatabaseWriter")
    @patch("gmailarchiver.core.importer.facade.time")
    @patch("gmailarchiver.core.importer.facade.Path.exists")
    async def test_import_archive_basic_flow(
        self,
        mock_exists: Mock,
        mock_time: Mock,
        mock_writer_class: Mock,
        mock_reader_class: Mock,
        mock_scanner_class: Mock,
    ) -> None:
        """Test basic import flow without Gmail lookups."""
        # Mock Path.exists()
        mock_exists.return_value = True

        # Mock time
        mock_time.time.side_effect = [1000.0, 1001.0]  # 1 second execution

        # Setup mocks
        mock_scanner = Mock()
        mock_scanner.decompress_to_temp.return_value = (Path("/tmp/test.mbox"), False)
        mock_scanner_class.return_value = mock_scanner

        mock_message = Mock()
        mock_message.message.__getitem__ = Mock(side_effect=lambda k: "test@example.com")
        mock_message.offset = 0
        mock_message.length = 100

        mock_reader = Mock()
        mock_reader.read_messages.return_value = [mock_message]
        mock_reader.extract_rfc_message_id.return_value = "<test@example.com>"
        mock_reader.extract_metadata.return_value = Mock(
            rfc_message_id="<test@example.com>", gmail_id=None
        )
        # Mock the new scan_rfc_message_ids method
        mock_reader.scan_rfc_message_ids.return_value = [("<test@example.com>", 0, 100)]
        mock_reader_class.return_value = mock_reader

        from gmailarchiver.core.importer._writer import WriteResult

        mock_writer = Mock()
        mock_writer.load_existing_ids = AsyncMock(return_value=set())
        mock_writer.is_duplicate.return_value = False
        mock_writer.write_message = AsyncMock(return_value=WriteResult.IMPORTED)
        mock_writer.record_archive_run = AsyncMock()
        mock_writer_class.return_value = mock_writer

        # Import
        mock_db = Mock()
        mock_db.commit = AsyncMock()
        mock_db.get_all_rfc_message_ids = AsyncMock(return_value=set())  # No existing messages
        facade = ImporterFacade(db_manager=mock_db)
        result = await facade.import_archive("/tmp/test.mbox")

        assert isinstance(result, ImportResult)
        assert result.archive_file == "/tmp/test.mbox"
        assert result.messages_imported == 1
        assert result.messages_skipped == 0
        assert result.messages_failed == 0
        assert result.execution_time_ms == 1000.0

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.importer.facade.Path.exists")
    async def test_import_archive_file_not_found(self, mock_exists: Mock) -> None:
        """Test import when file doesn't exist."""
        mock_exists.return_value = False

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)

        with pytest.raises(FileNotFoundError, match="Archive not found"):
            await facade.import_archive("/tmp/missing.mbox")


@pytest.mark.unit
class TestImporterFacadeImportMultiple:
    """Tests for import_multiple method."""

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.importer.facade.FileScanner")
    @patch("gmailarchiver.core.importer.facade.ImporterFacade.import_archive")
    async def test_import_multiple_success(
        self, mock_import: AsyncMock, mock_scanner_class: Mock
    ) -> None:
        """Test importing multiple archives."""
        mock_scanner = Mock()
        mock_scanner.scan_pattern.return_value = [
            Path("/tmp/archive1.mbox"),
            Path("/tmp/archive2.mbox"),
        ]
        mock_scanner_class.return_value = mock_scanner

        result1 = ImportResult(
            archive_file="/tmp/archive1.mbox",
            messages_imported=10,
            messages_skipped=2,
            messages_failed=0,
            execution_time_ms=500.0,
        )
        result2 = ImportResult(
            archive_file="/tmp/archive2.mbox",
            messages_imported=5,
            messages_skipped=1,
            messages_failed=0,
            execution_time_ms=300.0,
        )
        mock_import.side_effect = [result1, result2]

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        multi_result = await facade.import_multiple("/tmp/*.mbox")

        assert multi_result.total_files == 2
        assert multi_result.total_messages_imported == 15
        assert multi_result.total_messages_skipped == 3
        assert multi_result.total_messages_failed == 0
        assert len(multi_result.file_results) == 2

    @pytest.mark.asyncio
    @patch("gmailarchiver.core.importer.facade.FileScanner")
    async def test_import_multiple_no_matches(self, mock_scanner_class: Mock) -> None:
        """Test importing when glob pattern matches no files."""
        mock_scanner = Mock()
        mock_scanner.scan_pattern.return_value = []
        mock_scanner_class.return_value = mock_scanner

        mock_db = Mock()
        facade = ImporterFacade(db_manager=mock_db)
        multi_result = await facade.import_multiple("/tmp/*.mbox")

        assert multi_result.total_files == 0
        assert multi_result.total_messages_imported == 0
        assert len(multi_result.file_results) == 0
