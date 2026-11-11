"""Mail source for messages pushed by a Power Automate flow."""

from datetime import datetime, timezone

from ..pushed_store import pushed_images, pushed_store
from ..schemas import Email
from .base import EmailProvider, InlineImage, MailQuery


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
        for email in pushed_store.all(self.owner):
            received = email.received_at
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

    def fetch_images(self, email: Email, max_images: int, max_bytes: int) -> list[InlineImage]:
        """Images the flow sent with this email (pushed mail cannot be fetched later)."""
        images = [
            InlineImage(name=name, data=data)
            for name, data in pushed_images.get(self.owner, email.id)
            if len(data) <= max_bytes
        ]
        return images[:max_images]

    def done_with_images(self, email: Email) -> None:
        pushed_images.drop(self.owner, email.id)
