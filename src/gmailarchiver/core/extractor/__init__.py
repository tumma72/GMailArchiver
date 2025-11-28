"""Extractor package for message extraction."""

from gmailarchiver.core.extractor._extractor import ExtractorError
from gmailarchiver.core.extractor.facade import ExtractStats, MessageExtractor

__all__ = ["MessageExtractor", "ExtractorError", "ExtractStats"]
