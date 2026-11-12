"""Compare the two priority models on your hand-labelled emails, with no API calls.

  python -m src.evaluate      # first: classifies the test set once and caches Claude's answers
  python -m src.compare       # then: scores every cached email with BOTH models -> reports/

Both models use the same cached factor scores from the same Claude answer, so any difference in
stars comes only from the formula: content only, or content plus the topic and action labels.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from datetime import datetime

import numpy as np

from .config import REPORTS, get_config, topics
from .dataset import labelled_set, read_jsonl
from .evaluate import CACHE, priority_metrics, result_from_cache
from .llm import ClaudeClassifier, build_system_prompt
from .priority import MODELS, compute

NAMES = {"content_only": "Content only", "combined": "Content + categories"}


def cache_key(cfg: dict) -> str:
    """Same key as src.evaluate: model name + prompt."""
    return hashlib.sha1((ClaudeClassifier(cfg).model + build_system_prompt(cfg)).encode()).hexdigest()[:12]


def score_both(cfg: dict) -> list[dict]:
    key = cache_key(cfg)
    cache = {(r["id"], r["key"]): r for r in read_jsonl(CACHE)}
    rows = []
    for row in labelled_set(cfg):
        hit = cache.get((row["id"], key))
        if not hit:
            continue
        r = result_from_cache(hit["result"])
        if r.factors is None:
            continue
        stars = {m: compute(r.topic, r.action, r.factors, row["received"], cfg, model=m) for m in MODELS}
        rows.append({"row": row, "result": r, "stars": stars})
    return rows


def summary(rows: list[dict], model: str) -> dict:
    owner = [x["row"].get("stars") for x in rows]
    system = [x["stars"][model].stars for x in rows]
    m = priority_metrics(owner, system)
    promos = [x["stars"][model].stars for x in rows if x["result"].topic == "Promotions"]
    m["promotions_above_3"] = int(sum(s > 3 for s in promos))
    m["mean_stars"] = round(float(np.mean(system)), 2) if system else None
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    cfg = get_config()
    rows = score_both(cfg)
    if not rows:
        raise SystemExit("No cached results for your labelled emails. Run `python -m src.evaluate` first "
                         "(with the same model and prompt).")

    sums = {m: summary(rows, m) for m in MODELS}
    keys = ["priority_rated", "priority_within_one", "priority_exact", "priority_critical_recall",
            "priority_over_ranking", "priority_spearman", "priority_mean_difference", "mean_stars",
            "promotions_above_3"]
    agree = np.mean([x["stars"]["content_only"].stars == x["stars"]["combined"].stars for x in rows])
    by_topic = defaultdict(lambda: defaultdict(list))
    for x in rows:
        for m in MODELS:
            by_topic[x["result"].topic][m].append(x["stars"][m].stars)
        if x["row"].get("stars"):
            by_topic[x["result"].topic]["you"].append(x["row"]["stars"])
    diffs = sorted((x for x in rows if x["stars"]["content_only"].stars != x["stars"]["combined"].stars),
                   key=lambda x: -abs(x["stars"]["content_only"].stars - x["stars"]["combined"].stars))

    def closer(x):
        o = x["row"].get("stars")
        if not o:
            return ""
        a, b = abs(x["stars"]["content_only"].stars - o), abs(x["stars"]["combined"].stars - o)
        return "content only" if a < b else "combined" if b < a else "tie"

    mean = lambda v: f"{np.mean(v):.1f}" if v else "–"
    lines = [
        f"# Priority models compared · {datetime.now():%Y-%m-%d %H:%M}",
        f"{len(rows)} hand-labelled emails, same Claude answers scored two ways. "
        f"The models give the same stars for {agree:.0%} of them.\n",
        "## Against your ratings\n",
        "| Metric | Target | " + " | ".join(NAMES[m] for m in MODELS) + " |",
        "|---|---|" + "---|" * len(MODELS),
        *[f"| {k} | {cfg.get('targets', {}).get(k, cfg.get('targets', {}).get(k + '_max', ''))} | "
          + " | ".join(str(sums[m].get(k, "–")) for m in MODELS) + " |" for k in keys],
        "\nHigher is better except over-ranking, mean difference (closer to 0 is better) and promotions above 3.\n",
        "## Average stars by topic\n",
        "| Topic | You | " + " | ".join(NAMES[m] for m in MODELS) + " |", "|---|---|" + "---|" * len(MODELS),
        *[f"| {t} | {mean(by_topic[t]['you'])} | " + " | ".join(mean(by_topic[t][m]) for m in MODELS) + " |"
          for t in topics(cfg) if t in by_topic],
        f"\n## Emails where the models differ ({len(diffs)})\n",
        "| Subject | Topic / action | Factors | You | Content only | Combined | Closer to you |",
        "|---|---|---|---|---|---|---|",
        *[f"| {x['row']['subject'][:50].replace('|', '/')} | {x['result'].topic} / {x['result'].action} "
          f"| C{x['result'].factors.consequence} U{x['stars']['content_only'].urgency} R{x['result'].factors.relevance} "
          f"| {x['row'].get('stars') or chr(8211)} | {x['stars']['content_only'].stars} | {x['stars']['combined'].stars} "
          f"| {closer(x)} |" for x in diffs[:100]],
    ]
    wins = defaultdict(int)
    for x in diffs:
        wins[closer(x)] += 1
    if diffs:
        lines.insert(5, f"Where they differ, the closer one to your rating: content only {wins['content only']}, "
                        f"combined {wins['combined']}, tie {wins['tie']}.\n")
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"compare_{datetime.now():%Y%m%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6 + len(keys) + 2]))
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    main()
