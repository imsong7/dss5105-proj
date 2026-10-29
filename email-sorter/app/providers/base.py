from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..models import Email


@dataclass(frozen=True)
class InlineImage:
    name: str
    data: bytes


@dataclass(frozen=True)
class MailQuery:
    """Which emails to fetch.

    ``limit`` is always a hard safety cap. ``since`` and ``before`` form an
    inclusive received-date window; leave both as ``None`` to get the newest
    ``limit`` emails. Both bounds are inclusive so a UI can send
    ``before = end of the chosen day`` without losing that day's mail.
    """

    limit: int = 15
    since: datetime | None = None
    before: datetime | None = None


class ProviderError(Exception):
    """Something went wrong talking to the mail source."""


class AuthError(ProviderError):
    """Credentials are missing, wrong or expired."""


class EmailProvider(ABC):
    """Every mail source (Outlook, Gmail, IMAP...) implements this one method."""

    name: str = "base"

    @abstractmethod
    def fetch_emails(self, query: MailQuery | None = None) -> list[Email]:
        """Return matching emails, newest first.

        ``query`` carries an optional received-date window plus a hard cap.
        When it is omitted or has no window, return the newest ``query.limit``
        emails (15 by default).
        """

    def fetch_images(
        self, email: Email, max_images: int, max_bytes: int
    ) -> list[InlineImage]:
        """Return inline images only; file attachments are not processed."""
        return []
