"""SQLite storage. Holds metadata, labels and corrections, but never email bodies."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import DB_PATH
from .preprocess import EmailRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    received TEXT,
    sender TEXT,
    sender_name TEXT,
    subject TEXT,
    web_link TEXT,
    conversation_id TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    email_id TEXT PRIMARY KEY REFERENCES emails(id),
    topic TEXT, action TEXT,
    confidence REAL,
    source TEXT,               -- shortcut | claude | fallback
    reason TEXT,               -- Claude's one-line reason
    rules_fired TEXT,
    model TEXT,
    visible INTEGER,
    created TEXT,
    stars_auto INTEGER,        -- 1..5 computed at arrival (NULL = unrated)
    stars_user INTEGER,        -- 1..5 set by the owner in the dashboard (overrides stars_auto)
    priority_score REAL,
    consequence INTEGER, urgency INTEGER, relevance INTEGER,
    deadline TEXT,             -- YYYY-MM-DD
    suspicious INTEGER,
    key_point TEXT,
    priority_notes TEXT,       -- floors or caps that changed the stars
    priority_model TEXT        -- content_only | combined
);
CREATE TABLE IF NOT EXISTS corrections (
    email_id TEXT, field TEXT, old TEXT, new TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PRIORITY_COLUMNS = {
    "stars_auto": "INTEGER", "stars_user": "INTEGER", "priority_score": "REAL",
    "consequence": "INTEGER", "urgency": "INTEGER", "relevance": "INTEGER",
    "deadline": "TEXT", "suspicious": "INTEGER", "key_point": "TEXT", "priority_notes": "TEXT",
    "priority_model": "TEXT",
}


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")  # worker and dashboard can use it at the same time
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con) -> None:
    """Add priority columns to databases created before the priority ranking existed."""
    have = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
    for col, kind in PRIORITY_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE predictions ADD COLUMN {col} {kind}")
    con.commit()


def _priority_values(result) -> tuple:
    f, p = getattr(result, "factors", None), getattr(result, "priority", None)
    return (
        p.stars if p else None, p.score if p else None,
        f.consequence if f else None, p.urgency if p else (f.urgency if f else None),
        f.relevance if f else None, f.deadline if f else None,
        int(f.suspicious) if f else None, f.key_point if f else None,
        ", ".join(p.notes) if p and p.notes else None,
        getattr(p, "model", None) if p else None,
    )


def get_state(con, key: str) -> str | None:
    row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_state(con, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, value))
    con.commit()


def already_labelled(con, email_id: str) -> bool:
    return con.execute("SELECT 1 FROM predictions WHERE email_id=?", (email_id,)).fetchone() is not None


def latest_received(con) -> str | None:
    return con.execute("SELECT MAX(received) FROM emails").fetchone()[0]


def save(con, rec: EmailRecord, result, model: str, visible: bool) -> None:
    con.execute(
        "INSERT OR REPLACE INTO emails VALUES (?,?,?,?,?,?,?)",
        (rec.id, rec.received, rec.sender, rec.sender_name, rec.subject, rec.web_link, rec.conversation_id),
    )
    con.execute(
        """INSERT OR REPLACE INTO predictions
           (email_id, topic, action, confidence, source, reason, rules_fired, model, visible, created,
            stars_auto, priority_score, consequence, urgency, relevance, deadline, suspicious, key_point,
            priority_notes, priority_model, stars_user)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
        (rec.id, result.topic, result.action, result.confidence, result.source, result.reason,
         ",".join(result.rules_fired), model, int(visible), now(), *_priority_values(result)),
    )
    con.commit()


def update_priority(con, email_id: str, result) -> None:
    """Set priority fields only (labels and the owner's star override are kept). Used by --reclassify."""
    con.execute(
        """UPDATE predictions SET stars_auto=?, priority_score=?, consequence=?, urgency=?, relevance=?,
           deadline=?, suspicious=?, key_point=?, priority_notes=?, priority_model=? WHERE email_id=?""",
        (*_priority_values(result), email_id),
    )
    con.commit()


