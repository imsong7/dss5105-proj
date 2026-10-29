"""Mail source for messages pushed by a Power Automate flow."""

from datetime import datetime, timezone

from ..inbound_store import inbound_store
from ..models import Email
from .base import EmailProvider, MailQuery


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _received_at(email: Email) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(email.received.replace("Z", "+00:00")))
    except (AttributeError, TypeError, ValueError):
        return None


class PushedProvider(EmailProvider):
    """Reads this owner's slice of the queue filled by ``POST /api/inbound/outlook``."""

    name = "powerautomate"

    def __init__(self, owner: str = ""):
        self.owner = owner

    def fetch_emails(self, query: MailQuery | None = None) -> list[Email]:
        query = query or MailQuery()
        since = _aware(query.since) if query.since else None
        before = _aware(query.before) if query.before else None

        matches: list[tuple[datetime, Email]] = []
        for email in inbound_store.all(self.owner):
            received = _received_at(email)
            if received is None:
                # Keep mail with an unparseable date rather than silently hiding it.
                matches.append((datetime.min.replace(tzinfo=timezone.utc), email))
                continue
            if since and received < since:
                continue
            if before and received > before:
                continue
            matches.append((received, email))

        matches.sort(key=lambda pair: pair[0], reverse=True)
        return [email for _, email in matches[: max(1, int(query.limit))]]
