from pathlib import Path

import typer

from gmailarchiver.cli.command_context import CommandContext
from gmailarchiver.connectors.auth import GmailAuthenticator
from gmailarchiver.connectors.gmail_client import GmailClient
from gmailarchiver.core.workflows.archive import ArchiveConfig, ArchiveWorkflow


async def archive_command(
    ctx: CommandContext,
    age_threshold: str,
    output: str | None,
    compress: str | None,
    incremental: bool,
    trash: bool,
    delete: bool,
    dry_run: bool,
    verbose: bool,
    credentials: str | None,
    json_output: bool,
) -> None:
    """Async implementation of the archive command."""
    out = ctx.output
    assert ctx.storage is not None  # Guaranteed by requires_storage=True

    # Phase 1: Authentication
    with ctx.ui.spinner("Authenticating with Gmail") as task:
        try:
            authenticator = GmailAuthenticator(credentials_file=credentials)
            # authenticate is sync, but we are in async context.
            # Ideally it should be async, but for now we call it as is.
            # If it blocks too long, it should be run in executor, but likely it just does local file check or browser launch.
            oauth_creds = authenticator.authenticate()
            task.complete("Connected")
        except Exception as e:
            task.fail("Authentication failed")
            ctx.fail_and_exit(
                "Authentication Failed",
                f"Failed to authenticate with Gmail: {e}",
                suggestion="Run 'gmailarchiver auth-reset' and try again",
            )
            return

    # Phase 2: Discovery, Archiving, Validation
    config = ArchiveConfig(
        age_threshold=age_threshold,
        output_file=output,
        compress=compress,
        incremental=incremental,
        dry_run=dry_run,
        trash=trash,
        delete=delete,
    )

    async with GmailClient(oauth_creds) as gmail:
        workflow = ArchiveWorkflow(gmail, ctx.storage, out, ctx.ui)

        try:
            result = await workflow.run(config)
        except ValueError as e:
            # Handle user input errors (age threshold)
            ctx.fail_and_exit(
                title="Invalid Input",
                message=str(e),
                suggestion="Check your age threshold format",
            )
            return
        except Exception as e:
            ctx.fail_and_exit(
                title="Archive Failed",
                message=str(e),
                suggestion="Check your network connection and Gmail API access",
            )
            return

        # Phase 3: Reporting and UI Interaction

        # 3.1 Handle Dry Run
        if dry_run:
            ctx.warning("DRY RUN completed - no changes made")
            report_data = {
                "Messages Found": result.found_count,
                "Messages to Archive": (
                    result.found_count - result.skipped_count - result.duplicate_count
                ),
                "Already Archived": result.skipped_count + result.duplicate_count,
                "Output File": result.actual_file,
                "Mode": "Dry Run (no changes made)",
            }
            ctx.show_report("Archive Preview", report_data)
            return

        # 3.2 Handle Interruption
        if result.interrupted:
            ctx.warning("Archive was interrupted (Ctrl+C)")
            ctx.info(f"Partial archive saved: {result.actual_file}")
            ctx.info(f"Progress: {result.archived_count} messages archived")
            ctx.suggest_next_steps(
                [
                    f"Resume: gmailarchiver archive {age_threshold}",
                    "Cleanup: gmailarchiver cleanup --list",
                ]
            )
            return

        # 3.3 Validation reporting
        if not result.validation_passed and result.archived_count > 0:
            if verbose and result.validation_details:
                out.show_validation_report(result.validation_details, title="Archive Validation")

            ctx.fail_and_exit(
                title="Validation Failed",
                message="Archive validation did not pass all checks",
                details=result.validation_details.get("errors", [])
                if result.validation_details
                else [],
                suggestion="Check disk space and file permissions. DO NOT delete Gmail messages yet.",
            )
        elif verbose and result.validation_details:
            out.show_validation_report(result.validation_details, title="Archive Validation")

        # 3.4 Handle No Messages
        if result.found_count == 0:
            ctx.warning("No messages found matching criteria")
            ctx.suggest_next_steps(
                [
                    "Check your age threshold",
                    "Verify messages exist in Gmail matching the criteria",
                ]
            )
            return

        if result.archived_count == 0:
            # Contextual message
            if result.duplicate_count > 0 and result.skipped_count > 0:
                ctx.info(
                    f"Nothing new to archive: {result.skipped_count:,} already archived, "
                    f"{result.duplicate_count:,} duplicates"
                )
            elif result.duplicate_count > 0:
                ctx.info(
                    f"Nothing new to archive: all {result.duplicate_count:,} messages are duplicates"
                )
            else:
                ctx.info(
                    f"Nothing new to archive: all {result.skipped_count:,} messages already archived"
                )

            # Offer deletion for existing messages (if user requested trash/delete)
            if (trash or delete) and Path(result.actual_file).exists():
                archived_ids = await ctx.storage.get_message_ids_for_archive(result.actual_file)
                if archived_ids:
                    count = len(archived_ids)
                    ctx.info(f"\nFound {count:,} messages in {result.actual_file}")

                    if delete:
                        ctx.warning("WARNING: PERMANENT DELETION")
                        ctx.warning("This action CANNOT be undone!")
                        if (
                            typer.prompt(f"\nType 'DELETE {count} MESSAGES' to confirm")
                            == f"DELETE {count} MESSAGES"
                        ):
                            with out.progress_context("Permanently deleting messages", total=None):
                                await workflow.delete_messages(result.actual_file, permanent=True)
                            ctx.success(f"Permanently deleted {count:,} messages from Gmail")
                        else:
                            ctx.info("Deletion cancelled")
                    elif trash:
                        if typer.confirm(
                            f"Move {count:,} messages to trash? (30-day recovery period)"
                        ):
                            with out.progress_context("Moving messages to trash", total=None):
                                await workflow.delete_messages(result.actual_file, permanent=False)
                            ctx.success(f"Moved {count:,} messages to trash")
                        else:
                            ctx.info("Cancelled")
            return

        # 3.5 Deletion for newly archived messages
        if (trash or delete) and result.archived_count > 0:
            if delete:
                ctx.warning("WARNING: PERMANENT DELETION")
                ctx.warning(f"This will permanently delete {result.archived_count} messages.")
                ctx.warning("This action CANNOT be undone!")
                if (
                    typer.prompt(f"\nType 'DELETE {result.archived_count} MESSAGES' to confirm")
                    == f"DELETE {result.archived_count} MESSAGES"
                ):
                    with out.progress_context("Permanently deleting messages", total=None):
                        await workflow.delete_messages(result.actual_file, permanent=True)
                    ctx.success("Messages permanently deleted")
                else:
                    ctx.info("Deletion cancelled")

            elif trash:
                if not typer.confirm(
                    f"\nMove {result.archived_count} messages to trash? (30-day recovery period)"
                ):
                    ctx.info("Cancelled")
                    return

                with out.progress_context("Moving messages to trash", total=None):
                    await workflow.delete_messages(result.actual_file, permanent=False)

                ctx.success("Messages moved to trash")

        # Phase 4: Final Summary
        report_data = {
            "Archived": f"{result.archived_count:,} messages",
            "File": output,
        }

        if result.skipped_count > 0 or result.duplicate_count > 0:
            skipped_parts = []
            if result.skipped_count > 0:
                skipped_parts.append(f"{result.skipped_count:,} already archived")
            if result.duplicate_count > 0:
                skipped_parts.append(f"{result.duplicate_count:,} duplicates")
            report_data["Skipped"] = ", ".join(skipped_parts)

        if compress:
            report_data["Compression"] = compress

        if trash:
            report_data["Gmail"] = "Moved to trash (30-day recovery)"
        elif delete:
            report_data["Gmail"] = "Permanently deleted"

        ctx.show_report("📦 Archive Summary", report_data)
        ctx.success("Archive completed!")

        # Contextual suggestions based on what happened
        suggestions: list[str] = []

        if result.archived_count > 0 and not trash and not delete:
            # Suggest deletion options if messages were archived but not deleted
            suggestions.append(
                f"Move to trash (recoverable): gmailarchiver archive {age_threshold} --trash"
            )

        if result.duplicate_count > 0:
            # Suggest dedupe review when duplicates were found
            suggestions.append("Review duplicates: gmailarchiver dedupe --dry-run")

        if suggestions:
            ctx.suggest_next_steps(suggestions)
