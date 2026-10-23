#!/usr/bin/env python
"""Fine-tune an email classifier on the preprocessed Category + Action CSVs.

The train/test CSVs are produced by preprocess.py:

    python preprocess.py --export
    python train.py --model distilbert-base-uncased
    python train.py --model microsoft/deberta-v3-small

Usage:
    python train.py                       # train both tasks with distilbert
    python train.py --models distilbert-base-uncased microsoft/deberta-v3-small
    python train.py --freeze_backbone     # train only the classification head
    python train.py --task category --epochs 4
"""
import argparse
import json
import os
import random

import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, Trainer, TrainingArguments)

from preprocess import DATA_DIR, DATASETS, SCRIPT_DIR, load_split

SEED = 42

# Fixed training configuration (edit here instead of via CLI).
MAX_LEN = 256
BATCH_SIZE = 16
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
OUT_DIR = os.path.join(SCRIPT_DIR, "model")
LR_HEAD = 1e-4          # lr when the backbone is frozen
LR_FULL = 2e-5          # lr when fine-tuning the whole model


# --------------------------------------------------------------------------- #
# Modeling
# --------------------------------------------------------------------------- #
class WeightedTrainer(Trainer):
    """Trainer with a per-class weighted CrossEntropyLoss on the classification head."""

    def __init__(self, class_weight=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weight = class_weight

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs.get("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        weight = self.class_weight.to(logits.device) if self.class_weight is not None else None
        loss = torch.nn.CrossEntropyLoss(weight=weight)(logits.view(-1, model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {"accuracy": accuracy_score(labels, preds),
            "macro_f1": f1_score(labels, preds, average="macro"),
            "weighted_f1": f1_score(labels, preds, average="weighted")}


def train_task(task, model_id, args):
    label_col = DATASETS[task]
    random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

    train_df = load_split(task, "train", DATA_DIR)
    val_df = load_split(task, "test", DATA_DIR)

    labels = sorted(set(train_df[label_col]) | set(val_df[label_col]))
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}
    train_df["label"] = train_df[label_col].map(label2id)
    val_df["label"] = val_df[label_col].map(label2id)

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tok(examples):
        return tokenizer(examples["text"], padding=False, truncation=True, max_length=MAX_LEN)

    train_ds = Dataset.from_pandas(train_df[["text", "label"]]).map(tok, batched=True)
    val_ds = Dataset.from_pandas(val_df[["text", "label"]]).map(tok, batched=True)
    train_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    val_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    model = AutoModelForSequenceClassification.from_pretrained(
        model_id, num_labels=len(labels), id2label=id2label, label2id=label2id)

    if args.freeze_backbone:
        for p in model.base_model.parameters():
            p.requires_grad = False
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    lr = LR_HEAD if args.freeze_backbone else LR_FULL
    print(f"\nTrainable params: {trainable:,} / {total:,} ({100 * trainable / total:.1f}%) | lr={lr}")

    counts = train_df["label"].value_counts().sort_index()
    class_weight = torch.tensor((len(train_df) / (len(labels) * counts)).values, dtype=torch.float32)
    print("Class weights:", {labels[i]: round(float(w), 3) for i, w in enumerate(class_weight)})

    out_dir = os.path.join(OUT_DIR, f"{model_id.replace('/', '_')}_{task}")
    os.makedirs(out_dir, exist_ok=True)

    trainer = WeightedTrainer(
        model=model, class_weight=class_weight, data_collator=data_collator,
        train_dataset=train_ds, eval_dataset=val_ds, compute_metrics=compute_metrics,
        args=TrainingArguments(
            output_dir=os.path.join(out_dir, "checkpoints"),
            num_train_epochs=args.epochs, learning_rate=lr,
            per_device_train_batch_size=BATCH_SIZE, per_device_eval_batch_size=BATCH_SIZE,
            warmup_ratio=WARMUP_RATIO, weight_decay=WEIGHT_DECAY,
            evaluation_strategy="epoch", save_strategy="epoch", save_total_limit=1,
            load_best_model_at_end=True, metric_for_best_model="macro_f1", greater_is_better=True,
            logging_dir=os.path.join(out_dir, "logs"), logging_steps=10,
            seed=SEED, report_to=[]))

    trainer.train()
    trainer.save_model(out_dir)
    tokenizer.save_pretrained(out_dir)

    pred_out = trainer.predict(val_ds)
    preds = np.argmax(pred_out.predictions, axis=-1)
    probs = torch.nn.functional.softmax(torch.from_numpy(pred_out.predictions), dim=-1).numpy()
    val_df["pred"] = [id2label[p] for p in preds]
    val_df["confidence"] = probs[np.arange(len(probs)), preds]
    val_df[["Subject", "From", "Preview", label_col, "pred", "confidence"]].to_csv(
        os.path.join(out_dir, "val_predictions.csv"), index=False, encoding="utf-8-sig")

    report = classification_report(val_df[label_col], val_df["pred"], labels=labels,
                                   output_dict=True, zero_division=0)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump({"task": task, "label_col": label_col, "model": model_id,
                   "source": f"{task}_train.csv",
                   "train_size": len(train_df), "val_size": len(val_df), "epochs": args.epochs,
                   "freeze_backbone": args.freeze_backbone, "lr": lr,
                   "trainable_params": trainable, "total_params": total,
                   "class_weight": True, "metrics": report, "label_order": labels,
                   "confusion_matrix": confusion_matrix(val_df[label_col], val_df["pred"], labels=labels).tolist()},
                  f, indent=2, ensure_ascii=False)

    acc = accuracy_score(val_df[label_col], val_df["pred"])
    macro_f1 = f1_score(val_df[label_col], val_df["pred"], average="macro")
    print(f"\nAccuracy : {acc:.4f}")
    print(f"Macro-F1 : {macro_f1:.4f}")
    print("Per-class F1:", {l: round(report[l]["f1-score"], 4) for l in labels})
    print("Saved to:", out_dir)
    return {"task": task, "model": model_id, "accuracy": acc, "macro_f1": macro_f1,
            "train_size": len(train_df), "val_size": len(val_df)}


# --------------------------------------------------------------------------- #
def print_summary(results):
    if not results:
        return
    print("\n" + "=" * 72)
    print(f"{'task':<10} {'model':<34} {'acc':>7} {'macro_f1':>9}")
    print("-" * 72)
    for r in sorted(results, key=lambda r: (r["task"], -r["macro_f1"])):
        print(f"{r['task']:<10} {r['model']:<34} {r['accuracy']:>7.4f} {r['macro_f1']:>9.4f}")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["category", "action", "both"], default="both")
    parser.add_argument("--models", nargs="+", default=["distilbert-base-uncased"],
                        help="one or more HF model names, e.g. --models distilbert-base-uncased microsoft/deberta-v3-small")
    parser.add_argument("--freeze_backbone", action="store_true",
                        help="train only the classification head (backbone frozen)")
    parser.add_argument("--epochs", type=int, default=4)
    args = parser.parse_args()

    tasks = ["category", "action"] if args.task == "both" else [args.task]
    results = [train_task(task, model, args) for model in args.models for task in tasks]
    print_summary(results)


if __name__ == "__main__":
    main()
