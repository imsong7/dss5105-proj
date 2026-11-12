"""Owner dashboard: paste your Graph token, sync, browse emails by priority, correct labels and stars.

  streamlit run app/dashboard.py

Never shows email bodies: click "Open in Outlook" to read an email.
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import graph_token, store  # noqa: E402
from src.config import actions, get_config, topics  # noqa: E402
from src.graph_token import TokenExpired  # noqa: E402
from src.llm import ClaudeClassifier  # noqa: E402
from src.priority import STAR_TEXT, TEXT_STAR  # noqa: E402
from src.sync import sync_once  # noqa: E402

st.set_page_config(page_title="Inbox Sorter", layout="wide")


def check_password() -> bool:
    """Owner-only gate. Set DASHBOARD_PASSWORD in .env; required if this runs anywhere but your own laptop."""
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw or st.session_state.get("authed"):
        return True
    entered = st.text_input("Password", type="password")
    if entered and hmac.compare_digest(entered, pw):
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("Wrong password")
    return False


if not check_password():
    st.stop()

get_config.cache_clear()
cfg = get_config()
dcfg = cfg.get("dashboard") or {}
TOPICS, ACTIONS = topics(cfg), actions(cfg)


@st.cache_resource
def db():
    return store.connect()


con = db()

# ---------------- Sidebar: token + sync ----------------
with st.sidebar:
    st.header("Connection")
    info = graph_token.inspect(graph_token.load())
    if not info.present:
        st.warning("No Graph token")
    elif info.expired:
        st.error("Token expired: paste a new one")
    elif info.minutes_left is not None:
        st.success(f"Token valid for {info.minutes_left:.0f} min" + (f"\n\n{info.account}" if info.account else ""))
    else:
        st.info("Token saved (expiry unknown)")
    if info.present and info.can_read_mail is False:
        st.error("This token has no Mail.Read permission. Consent to Mail.Read in Graph Explorer, then copy a new token.")

    with st.form("token_form", clear_on_submit=True):
        raw = st.text_input("Paste Graph Explorer access token", type="password")
        if st.form_submit_button("Save token") and raw:
            try:
                graph_token.save(raw)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY is missing from .env")

    if st.button("Sync now", type="primary", disabled=not info.present or info.expired):
        with st.spinner("Reading new mail and classifying with Claude..."):
            try:
                rep = sync_once(con, cfg, graph_token.get(), ClaudeClassifier(cfg))
                msg = f"Labelled {rep.labelled} new emails."
                if rep.remaining:
                    msg += f" {rep.remaining} more waiting: press Sync again."
                st.success(msg)
                if rep.last_error:
                    st.warning(f"Claude problem: {rep.last_error}")
            except TokenExpired as e:
                st.error(str(e))
            except PermissionError as e:
                st.error(str(e))
    last = store.get_state(con, "last_sync")
    if last:
        st.caption(f"Last sync: {pd.Timestamp(last).tz_convert(dcfg.get('timezone', 'UTC')):%d %b %H:%M}")
    if info.present and st.button("Forget token"):
        graph_token.clear()
        st.rerun()

    st.divider()
    st.header("Filters")
    days = st.slider("Days", 1, 90, dcfg.get("default_days", 14))
    sel_t = st.multiselect("Topic (A)", TOPICS, default=TOPICS)
    sel_a = st.multiselect("Action (B)", ACTIONS, default=ACTIONS)
    min_stars = st.select_slider("Minimum priority", options=[1, 2, 3, 4, 5], value=1,
                                 format_func=lambda n: STAR_TEXT[n])
    sort_by = st.radio("Sort by", ["Priority", "Newest", "Due date"], horizontal=True)
    search = st.text_input("Search sender or subject")

if cfg["worker"].get("shadow_mode"):
    st.warning("Shadow mode is on: new labels are stored but hidden. Set worker.shadow_mode: false in config.yaml.")

tab_inbox, tab_health = st.tabs(["Inbox", "Health"])
TZ = dcfg.get("timezone", "UTC")
STAR_OPTIONS = [STAR_TEXT[n] for n in (5, 4, 3, 2, 1)]


def due_text(deadline) -> str:
    if not isinstance(deadline, str) or not deadline:
        return ""
    d = pd.Timestamp(deadline)
    days = (d.date() - pd.Timestamp.now(tz=TZ).date()).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else "overdue" if days < 0 else f"in {days} days"
    return f"{d:%a %d %b} \u00b7 {when}"


def why_text(row) -> str:
    parts = [row["key_point"] if isinstance(row["key_point"], str) and row["key_point"] else row["reason"] or ""]
    if pd.notna(row["consequence"]):
        parts.append(f"(C{int(row['consequence'])} U{int(row['urgency'])} R{int(row['relevance'])})")
    if isinstance(row["priority_notes"], str) and row["priority_notes"]:
        parts.append(f"[{row['priority_notes']}]")
    if pd.notna(row["stars_user"]):
        parts.append("\u00b7 adjusted by you")
    return " ".join(p for p in parts if p)


# ---------------- Inbox ----------------
with tab_inbox:
    df = store.dashboard_rows(con, days, dcfg.get("max_rows", 500))
    if df.empty:
        st.info("No labelled emails yet. Paste a token in the sidebar and press Sync now.")
    else:
        df["received_ts"] = pd.to_datetime(df["received"], utc=True)
        df["received"] = df["received_ts"].dt.tz_convert(TZ).dt.strftime("%d %b %H:%M")
        df["from"] = df["sender_name"].where(df["sender_name"].fillna("") != "", df["sender"])
        df["priority"] = df["stars"].map(lambda n: STAR_TEXT.get(int(n)) if pd.notna(n) else None)
        df["due"] = df["deadline"].map(due_text)
        df["why"] = df.apply(why_text, axis=1)
        df["subject"] = [("\u26a0 Possible phishing \u00b7 " if s == 1 else "") + (subj or "")
                         for s, subj in zip(df["suspicious"], df["subject"])]

        view = df[df["topic"].isin(sel_t) & df["action"].isin(sel_a)]
        if min_stars > 1:
            view = view[view["stars"].fillna(0) >= min_stars]
        if search:
            s = search.lower()
            view = view[view["from"].str.lower().str.contains(s, regex=False)
                        | view["subject"].fillna("").str.lower().str.contains(s, regex=False)]
        if sort_by == "Priority":
            view = view.sort_values(["stars", "received_ts"], ascending=[False, False], na_position="last")
        elif sort_by == "Due date":
            view = view.sort_values(["deadline", "stars"], ascending=[True, False], na_position="last")
        else:
            view = view.sort_values("received_ts", ascending=False)
        view = view.reset_index(drop=True)

        counts = view["stars"].value_counts()
        cols = st.columns(6)
        for c, n in zip(cols, (5, 4, 3, 2, 1)):
            c.metric(STAR_TEXT[n], int(counts.get(n, 0)))
        cols[5].metric("Unrated", int(view["stars"].isna().sum()))

        st.caption("Change a Priority, Topic or Action to correct it, then press Save corrections. "
                   "Stars are set when an email arrives and stay fixed unless you change them.")
        st.data_editor(
            view[["priority", "topic", "action", "received", "from", "subject", "due", "why", "web_link"]],
            key="editor", hide_index=True, width="stretch", height=600,
            disabled=["received", "from", "subject", "due", "why", "web_link"],
            column_config={
                "priority": st.column_config.SelectboxColumn("Priority", options=STAR_OPTIONS, width="small"),
                "topic": st.column_config.SelectboxColumn("Topic (A)", options=TOPICS, required=True),
                "action": st.column_config.SelectboxColumn("Action (B)", options=ACTIONS, required=True),
                "received": st.column_config.TextColumn("Received", width="small"),
                "from": st.column_config.TextColumn("From", width="medium"),
                "subject": st.column_config.TextColumn("Subject", width="large"),
                "due": st.column_config.TextColumn("Due", width="small"),
                "why": st.column_config.TextColumn("Why", width="medium"),
                "web_link": st.column_config.LinkColumn("Open", display_text="Open in Outlook"),
            },
        )
        edits = st.session_state.get("editor", {}).get("edited_rows", {})
        if st.button(f"Save corrections ({len(edits)})", disabled=not edits):
            for idx, changes in edits.items():
                eid = view.at[int(idx), "id"]
                for field in ("topic", "action"):
                    if field in changes:
                        store.save_correction(con, eid, field, changes[field])
                if changes.get("priority") in TEXT_STAR:
                    store.save_correction(con, eid, "stars", TEXT_STAR[changes["priority"]])
            del st.session_state["editor"]
            st.rerun()

# ---------------- Health ----------------
with tab_health:
    h = store.health(con, 7)
    if not h.get("emails"):
        st.info("No emails labelled in the last 7 days.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Emails labelled (7 days)", h["emails"])
        c2.metric("Labels corrected", f"{h['correction_rate']:.0%}")
        c3.metric("Stars adjusted", f"{h['star_override_rate']:.0%}")
        c4.metric("Sent to Further review", f"{h['further_review_share']:.0%}")
        st.subheader("Priority spread")
        st.bar_chart(pd.Series(h["stars"], name="emails"))
        st.subheader("How emails were decided")
        st.bar_chart(pd.Series(h["by_source"], name="share"))
    from src.llm import FAILURE_LOG
    if FAILURE_LOG.exists():
        import json as _json
        fails = [_json.loads(l) for l in FAILURE_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if fails:
            st.subheader("Claude answers that couldn't be used")
            st.dataframe(pd.DataFrame([{"when": f["at"], "problem": f["problems"][-1],
                                        "reply": f["replies"][-1][:300]} for f in fails[-20:]][::-1]),
                         hide_index=True)
            st.caption(f"{len(fails)} in total, logged in data/{FAILURE_LOG.name}. These emails show as "
                       "Further review without stars; `python -m src.sync --reclassify` retries them.")
    st.subheader("Your corrections")
    rep = store.corrections_report(con)
    if rep.empty:
        st.caption("None yet.")
    else:
        st.dataframe(rep, hide_index=True)
        st.caption("Frequent label corrections show where a definition in config.yaml needs sharpening. "
                   "Frequent star adjustments in one direction show a priority weight or cap to tune.")
