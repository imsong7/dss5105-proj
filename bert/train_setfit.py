#!/usr/bin/env python
"""Train a SetFit classifier on the preprocessed Category + Action datasets.

SetFit fits a frozen sentence-transformer encoder with a light classification
head via contrastive pairs, which works well on the small dataset here. Data
loading and label maps live in preprocess.py.

Usage:
    python train_setfit.py                        # train both tasks
    python train_setfit.py --task category --epochs 3
    python train_setfit.py --model BAAI/bge-small-en-v1.5

Run `python preprocess.py` to inspect label statistics before training.
"""
import argparse
import json
import os
import random

import numpy as np
import torch
from datasets import Dataset
from setfit import SetFitModel, Trainer, TrainingArguments
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.model_selection import train_test_split

from preprocess import DATASETS, SCRIPT_DIR, STRIP_SENDER, XLSX, build_records, task_df

SEED = 42

# Fixed SetFit configuration (edit here instead of via CLI).
NUM_ITERATIONS = 20
BATCH_SIZE = 16
VAL_SIZE = 0.2
OUT_DIR = os.path.join(SCRIPT_DIR, "model_setfit")


def train_task(task, records, args):
    label_col = DATASETS[task]
    random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

    df = task_df(records, label_col, STRIP_SENDER)

    labels = sorted(df[label_col].unique().tolist())
    label2id = {l: i for i, l in enumerate(labels)}
    df["label"] = df[label_col].map(label2id)

    cluster_key = (df["Subject"].fillna("").astype(str).str.strip().str.lower() + "||"
                   + df["From"].fillna("").astype(str).str.strip().str.lower() + "||"
                   + df["Preview"].fillna("").astype(str).str.strip().str.lower())
    df = df.assign(cluster_key=cluster_key)
    groups = df.drop_duplicates("cluster_key")
    train_groups, val_groups = train_test_split(
        groups, test_size=VAL_SIZE, random_state=SEED, stratify=groups["label"])
    train_df = df[df["cluster_key"].isin(train_groups["cluster_key"])].drop(columns="cluster_key").reset_index(drop=True)
    val_df = df[df["cluster_key"].isin(val_groups["cluster_key"])].drop(columns="cluster_key").reset_index(drop=True)

    train_ds = Dataset.from_pandas(train_df[["text", "label"]])
    val_ds = Dataset.from_pandas(val_df[["text", "label"]])

    model = SetFitModel.from_pretrained(args.model, labels=labels)
    print(f"\nSetFit base: {args.model} | labels: {labels}")

    trainer = Trainer(
        model=model,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        args=TrainingArguments(
            batch_size=BATCH_SIZE, num_epochs=args.epochs,
            num_iterations=NUM_ITERATIONS, seed=SEED))
    trainer.train()

    out_dir = os.path.join(OUT_DIR, f"{args.model.replace('/', '_')}_{task}")
    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir)

    preds = np.array(model.predict(val_df["text"].tolist()))
    probs = model.predict_proba(val_df["text"].tolist())
    prob_map = {l: i for i, l in enumerate(labels)}
    val_df["pred"] = preds
    val_df["confidence"] = probs[np.arange(len(probs)), [prob_map[p] for p in preds]]
    val_df[["Subject", "From", "Preview", label_col, "pred", "confidence"]].to_csv(
        os.path.join(out_dir, "val_predictions.csv"), index=False, encoding="utf-8-sig")

    report = classification_report(val_df[label_col], val_df["pred"], labels=labels,
                                   output_dict=True, zero_division=0)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump({"task": task, "label_col": label_col, "model": args.model,
                   "source": os.path.basename(XLSX),
                   "train_size": len(train_df), "val_size": len(val_df), "epochs": args.epochs,
                   "num_iterations": NUM_ITERATIONS, "trainable_params": "setfit",
                   "class_weight": False, "metrics": report, "label_order": labels,
                   "confusion_matrix": confusion_matrix(val_df[label_col], val_df["pred"], labels=labels).tolist()},
                  f, indent=2, ensure_ascii=False)

    print(f"\nAccuracy : {accuracy_score(val_df[label_col], val_df['pred']):.4f}")
    print(f"Macro-F1 : {f1_score(val_df[label_col], val_df['pred'], average='macro'):.4f}")
    print("Per-class F1:", {l: round(report[l]["f1-score"], 4) for l in labels})
    print("Saved to:", out_dir)


# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["category", "action", "both"], default="both")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2",
                        help="sentence-transformer backbone")
    parser.add_argument("--epochs", type=int, default=1)
    args = parser.parse_args()

    records = build_records(XLSX)
    for task in (["category", "action"] if args.task == "both" else [args.task]):
        train_task(task, records, args)


if __name__ == "__main__":
    main()
