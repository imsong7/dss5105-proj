"""Classify one email: optional free shortcuts -> Claude -> guardrails -> safe default.

Every result records how it was decided ('source'): shortcut | claude | fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .preprocess import EmailRecord
from .rules import apply_rules


@dataclass
class Result:
    topic: str
    action: str
    confidence: float
    source: str
    reason: str = ""
    rules_fired: list[str] = field(default_factory=list)


def classify(rec: EmailRecord, cfg: dict, claude: Callable[[str], object] | None) -> Result:
    rule = apply_rules(rec, cfg)

    # Both labels settled by shortcuts: no API call needed.
    if rule.topic and rule.action:
        return Result(rule.topic, rule.action, 1.0, "shortcut", "matched a sender rule", rule.fired)

    out = claude(rec.text) if claude else None
    if out is None:
        # Claude unavailable or gave an invalid answer: send it up to review, never down.
        return Result(rule.topic or cfg["fallback_topic"], cfg["fallback_action"], 0.0, "fallback",
                      "classification failed", rule.fired)

    topic = rule.topic or out.topic
    action = rule.action or out.action
    if action in rule.forbid_actions:            # e.g. no-reply sender can't need a reply
        action = cfg["fallback_action"]
    if out.confidence < cfg["claude"].get("min_confidence", 0.5) and not rule.action:
        action = cfg["fallback_action"]          # unsure: send it up to review
    return Result(topic, action, out.confidence, "claude", out.reason, rule.fired)
