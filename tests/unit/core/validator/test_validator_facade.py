"""Unit tests for validator.facade module.

Tests the ValidatorFacade orchestration of internal modules.
"""

import mailbox
import tempfile
from pathlib import Path

import pytest


@pytest.mark.unit
class TestValidatorFacade:
    """Unit tests for ValidatorFacade class."""

    def test_init(self) -> None:
        """Test facade initialization."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        facade = ValidatorFacade("archive.mbox", "state.db")
        assert facade.archive_path == Path("archive.mbox")
        assert facade.state_db_path == Path("state.db")
        assert facade.errors == []

    def test_validate_all_with_valid_archive(self) -> None:
        """Test validate_all with valid archive."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create mbox with message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg["From"] = "test@example.com"
            msg.set_payload("Body")
            mbox.add(msg)
            mbox.close()

            facade = ValidatorFacade(str(mbox_path))
            result = facade.validate_all()

            assert result is True
            assert len(facade.errors) == 0
        finally:
            mbox_path.unlink()

    def test_validate_all_with_empty_archive(self) -> None:
        """Test validate_all with empty archive."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create empty mbox
            mbox_path.touch()

            facade = ValidatorFacade(str(mbox_path))
            result = facade.validate_all()

            assert result is False
            assert any("empty" in err.lower() for err in facade.errors)
        finally:
            mbox_path.unlink()

    def test_validate_count_match(self) -> None:
        """Test validate_count with matching count."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create mbox with 2 messages
            mbox = mailbox.mbox(str(mbox_path))
            for i in range(2):
                msg = mailbox.mboxMessage()
                msg["From"] = f"test{i}@example.com"
                msg.set_payload(f"Body {i}")
                mbox.add(msg)
            mbox.close()

            facade = ValidatorFacade(str(mbox_path))
            result = facade.validate_count(2)

            assert result is True
        finally:
            mbox_path.unlink()

    def test_validate_count_mismatch(self) -> None:
        """Test validate_count with mismatching count."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg["From"] = "test@example.com"
            msg.set_payload("Body")
            mbox.add(msg)
            mbox.close()

            facade = ValidatorFacade(str(mbox_path))
            result = facade.validate_count(5)

            assert result is False
            assert any("mismatch" in err.lower() for err in facade.errors)
        finally:
            mbox_path.unlink()

    def test_compute_checksum(self) -> None:
        """Test compute_checksum delegation."""
        import hashlib

        from gmailarchiver.core.validator.facade import ValidatorFacade

        facade = ValidatorFacade("dummy.mbox")
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()

        checksum = facade.compute_checksum(data)

        assert checksum == expected

    def test_validate_comprehensive_basic(self) -> None:
        """Test validate_comprehensive with basic validation."""
        from gmailarchiver.core.validator.facade import ValidatorFacade

        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            mbox_path = Path(f.name)

        try:
            # Create mbox with 1 message
            mbox = mailbox.mbox(str(mbox_path))
            msg = mailbox.mboxMessage()
            msg["From"] = "test@example.com"
            msg.set_payload("Body")
            mbox.add(msg)
            mbox.close()

            facade = ValidatorFacade(str(mbox_path))
            results = facade.validate_comprehensive({"msg1"})

            assert hasattr(results, "count_check")
            assert hasattr(results, "integrity_check")
            assert hasattr(results, "passed")
        finally:
            mbox_path.unlink()
