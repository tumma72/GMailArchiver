from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gmailarchiver.data.db_manager import DBManager
from gmailarchiver.data.schema_manager import SchemaManager


@dataclass
class StatusConfig:
    """Configuration for status operation."""

    state_db: Path
    verbose: bool = False


@dataclass
class StatusResult:
    """Result of status operation."""

    schema_version: str
    database_size_bytes: int
    total_messages: int
    recent_runs: list[dict[str, Any]]
    archive_files_count: int
    archive_files_sample: list[str]


class StatusWorkflow:
    """Workflow for retrieving system status."""

    async def run(self, config: StatusConfig) -> StatusResult:
        """Run status workflow."""
        if not config.state_db.exists():
            raise FileNotFoundError(f"Database not found: {config.state_db}")

        db_size = config.state_db.stat().st_size

        # 1. Detect Schema Version (using SchemaManager for robustness)
        schema_mgr = SchemaManager(config.state_db)
        version_enum = await schema_mgr.detect_version()
        version_str = version_enum.value

        # 2. Get Stats via DBManager
        # Use validate_schema=False to allow inspecting old/broken databases
        db = DBManager(config.state_db, validate_schema=False, auto_create=False)
        await db.initialize()

        try:
            # Handle different schema versions gracefully
            # If schema is very old, get_message_count might fail if table names differ
            # DBManager methods generally assume current schema, but get_message_count is simple.
            # v1.0 used 'archived_messages', v1.1+ uses 'messages'.
            # DBManager.get_message_count uses 'messages'.

            # We might need to handle this manually or rely on DBManager adaptation?
            # DBManager seems to use 'messages' hardcoded.
            # If version is 1.0, this might fail.

            # Let's check if we can query dynamically if DBManager fails?
            # Or assume DBManager is the gateway.
            # If DBManager fails, we can't do much.

            total_messages = 0
            try:
                total_messages = await db.get_message_count()
            except Exception:
                # Fallback for v1.0 schema if DBManager assumes v1.1+
                if version_str == "1.0" and db.conn:
                    try:
                        cursor = await db.conn.execute("SELECT COUNT(*) FROM archived_messages")
                        res = await cursor.fetchone()
                        total_messages = int(res[0]) if res else 0
                    except Exception:
                        pass

            recent_runs: list[dict[str, Any]] = []
            try:
                recent_runs = await db.get_archive_runs(limit=10 if config.verbose else 5)
            except Exception:
                # Fallback for v1.0 schema which might have different archive_runs table structure
                if version_str == "1.0" and db.conn:
                    try:
                        cursor = await db.conn.execute(
                            "SELECT run_id, run_timestamp, query, messages_archived, archive_file "
                            "FROM archive_runs ORDER BY run_timestamp DESC LIMIT ?",
                            (10 if config.verbose else 5,),
                        )
                        rows = await cursor.fetchall()
                        for row in rows:
                            recent_runs.append(
                                {
                                    "run_id": row[0],
                                    "run_timestamp": row[1],
                                    "query": row[2],
                                    "messages_archived": row[3],
                                    "archive_file": row[4],
                                    # Add missing fields with defaults for compatibility
                                    "account_id": "default",
                                    "operation_type": "archive",
                                }
                            )
                    except Exception:
                        pass

            # Calculate unique archive files from runs
            archive_files = set(
                run["archive_file"] for run in recent_runs if run.get("archive_file")
            )

            # For v1.0 schema, also try to extract archive files from archived_messages table
            if version_str == "1.0" and len(archive_files) == 0 and db.conn:
                try:
                    cursor = await db.conn.execute(
                        "SELECT DISTINCT archive_file FROM archived_messages"
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        if row[0]:
                            archive_files.add(row[0])
                except Exception:
                    pass  # If this fails, we'll just use the archive_runs files

            sorted_files = sorted(list(archive_files))

            return StatusResult(
                schema_version=version_str,
                database_size_bytes=db_size,
                total_messages=total_messages,
                recent_runs=recent_runs,
                archive_files_count=len(archive_files),
                archive_files_sample=sorted_files[-5:] if sorted_files else [],
            )

        finally:
            await db.close()
