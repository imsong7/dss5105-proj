"""Classify one email: optional free shortcuts -> Claude -> guardrails -> safe default.

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
    # Diagnostics of this call's Claude API invocation (none when no API call was made).
    api_called: bool = False
    api_duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    stop_reason: str | None = None
    app_attempts: int = 0
    app_retry_attempts: int = 0
    retry_call_ms: int = 0
    retry_backoff_ms: int = 0
    error: str | None = None
    error_type: str | None = None
    factors: Factors | None = None
    priority: Priority | None = None     # None = unrated
    event: dict | None = None            # date, time and place found in the email

    @property
    def stars(self) -> int | None:
        return self.priority.stars if self.priority else None


def _with_priority(r: Result, rec: EmailRecord, cfg: dict) -> Result:
    if r.factors is not None and cfg.get("priority"):
        r.priority = compute(r.topic, r.action, r.factors, rec.received, cfg)
    return r


def _diagnostics(info) -> dict:
    """Result fields from a call's own CallInfo (empty when the callable gives none)."""
    if info is None:
        return {}
    return dict(
        api_called=info.api_called,
        api_duration_ms=info.api_duration_ms,
        input_tokens=info.input_tokens,
        output_tokens=info.output_tokens,
        cache_read_tokens=info.cache_read_tokens,
        stop_reason=info.stop_reason,
        app_attempts=info.app_attempts,
        app_retry_attempts=info.app_retry_attempts,
        retry_call_ms=info.retry_call_ms,
        retry_backoff_ms=info.retry_backoff_ms,
        error=info.error,
        error_type=info.error_type,
    )


def classify(rec: EmailRecord, cfg: dict, claude: Callable[[str], object] | None) -> Result:
    rule = apply_rules(rec, cfg)

    # Both labels settled by shortcuts: no API call needed.
    if rule.topic and rule.action:
        return Result(rule.topic, rule.action, 1.0, "shortcut", "matched a sender rule", rule.fired)

    info = None
    if claude is None:
        out = None
    elif hasattr(claude, "run"):        # returns its own per-call diagnostics
        call = claude.run(rec.text, rec.received)
        out, info = call.labels, call.info
    else:
        out = claude(rec.text, rec.received)
    diag = _diagnostics(info)
    if out is None:
        # Claude unavailable or gave an invalid answer: send it up to review, never down.
        return Result(rule.topic or cfg["fallback_topic"], cfg["fallback_action"], 0.0, "fallback",
                      "classification failed", rule.fired, **diag)

    topic = rule.topic or out.topic
    action = rule.action or out.action
    if action in rule.forbid_actions:            # e.g. no-reply sender can't need a reply
        action = cfg["fallback_action"]
    if out.confidence < cfg["claude"].get("min_confidence", 0.5) and not rule.action:
        action = cfg["fallback_action"]          # unsure: send it up to review
    result = Result(topic, action, out.confidence, "claude", out.reason, rule.fired,
                    factors=out.priority, event=out.event, **diag)
    return _with_priority(result, rec, cfg)
