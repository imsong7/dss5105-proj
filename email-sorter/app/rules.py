"""Sender-based category overrides."""

from email.utils import parseaddr

SENDER_RULES = {
    "category": {"notifications@instructure.com": "canva"},
}


def sender_address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def category_by_rule(sender: str) -> str | None:
    """Return the matching category, if any."""
    return SENDER_RULES["category"].get(sender_address(sender))
