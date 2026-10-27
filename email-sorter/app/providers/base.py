from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Email


@dataclass(frozen=True)
class InlineImage:
    name: str
    data: bytes


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

    def fetch_images(
        self, email: Email, max_images: int, max_bytes: int
    ) -> list[InlineImage]:
        """Return inline images only; file attachments are not processed."""
        return []
