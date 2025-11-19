"""Tests for archive validation module."""

import gzip
import hashlib
import lzma
import mailbox
import sqlite3
import tempfile
from compression import zstd
from pathlib import Path
from unittest.mock import patch

from gmailarchiver.validator import ArchiveValidator


class TestArchiveValidatorInit:
    """Tests for ArchiveValidator initialization."""

    def test_init(self) -> None:
        """Test initialization."""
        validator = ArchiveValidator('archive.mbox', 'state.db')
        assert validator.archive_path == Path('archive.mbox')
        assert validator.state_db_path == Path('state.db')
        assert validator.errors == []


class TestGetMboxPath:
    """Tests for _get_mbox_path method."""

    def test_get_mbox_path_uncompressed(self) -> None:
        """Test getting path for uncompressed mbox."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        try:
            validator = ArchiveValidator(str(mbox_path))
            path, is_temp = validator._get_mbox_path()

            assert path == mbox_path
            assert is_temp is False
        finally:
            mbox_path.unlink()

    def test_get_mbox_path_gzip(self) -> None:
        """Test decompressing gzip archive."""
        # Create a test mbox
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            test_mbox = Path(f.name)
            f.write(b'From test@example.com\nSubject: Test\n\nBody')

        # Compress it
        with tempfile.NamedTemporaryFile(suffix='.gz', delete=False) as f:
            gz_path = Path(f.name)

        try:
            with gzip.open(gz_path, 'wb') as f_out:
                with open(test_mbox, 'rb') as f_in:
                    f_out.write(f_in.read())

            validator = ArchiveValidator(str(gz_path))
            path, is_temp = validator._get_mbox_path()

            assert is_temp is True
            assert path.exists()
            assert path.suffix == '.mbox'

            # Clean up temp file
            if path.exists():
                path.unlink()
        finally:
            test_mbox.unlink()
            gz_path.unlink()

    def test_get_mbox_path_lzma(self) -> None:
        """Test decompressing lzma archive."""
        # Create a test mbox
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            test_mbox = Path(f.name)
            f.write(b'From test@example.com\nSubject: Test\n\nBody')

        # Compress it
        with tempfile.NamedTemporaryFile(suffix='.xz', delete=False) as f:
            xz_path = Path(f.name)

        try:
            with lzma.open(xz_path, 'wb') as f_out:
                with open(test_mbox, 'rb') as f_in:
                    f_out.write(f_in.read())

            validator = ArchiveValidator(str(xz_path))
            path, is_temp = validator._get_mbox_path()

            assert is_temp is True
            assert path.exists()
            assert path.suffix == '.mbox'

            # Clean up temp file
            if path.exists():
                path.unlink()
        finally:
            test_mbox.unlink()
            xz_path.unlink()

    def test_get_mbox_path_zstd(self) -> None:
        """Test decompressing zstd archive."""
        # Create a test mbox
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            test_mbox = Path(f.name)
            f.write(b'From test@example.com\nSubject: Test\n\nBody')

        # Compress it
        with tempfile.NamedTemporaryFile(suffix='.zst', delete=False) as f:
            zst_path = Path(f.name)

        try:
            with zstd.open(zst_path, 'wb') as f_out:
                with open(test_mbox, 'rb') as f_in:
                    f_out.write(f_in.read())

            validator = ArchiveValidator(str(zst_path))
            path, is_temp = validator._get_mbox_path()

            assert is_temp is True
            assert path.exists()
            assert path.suffix == '.mbox'

            # Clean up temp file
            if path.exists():
                path.unlink()
        finally:
            test_mbox.unlink()
            zst_path.unlink()

    def test_get_mbox_path_unknown_extension(self) -> None:
        """Test handling unknown file extension."""
        with tempfile.NamedTemporaryFile(suffix='.unknown', delete=False) as f:
            unknown_path = Path(f.name)

        try:
            validator = ArchiveValidator(str(unknown_path))
            path, is_temp = validator._get_mbox_path()

            # Should return as-is
            assert path == unknown_path
            assert is_temp is False
        finally:
            unknown_path.unlink()


class TestValidateComprehensive:
    """Tests for validate_comprehensive method."""

    def test_validate_comprehensive_success(self) -> None:
        """Test successful comprehensive validation."""
        # Create test mbox with 2 messages
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        # Create test database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with test messages
            mbox = mailbox.mbox(str(mbox_path))
            msg1 = mailbox.mboxMessage()
            msg1['From'] = 'test1@example.com'
            msg1['Subject'] = 'Test 1'
            msg1.set_payload('Body 1')
            mbox.add(msg1)

            msg2 = mailbox.mboxMessage()
            msg2['From'] = 'test2@example.com'
            msg2['Subject'] = 'Test 2'
            msg2.set_payload('Body 2')
            mbox.add(msg2)
            mbox.close()

            # Create test database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE archived_messages (
                    gmail_id TEXT PRIMARY KEY,
                    archived_timestamp TEXT,
                    archive_file TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    message_date TEXT,
                    checksum TEXT
                )
            ''')
            conn.execute(
                'INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('msg1', '2025-01-01', 'archive.mbox', 'Test 1',
                 'test1@example.com', '2025-01-01', 'abc')
            )
            conn.execute(
                'INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('msg2', '2025-01-01', 'archive.mbox', 'Test 2',
                 'test2@example.com', '2025-01-01', 'def')
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            expected_ids = {'msg1', 'msg2'}
            results = validator.validate_comprehensive(expected_ids, sample_size=2)

            assert results['count_check'] is True
            assert results['database_check'] is True
            assert results['integrity_check'] is True
            assert results['spot_check'] is True
            assert results['passed'] is True
            assert results['errors'] == []

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_validate_comprehensive_count_mismatch(self) -> None:
        """Test validation with count mismatch."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['From'] = 'test@example.com'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Create database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE archived_messages (
                    gmail_id TEXT PRIMARY KEY,
                    archived_timestamp TEXT,
                    archive_file TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    message_date TEXT,
                    checksum TEXT
                )
            ''')
            conn.execute(
                'INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('msg1', '2025-01-01', 'archive.mbox', 'Test',
                 'test@example.com', '2025-01-01', 'abc')
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            # Expect 2 messages but only have 1
            expected_ids = {'msg1', 'msg2'}
            results = validator.validate_comprehensive(expected_ids, sample_size=2)

            assert results['count_check'] is False
            assert results['passed'] is False
            assert any('Count mismatch' in err for err in results['errors'])

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_validate_comprehensive_db_not_found(self) -> None:
        """Test validation when database doesn't exist."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create empty mbox
            mbox = mailbox.mbox(str(mbox_path))
            mbox.close()

            validator = ArchiveValidator(str(mbox_path), '/nonexistent/db.db')
            results = validator.validate_comprehensive(set(), sample_size=10)

            assert results['database_check'] is False
            assert any('State database not found' in err for err in results['errors'])

        finally:
            mbox_path.unlink()

    def test_validate_comprehensive_invalid_mbox(self) -> None:
        """Test validation with invalid mbox file."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)
            # Write invalid content
            f.write(b'Not a valid mbox file')

        try:
            validator = ArchiveValidator(str(mbox_path), 'nonexistent.db')
            results = validator.validate_comprehensive({'msg1'}, sample_size=10)

            # Should fail gracefully
            assert results['passed'] is False

        finally:
            mbox_path.unlink()

    def test_validate_comprehensive_empty_expected_ids(self) -> None:
        """Test validation with empty expected IDs (spot check skipped)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create empty mbox
            mbox = mailbox.mbox(str(mbox_path))
            mbox.close()

            # Create empty database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE archived_messages (
                    gmail_id TEXT PRIMARY KEY,
                    archived_timestamp TEXT,
                    archive_file TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    message_date TEXT,
                    checksum TEXT
                )
            ''')
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            results = validator.validate_comprehensive(set(), sample_size=10)

            # Spot check should be skipped for empty expected_ids
            # Overall validation considers: spot_check OR not expected_message_ids
            # So it should still be able to pass other checks
            assert results['count_check'] is True  # 0 == 0
            assert results['database_check'] is True  # 0 >= 0

        finally:
            mbox_path.unlink()
            db_path.unlink()


