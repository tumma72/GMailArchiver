"""Scan steps for mbox files.

This module provides steps for scanning mbox archives:
- ScanMboxStep: Scan mbox for RFC Message-IDs with offsets
"""

from dataclasses import dataclass, field
from pathlib import Path

from gmailarchiver.core.importer._reader import MboxReader
from gmailarchiver.core.importer._scanner import FileScanner
from gmailarchiver.core.workflows.step import (
    ContextKeys,
    StepContext,
    StepResult,
)
from gmailarchiver.shared.protocols import ProgressReporter


@dataclass
class MboxScanInput:
    """Input for ScanMboxStep."""

    archive_path: str | Path


@dataclass
class MboxScanOutput:
    """Output from ScanMboxStep."""

    archive_file: str
    total_messages: int
    # List of (rfc_message_id, offset, length) tuples
    scanned_messages: list[tuple[str, int, int]] = field(default_factory=list)


class ScanMboxStep:
    """Step that scans an mbox file for messages.

    Extracts RFC Message-IDs and offsets for all messages in the archive.
    Does NOT check for duplicates - that's done by CheckDuplicatesStep.

    Input: MboxScanInput with archive path
    Output: MboxScanOutput with scanned message info
    Context: Sets MBOX_PATH for subsequent steps
    """

    name = "scan_mbox"
    description = "Scanning mbox for messages"

    async def execute(
        self,
        context: StepContext,
        input_data: MboxScanInput | str | Path,
        progress: ProgressReporter | None = None,
    ) -> StepResult[MboxScanOutput]:
        """Scan mbox file and extract message information.

        Args:
            context: Shared step context
            input_data: Path to mbox file (or MboxScanInput)
            progress: Optional progress reporter

        Returns:
            StepResult with MboxScanOutput containing scanned messages
        """
        # Check for None input
        if input_data is None:
            return StepResult.fail("No archive path provided")

        # Normalize input
        if isinstance(input_data, MboxScanInput):
            archive_path = Path(input_data.archive_path)
        else:
            archive_path = Path(input_data)

        # Validate file exists
        if not archive_path.exists():
            return StepResult.fail(f"Archive not found: {archive_path}")

        # Store path in context for other steps
        context.set(ContextKeys.MBOX_PATH, str(archive_path))
        context.set(ContextKeys.ARCHIVE_FILE, str(archive_path))

        scanner = FileScanner()
        reader = MboxReader()

        # Decompress if needed
        mbox_path, is_temp = scanner.decompress_to_temp(archive_path)

        try:
            if progress:
                with progress.task_sequence() as seq:
                    with seq.task(f"Scanning {archive_path.name}") as task:
                        # Fast scan: extract RFC Message-IDs with offsets
                        scanned_messages = reader.scan_rfc_message_ids(mbox_path, None)
                        total_count = len(scanned_messages)
                        task.complete(f"Found {total_count:,} messages")
            else:
                scanned_messages = reader.scan_rfc_message_ids(mbox_path, None)
                total_count = len(scanned_messages)

            output = MboxScanOutput(
                archive_file=str(archive_path),
                total_messages=total_count,
                scanned_messages=scanned_messages,
            )

            # Store results in context for other steps
            context.set(ContextKeys.MESSAGES, scanned_messages)
            context.set("total_scanned", total_count)

            return StepResult.ok(output, count=total_count)

        except Exception as e:
            return StepResult.fail(f"Failed to scan archive: {e}")
        finally:
            scanner.cleanup_temp_file(mbox_path, is_temp)
