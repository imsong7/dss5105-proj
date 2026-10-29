"""Turn a Graph message into a clean EmailRecord: model text, rule text and metadata features."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup

QUOTE_START = re.compile(
    r"^(On .{5,200} wrote:\s*$|From: .+$|-----\s*Original Message\s*-----|_{20,}\s*$)",
    re.M | re.I,
)
DATE_WORDS = re.compile(
    r"\b(deadline|due|by (mon|tues|wednes|thurs|fri|satur|sun)day|tomorrow|tonight|"
    r"\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|\d{1,2}[/.]\d{1,2}([/.]\d{2,4})?)\b",
    re.I,
)
REQUEST_WORDS = re.compile(
    r"\b(please|kindly|could you|can you|would you|let me know|confirm|reply|respond|"
    r"submit|register|sign up|complete|fill in|rsvp|pay)\b",
    re.I,
)

FEATURE_NAMES = [
    "to_me",            # I am in To
    "cc_only",          # I am only in CC
    "noreply_sender",
    "mass_mail",        # more than 10 recipients
    "questions",        # question marks, capped
    "request_words",    # please / could you / submit ..., capped
    "date_words",       # deadlines and dates, capped
    "same_domain",      # sender shares my email domain
    "is_reply",         # subject starts with RE:
    "is_forward",       # subject starts with FW:
    "log_length",       # body length, log-scaled
]


@dataclass
class EmailRecord:
    id: str
    received: str
    sender: str
    sender_name: str
    subject: str
    text: str          # cleaned + truncated: the text sent to Claude
    full_text: str     # cleaned, not truncated: input to rules; never stored in the database
    feats: list[float]
    web_link: str
    conversation_id: str

    def to_dict(self) -> dict:
        return asdict(self)


def _address(r: dict | None) -> str:
    return ((r or {}).get("emailAddress") or {}).get("address", "").lower()


def html_to_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n")


def strip_quoted(body: str) -> str:
    """Cut the quoted earlier thread. Keeps the body if the cut would leave nothing."""
    m = QUOTE_START.search(body)
    if m and m.start() > 0:
        body = body[: m.start()]
    return body


def clean_body(msg: dict) -> str:
    body = (msg.get("body") or {}).get("content") or ""
    if (msg.get("body") or {}).get("contentType", "").lower() == "html":
        body = html_to_text(body)
    body = strip_quoted(body.replace("\r\n", "\n"))
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body)
    return body.strip()


def compute_features(msg: dict, body: str, my_address: str, noreply_markers: list[str]) -> list[float]:
    sender = _address(msg.get("from"))
    to = [_address(r) for r in msg.get("toRecipients") or []]
    cc = [_address(r) for r in msg.get("ccRecipients") or []]
    subject = (msg.get("subject") or "").strip().lower()
    my_domain = my_address.split("@")[-1] if "@" in my_address else ""
    return [
        float(my_address in to),
        float(my_address in cc and my_address not in to),
        float(any(m in sender for m in noreply_markers)),
        float(len(to) + len(cc) > 10),
        min(body.count("?"), 5) / 5,
        min(len(REQUEST_WORDS.findall(body)), 5) / 5,
        min(len(DATE_WORDS.findall(body)), 5) / 5,
        float(bool(my_domain) and sender.endswith("@" + my_domain)),
        float(subject.startswith(("re:", "re :"))),
        float(subject.startswith(("fw:", "fwd:"))),
        min(math.log1p(len(body)) / 10, 1.0),
    ]


def to_record(msg: dict, my_address: str, cfg: dict) -> EmailRecord:
    body = clean_body(msg)
    subject = msg.get("subject") or ""
    full_text = f"Subject: {subject}\n\n{body}"
    max_chars = (cfg.get("preprocess") or {}).get("max_chars", 4000)
    sender = msg.get("from") or {}
    return EmailRecord(
        id=msg["id"],
        received=msg.get("receivedDateTime", ""),
        sender=_address(sender),
        sender_name=(sender.get("emailAddress") or {}).get("name", ""),
        subject=subject,
        text=full_text[:max_chars],
        full_text=full_text,
        feats=compute_features(msg, body, my_address.lower(), cfg["rules"]["noreply_markers"]),
        web_link=msg.get("webLink", ""),
        conversation_id=msg.get("conversationId", ""),
    )
