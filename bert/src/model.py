"""Model training and inference for BERT email classification.

Two modes:
  head   (default) — frozen sentence encoder + trainable logistic-regression head.
  full   — full DistilBERT fine-tune.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from .data import (
    BATCH_SIZE,
    ENCODERS,
    HEAD_C,
    LR,
    MAX_LEN,
    SEED,
    STRIP_SENDER,
    TASKS,
    WARMUP_RATIO,
    WEIGHT_DECAY,
    build_text,
    split_dataset,
)


def _from_pretrained(factory, model_id):
    """Load a cached model/tokenizer without a Hugging Face hub round-trip.

    ``from_pretrained`` can spend seconds checking the hub even when the files
    are already cached. Try the local cache first, then fall back to the normal
    download path on a cache miss (e.g. first-time setup).
    """
    try:
        return factory.from_pretrained(model_id, local_files_only=True)
    except OSError:
        return factory.from_pretrained(model_id)


class FrozenEncoder:
    """Frozen sentence encoder that produces L2-normalized embeddings."""

    def __init__(self, name):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.name = name
        self.model_id, self.prefix, self.pool = ENCODERS[name]
        self.torch = torch
        self.tok = _from_pretrained(AutoTokenizer, self.model_id)
        self.model = _from_pretrained(AutoModel, self.model_id).eval()
        for p in self.model.parameters():
            p.requires_grad = False

    def encode(self, texts, bs=16):
        torch = self.torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), bs):
                b = self.tok([self.prefix + t for t in texts[i:i + bs]], truncation=True,
                             max_length=MAX_LEN, padding=True, return_tensors="pt")
                h = self.model(**b).last_hidden_state
                if self.pool == "cls":
                    e = h[:, 0]
                else:
                    m = b["attention_mask"].unsqueeze(-1).float()
                    e = (h * m).sum(1) / m.sum(1)
                out.append(torch.nn.functional.normalize(e, dim=-1).numpy())
        return np.vstack(out) if out else np.zeros((0, self.model.config.hidden_size))


def fit_head(X, y):
    """Fit a logistic-regression head on embeddings."""
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(max_iter=5000, C=HEAD_C, class_weight="balanced").fit(X, y)


def evaluate(clf, X, d, labels):
    """Evaluate a classifier on embeddings X for dataframe d."""
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    probs = clf.predict_proba(X)
    pred = clf.classes_[probs.argmax(1)]
    rep = classification_report(d["label_key"], pred, labels=labels, output_dict=True, zero_division=0)
    return pred, probs.max(1), {
        "n": len(d), "accuracy": accuracy_score(d["label_key"], pred),
        "macro_f1": f1_score(d["label_key"], pred, labels=labels, average="macro", zero_division=0),
        "report": rep, "confusion_matrix": confusion_matrix(d["label_key"], pred, labels=labels).tolist()}


def embed_all(enc, df, syn):
    X = enc.encode(list(df["text"]))
    Xs = enc.encode(list(syn["text"])) if syn is not None and len(syn) else None
    return X, Xs


def train_once(df, syn, X, Xs, labels, seed):
    """Train one head on a train/val/test split."""
    tr, va, te = split_dataset(df, seed=seed)
    Xtr, ytr = X[tr["_i"]], list(tr["label_key"])
    if Xs is not None:
        Xtr, ytr = np.vstack([Xtr, Xs]), ytr + list(syn["label_key"])
    clf = fit_head(Xtr, ytr)
    return clf, (tr, va, te)


# --------------------------------------------------------------------------- #
# Mode: head — frozen encoder + logistic-regression head
# --------------------------------------------------------------------------- #
class EmbedPredictor:
    """For the app: EmbedPredictor('bert/models/embed/action').predict(subject, body)
    -> (label, confidence)."""

    def __init__(self, model_dir):
        import joblib
        with open(os.path.join(model_dir, "manifest.json")) as f:
            self.manifest = json.load(f)
        self.head = joblib.load(os.path.join(model_dir, "head.joblib"))
        self.enc = FrozenEncoder(self.manifest["encoder"])

    def predict(self, subject, body, from_addr=""):
        X = self.enc.encode([build_text(subject, from_addr, body)])
        p = self.head.predict_proba(X)[0]
        return str(self.head.classes_[p.argmax()]), float(p.max())


def train_head_final(t, df, info, syn, syn_info, en, labels_all, digest, args):
    """Train a frozen-encoder head for a task."""
    import joblib
    labels = info["supported_labels"]
    df = df.reset_index(drop=True).assign(_i=lambda d: range(len(d)))
    enc = FrozenEncoder(en)
    X, Xs = embed_all(enc, df, syn)
    clf, (tr, va, te) = train_once(df, syn, X, Xs, labels, SEED)
    out = os.path.join(args.out_dir, f"{t}_head")
    os.makedirs(out, exist_ok=True)
    res = {}
    for name, d in [("validation", va), ("test", te)]:
        pred, conf, r = evaluate(clf, X[d["_i"]], d, labels)
        res[name] = r
        d.assign(pred=pred, confidence=conf)[
            ["review_id", "Subject", "From", "label_key", "pred", "confidence"]].to_csv(
            os.path.join(out, f"{'val' if name == 'validation' else 'test'}_predictions.csv"),
            index=False, encoding="utf-8-sig")
    # reported numbers use the 60% train split; for the app, refit head on train+val
    trva = pd.concat([tr, va])
    Xf, yf = X[trva["_i"]], list(trva["label_key"])
    if Xs is not None:
        Xf, yf = np.vstack([Xf, Xs]), yf + list(syn["label_key"])
    final = fit_head(Xf, yf)
    joblib.dump(final, os.path.join(out, "head.joblib"))
    model_id, prefix, pool = ENCODERS[en]
    manifest = {
        "task": t, "type": "frozen_encoder+logreg", "encoder": en, "encoder_model_id": model_id,
        "text_prefix": prefix, "pooling": pool, "normalize": True, "head_C": HEAD_C,
        "labels": list(final.classes_), "app_label_keys": labels_all,
        "rule_labels": info["rule_labels"], "sender_rules": info["sender_rules"],
        "input": {"format": "Subject: {subject}\\n{preview}", "strip_sender": STRIP_SENDER,
                  "max_len": MAX_LEN},
        "head_trained_on": "train+val (+synthetic)" if Xs is not None else "train+val",
        "n_head_rows": len(yf),
        "synthetic": ({"csv": os.path.basename(args.synthetic), **syn_info} if syn_info else None),
        "taxonomy_sha256_16": digest, "review_csv": os.path.basename(args.review), "seed": SEED,
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out, "metrics.json"), "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    r = res["test"]
    print(f"[{t}] {en} TEST acc={r['accuracy']:.4f} macro_f1={r['macro_f1']:.4f} -> {out}")
    return res


def head_compare(data, syn_data, encoders, seeds, out_dir):
    """Compare encoders on real vs real+synthetic, multiple seeds."""
    rows = []
    for t, (df, info) in data.items():
        labels = info["supported_labels"]
        df = df.reset_index(drop=True).assign(_i=lambda d: range(len(d)))
        syn = syn_data.get(t, (None, None))[0]
        for en in encoders:
            print(f"[{t}] embedding with {en} ...", flush=True)
            enc = FrozenEncoder(en)
            X, Xs = embed_all(enc, df, syn)
            conds = [("real", None)] + ([("real+syn", Xs)] if Xs is not None else [])
            for seed in seeds:
                for cname, xs in conds:
                    clf, (tr, va, te) = train_once(df, syn if xs is not None else None, X, xs,
                                                   labels, seed)
                    _, _, r = evaluate(clf, X[te["_i"]], te, labels)
                    row = {"task": t, "encoder": en, "condition": cname, "seed": seed,
                           "accuracy": r["accuracy"], "macro_f1": r["macro_f1"]}
                    for l in labels:
                        row["f1_" + l] = r["report"][l]["f1-score"]
                    rows.append(row)
    runs = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    runs.to_csv(os.path.join(out_dir, "compare_head_runs.csv"), index=False, encoding="utf-8-sig")
    lines = [f"seeds={seeds} | frozen encoder + logistic-regression head | test = real emails only"]
    for (t, en), g in runs.groupby(["task", "encoder"], sort=False):
        lines.append(f"\n[{t}] {en}")
        for c, gc in g.groupby("condition", sort=False):
            per = "  ".join(f"{k[3:]}={gc[k].mean():.2f}"
                            for k in gc.columns if k.startswith("f1_") and gc[k].notna().any())
            lines.append(f"  {c:<9} macro_f1 {gc.macro_f1.mean():.3f} +- "
                         f"{gc.macro_f1.std(ddof=1) if len(gc) > 1 else 0:.3f} | "
                         f"acc {gc.accuracy.mean():.3f} | F1 {per}")
        if g["condition"].nunique() == 2:
            p = g.pivot(index="seed", columns="condition", values="macro_f1")
            d = p["real+syn"] - p["real"]
            lines.append(f"  diff (syn - real) {d.mean():+.3f} +- "
                         f"{d.std(ddof=1) if len(d) > 1 else 0:.3f} | "
                         f"better {int((d > 0).sum())} / tie {int((d == 0).sum())} / "
                         f"worse {int((d < 0).sum())}")
    txt = "\n".join(lines)
    with open(os.path.join(out_dir, "compare_head_summary.txt"), "w") as f:
        f.write(txt + "\n")
    print("\n" + "=" * 70 + "\n" + txt + "\n" + "=" * 70 + f"\nsaved -> {out_dir}/compare_head_summary.txt")


# --------------------------------------------------------------------------- #
# Mode: full — full DistilBERT fine-tune
# --------------------------------------------------------------------------- #
def train_full_task(task, df, info, labels_all, tax_digest, args, syn=None, syn_info=None,
                    seed=SEED, out_dir=None, keep_model=True):
    """Fine-tune distilbert-base-uncased for a task."""
    import torch
    import shutil
    from datasets import Dataset
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              DataCollatorWithPadding, Trainer, TrainingArguments)

    random_seed = seed
    import random as _random
    _random.seed(random_seed); np.random.seed(random_seed); torch.manual_seed(random_seed)
    labels = info["supported_labels"]
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}
    train_df, val_df, test_df = split_dataset(df, seed=random_seed)
    n_train_real = len(train_df)
    if syn is not None and len(syn):
        syn = syn[syn["label_key"].isin(labels)]
        cols = ["review_id", "Subject", "From", "Preview", "label_key", "text"]
        train_df = pd.concat([train_df.assign(is_synthetic=False),
                              syn[cols].assign(is_synthetic=True)],
                             ignore_index=True).sample(frac=1, random_state=random_seed)
        train_df = train_df.reset_index(drop=True)
        print(f"[{task}] + {len(syn)} synthetic rows in TRAIN only (val/test stay real)")
    for d in (train_df, val_df, test_df):
        d["label"] = d["label_key"].map(label2id)
    print(f"\n[{task}] train/val/test = {len(train_df)}/{len(val_df)}/{len(test_df)} | labels={labels}")

    tok = AutoTokenizer.from_pretrained(args.model)

    def enc(b):
        return tok(b["text"], truncation=True, max_length=MAX_LEN)

    def ds(d):
        x = Dataset.from_pandas(d[["text", "label"]]).map(enc, batched=True)
        x.set_format("torch", columns=["input_ids", "attention_mask", "label"])
        return x

    train_ds, val_ds, test_ds = ds(train_df), ds(val_df), ds(test_ds)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(labels), id2label=id2label, label2id=label2id)

    counts = train_df["label"].value_counts().reindex(range(len(labels)), fill_value=0)
    cw = torch.tensor((len(train_df) / (len(labels) * counts.clip(lower=1))).values,
                      dtype=torch.float32)

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            y = inputs.pop("labels")
            out = model(**inputs)
            loss = torch.nn.CrossEntropyLoss(weight=cw.to(out.logits.device))(out.logits, y)
            return (loss, out) if return_outputs else loss

    def metrics(p):
        pred = np.argmax(p.predictions, -1)
        return {"accuracy": accuracy_score(p.label_ids, pred),
                "macro_f1": f1_score(p.label_ids, pred, average="macro", zero_division=0)}

    out_dir = out_dir or os.path.join(args.out_dir, f"{task}_full")
    steps_per_epoch = -(-len(train_df) // BATCH_SIZE)
    warmup_steps = int(WARMUP_RATIO * steps_per_epoch * args.epochs)
    targs = dict(output_dir=os.path.join(out_dir, "checkpoints"), num_train_epochs=args.epochs,
                 learning_rate=args.lr, per_device_train_batch_size=BATCH_SIZE,
                 per_device_eval_batch_size=BATCH_SIZE, warmup_steps=warmup_steps,
                 weight_decay=WEIGHT_DECAY, save_strategy="epoch", save_total_limit=1,
                 load_best_model_at_end=True, metric_for_best_model="macro_f1",
                 greater_is_better=True, logging_steps=5, seed=random_seed, report_to=[])
    try:
        targs_obj = TrainingArguments(eval_strategy="epoch", **targs)
    except TypeError:  # transformers < 4.41
        targs_obj = TrainingArguments(evaluation_strategy="epoch", **targs)
    trainer = WeightedTrainer(model=model, args=targs_obj, train_dataset=train_ds,
                              eval_dataset=val_ds, data_collator=DataCollatorWithPadding(tok),
                              compute_metrics=metrics)
    trainer.train()
    trainer.save_model(out_dir)
    tok.save_pretrained(out_dir)

    def evaluate(d, x, name):
        p = trainer.predict(x)
        probs = torch.softmax(torch.from_numpy(p.predictions), -1).numpy()
        pred = probs.argmax(-1)
        d = d.copy()
        d["pred"] = [id2label[i] for i in pred]
        d["confidence"] = probs.max(-1)
        rep = classification_report(d["label_key"], d["pred"], labels=labels,
                                    output_dict=True, zero_division=0)
        cm = confusion_matrix(d["label_key"], d["pred"], labels=labels).tolist()
        d[["review_id", "Subject", "From", "label_key", "pred", "confidence"]].to_csv(
            os.path.join(out_dir, f"{name}_predictions.csv"), index=False, encoding="utf-8-sig")
        return {"n": len(d),
                "accuracy": accuracy_score(d["label_key"], d["pred"]),
                "macro_f1": f1_score(d["label_key"], d["pred"], labels=labels,
                                     average="macro", zero_division=0),
                "report": rep, "confusion_matrix": cm}

    best_epoch = None
    hist = [h for h in trainer.state.log_history if "eval_macro_f1" in h]
    if hist:
        best_epoch = max(hist, key=lambda h: h["eval_macro_f1"])["epoch"]
    res = {"validation": evaluate(val_df, val_ds, "val"), "test": evaluate(test_df, test_ds, "test"),
           "best_epoch_on_val": best_epoch, "val_history": hist}
    manifest = {
        "task": task, "base_model": args.model, "app_label_keys": labels_all,
        "supported_labels": labels, "unsupported_labels": info["unsupported_labels"],
        "rule_labels": info["rule_labels"], "sender_rules": info["sender_rules"],
        "rule_rows_excluded": info["rule_rows_excluded"],
        "provisional": bool(info["unsupported_labels"]) or args.provisional,
        "id2label": id2label, "taxonomy_sha256_16": tax_digest,
        "input": {"format": "Subject: {subject}\\n{preview}", "strip_sender": STRIP_SENDER,
                  "max_len": MAX_LEN},
        "split_sizes": {"train": len(train_df), "train_real": n_train_real,
                        "train_synthetic": len(train_df) - n_train_real,
                        "val": len(val_df), "test": len(test_df)},
        "synthetic": ({"csv": os.path.basename(args.synthetic), **syn_info} if syn_info else None),
        "label_counts_total": info["counts"], "duplicates_removed": info["duplicates_removed"],
        "class_weight": {labels[i]: round(float(w), 4) for i, w in enumerate(cw)},
        "epochs": args.epochs, "lr": args.lr, "seed": random_seed,
        "review_csv": os.path.basename(args.review),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    shutil.rmtree(os.path.join(out_dir, "checkpoints"), ignore_errors=True)
    if not keep_model:  # comparison runs: keep only metrics/predictions (*.json, *.csv)
        for fn in os.listdir(out_dir):
            p = os.path.join(out_dir, fn)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif not fn.endswith((".json", ".csv")):
                os.remove(p)
    t = res["test"]
    print(f"[{task}] TEST acc={t['accuracy']:.4f} macro_f1={t['macro_f1']:.4f} -> {out_dir}")
    return res


def tfidf_run(df, labels, seed, syn=None):
    """Cheap reference: TF-IDF + logistic regression on the same split."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    tr, _, te = split_dataset(df, seed=seed)
    if syn is not None and len(syn):
        tr = pd.concat([tr, syn[syn["label_key"].isin(labels)]], ignore_index=True)
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced").fit(
        vec.fit_transform(tr["text"]), tr["label_key"])
    pred = clf.predict(vec.transform(te["text"]))
    rep = classification_report(te["label_key"], pred, labels=labels,
                                output_dict=True, zero_division=0)
    return {"n": len(te), "accuracy": accuracy_score(te["label_key"], pred),
            "macro_f1": f1_score(te["label_key"], pred, labels=labels,
                                 average="macro", zero_division=0), "report": rep}


