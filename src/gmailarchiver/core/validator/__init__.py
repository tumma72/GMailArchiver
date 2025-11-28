"""Archive validation package.

Provides validation of mbox archives with support for:
- Compression handling (gzip, lzma, zstd)
- Message counting and integrity checks
- Database consistency validation
- Offset verification for v1.1 schemas
"""

from ..validator_legacy import (
    ArchiveValidator,
    ConsistencyReport,
    OffsetVerificationResult,
)
from ._checksum import ChecksumValidator
from ._counter import MessageCounter
from ._decompressor import Decompressor
from .facade import ValidatorFacade

# Re-export for backward compatibility
__all__ = [
    "ValidatorFacade",
    "ArchiveValidator",
    "ConsistencyReport",
    "OffsetVerificationResult",
    "Decompressor",
    "MessageCounter",
    "ChecksumValidator",
]
