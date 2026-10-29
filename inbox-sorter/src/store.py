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
    created TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    email_id TEXT, field TEXT, old TEXT, new TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")  # worker and dashboard can use it at the same time
    con.executescript(SCHEMA)
    return con


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
        "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (rec.id, result.topic, result.action, result.confidence, result.source, result.reason,
         ",".join(result.rules_fired), model, int(visible), now()),
    )
    con.commit()


def save_correction(con, email_id: str, field: str, new: str) -> None:
    if field not in ("topic", "action"):
        raise ValueError(field)
    row = con.execute(f"SELECT {field} FROM predictions WHERE email_id=?", (email_id,)).fetchone()
    old = row[0] if row else None
    if old == new:
        return
    con.execute("INSERT INTO corrections VALUES (?,?,?,?,?)", (email_id, field, old, new, now()))
    con.execute(f"UPDATE predictions SET {field}=? WHERE email_id=?", (new, email_id))
    con.commit()


def dashboard_rows(con, days: int, limit: int) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return pd.read_sql(
        """SELECT e.id, e.received, e.sender_name, e.sender, e.subject, e.web_link,
                  p.topic, p.action, p.confidence, p.source, p.reason
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
    return {
        "emails": total,
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