class TestValidateCount:
    """Tests for validate_count method."""

    def test_validate_count_match(self) -> None:
        """Test count validation with matching count."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        try:
            mbox = mailbox.mbox(str(mbox_path))
            for i in range(3):
                msg = mailbox.mboxMessage()
                msg['From'] = f'test{i}@example.com'
                msg.set_payload(f'Body {i}')
                mbox.add(msg)
            mbox.close()

            validator = ArchiveValidator(str(mbox_path))
            assert validator.validate_count(3) is True

        finally:
            mbox_path.unlink()

    def test_validate_count_mismatch(self) -> None:
        """Test count validation with mismatching count."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        try:
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['From'] = 'test@example.com'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            validator = ArchiveValidator(str(mbox_path))
            assert validator.validate_count(5) is False

        finally:
            mbox_path.unlink()

    def test_validate_count_invalid_file(self) -> None:
        """Test count validation with invalid file."""
        validator = ArchiveValidator('/nonexistent/file.mbox')
        assert validator.validate_count(10) is False
        assert len(validator.errors) > 0


class TestComputeChecksum:
    """Tests for compute_checksum method."""

    def test_compute_checksum(self) -> None:
        """Test checksum computation."""
        validator = ArchiveValidator('dummy.mbox')
        data = b'test data'
        expected = hashlib.sha256(data).hexdigest()

        checksum = validator.compute_checksum(data)

        assert checksum == expected

    def test_compute_checksum_different_data(self) -> None:
        """Test that different data produces different checksum."""
        validator = ArchiveValidator('dummy.mbox')
        checksum1 = validator.compute_checksum(b'data1')
        checksum2 = validator.compute_checksum(b'data2')

        assert checksum1 != checksum2


