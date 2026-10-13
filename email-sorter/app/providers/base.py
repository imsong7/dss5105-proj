from abc import ABC, abstractmethod

from ..models import Email


class ProviderError(Exception):
    """Something went wrong talking to the mail source."""


class AuthError(ProviderError):
    """Credentials are missing, wrong or expired."""


class EmailProvider(ABC):
    """Every mail source (Outlook, Gmail, IMAP...) implements this one method."""

    name: str = "base"

    @abstractmethod
    def fetch_emails(self, limit: int = 15) -> list[Email]:
        """Return the newest `limit` emails, newest first."""
