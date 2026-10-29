"""Phase 1 labelling tool: one email at a time, two dropdowns, Save & next.

  streamlit run app/label_tool.py

Reads data/raw.jsonl (from `python -m src.dataset export`) and writes your labels to
data/labels.jsonl. Second-pass mode re-labels a random 100 without showing your earlier
answers, for the consistency (kappa) check.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import actions, get_config, topics  # noqa: E402
from src.dataset import LABELS, LABELS_SECOND, RAW, read_jsonl, read_labels  # noqa: E402

st.set_page_config(page_title="Label emails", layout="centered")
cfg = get_config()
TOPICS, ACTIONS = topics(cfg), actions(cfg)


@st.cache_data
def load_raw(mtime: float):
    return read_jsonl(RAW)


if not RAW.exists():
    st.error("data/raw.jsonl not found. Run `python -m src.dataset export` first.")
    st.stop()
rows = load_raw(RAW.stat().st_mtime)

second = st.sidebar.toggle("Second-pass mode (kappa check)")
out_path = LABELS_SECOND if second else LABELS
done = read_labels(out_path)

if second:
    first = read_labels(LABELS)
    pool = sorted(i for i in first)
    random.Random(42).shuffle(pool)
    queue_ids = [i for i in pool[:100] if i not in done]
    by_id = {r["id"]: r for r in rows}
    queue = [by_id[i] for i in queue_ids if i in by_id]
else:
    only_new = st.sidebar.checkbox("Unlabelled only", value=True)
    queue = [r for r in rows if not (only_new and r["id"] in done)]

st.sidebar.metric("Labelled", f"{len(done)} / {100 if second else len(rows)}")
st.sidebar.caption(f"Saving to {out_path.name}")
with st.sidebar.expander("Label definitions"):
    for k, v in {**cfg["topics"], **cfg["actions"]}.items():
        st.markdown(f"**{k}**: {v}")

if not queue:
    st.success("Nothing left to label in this mode.")
    st.stop()

pos = st.session_state.setdefault("pos", 0) % len(queue)
r = queue[pos]

st.caption(f"Email {pos + 1} of {len(queue)} · {r['received'][:16].replace('T', ' ')} · {r.get('sender_name') or r['sender']}")
st.subheader(r["subject"] or "(no subject)")
st.text_area("Body", r["text"], height=320, disabled=True, label_visibility="collapsed")

prev = done.get(r["id"], {})
default_t = prev.get("topic") or (None if second else r.get("pre_topic"))
default_a = prev.get("action") or (None if second else r.get("pre_action"))
c1, c2 = st.columns(2)
topic = c1.selectbox("Topic (A)", TOPICS, index=TOPICS.index(default_t) if default_t in TOPICS else None,
                     key=f"t_{r['id']}")
action = c2.selectbox("Action (B)", ACTIONS, index=ACTIONS.index(default_a) if default_a in ACTIONS else None,
                      key=f"a_{r['id']}")
if not second and r.get("pre_topic"):
    st.caption(f"LLM pre-label: {r.get('pre_topic')} / {r.get('pre_action')}")

b1, b2, b3 = st.columns([2, 1, 1])
if b1.button("Save & next", type="primary", disabled=not (topic and action)):
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": r["id"], "topic": topic, "action": action,
                            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
    if not second and not only_new:  # otherwise the saved email drops out of the queue by itself
        st.session_state["pos"] = pos + 1
    st.rerun()
if b2.button("Skip"):
    st.session_state["pos"] = pos + 1
    st.rerun()
if b3.button("Back"):
    st.session_state["pos"] = max(pos - 1, 0)
    st.rerun()
