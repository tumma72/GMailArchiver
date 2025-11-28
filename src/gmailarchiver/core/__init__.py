"""Core layer - business logic for archiving operations."""

from .archiver_legacy import GmailArchiver
from .compressor import ArchiveCompressor, CompressionResult, CompressionSummary
from .consolidator import ArchiveConsolidator, ConsolidationResult
from .deduplicator import (
    DeduplicationError,
    DeduplicationReport,
    DeduplicationResult,
    MessageDeduplicator,
    MessageInfo,
)
from .doctor import CheckResult, CheckSeverity, Doctor, DoctorReport, FixResult
from .extractor import ExtractorError, ExtractStats, MessageExtractor
from .importer_legacy import ArchiveImporter, ImportResult, MultiImportResult
from .search import MessageSearchResult, SearchEngine, SearchResults
from .validator_legacy import (
    ArchiveValidator,
    ConsistencyReport,
    OffsetVerificationResult,
)

__all__ = [
    # Archiver
    "GmailArchiver",
    # Validator
    "ArchiveValidator",
    "OffsetVerificationResult",
    "ConsistencyReport",
    # Importer
    "ArchiveImporter",
    "ImportResult",
    "MultiImportResult",
    # Consolidator
    "ArchiveConsolidator",
    "ConsolidationResult",
    # Deduplicator
    "MessageDeduplicator",
    "DeduplicationError",
    "DeduplicationReport",
    "DeduplicationResult",
    "MessageInfo",
    # Search
    "SearchEngine",
    "SearchResults",
    "MessageSearchResult",
    # Extractor
    "MessageExtractor",
    "ExtractorError",
    "ExtractStats",
    # Compressor
    "ArchiveCompressor",
    "CompressionResult",
    "CompressionSummary",
    # Doctor
    "Doctor",
    "DoctorReport",
    "CheckResult",
    "CheckSeverity",
    "FixResult",
]
