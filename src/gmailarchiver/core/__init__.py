"""Core layer - business logic for archiving operations."""

from .archiver import ArchiverFacade
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
from .importer import ImporterFacade, ImportResult, MultiImportResult
from .search import MessageSearchResult, SearchEngine, SearchResults
from .validator import ConsistencyReport, OffsetVerificationResult, ValidatorFacade

__all__ = [
    # Archiver
    "ArchiverFacade",
    # Validator
    "ValidatorFacade",
    "OffsetVerificationResult",
    "ConsistencyReport",
    # Importer
    "ImporterFacade",
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