class TestReport:
    """Tests for report method."""

    @patch('builtins.print')
    def test_report_success(self, mock_print: patch) -> None:
        """Test report with successful validation."""
        validator = ArchiveValidator('archive.mbox')
        results = {
            'count_check': True,
            'database_check': True,
            'integrity_check': True,
            'spot_check': True,
            'errors': [],
            'passed': True
        }

        validator.report(results)

        # Verify print was called (report prints the validation status)
        assert mock_print.called
        # Check that success message appears
        calls = [str(call) for call in mock_print.call_args_list]
        full_output = ' '.join(calls)
        assert 'PASSED' in full_output

    @patch('builtins.print')
    def test_report_failure(self, mock_print: patch) -> None:
        """Test report with failed validation."""
        validator = ArchiveValidator('archive.mbox')
        results = {
            'count_check': False,
            'database_check': True,
            'integrity_check': True,
            'spot_check': False,
            'errors': ['Count mismatch', 'Spot check failed'],
            'passed': False
        }

        validator.report(results)

        # Verify print was called
        assert mock_print.called
        # Check that failure message and errors appear
        calls = [str(call) for call in mock_print.call_args_list]
        full_output = ' '.join(calls)
        assert 'FAILED' in full_output
        assert 'Count mismatch' in full_output


