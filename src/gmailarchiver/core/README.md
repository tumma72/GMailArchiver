# Core Layer

**Status**: ✅ Complete
**Tests**: `tests/core/` (all passing)

## Purpose

The core layer contains the primary business logic for Gmail archiving operations. It orchestrates workflow between the data layer (database, hybrid storage) and the connectors layer (Gmail API, auth) to perform high-level operations like archiving, validation, search, and deduplication.

## Components

| Module | Class | Description |
|--------|-------|-------------|
| `archiver.py` | `GmailArchiver` | Main orchestrator for archiving workflow |
| `validator.py` | `ArchiveValidator` | Multi-layer validation before deletion |
| `importer.py` | `ArchiveImporter` | Import existing mbox archives into database |
| `consolidator.py` | `ArchiveConsolidator` | Merge multiple archives into one |
| `deduplicator.py` | `MessageDeduplicator` | Message-ID based deduplication |
| `search.py` | `SearchEngine` | Full-text and metadata search via FTS5 |
| `extractor.py` | `MessageExtractor` | Extract messages from archives by ID |
| `compressor.py` | `ArchiveCompressor` | Compress archives (gzip, lzma, zstd) |
| `doctor.py` | `Doctor` | System health diagnostics and fixes |

## Dependencies

```
core/ ──────► data/ (DBManager, HybridStorage, State)
        └──► connectors/ (GmailClient)
        └──► shared/ (utils, validators)
```

## Import Convention

Within core layer (relative imports):
```python
from .validator import ArchiveValidator
```

Cross-layer (absolute imports):
```python
from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.shared.utils import parse_age
```

## Usage Examples

### Archive Messages
```python
from gmailarchiver.core.archiver import GmailArchiver
from gmailarchiver.connectors.gmail_client import GmailClient

client = GmailClient(credentials)
archiver = GmailArchiver(client, "archive_state.db")
result = archiver.archive("3y", "archive.mbox", incremental=True)
```

### Validate Archive
```python
from gmailarchiver.core.validator import ArchiveValidator

validator = ArchiveValidator("archive.mbox", state_db="archive_state.db")
results = validator.validate()
```

### Search Messages
```python
from gmailarchiver.core.search import SearchEngine

engine = SearchEngine("archive_state.db")
results = engine.search("from:alice@example.com subject:meeting")
```

### Run Diagnostics
```python
from gmailarchiver.core.doctor import Doctor

doctor = Doctor("archive_state.db")
report = doctor.run_diagnostics()
```

## Design Documentation

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed component design with Mermaid diagrams.
