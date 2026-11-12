"""Priority ranking: turn Claude's content factors into 1 to 5 stars.

Claude scores the content (consequence, urgency, relevance, deadline, suspicious); this module
turns those scores into stars with a fixed formula and guardrails from config.yaml, so the same
inputs always give the same stars.

Two priority models are supported (config.yaml -> priority.model):
- content_only (this version's default): stars depend ONLY on what the email says. The topic and
  action labels play no part in the score, floors or caps.
- combined (the main version's model): content factors plus a baseline from the two labels, with
  topic and action caps. Kept here so `python -m src.compare` can score both on the same data.

Stars are computed once, when the email is classified, and stay fixed. Urgency comes from the
deadline counted from the day the email ARRIVED, not from today. The owner can override the
stars in the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

STAR_TEXT = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆",
             4: "★★★★☆", 5: "★★★★★"}
TEXT_STAR = {v: k for k, v in STAR_TEXT.items()}


@dataclass
class Factors:
    consequence: int          # 0 to 3: what happens if ignored
    urgency: int              # 0 to 3: Claude's judgement, used when there is no deadline
    relevance: int            # 0 to 3: mass marketing ... you personally
    deadline: str | None      # YYYY-MM-DD or None
    suspicious: bool          # looks like phishing
    key_point: str            # under 12 words


@dataclass
class Priority:
    stars: int
    score: float
    urgency: int              # urgency actually used (from the deadline when there is one)
    notes: list[str]          # which floors or caps changed the result
    model: str = "content_only"


def received_day(received_iso: str, tz: str) -> date:
    dt = datetime.fromisoformat(received_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo(tz)).date()


def parse_deadline(value) -> str | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def urgency_from_deadline(deadline: str | None, received_iso: str, fallback: int, cfg: dict) -> int:
    """Days from arrival to the deadline -> urgency 0..3. No (or unparseable) deadline -> Claude's score."""
    p = cfg["priority"]
    d = parse_deadline(deadline)
    if not d or not received_iso:
        return fallback
    try:
        days = (date.fromisoformat(d) - received_day(received_iso, p.get("timezone", "UTC"))).days
    except ValueError:
        return fallback
    if days < 0:
        return 3  # already overdue when it arrived
    for max_days, u in p["deadline_bands"]:
        if days <= max_days:
            return int(u)
    return 0


MODELS = ("content_only", "combined")


def model_settings(cfg: dict, model: str | None = None) -> tuple[str, dict]:
    p = cfg["priority"]
    name = model or p.get("model", "content_only")
    if name not in MODELS or name not in p:
        raise ValueError(f"priority model '{name}' is not configured in config.yaml")
    return name, p[name]


def compute(topic: str, action: str, f: Factors, received_iso: str, cfg: dict,
            model: str | None = None) -> Priority:
    """Stars for one email. `model` defaults to priority.model in config.yaml."""
    name, s = model_settings(cfg, model)
    w = s["weights"]
    u = urgency_from_deadline(f.deadline, received_iso, f.urgency, cfg)
    content = w["consequence"] * f.consequence + w["urgency"] * u + w["relevance"] * f.relevance
    if name == "content_only":
        score = content                     # labels deliberately ignored
    else:
        score = (s.get("action_base") or {}).get(action, 0) + (s.get("topic_adjust") or {}).get(topic, 0) + content

    stars = 1
    for level in (5, 4, 3, 2):
        if score >= s["star_thresholds"][level]:
            stars = level
            break

    notes: list[str] = []
    fl = s.get("floors") or {}
    caps = s.get("caps") or {}

    def floor(minimum, why):
        nonlocal stars
        if minimum and stars < minimum:
            stars = minimum
            notes.append(why)

    def cap(maximum, why):
        nonlocal stars
        if maximum and stars > maximum:
            stars = maximum
            notes.append(why)

    # Floors first, then caps: a cap always has the final say.
    if f.consequence >= 3 and u >= 2:
        floor(fl.get("serious_and_soon"), "serious and due soon")
    if name == "combined":                 # label-based rules exist only in the combined model
        if action == "Needs a reply" and f.relevance >= 3:
            floor(fl.get("personal_reply"), "personal reply")
        cap((caps.get("topics") or {}).get(topic), f"{topic} cap")
        cap((caps.get("actions") or {}).get(action), f"{action} cap")
    if f.relevance == 0:
        cap(caps.get("mass_marketing"), "mass marketing cap")
    if f.suspicious:
        cap(caps.get("suspicious"), "possible phishing")
    return Priority(stars, round(score, 2), u, notes, name)
