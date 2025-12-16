"""
Tests for ADR-006 compliance: Single asyncio.run() pattern per CLI command.

This test suite verifies that CLI commands follow the async-first architecture
where each command has exactly ONE asyncio.run() call at the CLI boundary.

Red-Green-Refactor (TDD):
- RED: These tests initially FAIL for commands not yet refactored
- GREEN: Tests pass once command is refactored to single async workflow
- REFACTOR: Code cleanup while keeping tests green

Testing Strategy:
- Uses AST parsing to count asyncio.run() calls in function body
- Does NOT grep - parses actual Python code structure
- Excludes already-compliant commands (archive, extract, rollback, verify_integrity_cmd)
"""

import ast
import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

# Import CLI command functions to test
from gmailarchiver.__main__ import (  # type: ignore[import-untyped]
    backfill_gmail_ids_cmd,
    check,
    cleanup,
    compress,
    consolidate,
    dedupe,
    doctor,
    import_cmd,
    migrate,
    repair,
    retry_delete_cmd,
    search,
    status,
    validate,
    verify_consistency_cmd,
    verify_offsets_cmd,
)

# ============================================================================
# AST Inspection Utilities
# ============================================================================


def count_asyncio_run_calls(func: Callable[..., None]) -> int:
    """Count asyncio.run() calls in a function's AST.

    Args:
        func: Function to inspect

    Returns:
        Number of asyncio.run() calls found in function body
    """
    # Get function source code
    source = inspect.getsource(func)

    # Parse into AST
    tree = ast.parse(source)

    # Find the function definition node
    func_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func.__name__:
            func_def = node
            break

    if func_def is None:
        raise ValueError(f"Could not find function definition for {func.__name__}")

    # Count asyncio.run() calls
    count = 0
    for node in ast.walk(func_def):
        # Look for Call nodes where func is an Attribute 'run' on 'asyncio'
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio"
                ):
                    count += 1

    return count


def get_asyncio_run_locations(func: Callable[..., None]) -> list[int]:
    """Get line numbers of all asyncio.run() calls in a function.

    Args:
        func: Function to inspect

    Returns:
        List of line numbers (within function source) where asyncio.run() appears
    """
    # Get function source code and starting line number
    source = inspect.getsource(func)
    source_lines = source.split("\n")
    func_start_line = inspect.getsourcelines(func)[1]

    # Parse into AST
    tree = ast.parse(source)

    # Find the function definition node
    func_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func.__name__:
            func_def = node
            break

    if func_def is None:
        raise ValueError(f"Could not find function definition for {func.__name__}")

    # Find line numbers of asyncio.run() calls
    locations = []
    for node in ast.walk(func_def):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio"
                ):
                    # Get relative line number and add context
                    rel_lineno = node.lineno
                    abs_lineno = func_start_line + rel_lineno - 1
                    locations.append(abs_lineno)

    return locations


# ============================================================================
# Simple Commands: Expected to be easiest to refactor
# ============================================================================


