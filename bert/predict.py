#!/usr/bin/env python
"""Route emails through sender rules first, then the trained model.

Sender rules (see preprocess.SENDER_RULES) are applied before the model, so
senders handled deterministically never reach it. Emails are read from a CSV
with Subject / From / Preview columns.

Usage:
    python predict.py --task category --model distilbert-base-uncased --input emails.csv
    python predict.py --task action   --model microsoft/deberta-v3-small --input emails.csv --output preds.csv
"""
import argparse
import os

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from preprocess import (DATASETS, SCRIPT_DIR, STRIP_SENDER, build_text,
                        sender_rule_label)

MAX_LEN = 256
MODEL_DIR = os.path.join(SCRIPT_DIR, "model")


def load_model(task, model):
    out_dir = os.path.join(MODEL_DIR, f"{model.replace('/', '_')}_{task}")
    if not os.path.isdir(out_dir):
        raise FileNotFoundError(f"{out_dir} not found - train first: python train.py --task {task} --model {model}")
    tokenizer = AutoTokenizer.from_pretrained(out_dir)
    net = AutoModelForSequenceClassification.from_pretrained(out_dir)
    net.eval()
    return tokenizer, net


def predict(df, task, model):
    """Return df with added pred / confidence / source columns."""
    label_col = DATASETS[task]
    tokenizer, net = load_model(task, model)
    id2label = net.config.id2label

    preds, confs, sources = [None] * len(df), [None] * len(df), [None] * len(df)
    pending = []
    for pos, (i, r) in enumerate(df.iterrows()):
        rule = sender_rule_label(r.get("From"), label_col)
        if rule is not None:
            preds[pos], confs[pos], sources[pos] = rule, 1.0, "rule"
        else:
            pending.append((pos, i, r))

    if pending:
        texts = [build_text(r.get("Subject"), r.get("From"), r.get("Preview"), STRIP_SENDER)
                 for _, _, r in pending]
        enc = tokenizer(texts, return_tensors="pt", truncation=True, padding=True, max_length=MAX_LEN)
        with torch.no_grad():
            logits = net(**enc).logits
        probs = torch.softmax(logits, dim=-1).numpy()
        for (pos, _, _), p in zip(pending, probs):
            k = int(p.argmax())
            preds[pos], confs[pos], sources[pos] = id2label[k], float(p[k]), "model"

    out = df.copy()
    out["pred"] = preds
    out["confidence"] = confs
    out["source"] = sources
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["category", "action"], required=True)
    parser.add_argument("--model", default="distilbert-base-uncased")
    parser.add_argument("--input", required=True, help="CSV with Subject / From / Preview columns")
    parser.add_argument("--output", default=None, help="output CSV (default: <input>_pred.csv)")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    out = predict(df, args.task, args.model)
    out_path = args.output or os.path.splitext(args.input)[0] + "_pred.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(out)} predictions to {out_path}")
    print(out["source"].value_counts().to_string())


if __name__ == "__main__":
    main()
