import re
from html import unescape
from urllib.parse import parse_qs, urlparse

# A link keeps its address as "text<https://...>", the way Outlook writes links
# in plain text, so job listings and buttons still have somewhere to go.
_ANCHOR = re.compile(
    r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']?(?P<url>https?://[^"'\s>]+)["']?[^>]*>(?P<inner>.*?)</a\s*>"""
)
LINK_IN_TEXT = re.compile(r"<(https?://[^>\s]+)>")
_OPEN, _CLOSE = "\x02", "\x03"  # stand-ins, so the tag stripper leaves the address


def unwrap_safelink(url: str) -> str:
    """Outlook "Safe Links" wrap every address; keep the real one."""
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("safelinks.protection.outlook.com"):
        real = parse_qs(parsed.query).get("url")
        if real and real[0].startswith(("http://", "https://")):
            return real[0]
    return url


def _keep_link(match: re.Match) -> str:
    url = unwrap_safelink(unescape(match.group("url")))
    inner = match.group("inner")
    label = unescape(re.sub(r"(?s)<[^>]+>", " ", inner)).strip()
    if not label:
        return " "  # an image-only link (logos)
    if label.rstrip("/") == url.rstrip("/"):
        return f" {url} "
    return f"{inner}{_OPEN}{url}{_CLOSE}"


def strip_html(text: str) -> str:
    # Plain text that already writes links as "<https://...>" keeps them.
    text = LINK_IN_TEXT.sub(lambda m: f"{_OPEN}{m.group(1)}{_CLOSE}", text)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = _ANCHOR.sub(_keep_link, text)
    # A line break is one newline; the end of a block is a paragraph break.
    text = re.sub(r"(?i)<li\b[^>]*>", "\n• ", text)  # list items stay a list
    text = re.sub(r"(?i)<br\s*/?>|</tr>", "\n", text)
    text = re.sub(r"(?i)</p>|</div>|</h[1-6]>|</table>|</blockquote>|</ul>|</ol>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(text).replace(_OPEN, "<").replace(_CLOSE, ">")


def without_link_addresses(text: str) -> str:
    """The text with "<https://...>" addresses removed (for the model's budget)."""
    return LINK_IN_TEXT.sub("", text)


def clean(text: str, limit: int | None = None) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)  # no stray spaces at line starts and ends
    # A removed tag leaves a space behind: "23:59</b>." must not become "23:59 .".
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:limit] if limit else text


_OUTLOOK_HOSTS = ("outlook.office365.com", "outlook.office.com", "outlook.live.com")


def outlook_link(web_link: str = "", item_id: str = "") -> str:
    """A link that opens the message in Outlook on the web, or "".

    A ``webLink`` from Microsoft is used when it points at Outlook; otherwise one is built
    from the message's Outlook item id, in the same form Graph uses for ``webLink``.
    Nothing else is ever returned, so the link cannot lead anywhere but Outlook.
    """
    from urllib.parse import quote, urlparse

    link = (web_link or "").strip()
    parsed = urlparse(link)
    if parsed.scheme == "https" and (parsed.hostname or "").lower() in _OUTLOOK_HOSTS:
        return link[:2000]
    item_id = (item_id or "").strip()
    if not item_id or item_id.startswith("<") or len(item_id) > 500:
        return ""  # an internet message id ("<...@...>") cannot be opened in Outlook
    return f"https://outlook.office365.com/owa/?ItemID={quote(item_id, safe='')}&exvsurl=1&viewmodel=ReadMessageItem"

