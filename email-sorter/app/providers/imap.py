import email
import imaplib
from email.header import decode_header, make_header
from email.message import Message

from ..models import Email
from ..textutil import clean, strip_html
from .base import AuthError, EmailProvider, ProviderError


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

    def fetch_emails(self, limit: int = 15) -> list[Email]:
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
            _, data = box.search(None, "ALL")
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
