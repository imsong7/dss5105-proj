"""An event announced in an email's text -> one event card: what, when, where, and how to sign up.

Posters are read from images (``poster.py``); this reads the email text itself, so it
also works while Power Automate sends text only. It reuses the poster's date, venue
and link finders and returns the same shape as ``email.poster``.

Conservative on purpose: a wrong card is worse than none. An email gets a card only when
its subject names an event (talk, workshop, fair, ...), the event has a date AND a time,
and the email says where it is or how to sign up. Replies, Canvas notices and digests
listing many dates get no card. Dates that are sign-up deadlines ("register by 1 Nov")
are skipped, and a date with a time is preferred, since that is usually the event itself.
"""

from __future__ import annotations

import re

from app.extract.poster import _LINK, _VENUE_LABEL, _VENUE_WORDS, _WHEN, MAX_LINKS, find_links, find_when
from app.schemas import Email

READ_CHARS = 4000  # events are announced near the top; long digests are not events
MAX_DATES = 3  # more distinct dates than this: a digest or schedule, not one event

_EVENT_WORDS = re.compile(
    r"\b(?:event|talk|workshop|seminar|webinar|info(?:rmation)?\s+session|briefing|"
    r"conference|symposium|forum|panel|fair|festival|concert|performance|exhibition|"
    r"competition|hackathon|open\s+house|orientation|networking|sharing\s+session|"
    r"masterclass|bootcamp|tea\s+session|meet[\s-]and[\s-]greet)\b",
    re.IGNORECASE,
)
# Words just before a date that make it a sign-up or submission deadline, not the event.
_DEADLINE_BEFORE = re.compile(
    r"(?:register|registration|sign[\s-]?ups?|rsvp|deadline|due|closes?|closing|apply|"
    r"submit|submission|by|before)\W{0,12}(?:on\s+|by\s+)?$",
    re.IGNORECASE,
)
_SIGNUP_LINK = re.compile(
    r"regist|rsvp|sign[-_]?up|forms\.gle|forms\.office|docs\.google\.com/forms|eventbrite|"
    r"go\.gov\.sg|bit\.ly|tinyurl|qrco\.de|zoom\.us|teams\.microsoft",
    re.IGNORECASE,
)
_JUNK_LINK = re.compile(
    r"unsubscribe|optout|opt-out|preferences|privacy|mailto:|facebook\.com|instagram\.com|"
    r"linkedin\.com|twitter\.com|x\.com/|youtube\.com|tiktok\.com|\.(?:png|jpe?g|gif)(?:\?|$)",
    re.IGNORECASE,
)
_REPLY = re.compile(r"^\s*re\s*:", re.IGNORECASE)
_CANVAS = re.compile(r"instructure\.com|\bview\s+(?:assignment|announcement|discussion|quiz)\b", re.IGNORECASE)
_SUBJECT_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*|\[[^\]]{1,30}\]\s*)+", re.IGNORECASE)


def _event_when(text: str, received: str) -> dict | None:
    """The event's date: skip sign-up deadlines, prefer a date that has a time."""
    first = None
    for match in _WHEN.finditer(text):
        if _DEADLINE_BEFORE.search(text[max(0, match.start() - 30): match.start()]):
            continue
        when = find_when(text[match.start():], received)
        if when is None:
            continue
        if "time" in when:
            return when
        first = first or when
    return first


def _event_venue(lines: list[str]) -> str:
    """A labelled venue ("Venue: LT27"), else a short line naming one; never a whole paragraph."""
    for line in lines:
        if found := _VENUE_LABEL.search(line):
            return re.split(r"\.\s|;|\||\s{2,}", found.group("venue"))[0].strip(" .,-–")[:60]
    for line in lines:
        if len(line) <= 80 and _VENUE_WORDS.search(line) and not _LINK.search(line):
            return line.strip(" .,-–")[:60]
    return ""


def _event_links(text: str) -> list[dict]:
    links = [url for url in find_links(text) if not _JUNK_LINK.search(url)]
    links.sort(key=lambda url: 0 if _SIGNUP_LINK.search(url) else 1)  # sign-up links first
    return [{"url": url, "source": "text"} for url in links[:MAX_LINKS]]


def _title(subject: str) -> str:
    return _SUBJECT_PREFIX.sub("", subject or "").strip(" -–:|")[:80]


def _distinct_dates(text: str) -> int:
    return len({re.sub(r"\W+", " ", match.group("date")).strip().lower() for match in _WHEN.finditer(text)})


def parse_event(email: Email) -> dict | None:
    """The event in ``email``'s text, in ``email.poster``'s shape, or ``None``."""
    subject = email.subject or ""
    text = (email.body or email.preview or "")[:READ_CHARS]
    if _REPLY.match(subject) or not _EVENT_WORDS.search(subject):
        return None  # a conversation, or the subject does not announce an event
    if _CANVAS.search(f"{email.sender}\n{text}"):
        return None  # course notices have their own date handling
    if _distinct_dates(text) > MAX_DATES:
        return None
    when = _event_when(text, email.received)
    if when is None or "time" not in when:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    venue = _event_venue(lines)
    links = _event_links(text)
    if not venue and not any(_SIGNUP_LINK.search(link["url"]) for link in links):
        return None  # nowhere to go and no way to sign up: not worth a card
    return {
        "title": _title(subject),
        "when": when,
        "venue": venue,
        "links": links,
        "has_image": False,
    }
