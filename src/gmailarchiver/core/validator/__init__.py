"""Archive validation package.

Provides validation of mbox archives with support for:
- Compression handling (gzip, lzma, zstd)
- Message counting and integrity checks
- Database consistency validation
- Offset verification for v1.1 schemas
"""

from gmailarchiver.core.validator._checksum import ChecksumValidator
from gmailarchiver.core.validator._counter import MessageCounter
from gmailarchiver.core.validator._decompressor import Decompressor
from gmailarchiver.core.validator.facade import ValidatorFacade

# Re-export for backward compatibility (will use legacy temporarily)
__all__ = [
    "Decompressor",
    "MessageCounter",
    "ChecksumValidator",
    "ValidatorFacade",
]
