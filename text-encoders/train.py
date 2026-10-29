"""Train BERT heads (default) or a full DistilBERT model."""
import argparse
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

from src.data import (
    DEFAULT_ENCODERS,
    DEFAULT_REVIEW,
    DataError,
    ENCODERS,
    SEED,
    load_review,
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

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["head", "full"], default="head", help="training mode (default: head)")
    ap.add_argument("--task", choices=["category", "action", "both"], default="both", help="task to train (default: both)")
    ap.add_argument(
        "--review",
        default=DEFAULT_REVIEW,
        metavar="FILE",
        help="shared labels CSV (default: data/labels.csv)",
    )
    ap.add_argument("--encoder", choices=list(ENCODERS), help="head-mode encoder (default: task-specific)")
    ap.add_argument("--synthetic", metavar="CSV", help="synthetic CSV added to TRAIN only")
    ap.add_argument("--synthetic-tasks", choices=["category", "action", "both"], default="action", help="tasks using synthetic data (default: action)")
    ap.add_argument("--compare-seeds", metavar="LIST", help="seeds for comparison runs, e.g. 1,2,3")
    ap.add_argument("--check-only", action="store_true", help="validate data and splits (no training)")
    args = ap.parse_args()

    labels, digest = load_taxonomy()
    review = load_review(args.review)
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
