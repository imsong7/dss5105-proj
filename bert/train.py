"""Unified email classifier trainer.

Two modes:
  head   (default) — frozen sentence encoder + trainable logistic-regression head.
              Tiny, fast, no overfitting on ~80 real emails.
              Output -> bert/models/{task}_head/
  full   — full DistilBERT fine-tune. Slower, heavier.
              Output -> bert/models/{task}_full/

Shared data handling: review CSV validation, Canvas sender rule, stratified split,
synthetic rows added to TRAIN only (val/test stay real).

By default this reads bert/data/labels.csv and writes to bert/models or
bert/results. The default head encoders are category=bge-small-en and
action=e5-small-multi; use --encoder to override both.

Examples (repo root):

  # 1) Train the recommended frozen heads for the app
  python bert/train.py --task both
  python bert/train.py --task action --synthetic bert/data/synthetic.csv

  # 2) Train a full DistilBERT fine-tune on real data only
  python bert/train.py --mode full --task both

  # 3) Compare encoders / real vs real+synthetic (head mode, 10 seeds)
  python bert/train.py --synthetic bert/data/synthetic.csv \
      --compare-seeds 1,2,3,4,5,6,7,8,9,10
  cat bert/results/compare_head_summary.txt

  # 4) Compare DistilBERT vs TF-IDF (full mode, 5 seeds)
  python bert/train.py --synthetic bert/data/synthetic.csv \
      --mode full --compare-seeds 1,2,3,4,5 --task action
  cat bert/results/compare_full_summary.txt
"""
import argparse
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Make bert.src importable when run as `python bert/train.py`
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.data import (
    DEFAULT_ENCODERS,
    DataError,
    ENCODERS,
    SEED,
    load_taxonomy,
    split_dataset,
    synthetic_dataset,
    task_dataset,
)
from src.model import (
    RESULTS_DIR,
    full_compare_seeds,
    head_compare,
    train_full_task,
    train_head_final,
)

DEFAULT_REVIEW = os.path.join(SCRIPT_DIR, "data", "labels.csv")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["head", "full"], default="head",
                    help="head = frozen encoder + logreg head (default, recommended); "
                         "full = full DistilBERT fine-tune")
    ap.add_argument("--task", choices=["category", "action", "both"], default="both")
    ap.add_argument("--review", default=DEFAULT_REVIEW, metavar="CSV",
                    help="review CSV (default: bert/data/labels.csv)")
    ap.add_argument("--encoder", choices=list(ENCODERS),
                    help="head mode: override the task default "
                         "(category=bge-small-en, action=e5-small-multi)")
    ap.add_argument("--synthetic", metavar="CSV",
                    help="synthetic emails, added to the TRAIN split only")
    ap.add_argument("--synthetic-tasks", choices=["category", "action", "both"], default="action",
                    help="which tasks use the synthetic rows (default: action)")
    ap.add_argument("--compare-seeds", metavar="LIST",
                    help="e.g. 1,2,3,4,5 : repeat training on several splits, real-only vs "
                         "real+synthetic (models are NOT saved)")
    ap.add_argument("--check-only", action="store_true",
                    help="validate labels and print splits, no training")
    args = ap.parse_args()

    labels, digest = load_taxonomy()
    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
    args.provisional = bool((review.get("label_source", pd.Series(dtype=str)) == "provisional").any())
    tasks = ["category", "action"] if args.task == "both" else [args.task]
    data, syn_data = {}, {}
    ok = True
    for t in tasks:
        try:
            data[t] = task_dataset(review, t, labels[t])
            print(f"[{t}] OK rows={data[t][1]['rows_used']} counts={data[t][1]['counts']} "
                  f"rule={data[t][1]['rule_labels']} (excluded {data[t][1]['rule_rows_excluded']}) "
                  f"unsupported={data[t][1]['unsupported_labels']}")
        except DataError as e:
            ok = False
            print("ERROR", e)
    if args.synthetic and ok:
        st = ["category", "action"] if args.synthetic_tasks == "both" else [args.synthetic_tasks]
        for t in [t for t in tasks if t in st]:
            try:
                syn_data[t] = synthetic_dataset(args.synthetic, t, labels[t], data[t][0])
                si = syn_data[t][1]
                print(f"[{t}] synthetic OK rows={si['rows']} counts={si['counts']} "
                      f"(dropped: duplicates {si['removed_duplicates']}, "
                      f"too similar to real {si['removed_near_real']})")
            except DataError as e:
                ok = False
                print("ERROR", e)
    if not ok:
        sys.exit(2)

    seeds = [int(x) for x in args.compare_seeds.split(",") if x.strip()] if args.compare_seeds else None

    if args.check_only:
        for t, (df, _) in data.items():
            for sd in (seeds or [SEED]):
                tr, va, te = split_dataset(df, seed=sd)
                print(f"[{t}] seed={sd} split train/val/test = {len(tr)}/{len(va)}/{len(te)} "
                      f"test counts={te['label_key'].value_counts().to_dict()}")
        return

    if seeds:
        if args.mode == "head":
            head_compare(data, syn_data, list(ENCODERS), seeds, RESULTS_DIR)
        else:
            full_compare_seeds(data, syn_data, labels, digest, args, seeds)

        # Display comparison results
        summary_name = "compare_head_summary.txt" if args.mode == "head" else "compare_full_summary.txt"
        summary_path = os.path.join(RESULTS_DIR, summary_name)
        if os.path.exists(summary_path):
            print("\n" + "=" * 70)
            print(f"Comparison results -> {summary_path}")
            print("=" * 70)
            with open(summary_path) as f:
                print(f.read())
        return

    for t, (df, info) in data.items():
        syn, si = syn_data.get(t, (None, None))
        if args.mode == "head":
            encoder = args.encoder or DEFAULT_ENCODERS[t]
            train_head_final(t, df, info, syn, si, encoder, labels[t], digest, args)
        else:
            train_full_task(t, df, info, labels[t], digest, args, syn, si)


if __name__ == "__main__":
    main()