class TestSimpleCommands:
    """Test simple commands that should have single asyncio.run() call.

    These commands have straightforward logic with minimal branching.
    They should be refactored to follow the archive pattern:
    - Define inner async function with all async logic
    - Single asyncio.run() call to execute workflow
    - Post-workflow handling in sync context
    """

    def test_search_single_asyncio_run(self) -> None:
        """Test search command has at most 2 asyncio.run() calls.

        The search command is a special case that supports interactive mode,
        which requires:
        1. Async search execution
        2. Sync user prompts (questionary - blocking)
        3. Async extraction (if user selects messages)

        This creates an unavoidable sync barrier, requiring 2 calls:
        - Call 1: Search (+ extraction if --extract flag)
        - Call 2: Interactive extraction (only if --interactive used)

        Expected pattern:
            async def _search_workflow():
                # Search and optional extraction
                ...

            asyncio.run(_search_workflow())  # Initial search
            # ... display results, interactive prompts ...
            asyncio.run(_search_workflow())  # Optional: interactive extraction
        """
        count = count_asyncio_run_calls(search)
        locations = get_asyncio_run_locations(search)

        assert count <= 2, (
            f"search command must have at most 2 asyncio.run() calls (1 for search, "
            f"1 optional for interactive extraction), found {count} at lines: {locations}."
        )

    def test_verify_offsets_single_asyncio_run(self) -> None:
        """Test verify-offsets command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _verify_workflow():
                # All async operations here
                ...

            asyncio.run(_verify_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(verify_offsets_cmd)
        locations = get_asyncio_run_locations(verify_offsets_cmd)

        assert count == 1, (
            f"verify_offsets_cmd must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )


# ============================================================================
# Medium Complexity Commands: Moderate refactoring required
# ============================================================================


class TestMediumComplexityCommands:
    """Test medium complexity commands with conditional logic.

    These commands have moderate branching and multiple async operations.
    Refactoring involves consolidating multiple asyncio.run() calls into
    a single workflow function with proper error handling.
    """

    def test_validate_single_asyncio_run(self) -> None:
        """Test validate command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _validate_workflow():
                validator = create_validator()
                try:
                    result = await validator.validate()
                    return result
                finally:
                    await validator.close()

            result = asyncio.run(_validate_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(validate)
        locations = get_asyncio_run_locations(validate)

        assert count == 1, (
            f"validate command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_status_single_asyncio_run(self) -> None:
        """Test status command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _status_workflow():
                version = await manager.detect_schema_version()
                # ... other async operations
                return data

            data = asyncio.run(_status_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(status)
        locations = get_asyncio_run_locations(status)

        assert count == 1, (
            f"status command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_retry_delete_single_asyncio_run(self) -> None:
        """Test retry-delete command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _retry_delete_workflow():
                message_ids = await storage.get_message_ids_for_archive(file)
                await archiver.delete_archived_messages(message_ids, permanent)

            asyncio.run(_retry_delete_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(retry_delete_cmd)
        locations = get_asyncio_run_locations(retry_delete_cmd)

        assert count == 1, (
            f"retry_delete_cmd must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_verify_consistency_single_asyncio_run(self) -> None:
        """Test verify-consistency command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _verify_workflow():
                validator = create_validator()
                try:
                    report = await validator.verify_consistency()
                    return report
                finally:
                    await validator.close()

            report = asyncio.run(_verify_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(verify_consistency_cmd)
        locations = get_asyncio_run_locations(verify_consistency_cmd)

        assert count == 1, (
            f"verify_consistency_cmd must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_compress_single_asyncio_run(self) -> None:
        """Test compress command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _compress_workflow():
                # Compression logic
                result = await compress_archive(...)
                return result

            result = asyncio.run(_compress_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(compress)
        locations = get_asyncio_run_locations(compress)

        assert count == 1, (
            f"compress command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_repair_single_asyncio_run(self) -> None:
        """Test repair command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _repair_workflow():
                repairs = await storage.db.repair_database(dry_run)
                if backfill:
                    invalid_msgs = await storage.db.get_messages_with_invalid_offsets()
                    await run_backfill(invalid_msgs)
                return repairs

            repairs = asyncio.run(_repair_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(repair)
        locations = get_asyncio_run_locations(repair)

        assert count == 1, (
            f"repair command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )


# ============================================================================
# Complex Commands: Most refactoring required
# ============================================================================


class TestComplexCommands:
    """Test complex commands with extensive branching and workflows.

    These commands have:
    - Multiple conditional branches
    - Extensive error handling
    - Multiple async operations in different code paths
    - User interaction/confirmation prompts

    Refactoring requires careful consolidation of all async paths.
    """

    def test_cleanup_single_asyncio_run(self) -> None:
        """Test cleanup command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _cleanup_workflow():
                await storage.db.ensure_sessions_table()
                sessions = await storage.db.get_all_partial_sessions()
                for session in sessions:
                    # Handle cleanup
                    ...
                await storage.db.close()

            asyncio.run(_cleanup_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(cleanup)
        locations = get_asyncio_run_locations(cleanup)

        assert count == 1, (
            f"cleanup command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_migrate_single_asyncio_run(self) -> None:
        """Test migrate command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _migrate_workflow():
                current_version = await schema_mgr.detect_version()
                if await schema_mgr.needs_migration():
                    backup_path = await manager.create_backup()
                    await manager.migrate_to_v1_1(...)
                    final_version = await schema_mgr.detect_version()
                await manager._close()

            asyncio.run(_migrate_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(migrate)
        locations = get_asyncio_run_locations(migrate)

        assert count == 1, (
            f"migrate command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_dedupe_single_asyncio_run(self) -> None:
        """Test dedupe command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _dedupe_workflow():
                duplicates = await find_duplicates()
                report = await generate_report(duplicates)
                if confirm:
                    result = await deduplicate(duplicates, strategy, dry_run)
                if verify:
                    issues = await verify_integrity()
                return result

            result = asyncio.run(_dedupe_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(dedupe)
        locations = get_asyncio_run_locations(dedupe)

        assert count == 1, (
            f"dedupe command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_import_single_asyncio_run(self) -> None:
        """Test import command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _import_workflow():
                version = await schema_mgr.detect_version()
                if await schema_mgr.needs_migration():
                    # Migration handling
                result = await importer.import_archives(files, account_id)
                if verify:
                    issues = await storage.db.verify_database_integrity()
                return result

            result = asyncio.run(_import_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(import_cmd)
        locations = get_asyncio_run_locations(import_cmd)

        assert count == 1, (
            f"import_cmd must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_consolidate_single_asyncio_run(self) -> None:
        """Test consolidate command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _consolidate_workflow():
                result = await consolidator.consolidate_archives(
                    source_files, output_file, deduplicate, sort_by
                )
                if verify:
                    issues = await storage.db.verify_database_integrity()
                    validator = create_validator()
                    await validator.verify_consistency()
                    await validator.close()
                return result

            result = asyncio.run(_consolidate_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(consolidate)
        locations = get_asyncio_run_locations(consolidate)

        assert count == 1, (
            f"consolidate command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_doctor_single_asyncio_run(self) -> None:
        """Test doctor command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _doctor_workflow():
                doctor_instance = await create_doctor()
                try:
                    report = await doctor_instance.run_diagnostics()
                    if auto_fix:
                        fix_results = await doctor_instance.run_auto_fix()
                    if verify:
                        issues = await storage.db.verify_database_integrity()
                    return report
                finally:
                    await doctor_instance.close()

            report = asyncio.run(_doctor_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(doctor)
        locations = get_asyncio_run_locations(doctor)

        assert count == 1, (
            f"doctor command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_check_single_asyncio_run(self) -> None:
        """Test check command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _check_workflow():
                schema_version = await schema_mgr.detect_version()
                issues = await storage.db.verify_database_integrity()
                archive_file = await get_first_archive_file()

                # Consistency check
                validator = create_validator()
                try:
                    report = await validator.verify_consistency()
                finally:
                    await validator.close()

                # Offset verification
                if has_offsets:
                    offset_validator = create_validator()
                    try:
                        result = await offset_validator.verify_offsets()
                    finally:
                        await offset_validator.close()

                # Repair if needed
                repairs = await storage.db.repair_database(dry_run=False)

                return report

            report = asyncio.run(_check_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(check)
        locations = get_asyncio_run_locations(check)

        assert count == 1, (
            f"check command must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )

    def test_backfill_gmail_ids_single_asyncio_run(self) -> None:
        """Test backfill-gmail-ids command has exactly 1 asyncio.run() call.

        Expected pattern:
            async def _backfill_workflow():
                all_messages = await get_all_messages()
                results = await backfill_gmail_ids(all_messages, batch_size)
                if update_db:
                    await update_gmail_ids(updates)
                return results

            results = asyncio.run(_backfill_workflow())  # SINGLE call
        """
        count = count_asyncio_run_calls(backfill_gmail_ids_cmd)
        locations = get_asyncio_run_locations(backfill_gmail_ids_cmd)

        assert count == 1, (
            f"backfill_gmail_ids_cmd must have exactly 1 asyncio.run() call per ADR-006, "
            f"found {count} at lines: {locations}. "
            "Refactor to use single async workflow function."
        )


# ============================================================================
# Architecture Compliance Tests
# ============================================================================


class TestArchitectureCompliance:
    """Test overall architecture compliance with ADR-006.

    These tests verify architectural principles beyond just counting calls:
    - Async functions are properly defined
    - Resource cleanup happens in finally blocks
    - Error handling doesn't break async flow
    """

    @pytest.mark.parametrize(
        "command_func,command_name",
        [
            (search, "search"),
            (verify_offsets_cmd, "verify_offsets_cmd"),
            (validate, "validate"),
            (status, "status"),
            (retry_delete_cmd, "retry_delete_cmd"),
            (verify_consistency_cmd, "verify_consistency_cmd"),
            (compress, "compress"),
            (repair, "repair"),
            (cleanup, "cleanup"),
            (migrate, "migrate"),
            (dedupe, "dedupe"),
            (import_cmd, "import_cmd"),
            (consolidate, "consolidate"),
            (doctor, "doctor"),
            (check, "check"),
            (backfill_gmail_ids_cmd, "backfill_gmail_ids_cmd"),
        ],
    )
    def test_command_has_inner_async_function(
        self, command_func: Callable[..., None], command_name: str
    ) -> None:
        """Test that command defines inner async workflow function.

        Per ADR-006, the pattern should be:
            def command_name(...):
                async def _workflow():
                    # All async operations
                    ...

                result = asyncio.run(_workflow())
        """
        source = inspect.getsource(command_func)
        tree = ast.parse(source)

        # Find the outer function definition
        outer_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == command_func.__name__:
                outer_func = node
                break

        assert outer_func is not None, f"Could not find function {command_name}"

        # Look for inner async function definitions OR direct calls to imported async functions
        has_inner_async = False
        has_asyncio_run_call = False

        for node in ast.walk(outer_func):
            if isinstance(node, ast.AsyncFunctionDef):
                # Found an async function defined inside the command (Legacy Pattern)
                has_inner_async = True
                break

            # Check for asyncio.run(some_command(...)) (New Pattern)
            if isinstance(node, ast.Call):
                # Check if it's asyncio.run
                is_asyncio_run = False
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run":
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "asyncio":
                        is_asyncio_run = True

                if is_asyncio_run:
                    # Check if it's calling another function
                    if node.args and isinstance(node.args[0], ast.Call):
                        has_asyncio_run_call = True
                        break

        assert has_inner_async or has_asyncio_run_call, (
            f"{command_name} should define an inner async function OR call an imported async command. "
            "Per ADR-006, all async logic should be in a single async context "
            "called via asyncio.run()."
        )

    def test_all_tested_commands_exist(self) -> None:
        """Verify all command functions are properly imported and testable."""
        commands = [
            search,
            verify_offsets_cmd,
            validate,
            status,
            retry_delete_cmd,
            verify_consistency_cmd,
            compress,
            repair,
            cleanup,
            migrate,
            dedupe,
            import_cmd,
            consolidate,
            doctor,
            check,
            backfill_gmail_ids_cmd,
        ]

        for cmd in commands:
            assert callable(cmd), f"{cmd.__name__} should be callable"
            assert inspect.isfunction(cmd), f"{cmd.__name__} should be a function"


# ============================================================================
# Documentation Tests
# ============================================================================


class TestDocumentation:
    """Test that ADR-006 is properly documented."""

    def test_adr_006_exists(self) -> None:
        """Verify ADR-006 document exists and is readable."""
        repo_root = Path(__file__).parent.parent.parent
        adr_path = repo_root / "docs" / "adrs" / "006-async-first-architecture.md"
        assert adr_path.exists(), "ADR-006 document should exist"
        assert adr_path.is_file(), "ADR-006 should be a file"

        content = adr_path.read_text()
        assert "Single bridge at CLI" in content, "ADR-006 should document CLI bridge pattern"
        assert "asyncio.run()" in content, "ADR-006 should mention asyncio.run()"

    def test_adr_006_documents_single_run_pattern(self) -> None:
        """Verify ADR-006 explicitly documents the single asyncio.run() pattern."""
        repo_root = Path(__file__).parent.parent.parent
        adr_path = repo_root / "docs" / "adrs" / "006-async-first-architecture.md"
        content = adr_path.read_text()

        # Should document the CLI bridge pattern
        assert "CLI Bridge Pattern" in content, "ADR-006 should have CLI Bridge Pattern section"

        # Should show example with single asyncio.run()
        assert "asyncio.run(facade" in content or "asyncio.run(_" in content, (
            "ADR-006 should show asyncio.run() example"
        )
