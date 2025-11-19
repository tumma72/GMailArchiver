"""Tests for MessageExtractor class."""

import gzip
import lzma
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from gmailarchiver.db_manager import DBManager
from gmailarchiver.extractor import ExtractorError, MessageExtractor

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db(temp_dir: Path) -> Path:
    """Create temporary database with test messages."""
    db_path = temp_dir / "test.db"

    # Create database with v1.1 schema
    db = DBManager(str(db_path))

    # Add test messages
    test_messages = [
        {
            'gmail_id': 'msg001',
            'rfc_message_id': '<test001@example.com>',
            'archive_file': str(temp_dir / 'archive.mbox'),
            'mbox_offset': 0,
            'mbox_length': 100,
            'subject': 'Test Message 1',
            'from_addr': 'alice@example.com',
            'to_addr': 'bob@example.com',
        },
        {
            'gmail_id': 'msg002',
            'rfc_message_id': '<test002@example.com>',
            'archive_file': str(temp_dir / 'archive.mbox'),
            'mbox_offset': 100,
            'mbox_length': 150,
            'subject': 'Test Message 2',
            'from_addr': 'bob@example.com',
            'to_addr': 'alice@example.com',
        },
        {
            'gmail_id': 'msg003',
            'rfc_message_id': '<test003@example.com>',
            'archive_file': str(temp_dir / 'archive.mbox.gz'),
            'mbox_offset': 0,
            'mbox_length': 120,
            'subject': 'Test Message 3',
            'from_addr': 'charlie@example.com',
            'to_addr': 'alice@example.com',
        },
    ]

    for msg in test_messages:
        db.record_archived_message(
            gmail_id=msg['gmail_id'],
            rfc_message_id=msg['rfc_message_id'],
            archive_file=msg['archive_file'],
            mbox_offset=msg['mbox_offset'],
            mbox_length=msg['mbox_length'],
            subject=msg['subject'],
            from_addr=msg['from_addr'],
            to_addr=msg['to_addr'],
            record_run=False,
        )

    db.close()
    return db_path


@pytest.fixture
def sample_message() -> bytes:
    """Sample email message."""
    return b"""From alice@example.com Mon Jan 01 00:00:00 2024
From: alice@example.com
To: bob@example.com
Subject: Test Message
Message-ID: <test001@example.com>
Date: Mon, 01 Jan 2024 00:00:00 +0000

This is a test message body.
"""


@pytest.fixture
def uncompressed_mbox(temp_dir: Path, sample_message: bytes) -> Path:
    """Create uncompressed mbox file."""
    mbox_path = temp_dir / 'archive.mbox'

    # Write sample messages
    msg1 = sample_message
    msg2 = sample_message.replace(b'test001', b'test002').replace(b'Test Message', b'Test Message 2')

    with open(mbox_path, 'wb') as f:
        f.write(msg1)
        f.write(msg2)

    return mbox_path


@pytest.fixture
def compressed_mbox_gzip(temp_dir: Path, sample_message: bytes) -> Path:
    """Create gzip-compressed mbox file."""
    mbox_path = temp_dir / 'archive.mbox.gz'

    msg1 = sample_message.replace(b'test001', b'test003').replace(b'alice', b'charlie')

    with gzip.open(mbox_path, 'wb') as f:
        f.write(msg1)

    return mbox_path


@pytest.fixture
def compressed_mbox_lzma(temp_dir: Path, sample_message: bytes) -> Path:
    """Create lzma-compressed mbox file."""
    mbox_path = temp_dir / 'archive.mbox.xz'

    msg1 = sample_message.replace(b'test001', b'test004').replace(b'alice', b'dave')

    with lzma.open(mbox_path, 'wb') as f:
        f.write(msg1)

    return mbox_path


# ============================================================================
# Tests: Initialization
# ============================================================================


def test_init_with_existing_db(temp_db: Path) -> None:
    """Test initialization with existing database."""
    extractor = MessageExtractor(temp_db)
    assert extractor.db_path == temp_db
    extractor.close()


def test_init_with_missing_db(temp_dir: Path) -> None:
    """Test initialization with missing database."""
    missing_db = temp_dir / 'nonexistent.db'
    with pytest.raises(FileNotFoundError, match="Database not found"):
        MessageExtractor(missing_db)


def test_context_manager(temp_db: Path) -> None:
    """Test context manager protocol."""
    with MessageExtractor(temp_db) as extractor:
        assert extractor.db_path == temp_db
    # Database should be closed after context


# ============================================================================
# Tests: Extract by Gmail ID
# ============================================================================


