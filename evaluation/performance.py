"""Benchmark the deployed email-sorter backends.

Measures warm latency, peak memory, token use and invalid-format rate.

Four methods can be compared in one table:
    llama  - Ollama LLM (email-sorter)
    bert   - frozen text-encoder heads (email-sorter)
    ml     - classical TF-IDF pipelines (email-sorter)
    claude - Anthropic Claude API through the inbox-sorter pipeline

Usage:
    python evaluation/performance.py
    python evaluation/performance.py --model bert ml
    python evaluation/performance.py --model all
    python evaluation/performance.py --model llm --limit 20
"""

import argparse
import gc
import json
import statistics
import sys
import threading
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
EMAIL_DIR = REPO_ROOT / "email-sorter"
ENCODERS_DIR = REPO_ROOT / "text-encoders"
for _path in (REPO_ROOT, EMAIL_DIR, ENCODERS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.config import settings  # noqa: E402
from app.models import Email  # noqa: E402
from app.taxonomy import CONTENT_CATEGORIES, REPLY_NATURE  # noqa: E402
from evaluation import (  # noqa: E402
    display_path,
    package_version,
    write_csv,
    write_json,
)
from src.data import MAX_LEN, build_text, load_review, load_taxonomy, task_dataset  # noqa: E402

DEFAULT_REVIEW = REPO_ROOT / "data" / "labels.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results"

# Every method the benchmark can compare, in report order.
ALL_MODELS = ["llama", "bert", "ml", "claude"]
# Backends whose output is a free-form JSON answer that can fail validation.
JSON_BACKENDS = {"llama", "claude"}

try:
    import psutil
except ImportError:  # pragma: no cover - optional
    psutil = None


# Arguments and data
def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--review", default=str(DEFAULT_REVIEW), help="shared labels CSV")
    ap.add_argument(
        "--model",
        nargs="+",
        choices=["bert", "ml", "llm", "claude", "all"],
        help="one or more models to benchmark (default: llm bert)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=30,
        help="sample size; 0 = all usable emails",
    )
    ap.add_argument(
        "--claude-limit",
        type=int,
        default=0,
        help="max emails for the Claude backend; 0 = use the full sample (API calls cost money)",
    )
    ap.add_argument("--runs", type=int, default=5, help="calls per email")
    ap.add_argument("--warmup", type=int, default=2, help="warm-up calls (not measured)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    return ap.parse_args(argv)


def selected_models(args: argparse.Namespace) -> list[str]:
    if args.model:
        selected = []
        for value in args.model:
            selected.extend(ALL_MODELS if value == "all" else [value])
    else:
        selected = ["llm", "bert"]

    if len(set(selected)) != len(selected):
        raise SystemExit("--model values must not be repeated.")
    return selected


def load_benchmark_rows(args: argparse.Namespace) -> tuple:
    labels, tax_digest = load_taxonomy()
    review = load_review(args.review)
    df, _ = task_dataset(review, "action", labels["action"], False)
    df = df.copy()
    total = len(df)

    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.limit and args.limit < total:
        n_classes = df["label_key"].nunique()
        if args.limit < n_classes:
            raise SystemExit(f"--limit must be 0 or at least {n_classes}")
        from sklearn.model_selection import train_test_split

        sample, _ = train_test_split(
            df,
            train_size=args.limit,
            stratify=df["label_key"],
            random_state=args.seed,
        )
        df = sample
    df = df.sample(frac=1, random_state=args.seed).reset_index(drop=True)
    if df.empty:
        raise SystemExit("No benchmark rows selected")
    if args.warmup > len(df):
        raise SystemExit(f"--warmup {args.warmup} > sample size {len(df)}")

    meta = {
        "total_rows": total,
        "sample_n": len(df),
        "sample_action_counts": {
            str(k): int(v) for k, v in df["label_key"].value_counts().items()
        },
        "taxonomy_sha256_16": tax_digest,
        "sample_review_ids": df["review_id"].tolist(),
    }
    return df, meta


def email_for(row: pd.Series, text: str) -> Email:
    return Email(
        id=str(row["review_id"]),
        subject=str(row.get("Subject", "")),
        sender=str(row.get("From", "")),
        received=str(row.get("Received DateTime", "")),
        preview=text,
        body=text,
    )


# Memory
class MemorySampler:
    """Sample benchmark-process RSS and (optionally) Ollama server RSS."""

    def __init__(self, include_ollama: bool, enabled: bool = True):
        self.include_ollama = include_ollama
        self.enabled = enabled and psutil is not None
        self._stop = threading.Event()
        self._thread = None
        self._process = psutil.Process() if self.enabled else None
        self.baseline = 0
        self.peak = 0
        self.ollama_baseline = 0
        self.ollama_peak = 0

    def _rss(self) -> int:
        try:
            return int(self._process.memory_info().rss)
        except Exception:
            return 0

    def _ollama_rss(self) -> int:
        if not self.include_ollama or psutil is None:
            return 0
        total = 0
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                exe = Path(cmdline[0]).name.lower() if cmdline else ""
                if (
                    "ollama" in name
                    or "llama-server" in name
                    or "ollama" in exe
                    or "llama-server" in exe
                ):
                    total += int(proc.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue
        return total

    def start(self) -> None:
        if not self.enabled:
            return
        self.baseline = self._rss()
        self.ollama_baseline = self._ollama_rss()
        self.peak = self.baseline
        self.ollama_peak = self.ollama_baseline
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(0.15):
            self.peak = max(self.peak, self._rss())
            if self.include_ollama:
                self.ollama_peak = max(self.ollama_peak, self._ollama_rss())

    def stop(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.peak = max(self.peak, self._rss())
        if self.include_ollama:
            self.ollama_peak = max(self.ollama_peak, self._ollama_rss())
        mb = 1024 * 1024
        return {
            "enabled": True,
            "baseline_mb": self.baseline / mb,
            "peak_mb": self.peak / mb,
            "delta_mb": (self.peak - self.baseline) / mb,
            "ollama_baseline_mb": (
                self.ollama_baseline / mb if self.include_ollama else None
            ),
            "ollama_peak_mb": self.ollama_peak / mb if self.include_ollama else None,
            "peak_total_mb": (self.peak + self.ollama_peak) / mb,
        }


# Backends
@dataclass
class Prediction:
    category: str
    action: str
    raw_valid: bool | None = None
    invalid_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_excerpt: str = ""


@dataclass
class CallRecord:
    backend: str
    review_id: str
    phase: str
    run: int
    latency_ms: float
    category: str
    action: str
    raw_valid: bool | None
    invalid_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    true_action: str
    true_category: str
    raw_excerpt: str


def _norm_label(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _llama_raw_status(result: dict) -> tuple:
    raw = result.get("raw")
    parsed = result.get("parsed")
    err = result.get("parsing_error")
    content = getattr(raw, "content", "") if raw is not None else ""
    excerpt = str(content)[:500].replace("\n", "\\n")

    if err is not None:
        return False, f"parsing_error: {str(err)[:200]}", excerpt
    if parsed is None:
        return False, "parsed_none", excerpt
    if not isinstance(content, str) or not content.strip():
        return False, "empty_raw", excerpt
    try:
        data = json.loads(content)
    except Exception:
        return False, "raw_not_json", excerpt
    if not isinstance(data, dict):
        return False, "raw_not_object", excerpt

    category = _norm_label(data.get("content_category"))
    action = _norm_label(data.get("reply_nature"))
    if category not in CONTENT_CATEGORIES:
        return False, f"invalid_category:{category or '<missing>'}", excerpt
    if action not in REPLY_NATURE:
        return False, f"invalid_action:{action or '<missing>'}", excerpt
    return True, None, excerpt


class LlamaBackend:
    name = "llama"

    def __init__(self) -> None:
        from app.llama_classifier import build_chain

        self.chain = build_chain(include_raw=True)

    def predict(self, email: Email) -> Prediction:
        result = self.chain.invoke(
            {
                "sender": email.sender,
                "subject": email.subject,
                "received": email.received,
                "body": email.body[: settings.body_char_limit] or email.preview,
            }
        )
        parsed = result.get("parsed")
        if parsed is None:
            category, action = "__invalid__", "__invalid__"
        elif hasattr(parsed, "content_category"):
            category = str(parsed.content_category)
            action = str(parsed.reply_nature)
        elif isinstance(parsed, dict):
            category = str(parsed.get("content_category", "__invalid__"))
            action = str(parsed.get("reply_nature", "__invalid__"))
        else:
            category, action = "__invalid__", "__invalid__"

        valid, reason, excerpt = _llama_raw_status(result)
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        meta = getattr(raw, "response_metadata", None) or {}
        input_tokens = usage.get("input_tokens") or meta.get("prompt_eval_count")
        output_tokens = usage.get("output_tokens") or meta.get("eval_count")
        return Prediction(
            category=category,
            action=action,
            raw_valid=valid,
            invalid_reason=reason,
            input_tokens=int(input_tokens) if input_tokens is not None else None,
            output_tokens=int(output_tokens) if output_tokens is not None else None,
            raw_excerpt=excerpt,
        )

    def token_usage(self, email: Email, pred: Prediction) -> tuple:
        return pred.input_tokens, pred.output_tokens

    def model_info(self) -> dict:
        return {"model": settings.ollama_model}


class BertBackend:
    name = "bert"

    def __init__(self) -> None:
        from app.bert_classifier import BertClassifier

        self.clf = BertClassifier()
        if not self.clf.available:
            raise RuntimeError("BERT models are not available")

    def predict(self, email: Email) -> Prediction:
        result = self.clf.classify(email)
        return Prediction(
            category=result.content_category,
            action=result.reply_nature,
            raw_valid=None,
            invalid_reason=None,
            output_tokens=0,
        )

    def _count_tokens(self, predictor, email: Email) -> int:
        if predictor is None:
            return 0
        from app.bert_classifier import _model_text

        text = predictor.enc.prefix + build_text(
            email.subject, email.sender, _model_text(email)
        )
        ids = predictor.enc.tok(
            text, truncation=True, max_length=MAX_LEN
        )["input_ids"]
        return len(ids)

    def token_usage(self, email: Email, pred: Prediction) -> tuple:
        from app.rules import category_by_rule

        category_tokens = 0
        if not category_by_rule(email.sender):
            category_tokens = self._count_tokens(self.clf._category_clf, email)
        action_tokens = self._count_tokens(self.clf._action_clf, email)
        return category_tokens + action_tokens, 0

    def model_info(self) -> dict:
        return {"model": "bge-small-en + e5-small-multi"}


class MLBackend:
    name = "ml"

    def __init__(self) -> None:
        from app.ml_classifier import MLClassifier

        self.clf = MLClassifier()

    def predict(self, email: Email) -> Prediction:
        result = self.clf.classify(email)
        return Prediction(
            category=result.content_category,
            action=result.reply_nature,
            raw_valid=None,
            invalid_reason=None,
            output_tokens=0,
        )

    def token_usage(self, email: Email, pred: Prediction) -> tuple:
        return None, 0

    def model_info(self) -> dict:
        return {"model": "TF-IDF LinearSVC + ComplementNB"}


class ClaudeBackend:
    """Anthropic Claude through the inbox-sorter pipeline.

    The inbox-sorter owns the taxonomy, the sender rules and the guardrails;
    the adapter only maps its labels onto the email-sorter taxonomy so the
    four methods can be compared in one table.
    """

    name = "claude"

    def __init__(self) -> None:
        from evaluation.inbox_sorter import InboxSorterBackend

        self.inner = InboxSorterBackend()

    def predict(self, email: Email) -> Prediction:
        result = self.inner.predict(email)
        return Prediction(
            category=result.category,
            action=result.action,
            raw_valid=result.raw_valid,
            invalid_reason=result.invalid_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            raw_excerpt=result.raw_excerpt,
        )

    def token_usage(self, email: Email, pred: Prediction) -> tuple:
        return pred.input_tokens, pred.output_tokens

    def backend_notes(self) -> list[str]:
        """Warnings about labels that could not be mapped (renamed in config.yaml)."""
        return list(getattr(self.inner, "mapping_notes", []))

    def check_health(self) -> None:
        """Abort the run when the API call itself failed (key, quota, network)."""
        classifier = self.inner.clf
        if getattr(classifier, "api_failed", False):
            raise RuntimeError(
                f"Claude API call failed: {getattr(classifier, 'last_error', 'unknown error')}"
            )

    def model_info(self) -> dict:
        return {"model": f"claude ({self.inner.model_name})"}


def make_backend(
    name: str,
) -> LlamaBackend | BertBackend | MLBackend | ClaudeBackend:
    if name == "llama":
        return LlamaBackend()
    if name == "bert":
        return BertBackend()
    if name == "ml":
        return MLBackend()
    if name == "claude":
        return ClaudeBackend()
    raise ValueError(f"unknown backend: {name}")


def _claude_model_name() -> str | None:
    """Read the inbox-sorter's Claude model name without calling the API."""
    try:
        from evaluation.inbox_sorter import load_inbox_modules

        modules = load_inbox_modules()
        classifier = modules.llm.ClaudeClassifier(modules.config.get_config())
        return classifier.model or None
    except Exception:
        return None


def _claude_input_cap() -> int | None:
    """The inbox-sorter's per-email character cap for the text sent to Claude."""
    try:
        from evaluation.inbox_sorter import load_inbox_modules

        modules = load_inbox_modules()
        cfg = modules.config.get_config()
        return int((cfg.get("preprocess") or {}).get("max_chars", 4000))
    except Exception:
        return None


# Running and stats
def _timed_predict(
    backend: LlamaBackend | BertBackend | MLBackend | ClaudeBackend, email: Email
) -> tuple:
    start = time.perf_counter()
    pred = backend.predict(email)
    return pred, (time.perf_counter() - start) * 1000


def _call(backend, name, row, phase, run, text) -> CallRecord:
    email = email_for(row, text)
    pred, latency = _timed_predict(backend, email)
    pred.input_tokens, pred.output_tokens = backend.token_usage(email, pred)
    return _record(name, row, pred, latency, phase, run)


def _record(backend, row, pred, latency_ms, phase, run) -> CallRecord:
    return CallRecord(
        backend=backend,
        review_id=str(row["review_id"]),
        phase=phase,
        run=run,
        latency_ms=latency_ms,
        category=pred.category,
        action=pred.action,
        raw_valid=pred.raw_valid,
        invalid_reason=pred.invalid_reason,
        input_tokens=pred.input_tokens,
        output_tokens=pred.output_tokens,
        true_action=str(row["label_key"]),
        true_category=str(row.get("category", "")),
        raw_excerpt=pred.raw_excerpt,
    )


def run_backend(name: str, rows: pd.DataFrame, args: argparse.Namespace) -> tuple:
    records = []
    sampler = MemorySampler(include_ollama=(name == "llama"))
    backend = None
    error = None

    gc.collect()
    sampler.start()
    try:
        backend = make_backend(name)

        for _, row in rows.head(args.warmup).iterrows():
            text = str(row.get("Preview", ""))
            records.append(_call(backend, name, row, "warmup", 0, text))
        if records and hasattr(backend, "check_health"):
            backend.check_health()

        for run in range(1, args.runs + 1):
            print(f"[{name}] run {run}/{args.runs} ({len(rows)} emails) ...", flush=True)
            for _, row in rows.iterrows():
                text = str(row.get("Preview", ""))
                records.append(_call(backend, name, row, "main", run, text))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[{name}] benchmark failed: {error}")
        traceback.print_exc()
    finally:
        memory = sampler.stop()

    summary = _summarise(
        name=name,
        backend=backend,
        rows=rows,
        records=records,
        memory=memory,
        error=error,
        args=args,
    )
    return summary, records


def _pct(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def _mean(values: list[float]) -> float | None:
    return float(statistics.fmean(values)) if values else None


def _summarise(
    *,
    name,
    backend,
    rows,
    records,
    memory,
    error,
    args,
) -> dict:
    main = [r for r in records if r.phase == "main"]
    latencies = [r.latency_ms for r in main]
    warm_p50 = _pct(latencies, 50)

    input_tokens = [r.input_tokens for r in main if r.input_tokens is not None]
    output_tokens = [r.output_tokens for r in main if r.output_tokens is not None]

    invalid = [r for r in main if r.raw_valid is False]
    checks_format = name in JSON_BACKENDS
    invalid_rate = len(invalid) / len(main) if main and checks_format else None
    reasons = Counter(r.invalid_reason or "unknown" for r in invalid)

    model_info = backend.model_info() if backend is not None else {}
    notes = []
    if error:
        notes.append(f"error: {error}")
    if name == "llama":
        notes.append("invalid rate uses raw JSON/labels before Pydantic coercion")
    elif name == "bert":
        notes.append("constructor loads both encoders and heads")
    elif name == "claude":
        notes.append("inbox-sorter pipeline: sender rules -> Claude API -> guardrails")
        notes.append("remote API: latency includes network round-trips")
        notes.append("invalid rate uses the raw JSON before label validation")
    else:
        notes.append("constructor loads both classical ML pipelines")
    if backend is not None and hasattr(backend, "backend_notes"):
        notes.extend(backend.backend_notes())
    if reasons:
        notes.append(
            "invalid reasons: "
            + "; ".join(f"{k}={v}" for k, v in reasons.most_common(5))
        )

    return {
        "backend": name,
        "error": error,
        "model": model_info.get("model", ""),
        "sample_n": len(rows),
        "runs": args.runs,
        "warm_p50_ms": warm_p50,
        "peak_total_mb": memory.get("peak_total_mb"),
        "input_tokens_mean": _mean(input_tokens),
        "output_tokens_mean": _mean(output_tokens),
        "invalid_format_rate": invalid_rate,
        "notes": "; ".join(notes),
    }


# Output
def render_report(summary: pd.DataFrame, manifest: dict) -> str:
    def fmt(value, digits: int = 1) -> str:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "—"
        if isinstance(value, (int, np.integer)):
            return str(value)
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.{digits}f}"
        return str(value)

    lines = [
        "Operational performance — email-sorter backends",
        f"Sample: {manifest['sample_n']} of {manifest['total_rows']} action-usable emails "
        f"| runs/email: {manifest['runs']} | seed: {manifest['seed']}",
        f"Input: body/Preview (Llama cap {manifest['body_char_limit']} chars)",
        "",
    ]
    header = (
        f"{'Backend':<8} {'N':>3} {'Warm p50 ms':>12} {'Peak MB':>8} "
        f"{'In tok':>7} {'Out tok':>7} {'Invalid':>7}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for _, row in summary.iterrows():
        error = row.get("error")
        if isinstance(error, str) and error:
            lines.append(f"{row['backend']:<8} ERROR: {error}")
            continue
        lines.append(
            f"{row['backend']:<8} {int(row['sample_n']):>3} "
            f"{fmt(row['warm_p50_ms']):>12} {fmt(row['peak_total_mb']):>8} "
            f"{fmt(row['input_tokens_mean']):>7} {fmt(row['output_tokens_mean']):>7} "
            f"{fmt(row['invalid_format_rate'], 3):>7}"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- Warm latency excludes warm-up calls.",
            "- Peak MB is benchmark process + Ollama server RSS (Llama).",
            "- Llama tokens include the system prompt; encoder tokens are head inputs; ML has no tokens.",
            "- Invalid-format checks apply to Llama's and Claude's raw JSON output.",
            "- This is an operational benchmark, not the offline quality evaluation.",
        ]
    )
    if manifest.get("sample_action_counts"):
        lines.append(f"- Sample action counts: {manifest['sample_action_counts']}")
    subsets = [
        f"{row['backend']}={int(row['sample_n'])}"
        for _, row in summary.iterrows()
        if int(row.get("sample_n") or 0) != int(manifest.get("sample_n") or 0)
    ]
    if subsets:
        lines.append(
            f"- Backends benchmarked on a smaller sample: {', '.join(subsets)}"
        )
    return "\n".join(lines) + "\n"


def write_artifacts(
    out_dir: Path, summary: pd.DataFrame, runs: pd.DataFrame, manifest: dict
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(summary, out_dir / "operational_performance_summary.csv")
    write_csv(runs, out_dir / "operational_performance_runs.csv")
    plot_operational_performance(
        summary, out_dir / "operational_performance_comparison.png"
    )
    write_json(manifest, out_dir / "operational_performance_manifest.json")
    report = render_report(summary, manifest)
    print("\n" + "=" * 100)
    print(report)
    print("=" * 100)
    print(f"Saved artifacts -> {out_dir}")


def plot_operational_performance(summary: pd.DataFrame, path: Path) -> None:
    """Plot warm latency and peak memory for successful model runs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    successful = summary[
        summary["error"].fillna("").astype(str).eq("")
    ].reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    if successful.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No successful model runs", ha="center", va="center")
            ax.set_axis_off()
    else:
        labels = {
            "bert": "Text encoder",
            "ml": "Classical ML",
            "llama": "Llama",
            "claude": "Claude (API)",
        }
        model_names = [
            labels.get(str(name), str(name)) for name in successful["backend"]
        ]
        positions = np.arange(len(successful), dtype=float)
        for ax, column, title, ylabel in (
            (axes[0], "warm_p50_ms", "Warm latency", "Milliseconds"),
            (axes[1], "peak_total_mb", "Peak memory", "Megabytes"),
        ):
            values = pd.to_numeric(successful[column], errors="coerce").to_numpy()
            valid = np.isfinite(values)
            if valid.any():
                ax.bar(positions[valid], values[valid], 0.55)
            else:
                ax.text(
                    0.5, 0.5, "Measurement unavailable",
                    ha="center", va="center", transform=ax.transAxes,
                )
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.set_xticks(positions)
            ax.set_xticklabels(model_names, rotation=15, ha="right")
            ax.grid(axis="y", alpha=0.25)
            ax.set_axisbelow(True)

    fig.suptitle("Operational performance comparison")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")
    if args.claude_limit < 0:
        raise SystemExit("--claude-limit must be >= 0")

    rows, meta = load_benchmark_rows(args)
    models = selected_models(args)
    backends = ["llama" if model == "llm" else model for model in models]
    print(
        f"Benchmarking {len(rows)} emails x {args.runs} runs "
        f"({', '.join(backends)}) | counts={meta['sample_action_counts']}"
    )
    if "claude" in backends:
        calls = len(rows) * (args.runs + args.warmup)
        print(
            f"[claude] about {calls} Anthropic API calls "
            f"({args.runs} runs + {args.warmup} warm-up per email); "
            "use --claude-limit to cap the sample."
        )

    summary_rows = []
    all_records = []
    for name in backends:
        print(f"\n=== {name} ===", flush=True)
        backend_rows = rows
        if name == "claude" and args.claude_limit:
            backend_rows = rows.head(args.claude_limit)
            print(
                f"[claude] benchmarking {len(backend_rows)} of {len(rows)} emails "
                "(API calls are capped for cost)",
                flush=True,
            )
        summary, records = run_backend(name, backend_rows, args)
        summary_rows.append(summary)
        all_records.extend(records)
        if summary.get("error"):
            print(f"[{name}] ERROR: {summary['error']}")
        else:
            peak = summary.get("peak_total_mb")
            peak_s = f"{peak:.1f}" if peak is not None else "n/a"
            p50 = summary["warm_p50_ms"]
            p50_s = f"{p50:.1f}" if p50 is not None else "n/a"
            print(f"[{name}] warm p50={p50_s} ms peak={peak_s} MB")

    summary = pd.DataFrame(summary_rows)
    runs = pd.DataFrame([r.__dict__ for r in all_records])
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_file": display_path(args.review, REPO_ROOT),
        "model": models,
        "limit": args.limit,
        "claude_limit": args.claude_limit,
        "total_rows": meta["total_rows"],
        "sample_n": meta["sample_n"],
        "sample_action_counts": meta["sample_action_counts"],
        "sample_review_ids": meta["sample_review_ids"],
        "runs": args.runs,
        "warmup": args.warmup,
        "seed": args.seed,
        "body_char_limit": settings.body_char_limit,
        "ollama_model": settings.ollama_model,
        "taxonomy_sha256_16": meta["taxonomy_sha256_16"],
        "input_protocol": {
            "full": "body/Preview; Llama truncated to body_char_limit, BERT to MAX_LEN tokens",
        },
        "versions": {
            pkg: package_version(pkg)
            for pkg in (
                "numpy",
                "pandas",
                "scikit-learn",
                "torch",
                "transformers",
                "langchain-core",
                "langchain-ollama",
                "psutil",
                "anthropic",
            )
        },
    }
    if "claude" in backends:
        manifest["claude_model"] = _claude_model_name()
        cap = _claude_input_cap()
        manifest["input_protocol"]["claude"] = (
            "inbox-sorter pipeline text: 'Subject: ...' + body, "
            f"capped at {cap} chars"
            if cap
            else "inbox-sorter pipeline text"
        )
    write_artifacts(Path(args.out_dir), summary, runs, manifest)


if __name__ == "__main__":
    main()
