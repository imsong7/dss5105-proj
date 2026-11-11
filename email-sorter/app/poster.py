"""Turn the pictures in an email (posters, flyers) into facts a student can act on.

OCR (``ocr.py``) gives raw text from inline images. This module reads that text
and the images themselves and keeps only what helps:

* a QR code's link (posters hide the sign-up link there),
* the event title, its date and time, and the venue,
* links written on the poster,
* a small preview of the poster for the email view.

Everything runs locally. QR codes need OpenCV (``opencv-python-headless``);
without it the rest still works and no QR links are found.
"""

from __future__ import annotations

import io
import logging
import re
from collections import OrderedDict
from datetime import date
from threading import Lock

from PIL import Image, ImageOps

from .calendar import (
    _ISO_DATE,
    _NUMERIC_DATE,
    MONTH_NAME,
    _ORDINAL,
    _parse_date,
    _received_date,
)
from .schemas import Email

log = logging.getLogger(__name__)

THUMB_WIDTH = 480
MAX_THUMBS = 500
MAX_LINKS = 4

# ---- QR codes ---------------------------------------------------------------


def decode_qr(data: bytes) -> list[str]:
    """Every web link in the QR codes of one image ([] when OpenCV is missing)."""
    try:
        import cv2  # noqa: PLC0415 - optional dependency
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return []
    try:
        with Image.open(io.BytesIO(data)) as img:
            rgb = ImageOps.exif_transpose(img).convert("RGB")
            pixels = np.array(rgb)[:, :, ::-1]  # RGB -> BGR for OpenCV
        detector = cv2.QRCodeDetector()
        found, texts, _points, _ = detector.detectAndDecodeMulti(pixels)
        values = list(texts) if found else []
        if not any(values):
            single, _pts, _ = detector.detectAndDecode(pixels)
            values = [single] if single else []
    except Exception as exc:  # a broken image must never stop the mail
        log.info("QR decoding skipped: %s", exc)
        return []
    links = []
    for value in values:
        value = (value or "").strip()
        if re.match(r"https?://\S+$", value, re.I) and value not in links:
            links.append(value)
    return links


# ---- facts from the poster text ----------------------------------------------

_WEEKDAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+"
_DAY_MONTH = r"\d{1,2}" + _ORDINAL + r"\s+(?:of\s+)?" + MONTH_NAME + r"\.?(?:,?\s+\d{4})?"
_MONTH_DAY = MONTH_NAME + r"\.?\s+\d{1,2}" + _ORDINAL + r"(?:,?\s+\d{4})?"
_CLOCK = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)|\d{1,2}[:.]\d{2}"
_WHEN = re.compile(
    r"(?:" + _WEEKDAY + r")?"
    r"(?P<date>" + _DAY_MONTH + r"|" + _MONTH_DAY + r"|" + _ISO_DATE + r"|" + _NUMERIC_DATE + r")"
    r"(?:[\s,|·•@-]{1,6}(?:at\s+)?(?P<time>(?:" + _CLOCK + r")(?:\s*(?:-|–|—|to)\s*(?:" + _CLOCK + r"))?))?",
    re.IGNORECASE,
)

_LINK = re.compile(
    r"\b(?:https?://|www\.)[^\s<>\"')\]]+"
    r"|\b(?:bit\.ly|forms\.gle|go\.gov\.sg|tinyurl\.com|t\.ly|qrco\.de|linktr\.ee|nus\.edu\.sg|"
    r"forms\.office\.com|eventbrite\.\w+|zoom\.us)/[^\s<>\"')\]]*",
    re.IGNORECASE,
)

_VENUE_LABEL = re.compile(r"\b(?:venue|location|where|place)\s*[:\-–]\s*(?P<venue>.{3,80})", re.IGNORECASE)
_VENUE_WORDS = re.compile(
    r"\b(?:LT\s?\d+|MPSH\s?\d*|UTown|University\s+Town|Auditorium|Seminar\s+Room|SR\s?\d+|"
    r"Zoom|MS\s+Teams|Microsoft\s+Teams|Online|Lecture\s+Theatre|Theatre|Yusof\s+Ishak\s+House|YIH|"
    r"Kent\s+Ridge|COM\s?\d|Level\s+\d+|Room\s+[A-Z0-9-]+|Hall)\b",
    re.IGNORECASE,
)