def test_extract_by_gmail_id_success(
    temp_db: Path, uncompressed_mbox: Path, sample_message: bytes
) -> None:
    """Test extracting message by Gmail ID."""
    with MessageExtractor(temp_db) as extractor:
        message_bytes = extractor.extract_by_gmail_id('msg001', output_path=None)
        assert len(message_bytes) == 100  # As specified in fixture
        assert b'From: alice@example.com' in message_bytes


def test_extract_by_gmail_id_to_file(
    temp_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test extracting message to file."""
    output_file = temp_dir / 'extracted.eml'

    with MessageExtractor(temp_db) as extractor:
        extractor.extract_by_gmail_id('msg001', output_path=output_file)

    assert output_file.exists()
    assert output_file.stat().st_size == 100


def test_extract_by_gmail_id_not_found(temp_db: Path, uncompressed_mbox: Path) -> None:
    """Test extracting non-existent message by Gmail ID."""
    with MessageExtractor(temp_db) as extractor:
        with pytest.raises(ExtractorError, match="Message not found"):
            extractor.extract_by_gmail_id('nonexistent')


def test_extract_by_gmail_id_missing_archive(temp_db: Path) -> None:
    """Test extracting when archive file is missing."""
    with MessageExtractor(temp_db) as extractor:
        with pytest.raises(ExtractorError, match="Archive file not found"):
            extractor.extract_by_gmail_id('msg001')


# ============================================================================
# Tests: Extract by RFC Message-ID
# ============================================================================


def test_extract_by_rfc_message_id_success(
    temp_db: Path, uncompressed_mbox: Path
) -> None:
    """Test extracting message by RFC Message-ID."""
    with MessageExtractor(temp_db) as extractor:
        message_bytes = extractor.extract_by_rfc_message_id(
            '<test001@example.com>', output_path=None
        )
        assert len(message_bytes) == 100


def test_extract_by_rfc_message_id_not_found(
    temp_db: Path, uncompressed_mbox: Path
) -> None:
    """Test extracting non-existent message by RFC Message-ID."""
    with MessageExtractor(temp_db) as extractor:
        with pytest.raises(ExtractorError, match="Message not found"):
            extractor.extract_by_rfc_message_id('<nonexistent@example.com>')


# ============================================================================
# Tests: Compressed Archives
# ============================================================================


def test_extract_from_gzip(temp_db: Path, compressed_mbox_gzip: Path) -> None:
    """Test extracting from gzip-compressed archive."""
    with MessageExtractor(temp_db) as extractor:
        message_bytes = extractor.extract_by_gmail_id('msg003', output_path=None)
        assert len(message_bytes) == 120
        assert b'From: charlie@example.com' in message_bytes


def test_extract_from_lzma(temp_db: Path, temp_dir: Path, sample_message: bytes) -> None:
    """Test extracting from lzma-compressed archive."""
    # Create lzma archive and add to database
    mbox_path = temp_dir / 'archive.mbox.xz'
    msg = sample_message.replace(b'test001', b'test004')

    with lzma.open(mbox_path, 'wb') as f:
        f.write(msg)

    # Add message to database
    db = DBManager(str(temp_db))
    db.record_archived_message(
        gmail_id='msg004',
        rfc_message_id='<test004@example.com>',
        archive_file=str(mbox_path),
        mbox_offset=0,
        mbox_length=len(msg),
        record_run=False,
    )
    db.close()

    # Extract
    with MessageExtractor(temp_db) as extractor:
        message_bytes = extractor.extract_by_gmail_id('msg004', output_path=None)
        assert len(message_bytes) == len(msg)


def test_compression_format_detection(temp_db: Path) -> None:
    """Test compression format detection."""
    with MessageExtractor(temp_db) as extractor:
        assert extractor._get_compression_format(Path('test.mbox.gz')) == 'gzip'
        assert extractor._get_compression_format(Path('test.mbox.xz')) == 'lzma'
        assert extractor._get_compression_format(Path('test.mbox.lzma')) == 'lzma'
        assert extractor._get_compression_format(Path('test.mbox.zst')) == 'zstd'
        assert extractor._get_compression_format(Path('test.mbox')) is None


# ============================================================================
# Tests: Batch Extraction
# ============================================================================


def test_batch_extract_success(
    temp_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction of multiple messages."""
    output_dir = temp_dir / 'extracted'

    with MessageExtractor(temp_db) as extractor:
        stats = extractor.batch_extract(['msg001', 'msg002'], output_dir)

    assert stats['extracted'] == 2
    assert stats['failed'] == 0
    assert len(stats['errors']) == 0

    # Check files were created
    assert (output_dir / 'msg001.eml').exists()
    assert (output_dir / 'msg002.eml').exists()


def test_batch_extract_partial_failure(
    temp_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction with some failures."""
    output_dir = temp_dir / 'extracted'

    with MessageExtractor(temp_db) as extractor:
        stats = extractor.batch_extract(['msg001', 'nonexistent', 'msg002'], output_dir)

    assert stats['extracted'] == 2
    assert stats['failed'] == 1
    assert len(stats['errors']) == 1
    assert 'nonexistent' in stats['errors'][0]


def test_batch_extract_creates_directory(
    temp_db: Path, uncompressed_mbox: Path, temp_dir: Path
) -> None:
    """Test batch extraction creates output directory if it doesn't exist."""
    output_dir = temp_dir / 'new' / 'nested' / 'dir'

    with MessageExtractor(temp_db) as extractor:
        stats = extractor.batch_extract(['msg001'], output_dir)

    assert output_dir.exists()
    assert stats['extracted'] == 1


# ============================================================================
# Tests: Error Handling
# ============================================================================


def test_extract_with_invalid_offset(temp_db: Path, temp_dir: Path) -> None:
    """Test extraction with invalid offset (beyond file size)."""
    # Create small mbox file
    mbox_path = temp_dir / 'small.mbox'
    with open(mbox_path, 'wb') as f:
        f.write(b'Small content')

    # Add message with offset beyond file size
    db = DBManager(str(temp_db))
    db.record_archived_message(
        gmail_id='msg_invalid',
        rfc_message_id='<invalid@example.com>',
        archive_file=str(mbox_path),
        mbox_offset=10000,  # Way beyond file size
        mbox_length=100,
        record_run=False,
    )
    db.close()

    # Try to extract - should fail or return partial data
    with MessageExtractor(temp_db) as extractor:
        # This may not raise an error but will return less data than expected
        message_bytes = extractor.extract_by_gmail_id('msg_invalid', output_path=None)
        assert len(message_bytes) < 100  # Won't get full 100 bytes


def test_extract_from_corrupted_gzip(temp_db: Path, temp_dir: Path) -> None:
    """Test extraction from corrupted gzip file."""
    # Create corrupted gzip file
    corrupted_path = temp_dir / 'corrupted.mbox.gz'
    with open(corrupted_path, 'wb') as f:
        f.write(b'This is not a valid gzip file')

    # Add to database
    db = DBManager(str(temp_db))
    db.record_archived_message(
        gmail_id='msg_corrupted',
        rfc_message_id='<corrupted@example.com>',
        archive_file=str(corrupted_path),
        mbox_offset=0,
        mbox_length=100,
        record_run=False,
    )
    db.close()

    # Try to extract - should raise ExtractorError
    with MessageExtractor(temp_db) as extractor:
        with pytest.raises(ExtractorError, match="Failed to extract"):
            extractor.extract_by_gmail_id('msg_corrupted')


# ============================================================================
# Tests: Edge Cases
# ============================================================================


def test_extract_empty_message(temp_db: Path, temp_dir: Path) -> None:
    """Test extracting message with zero length."""
    # Create mbox with content
    mbox_path = temp_dir / 'archive.mbox'
    with open(mbox_path, 'wb') as f:
        f.write(b'Some content here')

    # Add message with zero length
    db = DBManager(str(temp_db))
    db.record_archived_message(
        gmail_id='msg_empty',
        rfc_message_id='<empty@example.com>',
        archive_file=str(mbox_path),
        mbox_offset=0,
        mbox_length=0,
        record_run=False,
    )
    db.close()

    # Extract
    with MessageExtractor(temp_db) as extractor:
        message_bytes = extractor.extract_by_gmail_id('msg_empty', output_path=None)
        assert len(message_bytes) == 0


def test_extract_with_special_characters_in_path(
    temp_db: Path, temp_dir: Path, sample_message: bytes
) -> None:
    """Test extraction when output path has special characters."""
    # Create mbox
    mbox_path = temp_dir / 'archive.mbox'
    with open(mbox_path, 'wb') as f:
        f.write(sample_message)

    # Update database with this path
    db = DBManager(str(temp_db))
    db.conn.execute(
        "UPDATE messages SET archive_file = ? WHERE gmail_id = ?",
        (str(mbox_path), 'msg001')
    )
    db.commit()
    db.close()

    # Extract to path with special characters
    output_file = temp_dir / 'test file [with] (special) chars.eml'

    with MessageExtractor(temp_db) as extractor:
        extractor.extract_by_gmail_id('msg001', output_path=output_file)

    assert output_file.exists()