class TestOffsetVerification:
    """Tests for offset verification (v1.1 schema)."""

    def test_verify_offsets_valid_offsets(self) -> None:
        """Test verify_offsets with valid offsets (all pass)."""
        # Create test mbox with 2 messages
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        # Create test database with v1.1 schema
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with test messages
            mbox = mailbox.mbox(str(mbox_path))
            msg1 = mailbox.mboxMessage()
            msg1['Message-ID'] = '<msg1@example.com>'
            msg1['From'] = 'test1@example.com'
            msg1['Subject'] = 'Test 1'
            msg1.set_payload('Body 1')
            mbox.add(msg1)

            msg2 = mailbox.mboxMessage()
            msg2['Message-ID'] = '<msg2@example.com>'
            msg2['From'] = 'test2@example.com'
            msg2['Subject'] = 'Test 2'
            msg2.set_payload('Body 2')
            mbox.add(msg2)
            mbox.close()

            # Read mbox to get actual offsets and lengths
            with open(mbox_path, 'rb') as f:
                content = f.read()
                # Find offsets for each message (they start with "From ")
                offset1 = content.find(b'From ')
                offset2 = content.find(b'From ', offset1 + 1)
                length1 = offset2 - offset1 if offset2 != -1 else len(content) - offset1
                length2 = len(content) - offset2 if offset2 != -1 else 0

            # Create v1.1 database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    thread_id TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    to_addr TEXT,
                    cc_addr TEXT,
                    date TIMESTAMP,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL,
                    body_preview TEXT,
                    checksum TEXT,
                    size_bytes INTEGER,
                    labels TEXT,
                    account_id TEXT DEFAULT 'default'
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, subject, from_addr,
                   archived_timestamp, archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', 'Test 1', 'test1@example.com',
                 '2025-01-01', str(mbox_path), offset1, length1)
            )
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, subject, from_addr,
                   archived_timestamp, archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                ('gmail2', '<msg2@example.com>', 'Test 2', 'test2@example.com',
                 '2025-01-01', str(mbox_path), offset2, length2)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            result = validator.verify_offsets()

            assert result.total_checked == 2
            assert result.successful_reads == 2
            assert result.failed_reads == 0
            assert result.accuracy_percentage == 100.0
            assert len(result.failures) == 0

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_offsets_compressed_archive(self) -> None:
        """Test verify_offsets with a gzip-compressed archive."""
        # Create uncompressed mbox and corresponding compressed archive
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.mbox.gz', delete=False) as f:
            gz_path = Path(f.name)

        try:
            # Create mbox with a single message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg['From'] = 'test@example.com'
            msg['Subject'] = 'Test compressed'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Compute offset and length in the uncompressed mbox
            with open(mbox_path, 'rb') as f_in:
                content = f_in.read()
                offset = content.find(b'From ')
                length = len(content) - offset

            # Compress to gzip archive
            with open(mbox_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    f_out.write(f_in.read())

            # Create v1.1 database referencing the compressed archive file
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(gz_path), offset, length)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(gz_path), str(db_path))
            result = validator.verify_offsets()

            assert result.total_checked == 1
            assert result.successful_reads == 1
            assert result.failed_reads == 0
            assert result.accuracy_percentage == 100.0
            assert len(result.failures) == 0

        finally:
            mbox_path.unlink()
            db_path.unlink()
            gz_path.unlink()

    def test_verify_offsets_corrupted_offset(self) -> None:
        """Test verify_offsets with corrupted offset (fails gracefully)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg['From'] = 'test@example.com'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Create v1.1 database with WRONG offset
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(mbox_path), 99999, 100)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            result = validator.verify_offsets()

            assert result.total_checked == 1
            assert result.successful_reads == 0
            assert result.failed_reads == 1
            assert result.accuracy_percentage == 0.0
            assert len(result.failures) == 1

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_offsets_wrong_message_id(self) -> None:
        """Test verify_offsets with wrong Message-ID (detects mismatch)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<actual@example.com>'
            msg['From'] = 'test@example.com'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Get actual offset
            with open(mbox_path, 'rb') as f:
                content = f.read()
                offset = content.find(b'From ')
                length = len(content) - offset

            # Create v1.1 database with WRONG Message-ID
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<wrong@example.com>', '2025-01-01', str(mbox_path), offset, length)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            result = validator.verify_offsets()

            assert result.total_checked == 1
            assert result.successful_reads == 0
            assert result.failed_reads == 1
            assert 'Message-ID mismatch' in result.failures[0]

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_offsets_v10_schema(self) -> None:
        """Test verify_offsets with v1.0 schema (skips gracefully)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create empty mbox
            mbox = mailbox.mbox(str(mbox_path))
            mbox.close()

            # Create v1.0 database (old schema without offsets)
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE archived_messages (
                    gmail_id TEXT PRIMARY KEY,
                    archived_timestamp TEXT,
                    archive_file TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    message_date TEXT,
                    checksum TEXT
                )
            ''')
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            result = validator.verify_offsets()

            # Should skip verification for v1.0 schema
            assert result.total_checked == 0
            assert result.successful_reads == 0
            assert result.failed_reads == 0
            assert result.skipped is True

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_offsets_length_mismatch(self) -> None:
        """Test verify_offsets with incorrect mbox_length."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg['From'] = 'test@example.com'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Get actual offset and actual length
            with open(mbox_path, 'rb') as f:
                content = f.read()
                offset = content.find(b'From ')
                actual_length = len(content) - offset

            # Create v1.1 database with WRONG length (larger than file)
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(mbox_path),
                 offset, actual_length + 1000)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            result = validator.verify_offsets()

            assert result.total_checked == 1
            assert result.failed_reads == 1
            assert 'length mismatch' in result.failures[0].lower()

        finally:
            mbox_path.unlink()
            db_path.unlink()


