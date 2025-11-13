"""OAuth2 authentication for Gmail API."""

import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

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
        token_file: str = 'token.pickle'
    ) -> None:
        """
        Initialize the authenticator.

        Args:
            credentials_file: Path to OAuth2 credentials JSON file
            token_file: Path to save/load access token
        """
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self._creds: Credentials | None = None

    def authenticate(self) -> Credentials:
        """
        Perform OAuth2 authentication flow.

        Returns:
            Google OAuth2 credentials

        Raises:
            FileNotFoundError: If credentials.json is not found
        """
        # Try to load existing token
        if self.token_file.exists():
            with open(self.token_file, 'rb') as token:
                self._creds = pickle.load(token)

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

            # Save the credentials for next run
            with open(self.token_file, 'wb') as token:
                pickle.dump(self._creds, token)

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
