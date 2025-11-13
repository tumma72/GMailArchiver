"""OAuth2 authentication for Gmail API."""

import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmailarchiver.path_validator import validate_file_path

# Gmail API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]


class GmailAuthenticator:
    """Handle OAuth2 authentication for Gmail API."""

    def __init__(
        self,
        credentials_file: str = 'credentials.json',
        token_file: str = 'token.json',
        validate_paths: bool = True
    ) -> None:
        """
        Initialize the authenticator.

        Args:
            credentials_file: Path to OAuth2 credentials JSON file
            token_file: Path to save/load access token (JSON format)
            validate_paths: Whether to validate paths (set False for testing)

        Raises:
            PathTraversalError: If validate_paths=True and paths attempt to escape working directory
        """
        # Validate paths to prevent path traversal attacks (unless disabled for testing)
        if validate_paths:
            self.credentials_file = validate_file_path(credentials_file)
            self.token_file = validate_file_path(token_file)
        else:
            from pathlib import Path
            self.credentials_file = Path(credentials_file).resolve()
            self.token_file = Path(token_file).resolve()
        self._creds: Credentials | None = None

    def authenticate(self) -> Credentials:
        """
        Perform OAuth2 authentication flow.

        Returns:
            Google OAuth2 credentials

        Raises:
            FileNotFoundError: If credentials.json is not found
        """
        # Try to load existing token from JSON
        if self.token_file.exists():
            with open(self.token_file) as token:
                creds_data = json.load(token)
            self._creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

        # If no valid credentials, refresh or run auth flow
        if not self._creds or not self._creds.valid:
            if self._creds and self._creds.expired and self._creds.refresh_token:
                # Refresh expired token
                self._creds.refresh(Request())
            else:
                # Run OAuth2 flow
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"Credentials file not found: {self.credentials_file}\n"
                        "Please download it from Google Cloud Console:\n"
                        "1. Go to https://console.cloud.google.com/\n"
                        "2. Create or select a project\n"
                        "3. Enable Gmail API\n"
                        "4. Create OAuth 2.0 Client ID (Desktop app)\n"
                        "5. Download credentials and save as 'credentials.json'"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file),
                    SCOPES
                )
                self._creds = flow.run_local_server(port=0)

            # Save the credentials for next run as JSON
            with open(self.token_file, 'w') as token:
                token.write(self._creds.to_json())

        return self._creds

    @property
    def credentials(self) -> Credentials | None:
        """Get current credentials."""
        return self._creds

    def revoke(self) -> None:
        """Revoke authentication and delete token file."""
        if self.token_file.exists():
            os.remove(self.token_file)
        self._creds = None