def save_correction(con, email_id: str, field: str, new) -> None:
    """Record an owner correction. field: topic | action | stars (stars = 1..5)."""
    if field == "stars":
        new = int(new)
        if not 1 <= new <= 5:
            raise ValueError("stars must be 1 to 5")
        row = con.execute("SELECT COALESCE(stars_user, stars_auto) FROM predictions WHERE email_id=?",
                          (email_id,)).fetchone()
        column = "stars_user"
    elif field in ("topic", "action"):
        row = con.execute(f"SELECT {field} FROM predictions WHERE email_id=?", (email_id,)).fetchone()
        column = field
    else:
        raise ValueError(field)
    old = row[0] if row else None
    if old == new:
        return
    con.execute("INSERT INTO corrections VALUES (?,?,?,?,?)",
                (email_id, field, None if old is None else str(old), str(new), now()))
    con.execute(f"UPDATE predictions SET {column}=? WHERE email_id=?", (new, email_id))
    con.commit()


def dashboard_rows(con, days: int, limit: int) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return pd.read_sql(
        """SELECT e.id, e.received, e.sender_name, e.sender, e.subject, e.web_link,
                  p.topic, p.action, p.confidence, p.source, p.reason,
                  COALESCE(p.stars_user, p.stars_auto) AS stars, p.stars_auto, p.stars_user,
                  p.consequence, p.urgency, p.relevance, p.deadline, p.suspicious, p.key_point,
                  p.priority_notes
           FROM emails e JOIN predictions p ON p.email_id = e.id
           WHERE p.visible = 1 AND e.received >= ?
           ORDER BY e.received DESC LIMIT ?""",
        con, params=(since, limit),
    )


def corrections_report(con) -> pd.DataFrame:
    """Which labels you corrected, from what to what. Use it to sharpen definitions or add examples."""
    return pd.read_sql(
        "SELECT field, old, new, COUNT(*) AS times FROM corrections GROUP BY field, old, new ORDER BY times DESC",
        con,
    )


def health(con, days: int = 7) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    total = con.execute("SELECT COUNT(*) FROM predictions WHERE created >= ?", (since,)).fetchone()[0]
    if not total:
        return {"emails": 0}
    corrected = con.execute(
        "SELECT COUNT(DISTINCT c.email_id) FROM corrections c JOIN predictions p ON p.email_id=c.email_id "
        "WHERE p.created >= ?", (since,)).fetchone()[0]
    by_source = dict(con.execute(
        "SELECT source, COUNT(*) FROM predictions WHERE created >= ? GROUP BY source", (since,)).fetchall())
    further = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE created >= ? AND action='Further review'", (since,)).fetchone()[0]
    stars = dict(con.execute(
        "SELECT COALESCE(stars_user, stars_auto), COUNT(*) FROM predictions WHERE created >= ? "
        "GROUP BY 1", (since,)).fetchall())
    star_fixes = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE created >= ? AND stars_user IS NOT NULL", (since,)).fetchone()[0]
    return {
        "emails": total,
        "stars": {("unrated" if k is None else f"{k}\u2605"): v for k, v in sorted(stars.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
        "star_override_rate": star_fixes / total,
        "correction_rate": corrected / total,
        "further_review_share": further / total,
        "by_source": {k: v / total for k, v in by_source.items()},
    }


def purge(con, retention_days: int) -> int:
    """Delete everything about emails older than the retention period."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    old = "SELECT id FROM emails WHERE received < ?"
    n = con.execute(f"DELETE FROM predictions WHERE email_id IN ({old})", (cutoff,)).rowcount
    con.execute(f"DELETE FROM corrections WHERE email_id IN ({old})", (cutoff,))
    con.execute(f"DELETE FROM emails WHERE id IN ({old})", (cutoff,))
    con.commit()
    return n
