"""Archive validation package.

Provides validation of mbox archives with support for:
- Compression handling (gzip, lzma, zstd)
- Message counting and integrity checks
- Database consistency validation
- Offset verification for v1.1 schemas
"""

from ._checksum import ChecksumValidator
from ._counter import MessageCounter
from ._decompressor import Decompressor
from .facade import ConsistencyReport, OffsetVerificationResult, ValidatorFacade

# Re-export for backward compatibility - ValidatorFacade can be used as ArchiveValidator
__all__ = [
    "ValidatorFacade",
    "ConsistencyReport",
    "OffsetVerificationResult",
    "Decompressor",
    "MessageCounter",
    "ChecksumValidator",
]
