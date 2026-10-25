"""Deterministic pre-filter run before the model (architecture: "Canvas sender?").
Keep this in sync with SENDER_RULES in bert/src/data.py."""
from email.utils import parseaddr

SENDER_RULES = {
    "category": {"notifications@instructure.com": "canva"},
}


def sender_address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def category_by_rule(sender: str):
    """Return the app category key if a sender rule matches, else None."""
    return SENDER_RULES["category"].get(sender_address(sender))
