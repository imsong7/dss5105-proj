"""Where "Open in Outlook" should send the student.

Best case is the exact message. Microsoft Graph returns a ``webLink`` that opens
it in Outlook on the web. Mail pushed by Power Automate may not carry one, so
the link is built from Outlook's own message id when the flow sends it. With
neither, the link opens the inbox, and Microsoft shows its sign-in page first
if the student is not signed in.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode, urlparse

from .schemas import Email

OUTLOOK_HOME = "https://outlook.office.com/mail/"
OWA_ITEM = "https://outlook.office.com/owa/?ItemID={item}&exvsurl=1&viewmodel=ReadMessageItem"

# A pushed message is only trusted as a link target when it points at Outlook.
_OUTLOOK_HOSTS = (
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.cloud.microsoft",
    "outlook.live.com",
)


def _is_outlook_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == allowed or host.endswith("." + allowed) for allowed in _OUTLOOK_HOSTS
    )


def outlook_link(email: Email, owner: str = "") -> dict:
    """``{"url": ..., "exact": bool}``; ``exact`` is true when it opens this message."""
    if email.web_link and _is_outlook_url(email.web_link):
        return {"url": email.web_link, "exact": True}

    outlook_id = (email.outlook_id or "").strip()
    if outlook_id and not outlook_id.startswith("<"):
        return {"url": OWA_ITEM.format(item=quote(outlook_id, safe="")), "exact": True}

    hint = (owner or "").strip()
    if "@" in hint:
        return {"url": f"{OUTLOOK_HOME}?{urlencode({'login_hint': hint})}", "exact": False}
    return {"url": OUTLOOK_HOME, "exact": False}
