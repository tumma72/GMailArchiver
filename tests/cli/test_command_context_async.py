"""Tests for CLI async-only architecture.

These tests verify CommandContext works with GmailClient.
Since the architecture is now async-only, the `gmail` attribute stores GmailClient.
"""

from unittest.mock import MagicMock, patch

from gmailarchiver.cli.command_context import CommandContext, with_context
from gmailarchiver.connectors.gmail_client import GmailClient


class TestCommandContextGmail:
    """Tests for CommandContext Gmail client support."""

    def test_command_context_has_gmail_attribute(self) -> None:
        """Test CommandContext has gmail attribute."""
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager(json_mode=True)
        ctx = CommandContext(output=output)

        # Should have gmail attribute (defaults to None)
        assert hasattr(ctx, "gmail")
        assert ctx.gmail is None

    def test_command_context_can_store_async_gmail_client(self) -> None:
        """Test CommandContext can store GmailClient in gmail field."""
        from gmailarchiver.cli.output import OutputManager

        output = OutputManager(json_mode=True)
        ctx = CommandContext(output=output)

        # Create mock async client
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        async_client = GmailClient(mock_creds)

        # Should be able to set gmail to GmailClient
        ctx.gmail = async_client
        assert ctx.gmail is async_client
        assert isinstance(ctx.gmail, GmailClient)


class TestWithContextGmailAuth:
    """Tests for with_context decorator Gmail authentication."""

    def test_with_context_accepts_requires_gmail_param(self) -> None:
        """Test with_context decorator accepts requires_gmail parameter."""

        # Should not raise - decorator accepts the parameter
        @with_context(requires_gmail=True)
        def dummy_command(ctx: CommandContext) -> None:
            pass

        # Decorator should create a wrapper
        assert callable(dummy_command)

    @patch("gmailarchiver.cli.command_context.GmailClient")
    def test_with_context_initializes_async_gmail_client(self, mock_gmail_cls: MagicMock) -> None:
        """Test with_context initializes GmailClient when requires_gmail=True."""
        from unittest.mock import AsyncMock

        # Mock GmailClient.create() to return a mock client
        mock_client = MagicMock(spec=GmailClient)
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_client._credentials = mock_creds
        mock_client._authenticator = None
        mock_client.close = AsyncMock()
        mock_gmail_cls.create = AsyncMock(return_value=mock_client)

        captured_ctx: CommandContext | None = None

        @with_context(requires_gmail=True)
        def test_command(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        # Call the command
        test_command(json_output=True)

        # Context should have gmail set
        assert captured_ctx is not None
        assert captured_ctx.gmail is not None
        # GmailClient.create was called
        mock_gmail_cls.create.assert_called_once()

    @patch("gmailarchiver.cli.command_context.GmailClient")
    def test_async_gmail_client_properly_closed_on_exit(self, mock_gmail_cls: MagicMock) -> None:
        """Test GmailClient is properly closed when command exits."""
        from unittest.mock import AsyncMock

        # Track if close was called
        close_called = False

        async def tracked_close() -> None:
            nonlocal close_called
            close_called = True

        # Mock GmailClient.create() to return a mock client
        mock_client = MagicMock(spec=GmailClient)
        mock_creds = MagicMock()
        mock_creds.token = "test_token"
        mock_client._credentials = mock_creds
        mock_client._authenticator = None
        mock_client.close = tracked_close
        mock_gmail_cls.create = AsyncMock(return_value=mock_client)

        @with_context(requires_gmail=True)
        def test_command(ctx: CommandContext) -> None:
            # Command body - gmail client should be available
            assert ctx.gmail is not None

        test_command(json_output=True)

        # Close should have been called during cleanup
        assert close_called is True


class TestWithContextNoGmail:
    """Tests for using with_context without Gmail."""

    def test_with_context_no_gmail_required(self) -> None:
        """Test with_context works without requiring Gmail."""
        captured_ctx: CommandContext | None = None

        @with_context(requires_gmail=False)
        def test_command(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        test_command(json_output=True)

        assert captured_ctx is not None
        # gmail should be None when not required
        assert captured_ctx.gmail is None

    def test_with_context_default_no_gmail(self) -> None:
        """Test with_context defaults to not requiring Gmail."""
        captured_ctx: CommandContext | None = None

        @with_context()
        def test_command(ctx: CommandContext) -> None:
            nonlocal captured_ctx
            captured_ctx = ctx

        test_command(json_output=True)

        assert captured_ctx is not None
        # gmail should be None by default
        assert captured_ctx.gmail is None
