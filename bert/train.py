"""Unified email classifier trainer.

Two modes:
  head   (default) — frozen sentence encoder + trainable logistic-regression head.
              Tiny, fast, no overfitting on ~80 real emails.
              Output -> bert/models/{task}_head/
  full   — full DistilBERT fine-tune. Slower, heavier.
              Output -> bert/models/{task}_full/

Shared data handling: review CSV validation, Canvas sender rule, stratified split,
synthetic rows added to TRAIN only (val/test stay real).

Examples (repo root):

  # 1) Train the recommended frozen heads for the app
  python bert/train.py --review bert/data/labels.csv --task both
  python bert/train.py --review bert/data/labels.csv --task action --mode head \
      --encoder e5-small-multi --synthetic bert/data/synthetic.csv

  # 2) Train a full DistilBERT fine-tune on real data only
  python bert/train.py --review bert/data/labels.csv --task both --mode full

  # 3) Compare encoders / real vs real+synthetic (head mode, 10 seeds, no model saved)
  python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
      --mode head --compare-seeds 1,2,3,4,5,6,7,8,9,10
  cat bert/results/compare_head_summary.txt

  # 4) Compare DistilBERT vs TF-IDF (full mode, 5 seeds, no model saved)
  python bert/train.py --review bert/data/labels.csv --synthetic bert/data/synthetic.csv \
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
    DataError,
    ENCODERS,
    SEED,
    load_taxonomy,
    split_dataset,
    synthetic_dataset,
    task_dataset,
)
from src.model import (head_compare, train_full_task, train_head_final, tfidf_run,
                       full_compare_seeds)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["head", "full"], default="head",
                    help="head = frozen encoder + logreg head (default, recommended); "
                         "full = full DistilBERT fine-tune")
    ap.add_argument("--review", metavar="CSV")
    ap.add_argument("--check-only", action="store_true",
                    help="validate labels and print splits, no training")
    ap.add_argument("--task", choices=["category", "action", "both"], default="both")
    ap.add_argument("--allow-missing-labels", action="store_true")
    ap.add_argument("--model", default="distilbert-base-uncased",
                    help="full mode only: HF model id")
    ap.add_argument("--epochs", type=int, default=10,
                    help="full mode only: training epochs")
    ap.add_argument("--lr", type=float, default=5e-5,
                    help="full mode only: learning rate")
    ap.add_argument("--encoder", choices=list(ENCODERS), default="bge-small-en",
                    help="head mode only: frozen encoder name")
    ap.add_argument("--out-dir", metavar="DIR",
                    help="output dir (default: models/)")
    ap.add_argument("--synthetic", metavar="CSV",
                    help="synthetic emails, added to the TRAIN split only")
    ap.add_argument("--synthetic-tasks", choices=["category", "action", "both"], default="action",
                    help="which tasks use the synthetic rows (default: action)")
    ap.add_argument("--compare-seeds", metavar="LIST",
                    help="e.g. 1,2,3,4,5 : repeat training on several splits, real-only vs "
                         "real+synthetic (models are NOT saved)")
    ap.add_argument("--compare-dir", metavar="DIR",
                    help="comparison output dir (default: results/)")
    ap.add_argument("--encoders", default=",".join(ENCODERS),
                    help="head mode only: encoders used with --compare-seeds")
    ap.add_argument("--tfidf-only", action="store_true",
                    help="full mode only: with --compare-seeds, skip BERT, run TF-IDF only (fast)")
    args = ap.parse_args()

    if not args.review:
        ap.error("--review CSV is required")

    labels, digest = load_taxonomy()
    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
    args.provisional = bool((review.get("label_source", pd.Series(dtype=str)) == "provisional").any())
    tasks = ["category", "action"] if args.task == "both" else [args.task]
    data, syn_data = {}, {}
    ok = True
    for t in tasks:
        try:
            data[t] = task_dataset(review, t, labels[t], args.allow_missing_labels)
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

    # Resolve output / compare dirs by mode
    if args.out_dir is None:
        args.out_dir = os.path.join(SCRIPT_DIR, "models")
    if args.compare_dir is None:
        args.compare_dir = os.path.join(SCRIPT_DIR, "results")

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
            enc_list = [e.strip() for e in args.encoders.split(",") if e.strip()]
            head_compare(data, syn_data, enc_list, seeds, args.compare_dir)
        else:
            full_compare_seeds(data, syn_data, labels, digest, args, seeds)

        # Display comparison results
        summary_name = "compare_head_summary.txt" if args.mode == "head" else "compare_full_summary.txt"
        summary_path = os.path.join(args.compare_dir, summary_name)
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
            train_head_final(t, df, info, syn, si, args.encoder, labels[t], digest, args)
        else:
            train_full_task(t, df, info, labels[t], digest, args, syn, si)


if __name__ == "__main__":
    main()
