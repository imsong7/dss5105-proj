"""Rules that run before and after Claude.

- Guardrail (always on): no-reply senders can never be labelled Needs a reply.
- Shortcuts (off by default, `rules.use_shortcuts`): obvious emails such as Canvas notifications
  are labelled for free without a Claude call. Check each shortcut's precision with
  `python -m src.evaluate` before turning them on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .preprocess import EmailRecord


@dataclass
class RuleResult:
    topic: str | None = None
    action: str | None = None
    forbid_actions: set[str] = field(default_factory=set)
    fired: list[str] = field(default_factory=list)


def _matches(sender: str, patterns: list[str]) -> bool:
    """Patterns are full addresses or '@domain' suffixes (subdomains count)."""
    for p in patterns or []:
        p = p.lower().strip()
        if not p:
            continue
        if p.startswith("@"):
            domain = sender.split("@")[-1]
            if sender.endswith(p) or domain.endswith("." + p[1:]):
                return True
        elif sender == p:
            return True
    return False


def apply_rules(rec: EmailRecord, cfg: dict) -> RuleResult:
    r = cfg["rules"]
    out = RuleResult()
    sender = rec.sender
    subject = rec.subject.lower()
    body = rec.full_text.lower()

    if not r.get("use_shortcuts", False):
        pass
    elif _matches(sender, r.get("canvas_senders")):
        out.topic = "Canvas"
        out.fired.append("canvas_sender")
        if any(k in subject for k in r.get("canvas_reminder_keywords") or []):
            out.action = "Reminder"
            out.fired.append("canvas_reminder")
    elif _matches(sender, r.get("medical_senders")):
        out.topic = "Medical"
        out.fired.append("medical_sender")
    elif _matches(sender, r.get("career_senders")):
        out.topic = "Career"
        out.fired.append("career_sender")
    elif _matches(sender, r.get("fos_senders")):
        out.topic = "FoS General"
        out.fired.append("fos_sender")
    elif any(m in body for m in r.get("promotion_markers") or []):
        out.topic = "Promotions"
        out.action = "No action needed"
        out.fired.append("promotion_marker")

    if any(m in sender for m in r.get("noreply_markers") or []):
        out.forbid_actions.add("Needs a reply")  # you can't reply to a no-reply address
        out.fired.append("noreply_sender")
        if out.action == "Needs a reply":
            out.action = None

    # Keep rule output within the configured label set (labels may be renamed in config).
    if out.topic and out.topic not in cfg["topics"]:
        out.topic = None
    if out.action and out.action not in cfg["actions"]:
        out.action = None
    return out
