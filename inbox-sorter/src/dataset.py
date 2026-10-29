"""Build a hand-labelled test set, so you can measure how accurate Claude is on your own mail.

  python -m src.dataset export --n 300      # recent Inbox emails -> data/raw.jsonl (needs a pasted token)
  streamlit run app/label_tool.py           # label them yourself, without seeing Claude's answer
  python -m src.dataset kappa               # labelling consistency vs. your second pass
  python -m src.evaluate                    # Claude's accuracy against your labels

You label blind on purpose: if you saw Claude's guess first, you'd tend to agree with it and the
accuracy figures would look better than they are.

data/raw.jsonl contains email text. It stays on your machine, is gitignored, and should be
deleted when you no longer need it.
"""
from __future__ import annotations

import argparse
import json

from .config import DATA, get_config

RAW = DATA / "raw.jsonl"
LABELS = DATA / "labels.jsonl"
LABELS_SECOND = DATA / "labels_second.jsonl"


def read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def read_labels(path) -> dict[str, dict]:
    """Latest label per email id (later lines win)."""
    return {r["id"]: r for r in read_jsonl(path)}


def labelled_set(cfg: dict) -> list[dict]:
    """Raw emails joined with your labels (only labels that exist in config.yaml)."""
    rows = {r["id"]: r for r in read_jsonl(RAW)}
    out = []
    for eid, lab in read_labels(LABELS).items():
        if eid in rows and lab["topic"] in cfg["topics"] and lab["action"] in cfg["actions"]:
            out.append({**rows[eid], "topic": lab["topic"], "action": lab["action"]})
    return out


def cmd_export(args, cfg):
    from . import graph_token
    from .graph import list_inbox, my_address
    from .preprocess import to_record

    token = graph_token.get()
    me = my_address(token)
    msgs = list_inbox(token, max_n=args.n)
    existing = {r["id"]: r for r in read_jsonl(RAW)}
    for m in msgs:
        existing[m["id"]] = to_record(m, me, cfg).to_dict()
    rows = sorted(existing.values(), key=lambda r: r["received"])
    write_jsonl(RAW, rows)
    print(f"Saved {len(rows)} emails to {RAW} ({len(msgs)} fetched this run).")


def cmd_kappa(args, cfg):
    from sklearn.metrics import cohen_kappa_score

    first, second = read_labels(LABELS), read_labels(LABELS_SECOND)
    ids = [i for i in second if i in first]
    if len(ids) < 20:
        raise SystemExit(f"Only {len(ids)} emails double-labelled; aim for 100 (second-pass mode in the label tool).")
    for field in ("topic", "action"):
        k = cohen_kappa_score([first[i][field] for i in ids], [second[i][field] for i in ids])
        agree = sum(first[i][field] == second[i][field] for i in ids) / len(ids)
        print(f"{field:6s}  kappa={k:.3f}  raw agreement={agree:.1%}  (n={len(ids)})")
    print("\nKappa above 0.8 is strong. Disagreements usually point to a label definition that needs tightening.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--n", type=int, default=300)
    sub.add_parser("kappa")
    args = p.parse_args()
    cfg = get_config()
    {"export": cmd_export, "kappa": cmd_kappa}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
