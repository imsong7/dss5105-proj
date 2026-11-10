"""Sender-based category overrides."""

import re
from email.utils import parseaddr

SENDER_RULES = {
    "category": {"notifications@instructure.com": "canva"},
}


def sender_address(sender: str) -> str:
    value = sender or ""
    address = parseaddr(value)[1].strip()
    if not address:
        match = re.search(r"<\s*([^<>\s]+@[^<>\s]+)\s*>", value)
        address = match.group(1) if match else ""
    return address.lower()


def category_by_rule(sender: str) -> str | None:
    """Return the matching category, if any."""
    return SENDER_RULES["category"].get(sender_address(sender))


_COURSE_CODE = re.compile(r"\b[A-Z]{2,5}\s?\d{4}[A-Z]?\b")
_COURSEWORK = re.compile(
    r"\b(?:assignment|quiz|exam(?:ination)?|test|tutorial|lecture|project|grade|grading|"
    r"feedback|submission|submit|due|deadline|presentation|consultation|reading week)\b",
    re.IGNORECASE,
)


def coursework_by_rule(subject: str, body: str, has_deadline: bool, is_exam: bool):
    """Mail about a course (code plus coursework words) is general university mail.

    Returns ``(category, action, reason)``, or ``None`` when it does not look like
    coursework. Small models often file lecturer mail under "Career related", so
    this runs before the model. The action comes from whether a date was found.
    """
    text = f"{subject}\n{body}"
    # Course codes are written in capitals, so keep that check case-sensitive.
    if not _COURSE_CODE.search(text) or not _COURSEWORK.search(subject + "\n" + body[:600]):
        return None

    if has_deadline and not is_exam:
        action = "needs_action"
    elif has_deadline:
        action = "reminder"
    else:
        action = "no_immediate_action"

    return "general", action, "Mentions a course code and coursework, so it is filed as general."
