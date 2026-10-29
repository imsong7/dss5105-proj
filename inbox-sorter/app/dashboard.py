"""Owner dashboard: paste your Graph token, sync, browse labelled emails, correct labels.

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
    search = st.text_input("Search sender or subject")

if cfg["worker"].get("shadow_mode"):
    st.warning("Shadow mode is on: new labels are stored but hidden. Set worker.shadow_mode: false in config.yaml.")

tab_inbox, tab_health = st.tabs(["Inbox", "Health"])

# ---------------- Inbox ----------------
with tab_inbox:
    df = store.dashboard_rows(con, days, dcfg.get("max_rows", 500))
    if df.empty:
        st.info("No labelled emails yet. Paste a token in the sidebar and press Sync now.")
    else:
        df["received"] = (pd.to_datetime(df["received"], utc=True)
                          .dt.tz_convert(dcfg.get("timezone", "UTC")).dt.strftime("%d %b %H:%M"))
        df["from"] = df["sender_name"].where(df["sender_name"].fillna("") != "", df["sender"])
        view = df[df["topic"].isin(sel_t) & df["action"].isin(sel_a)]
        if search:
            s = search.lower()
            view = view[view["from"].str.lower().str.contains(s, regex=False)
                        | view["subject"].fillna("").str.lower().str.contains(s, regex=False)]
        view = view.reset_index(drop=True)

        counts = view["action"].value_counts()
        for c, a in zip(st.columns(len(ACTIONS)), ACTIONS):
            c.metric(a, int(counts.get(a, 0)))

        st.caption("Change a Topic or Action to correct it, then press Save corrections.")
        st.data_editor(
            view[["received", "from", "subject", "topic", "action", "reason", "web_link"]],
            key="editor", hide_index=True, width="stretch", height=600,
            disabled=["received", "from", "subject", "reason", "web_link"],
            column_config={
                "received": st.column_config.TextColumn("Received", width="small"),
                "from": st.column_config.TextColumn("From", width="medium"),
                "subject": st.column_config.TextColumn("Subject", width="large"),
                "topic": st.column_config.SelectboxColumn("Topic (A)", options=TOPICS, required=True),
                "action": st.column_config.SelectboxColumn("Action (B)", options=ACTIONS, required=True),
                "reason": st.column_config.TextColumn("Why", width="medium"),
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
            del st.session_state["editor"]
            st.rerun()

# ---------------- Health ----------------
with tab_health:
    h = store.health(con, 7)
    if not h.get("emails"):
        st.info("No emails labelled in the last 7 days.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Emails labelled (7 days)", h["emails"])
        c2.metric("Corrected by you", f"{h['correction_rate']:.0%}")
        c3.metric("Sent to Further review", f"{h['further_review_share']:.0%}")
        st.subheader("How emails were decided")
        st.bar_chart(pd.Series(h["by_source"], name="share"))
    st.subheader("Your corrections")
    rep = store.corrections_report(con)
    if rep.empty:
        st.caption("None yet.")
    else:
        st.dataframe(rep, hide_index=True)
        st.caption("Frequent corrections show where a definition in config.yaml needs sharpening, "
                   "or where an example would help Claude.")
