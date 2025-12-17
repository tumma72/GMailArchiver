"""Database schema migration system for Gmail Archiver."""

import asyncio
import email
import hashlib
import shutil
from contextlib import closing
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Any

import aiosqlite
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


class MigrationError(Exception):
    """Raised when migration fails."""

    pass


class MigrationManager:
    """
    Manage database schema migrations.

    Handles migration from v1.0.x schema (archived_messages) to v1.1.0 schema
    (messages table with mbox_offset, FTS5, and enhanced indexing).
    """

    SCHEMA_VERSION_1_0 = "1.0"
    SCHEMA_VERSION_1_1 = "1.1"

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize migration manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path).resolve()
        self.conn: aiosqlite.Connection | None = None

    async def _connect(self) -> aiosqlite.Connection:
        """
        Get database connection.

        Returns:
            SQLite connection
        """
        if self.conn is None:
            self.conn = await aiosqlite.connect(str(self.db_path))
            # Enable foreign key support
            await self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    async def _close(self) -> None:
        """Close database connection."""
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def detect_schema_version(self) -> str:
        """
        Detect current database schema version.

        Returns:
            Schema version string ("1.0", "1.1", or "none")
        """
        if not self.db_path.exists():
            return "none"

        conn = await self._connect()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )

        if await cursor.fetchone():
            # Schema version table exists - read version
            version_cursor = await conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = await version_cursor.fetchone()
            return row[0] if row else "1.0"

        # Check for v1.0 schema (archived_messages table)
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        if await cursor.fetchone():
            return "1.0"

        # Check for v1.1 schema (messages table)
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if await cursor.fetchone():
            return "1.1"

        return "none"

    async def needs_migration(self) -> bool:
        """
        Check if database needs migration to v1.1.

        Returns:
            True if migration is needed
        """
        version = await self.detect_schema_version()
        return version in ("1.0", "none")

    async def create_backup(self) -> Path:
        """
        Create backup of database before migration.

        Returns:
            Path to backup file

        Raises:
            MigrationError: If backup creation fails
        """
        if not self.db_path.exists():
            raise MigrationError(f"Database not found: {self.db_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.parent / f"{self.db_path.name}.backup.{timestamp}"

        try:
            console.print(f"[cyan]Creating backup: {backup_path}[/cyan]")
            # File copy is CPU-bound, wrap in thread
            await asyncio.to_thread(shutil.copy2, self.db_path, backup_path)
            console.print("[green]✓ Backup created successfully[/green]")
            return backup_path
        except Exception as e:
            raise MigrationError(f"Failed to create backup: {e}") from e

    async def _create_enhanced_schema(self, conn: aiosqlite.Connection) -> None:
        """
        Create enhanced v1.1.0 schema.

        Args:
            conn: SQLite connection
        """
        # Create messages table (enhanced schema)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                gmail_id TEXT PRIMARY KEY,
                rfc_message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT,
                from_addr TEXT,
                to_addr TEXT,
                cc_addr TEXT,
                date TIMESTAMP,
                archived_timestamp TIMESTAMP NOT NULL,
                archive_file TEXT NOT NULL,
                mbox_offset INTEGER NOT NULL,
                mbox_length INTEGER NOT NULL,
                body_preview TEXT,
                checksum TEXT,
                size_bytes INTEGER,
                labels TEXT,
                account_id TEXT DEFAULT 'default'
            )
        """)

        # Create performance indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_rfc_message_id ON messages(rfc_message_id)",
            "CREATE INDEX IF NOT EXISTS idx_thread_id ON messages(thread_id)",
            "CREATE INDEX IF NOT EXISTS idx_archive_file ON messages(archive_file)",
            "CREATE INDEX IF NOT EXISTS idx_date ON messages(date)",
            "CREATE INDEX IF NOT EXISTS idx_from ON messages(from_addr)",
            "CREATE INDEX IF NOT EXISTS idx_subject ON messages(subject)",
        ]
        for index_sql in indexes:
            await conn.execute(index_sql)

        # Create FTS5 virtual table for full-text search
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                subject,
                from_addr,
                to_addr,
                body_preview,
                content=messages,
                content_rowid=rowid,
                tokenize='porter unicode61 remove_diacritics 1'
            )
        """)

        # Create auto-sync triggers for FTS5
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, subject, from_addr, to_addr, body_preview)
                VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_preview);
            END
        """)

        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
                UPDATE messages_fts
                SET subject = new.subject,
                    from_addr = new.from_addr,
                    to_addr = new.to_addr,
                    body_preview = new.body_preview
                WHERE rowid = new.rowid;
            END
        """)

        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE rowid = old.rowid;
            END
        """)

        # Create accounts table (for future multi-account support)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                provider TEXT DEFAULT 'gmail',
                added_timestamp TEXT,
                last_sync_timestamp TEXT
            )
        """)

        # Insert default account
        await conn.execute(
            """
            INSERT OR IGNORE INTO accounts (account_id, email, added_timestamp)
            VALUES ('default', 'default', ?)
        """,
            (datetime.now().isoformat(),),
        )

        # Keep archive_runs table (already exists, just ensure it's there)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                messages_archived INTEGER NOT NULL,
                archive_file TEXT NOT NULL,
                account_id TEXT DEFAULT 'default',
                operation_type TEXT DEFAULT 'archive'
            )
        """)

        # Create schema_version table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                migrated_timestamp TEXT NOT NULL
            )
        """)

        await conn.commit()

    def _extract_rfc_message_id(self, msg: email.message.Message) -> str:
        """
        Extract RFC 2822 Message-ID from email message.

        Args:
            msg: Email message

        Returns:
            Message-ID header value (or generated fallback)
        """
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            # Generate fallback Message-ID from Subject + Date
            subject = msg.get("Subject", "no-subject")
            date = msg.get("Date", "no-date")
            fallback_id = f"<{hashlib.sha256(f'{subject}{date}'.encode()).hexdigest()}@generated>"
            return fallback_id
        return message_id

    def _extract_body_preview(self, msg: email.message.Message, max_chars: int = 1000) -> str:
        """
        Extract body preview from email message.

        Args:
            msg: Email message
            max_chars: Maximum characters to extract

        Returns:
            Plain text preview
        """
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload and isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")
                            break
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body = payload.decode("utf-8", errors="ignore")
            except Exception:
                pass

        return body[:max_chars]

    def _extract_thread_id(self, msg: email.message.Message) -> str | None:
        """
        Extract thread ID from email headers.

        Args:
            msg: Email message

        Returns:
            Thread ID or None
        """
        # Try X-GM-THRID header first (Gmail-specific)
        thread_id = msg.get("X-GM-THRID", "").strip()
        if thread_id:
            return thread_id

        # Fallback to References header
        references = msg.get("References", "").strip()
        if references:
            # Use first reference as thread ID
            refs = references.split()
            return refs[0] if refs else None

        return None

    async def migrate_v1_to_v1_1(self, progress_callback: Any = None) -> None:
        """
        Migrate database from v1.0 to v1.1 schema.

        Scans actual mbox files to extract real RFC Message-IDs, offsets, and metadata.

        Args:
            progress_callback: Optional callback for progress updates

        Raises:
            MigrationError: If migration fails
        """

        conn = await self._connect()

        try:
            console.print("[cyan]Starting migration from v1.0 to v1.1...[/cyan]")

            # 1. Rename old table
            console.print("[cyan]Renaming archived_messages to archived_messages_old...[/cyan]")
            await conn.execute("ALTER TABLE archived_messages RENAME TO archived_messages_old")

            # 2. Create new schema
            console.print("[cyan]Creating enhanced schema with mbox_offset tracking...[/cyan]")
            await self._create_enhanced_schema(conn)

            # 2a. Add audit trail columns to archive_runs if they don't exist (v1.1 enhancement)
            # Check if operation_type column exists
            cursor = await conn.execute("PRAGMA table_info(archive_runs)")
            columns = {row[1] for row in await cursor.fetchall()}

            if "operation_type" not in columns:
                console.print("[cyan]Adding operation_type column to archive_runs...[/cyan]")
                await conn.execute("""
                    ALTER TABLE archive_runs
                    ADD COLUMN operation_type TEXT DEFAULT 'archive'
                """)

            # Note: account_id is already added by _create_enhanced_schema
            # via CREATE TABLE IF NOT EXISTS. But if the table already existed,
            # we need to add it
            if "account_id" not in columns:
                console.print("[cyan]Adding account_id column to archive_runs...[/cyan]")
                await conn.execute("""
                    ALTER TABLE archive_runs
                    ADD COLUMN account_id TEXT DEFAULT 'default'
                """)

            # 3. Migrate data with progress tracking
            console.print("[cyan]Scanning mbox files and extracting metadata...[/cyan]")
            cursor = await conn.execute("SELECT COUNT(*) FROM archived_messages_old")
            row = await cursor.fetchone()
            total_messages = row[0] if row else 0

            console.print(f"[cyan]Processing {total_messages} messages...[/cyan]")

            # Group messages by archive file for efficient processing
            cursor = await conn.execute("SELECT DISTINCT archive_file FROM archived_messages_old")
            archive_files = [row[0] for row in await cursor.fetchall()]

            migrated_count = 0
            skipped_count = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Migrating messages...", total=total_messages)

                for archive_file in archive_files:
                    archive_path = Path(archive_file)

                    # Check if mbox file exists
                    if not archive_path.exists():
                        console.print(
                            f"[yellow]Warning: Archive file not found: {archive_path}[/yellow]"
                        )
                        # Count messages that will be skipped
                        cursor = await conn.execute(
                            "SELECT COUNT(*) FROM archived_messages_old WHERE archive_file = ?",
                            (archive_file,),
                        )
                        row = await cursor.fetchone()
                        skip_count = row[0] if row else 0
                        skipped_count += skip_count
                        progress.update(task, advance=skip_count)
                        continue

                    # Get all messages from v1.0 for this archive
                    cursor = await conn.execute(
                        """SELECT gmail_id, archived_timestamp, subject, from_addr,
                                  message_date, checksum
                           FROM archived_messages_old
                           WHERE archive_file = ?""",
                        (archive_file,),
                    )
                    old_messages = {
                        row[0]: {
                            "archived_timestamp": row[1],
                            "subject": row[2],
                            "from_addr": row[3],
                            "message_date": row[4],
                            "checksum": row[5],
                        }
                        for row in await cursor.fetchall()
                    }

                    # CPU-bound mbox scanning in thread pool
                    records, file_skipped, warnings = await asyncio.to_thread(
                        self._scan_mbox_for_migration_sync,
                        archive_path,
                        old_messages,
                    )

                    # Log any warnings
                    for warning in warnings:
                        console.print(f"[yellow]Warning: {warning}[/yellow]")

                    # Insert records into database (async)
                    for record in records:
                        await conn.execute(
                            """
                            INSERT INTO messages
                            (gmail_id, rfc_message_id, thread_id,
                             subject, from_addr, to_addr, cc_addr,
                             date, archived_timestamp, archive_file,
                             mbox_offset, mbox_length,
                             body_preview, checksum, size_bytes,
                             labels, account_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                    ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record["gmail_id"],
                                record["rfc_message_id"],
                                record["thread_id"],
                                record["subject"],
                                record["from_addr"],
                                record["to_addr"],
                                record["cc_addr"],
                                record["date"],
                                record["archived_timestamp"],
                                record["archive_file"],
                                record["mbox_offset"],
                                record["mbox_length"],
                                record["body_preview"],
                                record["checksum"],
                                record["size_bytes"],
                                None,  # labels
                                "default",  # account_id
                            ),
                        )
                        migrated_count += 1
                        progress.update(task, advance=1)

                    # Update progress for skipped messages
                    skipped_count += file_skipped
                    progress.update(task, advance=file_skipped)

            # 4. Drop old table
            console.print("[cyan]Dropping old table...[/cyan]")
            await conn.execute("DROP TABLE archived_messages_old")

            # 5. Set schema version
            console.print("[cyan]Setting schema version to 1.1...[/cyan]")
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version VALUES (?, ?)",
                (self.SCHEMA_VERSION_1_1, datetime.now().isoformat()),
            )

            # Commit the transaction before VACUUM
            await conn.commit()

            # 6. Run VACUUM to reclaim space (must be outside transaction)
            console.print("[cyan]Running VACUUM to reclaim space...[/cyan]")
            await conn.execute("VACUUM")

            status_msg = f"✓ Migration completed! Migrated {migrated_count} messages"
            if skipped_count > 0:
                status_msg += f" (skipped {skipped_count})"
            console.print(f"[green]{status_msg}[/green]")

        except Exception as e:
            await conn.rollback()
            raise MigrationError(f"Migration failed: {e}") from e

    async def validate_migration(self) -> bool:
        """
        Validate migration was successful.

        Returns:
            True if validation passes

        Raises:
            MigrationError: If validation fails
        """
        conn = await self._connect()

        try:
            # Check schema version
            cursor = await conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = await cursor.fetchone()
            if not row or row[0] != self.SCHEMA_VERSION_1_1:
                raise MigrationError("Schema version not set to 1.1")

            # Check messages table exists
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            )
            if not await cursor.fetchone():
                raise MigrationError("messages table not found")

            # Check FTS5 table exists
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
            )
            if not await cursor.fetchone():
                raise MigrationError("messages_fts table not found")

            # Check message count
            cursor = await conn.execute("SELECT COUNT(*) FROM messages")
            row = await cursor.fetchone()
            message_count = row[0] if row else 0

            msg = f"✓ Validation passed: {message_count} messages in database"
            console.print(f"[green]{msg}[/green]")
            return True

        except Exception as e:
            raise MigrationError(f"Validation failed: {e}") from e

    async def rollback_migration(self, backup_path: Path) -> None:
        """
        Rollback migration by restoring from backup.

        Args:
            backup_path: Path to backup file

        Raises:
            MigrationError: If rollback fails
        """
        if not backup_path.exists():
            raise MigrationError(f"Backup file not found: {backup_path}")

        try:
            console.print(f"[yellow]Rolling back migration from {backup_path}...[/yellow]")

            # Close connection
            await self._close()

            # Remove current database
            if self.db_path.exists():
                self.db_path.unlink()

            # Restore from backup
            await asyncio.to_thread(shutil.copy2, backup_path, self.db_path)

            console.print("[green]✓ Rollback completed successfully[/green]")

        except Exception as e:
            raise MigrationError(f"Rollback failed: {e}") from e

    async def backfill_offsets_from_mbox(self, invalid_messages: list[dict[str, Any]]) -> int:
        """
        Backfill invalid offsets by scanning mbox files.

        Used to fix placeholder records from v1.1.0-beta.1 migration bug.
        Scans actual mbox files to extract real offsets, lengths, and RFC Message-IDs.

        Args:
            invalid_messages: List of messages with offset=-1 or length=-1
                             Each dict must have: gmail_id, rfc_message_id, archive_file

        Returns:
            Number of messages successfully backfilled

        Raises:
            MigrationError: If backfill fails
        """
        from collections import defaultdict

        if not invalid_messages:
            return 0

        conn = await self._connect()

        # Group messages by archive file for efficient scanning
        by_archive: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for msg in invalid_messages:
            by_archive[msg["archive_file"]].append(msg)

        backfilled = 0

        try:
            for archive_file, msgs in by_archive.items():
                archive_path = Path(archive_file)

                # Check if mbox file exists
                if not archive_path.exists():
                    console.print(
                        f"[yellow]Warning: Archive file not found: {archive_path}[/yellow]"
                    )
                    continue

                # Create lookup dictionary by RFC Message-ID
                msg_lookup = {m["rfc_message_id"]: m for m in msgs}

                # CPU-bound mbox scanning in thread pool
                updates, warnings = await asyncio.to_thread(
                    self._scan_mbox_for_backfill_sync,
                    archive_path,
                    msg_lookup,
                )

                # Log any warnings
                for warning in warnings:
                    console.print(f"[yellow]Warning: {warning}[/yellow]")

                # Apply updates to database (async)
                for gmail_id, offset, length in updates:
                    await conn.execute(
                        """
                        UPDATE messages
                        SET mbox_offset = ?, mbox_length = ?
                        WHERE gmail_id = ?
                        """,
                        (offset, length, gmail_id),
                    )
                    backfilled += 1

            # Commit all updates
            await conn.commit()

            console.print(f"[green]✓ Backfilled {backfilled} messages[/green]")
            return backfilled

        except Exception as e:
            await conn.rollback()
            raise MigrationError(f"Backfill failed: {e}") from e

    # ==================== SYNC HELPERS FOR CPU-BOUND WORK ====================
    # These methods run in thread pool via asyncio.to_thread() to avoid
    # blocking the event loop during CPU-intensive mbox/email operations.

    def _scan_mbox_for_migration_sync(
        self,
        archive_path: Path,
        old_messages: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, list[str]]:
        """
        Sync helper: Scan mbox file and extract metadata for migration.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            archive_path: Path to mbox file
            old_messages: Dict of gmail_id -> old message metadata from v1.0 DB

        Returns:
            Tuple of:
            - records: List of message records for database insertion
            - skipped: Number of messages skipped
            - warnings: List of warning messages
        """
        import mailbox

        records: list[dict[str, Any]] = []
        skipped = 0
        warnings: list[str] = []

        # Make a copy to avoid modifying the original
        remaining_messages = dict(old_messages)

        try:
            with closing(mailbox.mbox(str(archive_path))) as mbox:
                file_size = archive_path.stat().st_size
                keys_list = list(mbox.keys())

                for i, key in enumerate(keys_list):
                    try:
                        # Get offset from mbox._toc (private API but necessary)
                        offset: int = mbox._toc[key][0]  # type: ignore[attr-defined]

                        # Read message
                        msg = mbox[key]

                        # Calculate length
                        if i < len(keys_list) - 1:
                            next_offset = mbox._toc[keys_list[i + 1]][0]  # type: ignore
                            length = next_offset - offset
                        else:
                            length = file_size - offset

                        if remaining_messages:
                            # Pop one gmail_id from the dict
                            gmail_id = next(iter(remaining_messages.keys()))
                            old_meta = remaining_messages.pop(gmail_id)

                            # Extract RFC Message-ID
                            rfc_message_id = self._extract_rfc_message_id(msg)

                            # Extract thread ID
                            thread_id = self._extract_thread_id(msg)

                            # Extract body preview
                            body_preview = self._extract_body_preview(msg)

                            # Calculate checksum
                            message_bytes = msg.as_bytes()
                            checksum = hashlib.sha256(message_bytes).hexdigest()

                            records.append(
                                {
                                    "gmail_id": gmail_id,
                                    "rfc_message_id": rfc_message_id,
                                    "thread_id": thread_id,
                                    "subject": msg.get("Subject"),
                                    "from_addr": msg.get("From"),
                                    "to_addr": msg.get("To"),
                                    "cc_addr": msg.get("Cc"),
                                    "date": msg.get("Date"),
                                    "archived_timestamp": old_meta["archived_timestamp"],
                                    "archive_file": str(archive_path),
                                    "mbox_offset": offset,
                                    "mbox_length": length,
                                    "body_preview": body_preview,
                                    "checksum": checksum,
                                    "size_bytes": len(message_bytes),
                                }
                            )

                    except Exception as e:
                        warnings.append(f"Failed to process message {key}: {e}")
                        skipped += 1
                        continue

            # Handle any remaining old_messages that weren't in mbox
            if remaining_messages:
                warnings.append(
                    f"{len(remaining_messages)} messages from v1.0 DB not found in {archive_path}"
                )
                skipped += len(remaining_messages)

        except Exception as e:
            warnings.append(f"Failed to scan {archive_path}: {e}")
            skipped += len(remaining_messages)

        return records, skipped, warnings

    def _scan_mbox_for_backfill_sync(
        self,
        archive_path: Path,
        msg_lookup: dict[str, dict[str, Any]],
    ) -> tuple[list[tuple[str, int, int]], list[str]]:
        """
        Sync helper: Scan mbox file to extract offsets for backfill.

        This is CPU-bound work that runs in a thread pool via asyncio.to_thread().

        Args:
            archive_path: Path to mbox file
            msg_lookup: Dict mapping rfc_message_id -> message record

        Returns:
            Tuple of:
            - updates: List of (gmail_id, offset, length) tuples for database update
            - warnings: List of warning messages
        """
        import mailbox

        updates: list[tuple[str, int, int]] = []
        warnings: list[str] = []

        try:
            with closing(mailbox.mbox(str(archive_path))) as mbox:
                file_size = archive_path.stat().st_size
                keys_list = list(mbox.keys())

                for i, key in enumerate(keys_list):
                    try:
                        # Get offset from mbox._toc
                        offset: int = mbox._toc[key][0]  # type: ignore[attr-defined]

                        # Read message
                        email_msg: Message[str, str] = mbox[key]

                        # Extract RFC Message-ID
                        rfc_message_id = self._extract_rfc_message_id(email_msg)

                        # Check if this is one of our invalid messages
                        if rfc_message_id in msg_lookup:
                            # Calculate length
                            if i < len(keys_list) - 1:
                                next_offset = mbox._toc[keys_list[i + 1]][0]  # type: ignore
                                length = next_offset - offset
                            else:
                                length = file_size - offset

                            gmail_id = msg_lookup[rfc_message_id]["gmail_id"]
                            updates.append((gmail_id, offset, length))

                    except Exception as e:
                        warnings.append(f"Failed to process message {key}: {e}")
                        continue

        except Exception as e:
            warnings.append(f"Failed to scan {archive_path}: {e}")

        return updates, warnings

    async def __aenter__(self) -> MigrationManager:
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        await self._close()

    def __del__(self) -> None:
        """Ensure database connection is closed on garbage collection.

        This prevents ResourceWarning: unclosed database when a MigrationManager
        is used without an explicit context manager or _close() call in tests
        or CLI code paths.
        """
        # For async connections, we need to handle cleanup carefully
        # If there's an open connection, try to close it synchronously
        if self.conn is not None:
            try:
                # Try to run the async close in a new event loop if needed
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If a loop is already running, we can't close synchronously
                    # The connection will be cleaned up by the garbage collector
                    pass
                else:
                    loop.run_until_complete(self._close())
            except RuntimeError:
                # No event loop, or other issues - connection will be GC'd
                pass
