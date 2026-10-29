"""Read-only Microsoft Graph calls using the pasted token. Only GET requests are ever made."""
from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests

from .graph_token import TokenExpired

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
FIELDS = "id,receivedDateTime,from,toRecipients,ccRecipients,subject,body,conversationId,webLink"
PREFER = 'outlook.body-content-type="text"'


def _get(url: str, token: str, max_retries: int = 6) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Prefer": PREFER}
    for attempt in range(max_retries):
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code in (429, 503, 504):
            wait = int(r.headers.get("Retry-After", 2 ** attempt * 5))
            log.warning("Graph throttled (%s); waiting %ss", r.status_code, wait)
            time.sleep(wait)
            continue
        if r.status_code == 401:
            raise TokenExpired("Graph rejected the token (expired or invalid). Paste a new one from Graph Explorer.")
        if r.status_code == 403:
            raise PermissionError("The token can't read mail. In Graph Explorer, consent to Mail.Read and copy a new token.")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Graph request kept failing after {max_retries} retries")


def get_me(token: str) -> dict:
    return _get(f"{GRAPH}/me?$select=mail,userPrincipalName,displayName", token)


def my_address(token: str) -> str:
    me = get_me(token)
    return (me.get("mail") or me.get("userPrincipalName") or "").lower()


def list_inbox(token: str, since_iso: str | None = None, max_n: int = 1000) -> list[dict]:
    """Inbox messages, newest first, optionally only those received at or after since_iso."""
    url = f"{GRAPH}/me/mailFolders/inbox/messages?$select={FIELDS}&$orderby=receivedDateTime desc&$top=50"
    if since_iso:
        url += "&$filter=" + quote(f"receivedDateTime ge {since_iso}", safe="")
    out: list[dict] = []
    while url and len(out) < max_n:
        data = _get(url, token)
        out.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return out[:max_n]
