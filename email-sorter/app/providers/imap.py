import email
import imaplib
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message

from ..models import Email
from ..textutil import clean, strip_html
from .base import AuthError, EmailProvider, InlineImage, MailQuery, ProviderError

# IMAP wants English month names regardless of the machine locale, so a fixed
# table is safer than strftime("%b").
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(value: datetime) -> str:
    """Format a date the way IMAP ``SINCE``/``BEFORE`` expect: ``13-Nov-2026``."""
    return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year}"


def _imap_criteria(query: MailQuery) -> list[str]:
    """IMAP search keys for an inclusive received-date window.

    IMAP dates are day-granular, so the upper bound is pushed to the next day
    with ``BEFORE`` to keep the last day of the window included.
    """
    criteria: list[str] = []
    if query.since:
        criteria += ["SINCE", _imap_date(query.since)]
    if query.before:
        criteria += ["BEFORE", _imap_date(query.before + timedelta(days=1))]
    return criteria


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _body(msg: Message) -> str:
    plain, html = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = text
    return plain or strip_html(html)


class ImapProvider(EmailProvider):
    """Gmail, Yahoo, iCloud, or any normal IMAP mailbox.
    Gmail: enable 2-step verification and create an App Password.
    Host examples: imap.gmail.com, outlook.office365.com, imap.mail.yahoo.com"""

    name = "imap"

    def __init__(self, host: str, user: str, password: str, folder: str = "INBOX"):
        if not (host and user and password):
            raise AuthError("IMAP needs host, email address and app password.")
        self.host, self.user, self.password, self.folder = host.strip(), user.strip(), password, folder

    def fetch_emails(self, query: MailQuery | None = None) -> list[Email]:
        query = query or MailQuery()
        limit = max(1, int(query.limit))
        try:
            box = imaplib.IMAP4_SSL(self.host)
            box.login(self.user, self.password)
        except imaplib.IMAP4.error as exc:
            raise AuthError(f"IMAP login failed: {exc}") from exc
        except OSError as exc:
            raise ProviderError(f"Could not connect to {self.host}: {exc}") from exc

        emails: list[Email] = []
        try:
            box.select(self.folder, readonly=True)  # read-only: nothing gets marked as read
            _, data = box.search(None, *(_imap_criteria(query) or ["ALL"]))
            ids = data[0].split()[-limit:][::-1]
            for num in ids:
                _, parts = box.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(parts[0][1])
                body = clean(_body(msg))
                emails.append(
                    Email(
                        id=num.decode(),
                        subject=_decode(msg.get("Subject")) or "(no subject)",
                        sender=_decode(msg.get("From")) or "Unknown sender",
                        received=msg.get("Date", ""),
                        preview=body[:200].replace("\n", " "),
                        body=body,
                    )
                )
        finally:
            try:
                box.logout()
            except Exception:
                pass
        return emails

    def fetch_images(
        self, email_item: Email, max_images: int, max_bytes: int
    ) -> list[InlineImage]:
        try:
            box = imaplib.IMAP4_SSL(self.host)
            box.login(self.user, self.password)
        except imaplib.IMAP4.error as exc:
            raise AuthError(f"IMAP login failed: {exc}") from exc
        except OSError as exc:
            raise ProviderError(f"Could not connect to {self.host}: {exc}") from exc

        images = []
        try:
            status, _ = box.select(self.folder, readonly=True)
            if status != "OK":
                raise ProviderError(f"Could not open IMAP folder {self.folder!r}.")
            status, data = box.fetch(email_item.id.encode(), "(BODY.PEEK[])")
            if status != "OK" or not data or not data[0]:
                raise ProviderError("Could not refetch the email to read inline images.")
            message = email.message_from_bytes(data[0][1])
            for part in message.walk():
                content_type = part.get_content_type().lower()
                content_id = part.get("Content-ID")
                if (
                    not content_type.startswith("image/")
                    or (
                        part.get_content_disposition() != "inline"
                        and not content_id
                    )
                ):
                    continue
                payload = part.get_payload(decode=True)
                if not payload or len(payload) > max_bytes:
                    continue
                images.append(
                    InlineImage(
                        part.get_filename() or content_id or "inline image",
                        payload,
                    )
                )
                if len(images) >= max_images:
                    break
        finally:
            try:
                box.logout()
            except Exception:
                pass
        return images