def find_links(text: str) -> list[str]:
    links: list[str] = []
    for match in _LINK.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        if not url.lower().startswith("http"):
            url = "https://" + url
        if url not in links:
            links.append(url)
    return links


def find_when(text: str, received: str) -> dict | None:
    """The first date on the poster, with its time or time range if written."""
    received_day = _received_date(received)
    for match in _WHEN.finditer(text):
        date_text = re.sub(r"\.", "", match.group("date"))
        probe = _parse_date(date_text, 2000)
        if probe is None:
            continue
        _parsed, has_year = probe
        year = received_day.year if received_day else date.today().year
        parsed = _parse_date(date_text, year)[0] if not has_year else _parsed
        if not has_year and received_day and parsed < received_day:
            try:
                parsed = parsed.replace(year=parsed.year + 1)
            except ValueError:
                continue
        when = {"date": parsed.isoformat(), "year_inferred": not has_year}
        if match.group("time"):
            when["time"] = re.sub(r"\s+", " ", match.group("time")).strip()
        return when
    return None


def find_venue(lines: list[str]) -> str:
    for line in lines:
        if found := _VENUE_LABEL.search(line):
            return found.group("venue").strip(" .,-–")[:60]
    for line in lines:
        if _VENUE_WORDS.search(line) and not _LINK.search(line):
            return line.strip(" .,-–")[:60]
    return ""


def find_title(lines: list[str], skip: set[str]) -> str:
    """The first line that reads like a name: words, not a date, link or venue."""
    for line in lines[:8]:
        clean = line.strip(" .,:;-–|")
        letters = sum(ch.isalpha() for ch in clean)
        if (
            clean in skip
            or letters < 6
            or len(clean.split()) < 2
            or _WHEN.search(clean)
            or _LINK.search(clean)
            or _VENUE_LABEL.search(clean)
        ):
            continue
        return clean[:80]
    return ""


def facts_from_text(text: str, received: str = "") -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("[Text read from image")]
    venue = find_venue(lines)
    return {
        "title": find_title(lines, {venue}),
        "when": find_when(text, received),
        "venue": venue,
        "links": find_links(text),
    }


# ---- previews -----------------------------------------------------------------


class ThumbStore:
    """Small JPEG previews of posters, in memory, per account and email."""

    def __init__(self, limit: int = MAX_THUMBS):
        self.limit = limit
        self._items: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()
        self._lock = Lock()

    def put(self, owner: str, email_id: str, data: bytes) -> None:
        with self._lock:
            self._items[(owner, email_id)] = data
            self._items.move_to_end((owner, email_id))
            while len(self._items) > self.limit:
                self._items.popitem(last=False)

    def get(self, owner: str, email_id: str) -> bytes | None:
        with self._lock:
            return self._items.get((owner, email_id))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


thumbs = ThumbStore()


def make_thumb(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.seek(0)
            img = ImageOps.exif_transpose(img).convert("RGB")
            if img.width > THUMB_WIDTH:
                img = img.resize((THUMB_WIDTH, round(img.height * THUMB_WIDTH / img.width)), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=72, optimize=True)
            return out.getvalue()
    except Exception as exc:
        log.info("Poster preview skipped: %s", exc)
        return None


def _pixels(data: bytes) -> int:
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.width * img.height
    except Exception:
        return 0


# ---- the step run after OCR -----------------------------------------------------


def analyze(email: Email, images: list[bytes], owner: str = "") -> None:
    """Fill ``email.poster`` from its images and OCR text (nothing when no poster)."""
    if not images:
        return
    qr_links: list[str] = []
    for data in images:
        for link in decode_qr(data):
            if link not in qr_links:
                qr_links.append(link)

    facts = facts_from_text(email.ocr_text, email.received) if email.ocr_text else {
        "title": "", "when": None, "venue": "", "links": [],
    }
    links = [{"url": url, "source": "qr"} for url in qr_links]
    links += [{"url": url, "source": "text"} for url in facts["links"] if url not in qr_links]
    has_facts = bool(facts["title"] or facts["when"] or facts["venue"] or links)
    if not has_facts:
        return

    biggest = max(images, key=_pixels)
    thumb = make_thumb(biggest)
    if thumb:
        thumbs.put(owner, email.id, thumb)
    email.poster = {
        "title": facts["title"],
        "when": facts["when"],
        "venue": facts["venue"],
        "links": links[:MAX_LINKS],
        "has_image": thumb is not None,
    }