def info_labels(g):
    return [c[3:] for c in g.columns if c.startswith("f1_") and g[c].notna().any()]


def _row(task, seed, model, cond, r, labels):
    row = {"task": task, "seed": seed, "model": model, "condition": cond, "n_test": r["n"],
           "accuracy": r["accuracy"], "macro_f1": r["macro_f1"]}
    for l in labels:
        row["f1_" + l] = r["report"].get(l, {}).get("f1-score", np.nan)
    return row


def full_compare_seeds(data, syn_data, labels_tax, digest, args, seeds):
    """Train real-only vs real+synthetic on several splits; report mean +- sd and paired differences."""
    base = args.compare_dir
    os.makedirs(base, exist_ok=True)
    rows = []
    for t, (df, info) in data.items():
        syn, syn_info = syn_data.get(t, (None, None))
        conds = [("real", None, None)] + ([("real+syn", syn, syn_info)] if syn is not None else [])
        labels = info["supported_labels"]
        for seed in seeds:
            for cname, s, si in conds:
                if not args.tfidf_only:
                    print(f"\n===== [{t}] seed={seed} condition={cname} (BERT) =====")
                    r = train_full_task(t, df, info, labels_tax[t], digest, args, s, si,
                                        seed=seed, keep_model=False)["test"]
                    rows.append(_row(t, seed, "bert", cname, r, labels))
                r = tfidf_run(df, labels, seed, s)
                rows.append(_row(t, seed, "tfidf", cname, r, labels))
    runs = pd.DataFrame(rows)
    runs.to_csv(os.path.join(base, "compare_full_runs.csv"), index=False, encoding="utf-8-sig")
    metric_cols = [c for c in runs.columns if c not in ("task", "seed", "model", "condition", "n_test")]
    summ = runs.groupby(["task", "model", "condition"])[metric_cols].agg(["mean", "std"]).round(3)
    summ.to_csv(os.path.join(base, "compare_full_summary.csv"), encoding="utf-8-sig")
    lines = [f"seeds={seeds}  (same seed -> same real train/val/test split for both conditions; "
             f"test is always real)"]
    for (t, m), g in runs.groupby(["task", "model"]):
        lines.append(f"\n[{t}] {m.upper()}")
        for c, gc in g.groupby("condition"):
            f = gc["macro_f1"]; a = gc["accuracy"]
            per = "  ".join(f"{l}={gc['f1_' + l].mean():.2f}" for l in info_labels(gc))
            lines.append(f"  {c:<9} macro_f1 {f.mean():.3f} +- "
                         f"{f.std(ddof=1) if len(f) > 1 else 0:.3f} | "
                         f"acc {a.mean():.3f} +- {a.std(ddof=1) if len(a) > 1 else 0:.3f} | F1 {per}")
        if g["condition"].nunique() == 2:
            p = g.pivot(index="seed", columns="condition", values="macro_f1")
            d = p["real+syn"] - p["real"]
            lines.append(f"  diff (syn - real) macro_f1 {d.mean():+.3f} +- "
                         f"{d.std(ddof=1) if len(d) > 1 else 0:.3f} | "
                         f"better {int((d > 0).sum())} / tie {int((d == 0).sum())} / "
                         f"worse {int((d < 0).sum())} of {len(d)}")
    txt = "\n".join(lines)
    with open(os.path.join(base, "compare_full_summary.txt"), "w") as f:
        f.write(txt + "\n")
    print("\n" + "=" * 70 + "\n" + txt + "\n" + "=" * 70)
    print(f"saved -> {base}/compare_full_summary.txt, compare_full_summary.csv, compare_full_runs.csv")
