"""Classify one email: optional free shortcuts -> Claude -> guardrails -> safe default, then priority.

Every result records how it was decided ('source'): shortcut | claude | fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .preprocess import EmailRecord
from .priority import Factors, Priority, compute
from .rules import apply_rules


@dataclass
class Result:
    topic: str
    action: str
    confidence: float
    source: str
    reason: str = ""
    rules_fired: list[str] = field(default_factory=list)
    factors: Factors | None = None
    priority: Priority | None = None     # None = unrated

    @property
    def stars(self) -> int | None:
        return self.priority.stars if self.priority else None


def _with_priority(r: Result, rec: EmailRecord, cfg: dict) -> Result:
    if r.factors is not None and cfg.get("priority"):
        r.priority = compute(r.topic, r.action, r.factors, rec.received, cfg)
    return r


def classify(rec: EmailRecord, cfg: dict, claude: Callable | None) -> Result:
    rule = apply_rules(rec, cfg)

    # Both labels settled by shortcuts: no API call, so neutral priority factors from config.
    if rule.topic and rule.action:
        sf = (cfg.get("priority") or {}).get("shortcut_factors") or {}
        factors = Factors(int(sf.get("consequence", 1)), int(sf.get("urgency", 1)),
                          int(sf.get("relevance", 1)), None, False, "matched a sender rule")
        return _with_priority(Result(rule.topic, rule.action, 1.0, "shortcut", "matched a sender rule",
                                     rule.fired, factors), rec, cfg)

    out = claude(rec.text, rec.received) if claude else None
    if out is None:
        # Claude unavailable or gave an invalid answer: send it up to review, never down. Unrated.
        why = getattr(claude, "last_error", None) if claude else "no classifier"
        return Result(rule.topic or cfg["fallback_topic"], cfg["fallback_action"], 0.0, "fallback",
                      f"classification failed: {why}" if why else "classification failed", rule.fired)

    topic = rule.topic or out.topic
    action = rule.action or out.action
    if action in rule.forbid_actions:            # e.g. no-reply sender can't need a reply
        action = cfg["fallback_action"]
    if out.confidence < cfg["claude"].get("min_confidence", 0.5) and not rule.action:
        action = cfg["fallback_action"]          # unsure: send it up to review
    r = Result(topic, action, out.confidence, "claude", out.reason, rule.fired, out.priority)
    return _with_priority(r, rec, cfg)