class TestConsistencyChecks:
    """Tests for deep database consistency checks."""

    def test_verify_consistency_perfect_database(self) -> None:
        """Test verify_consistency with perfect database (all checks pass)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 2 messages
            mbox = mailbox.mbox(str(mbox_path))
            msg1 = mailbox.mboxMessage()
            msg1['Message-ID'] = '<msg1@example.com>'
            msg1['From'] = 'test1@example.com'
            msg1.set_payload('Body 1')
            mbox.add(msg1)

            msg2 = mailbox.mboxMessage()
            msg2['Message-ID'] = '<msg2@example.com>'
            msg2['From'] = 'test2@example.com'
            msg2.set_payload('Body 2')
            mbox.add(msg2)
            mbox.close()

            # Create v1.1 database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    subject TEXT,
                    from_addr TEXT,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute('''
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    subject,
                    from_addr,
                    content=messages,
                    content_rowid=rowid
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, subject, from_addr,
                   archived_timestamp, archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', 'Test 1', 'test1@example.com',
                 '2025-01-01', str(mbox_path), 0, 100)
            )
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, subject, from_addr,
                   archived_timestamp, archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                ('gmail2', '<msg2@example.com>', 'Test 2', 'test2@example.com',
                 '2025-01-01', str(mbox_path), 100, 100)
            )
            # Sync FTS5
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            report = validator.verify_consistency()

            assert report.orphaned_records == 0
            assert report.missing_records == 0
            assert report.duplicate_gmail_ids == 0
            assert report.duplicate_rfc_message_ids == 0
            assert report.fts_synced is True
            assert report.passed is True

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_consistency_orphaned_records(self) -> None:
        """Test verify_consistency with orphaned records (detects)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Create v1.1 database with 2 messages (one orphaned)
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(mbox_path), 0, 100)
            )
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail2', '<orphan@example.com>', '2025-01-01', str(mbox_path), 100, 100)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            report = validator.verify_consistency()

            assert report.orphaned_records == 1
            assert report.passed is False

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_consistency_missing_records(self) -> None:
        """Test verify_consistency with missing records (detects)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 2 messages
            mbox = mailbox.mbox(str(mbox_path))
            msg1 = mailbox.mboxMessage()
            msg1['Message-ID'] = '<msg1@example.com>'
            msg1.set_payload('Body 1')
            mbox.add(msg1)

            msg2 = mailbox.mboxMessage()
            msg2['Message-ID'] = '<msg2@example.com>'
            msg2.set_payload('Body 2')
            mbox.add(msg2)
            mbox.close()

            # Create v1.1 database with only 1 message (one missing)
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(mbox_path), 0, 100)
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            report = validator.verify_consistency()

            assert report.missing_records == 1
            assert report.passed is False

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_consistency_fts_desync(self) -> None:
        """Test verify_consistency with FTS5 desync (detects)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Create v1.1 database with messages table but empty FTS
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE messages (
                    gmail_id TEXT PRIMARY KEY,
                    rfc_message_id TEXT UNIQUE NOT NULL,
                    archived_timestamp TIMESTAMP NOT NULL,
                    archive_file TEXT NOT NULL,
                    mbox_offset INTEGER NOT NULL,
                    mbox_length INTEGER NOT NULL
                )
            ''')
            conn.execute('''
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    subject,
                    from_addr,
                    content=messages,
                    content_rowid=rowid
                )
            ''')
            conn.execute(
                '''INSERT INTO messages (gmail_id, rfc_message_id, archived_timestamp,
                   archive_file, mbox_offset, mbox_length)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('gmail1', '<msg1@example.com>', '2025-01-01', str(mbox_path), 0, 100)
            )
            # Don't sync FTS5 - create desync
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            report = validator.verify_consistency()

            assert report.fts_synced is False
            assert report.passed is False

        finally:
            mbox_path.unlink()
            db_path.unlink()

    def test_verify_consistency_v10_schema(self) -> None:
        """Test verify_consistency with v1.0 schema (limited checks)."""
        with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False) as f:
            mbox_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg['Message-ID'] = '<msg1@example.com>'
            msg.set_payload('Body')
            mbox.add(msg)
            mbox.close()

            # Create v1.0 database
            conn = sqlite3.connect(str(db_path))
            conn.execute('''
                CREATE TABLE archived_messages (
                    gmail_id TEXT PRIMARY KEY,
                    archived_timestamp TEXT,
                    archive_file TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    message_date TEXT,
                    checksum TEXT
                )
            ''')
            conn.execute(
                'INSERT INTO archived_messages VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('gmail1', '2025-01-01', 'archive.mbox', 'Test',
                 'test@example.com', '2025-01-01', 'abc')
            )
            conn.commit()
            conn.close()

            validator = ArchiveValidator(str(mbox_path), str(db_path))
            report = validator.verify_consistency()

            # Should have limited checks for v1.0 schema
            assert report.schema_version == '1.0'
            assert report.fts_synced is True  # No FTS in v1.0

        finally:
            mbox_path.unlink()
            db_path.unlink()
