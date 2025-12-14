"""OAuth2 authentication for Gmail API."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmailarchiver.shared.path_validator import validate_file_path

__all__ = ["GmailAuthenticator", "Credentials", "SCOPES"]

# Gmail API scopes
# NOTE: Using full Gmail access scope to support all operations including permanent deletion.
# The gmail.modify scope is insufficient for permanent deletion (messages.delete API).
# This is a breaking change - existing users must re-authenticate (run `gmailarchiver auth-reset`).
SCOPES = ["https://mail.google.com/"]


def _get_bundled_credentials_path() -> Path:
    """Get path to bundled OAuth credentials."""
    # Get the directory where this module is located
    module_dir = Path(__file__).parent
    return module_dir / "config" / "oauth_credentials.json"


def _get_default_token_path() -> Path:
    """
    Get default path for user token following XDG Base Directory standard.

    Returns:
        Path to token file in user's config directory:
        - Linux/macOS: ~/.config/gmailarchiver/token.json
        - Windows: %APPDATA%/gmailarchiver/token.json
    """
    import os

    # Respect XDG_CONFIG_HOME if set (Linux/macOS)
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        config_dir = Path(config_home)
    elif os.name == "nt":  # Windows
        config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # macOS/Linux
        config_dir = Path.home() / ".config"

    # Create gmailarchiver subdirectory
    app_config_dir = config_dir / "gmailarchiver"
    app_config_dir.mkdir(parents=True, exist_ok=True)

    return app_config_dir / "token.json"


class GmailAuthenticator:
    """
    Handle OAuth2 authentication for Gmail API.

    This uses pre-configured OAuth credentials bundled with the application.
    Users only need to authorize the app through their Google account - no need
    to create their own Google Cloud project or credentials.
    """

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
        validate_paths: bool = True,
        output: Any | None = None,
    ) -> None:
        """
        Initialize the authenticator.

        Args:
            credentials_file: Optional custom OAuth2 credentials file.
                            If None (default), uses bundled app credentials.
                            Only needed for developers or advanced users.
            token_file: Path to save/load user's access token (JSON format).
                       If None (default), uses ~/.config/gmailarchiver/token.json
            validate_paths: Whether to validate paths (set False for testing)
            output: Optional OutputManager for structured logging

        Raises:
            PathTraversalError: If validate_paths=True and paths attempt to escape working directory
        """
        # Use bundled credentials by default, or custom if provided
        if credentials_file is None:
            self.credentials_file = _get_bundled_credentials_path()
        else:
            if validate_paths:
                self.credentials_file = validate_file_path(credentials_file)
            else:
                self.credentials_file = Path(credentials_file).resolve()

        # Token file - use XDG config directory by default
        if token_file is None:
            self.token_file = _get_default_token_path()
        else:
            if validate_paths:
                self.token_file = validate_file_path(token_file)
            else:
                self.token_file = Path(token_file).resolve()

        self._creds: Credentials | None = None
        self.output = output

    def _log(self, message: str, level: str = "INFO") -> None:
        """Log message through OutputManager if available, otherwise print.

        Args:
            message: Message to log
            level: Severity level (INFO, WARNING, ERROR, SUCCESS)
        """
        if self.output:
            # Use OutputManager's methods
            if level == "WARNING":
                self.output.warning(message)
            elif level == "ERROR":
                self.output.error(message, exit_code=0)
            elif level == "SUCCESS":
                self.output.success(message)
            else:  # INFO
                self.output.info(message)
        else:
            # Fallback to print for backward compatibility
            print(message)

    def authenticate(self) -> Credentials:
        """
        Perform OAuth2 authentication flow.

        On first run, this will:
        1. Open your web browser
        2. Ask you to log in to your Google account
        3. Ask you to authorize Gmail Archiver to access your Gmail
        4. Save the authorization token locally for future use

        On subsequent runs, it will reuse the saved token (no browser needed).

        Returns:
            Google OAuth2 credentials

        Raises:
            FileNotFoundError: If bundled credentials are missing (shouldn't happen)
            Exception: If OAuth flow fails
        """
        # Try to load existing token from JSON
        if self.token_file.exists():
            try:
                with open(self.token_file) as token:
                    creds_data = json.load(token)
                self._creds = Credentials.from_authorized_user_info(creds_data, SCOPES)  # type: ignore[no-untyped-call]
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                self._log(f"Warning: Failed to load saved token: {e}", "WARNING")
                self._log("Will re-authenticate...", "INFO")
                self._creds = None

        # If no valid credentials, refresh or run auth flow
        if not self._creds or not self._creds.valid:
            if self._creds and self._creds.expired and self._creds.refresh_token:
                # Refresh expired token
                self._log("Refreshing expired token...", "INFO")
                try:
                    self._creds.refresh(Request())  # type: ignore[no-untyped-call]
                except Exception as e:
                    self._log(f"Warning: Token refresh failed: {e}", "WARNING")
                    self._log("Will re-authenticate...", "INFO")
                    self._creds = None

            # Run OAuth2 flow if we still don't have valid credentials
            if not self._creds or not self._creds.valid:
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"OAuth credentials file not found: {self.credentials_file}\n"
                        "This is a bug - the application's OAuth credentials are missing.\n"
                        "Please reinstall the application or report this issue."
                    )

                self._log("\n" + "=" * 60, "INFO")
                self._log("GMAIL AUTHORIZATION REQUIRED", "INFO")
                self._log("=" * 60, "INFO")
                self._log("\nThis application needs permission to access your Gmail.", "INFO")
                self._log("A browser window will open where you can:", "INFO")
                self._log("  1. Log in to your Google account", "INFO")
                self._log("  2. Review the permissions requested", "INFO")
                self._log("  3. Click 'Allow' to authorize Gmail Archiver", "INFO")
                self._log("\nYour authorization will be saved locally, so you only", "INFO")
                self._log("need to do this once (unless you revoke access).", "INFO")
                self._log("=" * 60 + "\n", "INFO")

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_file), SCOPES
                    )
                    # Use localhost redirect - most user-friendly
                    self._creds = flow.run_local_server(
                        port=0,
                        authorization_prompt_message="Opening browser for authorization...",
                        success_message="Authorization successful! You can close this window.",
                        open_browser=True,
                    )
                    self._log("\n✓ Authorization successful!", "SUCCESS")
                except Exception as e:
                    self._log(f"\n✗ Authorization failed: {e}", "ERROR")
                    raise

            # Save the credentials for next run as JSON
            try:
                with open(self.token_file, "w") as token:
                    token.write(self._creds.to_json())
                self._log(f"✓ Authorization saved to: {self.token_file}", "SUCCESS")
            except Exception as e:
                self._log(f"Warning: Failed to save token: {e}", "WARNING")
                self._log("You may need to re-authorize next time.", "WARNING")

        return self._creds

    @property
    def credentials(self) -> Credentials | None:
        """Get current credentials."""
        return self._creds

    def validate_scopes(self, required_scopes: list[str]) -> bool:
        """
        Validate that current credentials have required scopes.

        This is critical for operations like permanent deletion that require
        specific OAuth scopes. Use this before attempting operations that may
        fail with 403 Insufficient Permission errors.

        Args:
            required_scopes: List of required OAuth scope URLs

        Returns:
            True if all required scopes are present in credentials

        Example:
            >>> auth = GmailAuthenticator()
            >>> auth.authenticate()
            >>> if not auth.validate_scopes(['https://mail.google.com/']):
            ...     print("Missing deletion permission - re-authenticate required")
        """
        if not self._creds or not self._creds.scopes:
            return False

        creds_scopes = set(self._creds.scopes)
        required = set(required_scopes)

        # Full Gmail access (https://mail.google.com/) covers all Gmail operations
        if "https://mail.google.com/" in creds_scopes:
            return True

        # Otherwise check if specific required scopes are present
        return required.issubset(creds_scopes)

    def revoke(self) -> None:
        """Revoke authentication and delete token file."""
        if self.token_file.exists():
            os.remove(self.token_file)
        self._creds = None

    # ==================== ASYNC METHODS ====================
    # These methods wrap sync operations in asyncio.to_thread() to avoid
    # blocking the event loop during OAuth operations.

    async def authenticate_async(self) -> Credentials:
        """
        Perform OAuth2 authentication flow asynchronously.

        This wraps the sync authenticate() method in asyncio.to_thread() to
        prevent blocking the event loop during:
        - Token file I/O
        - Token refresh (network request)
        - OAuth flow (browser interaction, 30+ seconds)

        Returns:
            Google OAuth2 credentials

        Raises:
            FileNotFoundError: If bundled credentials are missing
            Exception: If OAuth flow fails
        """
        return await asyncio.to_thread(self.authenticate)

    async def refresh_token_async(self) -> Credentials | None:
        """
        Refresh expired token asynchronously.

        This method checks if the current token needs refresh and performs
        the refresh in a thread pool to avoid blocking the event loop.

        Returns:
            Refreshed credentials, or None if no credentials exist

        Note:
            This is a no-op if credentials are still valid or don't exist.
            Use authenticate_async() for initial authentication.
        """
        if not self._creds:
            return None

        if self._creds.valid:
            return self._creds

        if self._creds.expired and self._creds.refresh_token:
            await asyncio.to_thread(self._refresh_token_sync)

        return self._creds

    def _refresh_token_sync(self) -> None:
        """
        Sync helper: Refresh the current token.

        This is called via asyncio.to_thread() from refresh_token_async().
        """
        if self._creds and self._creds.expired and self._creds.refresh_token:
            self._creds.refresh(Request())  # type: ignore[no-untyped-call]

            # Save refreshed token
            try:
                with open(self.token_file, "w") as token:
                    token.write(self._creds.to_json())  # type: ignore[no-untyped-call]
            except Exception:
                pass  # Non-critical - token still valid in memory
