import requests

from ..models import Email
from ..textutil import clean, strip_html
from .base import AuthError, EmailProvider, ProviderError

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages"


class GraphProvider(EmailProvider):
    """Outlook / Microsoft 365 through Microsoft Graph using a pasted access token
    (for example from Graph Explorer). No Azure app registration needed."""

    name = "outlook"

    def __init__(self, token: str):
        token = (token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise AuthError("Paste a Microsoft Graph access token first.")
        self.token = token

    def fetch_emails(self, limit: int = 15) -> list[Email]:
        params = {
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,body",
            "$orderby": "receivedDateTime desc",
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Prefer": 'outlook.body-content-type="text"',
        }
        try:
            r = requests.get(GRAPH_URL, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Microsoft Graph: {exc}") from exc

        if r.status_code == 401:
            raise AuthError("Token expired or invalid. Paste a fresh token from Graph Explorer.")
        if r.status_code == 403:
            raise AuthError("Token is missing the Mail.Read permission. Consent to it in Graph Explorer.")
        if not r.ok:
            raise ProviderError(f"Graph returned {r.status_code}: {r.text[:200]}")

        emails = []
        for m in r.json().get("value", []):
            addr = (m.get("from") or {}).get("emailAddress", {})
            sender = addr.get("name") or addr.get("address") or "Unknown sender"
            if addr.get("address") and addr.get("name"):
                sender = f"{addr['name']} <{addr['address']}>"
            body = (m.get("body") or {}).get("content", "") or ""
            if "<html" in body.lower() or "<div" in body.lower():
                body = strip_html(body)
            emails.append(
                Email(
                    id=m["id"],
                    subject=m.get("subject") or "(no subject)",
                    sender=sender,
                    received=m.get("receivedDateTime", ""),
                    preview=clean(m.get("bodyPreview", ""), 200),
                    body=clean(body),
                )
            )
        return emails
