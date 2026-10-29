"""Measure Claude's accuracy against your hand labels and write a report.

  python -m src.evaluate               # classify every hand-labelled email with Claude (costs API calls)
  python -m src.evaluate --limit 50    # quicker, cheaper check on the first 50

Results are cached in data/eval_cache.jsonl per email and model, so re-running after you label more
emails only pays for the new ones. Change a definition in config.yaml? Use --fresh.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from datetime import datetime

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_score, recall_score

from .config import DATA, REPORTS, actions, get_config, topics
from .dataset import labelled_set, read_jsonl, write_jsonl
from .llm import ClaudeClassifier, build_system_prompt
from .pipeline import Result, classify
from .preprocess import EmailRecord
from .rules import apply_rules

REC_FIELDS = {f.name for f in fields(EmailRecord)}
CACHE = DATA / "eval_cache.jsonl"


def metrics(cfg, y_t, p_t, y_a, p_a) -> dict:
    m = {
        "topic_macro_f1": f1_score(y_t, p_t, average="macro", labels=topics(cfg), zero_division=0),
        "action_macro_f1": f1_score(y_a, p_a, average="macro", labels=actions(cfg), zero_division=0),
        "joint_accuracy": float(np.mean([a == b and c == d for a, b, c, d in zip(y_t, p_t, y_a, p_a)])),
        "further_review_share": float(np.mean([a == cfg["fallback_action"] for a in p_a])),
    }
    for name, lab, y, p in (("recall_needs_reply", "Needs a reply", y_a, p_a),
                            ("recall_needs_action", "Needs an action", y_a, p_a),
                            ("recall_medical", "Medical", y_t, p_t),
                            ("recall_career", "Career", y_t, p_t)):
        if lab in y:
            m[name] = recall_score(y, p, labels=[lab], average="macro", zero_division=0)
    if "No action needed" in p_a:
        m["precision_no_action_needed"] = precision_score(
            y_a, p_a, labels=["No action needed"], average="macro", zero_division=0)
    return {k: round(float(v), 4) for k, v in m.items()}


def gate(cfg, m: dict) -> list[tuple]:
    rows = []
    for key, target in (cfg.get("targets") or {}).items():
        if key == "max_further_review_share":
            v = m.get("further_review_share")
            rows.append(("further_review_share (max)", v, target, v is not None and v <= target))
        elif key in m:
            rows.append((key, m[key], target, m[key] >= target))
    return rows


def cm_table(y, p, labels) -> str:
    cm = confusion_matrix(y, p, labels=labels)
    short = [l[:12] for l in labels]
    head = "| true \\ predicted | " + " | ".join(short) + " |"
    sep = "|" + "---|" * (len(labels) + 1)
    body = "\n".join(f"| {short[i]} | " + " | ".join(str(v) for v in row) + " |" for i, row in enumerate(cm))
    return f"{head}\n{sep}\n{body}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--fresh", action="store_true", help="ignore cached results")
    args = ap.parse_args()
    cfg = get_config()

    data = labelled_set(cfg)
    if not data:
        raise SystemExit("No hand-labelled emails. Run `python -m src.dataset export`, then label with "
                         "`streamlit run app/label_tool.py`.")
    data = data[: args.limit] if args.limit else data

    clf = ClaudeClassifier(cfg)
    if not clf.enabled:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first.")
    # Cache key changes whenever the model or the prompt (definitions, examples) changes,
    # and whenever the token budget or thinking mode changes.
    key = hashlib.sha1(
        (
            clf.model
            + build_system_prompt(cfg)
            + f"|max_tokens={clf.max_tokens}|thinking={clf.thinking}"
        ).encode()
    ).hexdigest()[:12]
    cache = {} if args.fresh else {(r["id"], r["key"]): r for r in read_jsonl(CACHE)}

    preds, sources, guard = [], Counter(), defaultdict(list)
    for i, row in enumerate(data, 1):
        rec = EmailRecord(**{k: row[k] for k in REC_FIELDS})
        hit = cache.get((rec.id, key))
        if hit:
            r = Result(**hit["result"])
        else:
            r = classify(rec, cfg, clf)
            if r.source == "fallback" and clf.api_failed:
                raise SystemExit(f"Claude API error: {clf.last_error}")
            cache[(rec.id, key)] = {"id": rec.id, "key": key, "result": asdict(r)}
        preds.append(r)
        sources[r.source] += 1
        for name in apply_rules(rec, cfg).fired:
            if name == "noreply_sender":
                guard[name].append(row["action"] != "Needs a reply")
            elif name.endswith("_sender") or name == "promotion_marker":
                guard[name].append(r.topic == row["topic"])
        if i % 25 == 0:
            print(f"  {i}/{len(data)}")
    write_jsonl(CACHE, list(cache.values()))

    y_t, y_a = [r["topic"] for r in data], [r["action"] for r in data]
    p_t, p_a = [r.topic for r in preds], [r.action for r in preds]
    m = metrics(cfg, y_t, p_t, y_a, p_a)
    g = gate(cfg, m)
    passed = all(ok for *_, ok in g)

    misses = [(r, p) for r, p in zip(data, preds) if (r["topic"], r["action"]) != (p.topic, p.action)]
    lines = [
        f"# Evaluation report · {datetime.now():%Y-%m-%d %H:%M}",
        f"Model `{clf.model}`, {len(data)} hand-labelled emails.\n",
        f"## Accuracy targets: {'PASS' if passed else 'FAIL'}\n",
        "| Metric | Value | Target | OK |", "|---|---|---|---|",
        *[f"| {k} | {v} | {t} | {'yes' if ok else 'NO'} |" for k, v, t, ok in g],
        "\n## All metrics\n", *[f"- {k}: {v}" for k, v in m.items()],
        "\n## How emails were decided\n", *[f"- {k}: {v / len(data):.1%}" for k, v in sources.most_common()],
        "\n## Rule checks (keep a shortcut only if close to 100%)\n",
        *([f"- {k}: {np.mean(v):.1%} of {len(v)}" for k, v in sorted(guard.items())] or ["- none fired"]),
        "\n## Category A confusion\n", cm_table(y_t, p_t, topics(cfg)),
        "\n## Category B confusion\n", cm_table(y_a, p_a, actions(cfg)),
        "\n## Per-class detail\n", "```",
        classification_report(y_t, p_t, labels=topics(cfg), zero_division=0),
        classification_report(y_a, p_a, labels=actions(cfg), zero_division=0), "```",
        f"\n## Disagreements ({len(misses)})\n",
        "Subjects only. Use these to sharpen definitions or add examples in config.yaml.\n",
        "| Subject | You | Claude | Claude's reason |", "|---|---|---|---|",
        *[f"| {r['subject'][:60].replace('|', '/')} | {r['topic']} / {r['action']} | {p.topic} / {p.action} "
          f"| {p.reason.replace('|', '/')} |" for r, p in misses[:100]],
    ]
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"eval_{datetime.now():%Y%m%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:5 + len(g)]))
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    main()
