"""Send one reply through Microsoft Graph's ``sendMail`` endpoint."""

from __future__ import annotations

from email.utils import parseaddr

import requests

from app.mail.providers.graph import graph_error
from app.mail.text_utils import strip_bearer
from app.schemas import Email

GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


class ReplySendError(Exception):
    """A configuration or Graph error that the API should report."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _reply_subject(subject: str) -> str:
    subject = (subject or "").strip() or "(no subject)"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _recipient(sender: str) -> tuple[str, str]:
    name, address = parseaddr(sender or "")
    if not address and "@" in (sender or ""):
        address = sender.strip()
    if not address or "@" not in address:
        raise ReplySendError("Cannot send: the original sender has no email address.", 400)
    return name.strip(), address.strip()


def send_reply(email: Email, reply: str, token: str) -> dict:
    """Send ``reply`` to the original sender and return a small receipt."""
    token = strip_bearer(token)
    if not token:
        raise ReplySendError(
            "Paste a Microsoft Graph token with Mail.Send permission before sending.",
            400,
        )

    body = (reply or "").strip()
    if not body:
        raise ReplySendError("The reply is empty.", 400)
    if len(body) > 50_000:
        raise ReplySendError("The reply is too long.", 400)

    name, address = _recipient(email.sender)
    subject = _reply_subject(email.subject)
    to_recipient: dict[str, dict[str, str]] = {"emailAddress": {"address": address}}
    if name:
        to_recipient["emailAddress"]["name"] = name

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [to_recipient],
        },
        "saveToSentItems": True,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(GRAPH_SEND_URL, json=payload, headers=headers, timeout=30)
    except requests.RequestException:
        raise ReplySendError("Could not reach Microsoft Graph. Check your connection.", 502) from None

    if response.status_code == 401:
        raise ReplySendError("The token expired or is invalid. Paste a fresh token.", 401)
    if response.status_code == 403:
        raise ReplySendError(
            "The token is missing Mail.Send permission. Consent to it in Graph Explorer.",
            403,
        )
    if not response.ok:
        raise ReplySendError(
            f"Microsoft Graph returned {response.status_code}: {graph_error(response)}",
            502,
        )

    return {"sent": True, "to": address, "subject": subject}
