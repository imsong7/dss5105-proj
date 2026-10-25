"""Benchmark the deployed email-sorter backends.

Measures load/cold/warm latency, peak memory, model size, token use, energy,
invalid-format rate, 5-run consistency, and short/full agreement.

Usage:
    python evaluation/operational_performance.py
    python evaluation/operational_performance.py --backend llama --limit 20
    python evaluation/operational_performance.py --no-energy --no-memory
"""

import argparse
import gc
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
EMAIL_DIR = REPO_ROOT / "email-sorter"
BERT_DIR = REPO_ROOT / "bert"
for _path in (REPO_ROOT, EMAIL_DIR, BERT_DIR):
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
from src.data import MAX_LEN, build_text, load_taxonomy, task_dataset  # noqa: E402

DEFAULT_REVIEW = BERT_DIR / "data" / "labels.csv"
DEFAULT_OUT = REPO_ROOT / "evaluation" / "results"

try:
    import psutil
except ImportError:  # pragma: no cover - optional
    psutil = None


# Arguments and data
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--review", default=str(DEFAULT_REVIEW), help="review CSV")
    ap.add_argument(
        "--backend",
        choices=["both", "llama", "bert"],
        default="both",
        help="backend(s)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=30,
        help="sample size; 0 = all usable emails",
    )
    ap.add_argument("--runs", type=int, default=5, help="calls per email")
    ap.add_argument("--warmup", type=int, default=2, help="warm-up calls (not measured)")
    ap.add_argument("--short-chars", type=int, default=200, help="short-input characters")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--country", default="SGP", help="CodeCarbon country code")
    ap.add_argument(
        "--unload-ollama",
        action="store_true",
        help="unload Ollama first so the cold call includes model load",
    )
    ap.add_argument("--no-energy", action="store_true", help="disable energy tracking")
    ap.add_argument("--no-memory", action="store_true", help="disable memory sampling")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    return ap.parse_args()


def load_benchmark_rows(args: argparse.Namespace) -> tuple:
    labels, tax_digest = load_taxonomy()
    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
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


# Memory and energy
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


class EnergyMeter:
    """Optional CodeCarbon wrapper. The tracker is machine-wide."""

    def __init__(self, country: str, enabled: bool = True):
        self.enabled = enabled
        self.country = country
        self.tracker = None
        self.error = None
        if not enabled:
            return
        try:
            from codecarbon import OfflineEmissionsTracker

            self.tracker = OfflineEmissionsTracker(
                project_name="email-sorter-operational",
                country_iso_code=country,
                measure_power_secs=1,
                save_to_file=False,
                log_level="error",
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            self.error = f"{type(exc).__name__}: {exc}"

    def start(self) -> None:
        if self.tracker is None:
            return
        try:
            self.tracker.start()
        except Exception as exc:  # pragma: no cover
            self.error = f"{type(exc).__name__}: {exc}"
            self.tracker = None

    def stop(self) -> dict:
        if self.tracker is None:
            return {"enabled": False, "error": self.error}
        try:
            self.tracker.stop()
            data = getattr(self.tracker, "final_emissions_data", None)
            return {
                "enabled": True,
                "energy_kwh": getattr(data, "energy_consumed", None),
                "co2_kg": getattr(data, "emissions", None),
                "duration_s": getattr(data, "duration", None),
                "cpu_power_w": getattr(data, "cpu_power", None),
                "ram_power_w": getattr(data, "ram_power", None),
                "tracking_mode": getattr(data, "tracking_mode", None),
                "country": getattr(data, "country_iso_code", self.country),
                "error": None,
            }
        except Exception as exc:  # pragma: no cover
            return {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}


# Backends
@dataclass
class Prediction:
    category: str
    action: str
    raw_valid: bool | None = None
    invalid_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    server_load_ms: float | None = None
    raw_excerpt: str = ""


@dataclass
class CallRecord:
    backend: str
    review_id: str
    phase: str
    run: int
    input_mode: str
    input_chars: int
    latency_ms: float
    category: str
    action: str
    raw_valid: bool | None
    invalid_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    server_load_ms: float | None
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
        from app.classifier import build_chain

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
        load_ns = meta.get("load_duration")
        server_load_ms = float(load_ns) / 1_000_000 if load_ns is not None else None
        return Prediction(
            category=category,
            action=action,
            raw_valid=valid,
            invalid_reason=reason,
            input_tokens=int(input_tokens) if input_tokens is not None else None,
            output_tokens=int(output_tokens) if output_tokens is not None else None,
            server_load_ms=server_load_ms,
            raw_excerpt=excerpt,
        )

    def token_usage(self, email: Email, pred: Prediction) -> tuple:
        return pred.input_tokens, pred.output_tokens

    def model_info(self) -> dict:
        import requests

        base = settings.ollama_base_url.rstrip("/")
        info = {
            "model": settings.ollama_model,
            "model_size_mb": None,
            "loaded_size_mb": None,
            "model_detail": "",
        }
        try:
            tags = requests.get(base + "/api/tags", timeout=15).json()
            models = tags.get("models", [])
            match = next(
                (
                    m
                    for m in models
                    if m.get("name") == settings.ollama_model
                    or m.get("model") == settings.ollama_model
                    or str(m.get("name", "")).startswith(settings.ollama_model)
                ),
                None,
            )
            if match:
                info["model_size_mb"] = float(match.get("size", 0)) / (1024 * 1024)
                details = match.get("details") or {}
                info["model_detail"] = ", ".join(
                    f"{k}={v}" for k, v in details.items() if v
                )
        except Exception as exc:
            info["error"] = f"tags: {type(exc).__name__}: {exc}"

        try:
            ps = requests.get(base + "/api/ps", timeout=15).json()
            loaded = next(
                (
                    m
                    for m in ps.get("models", [])
                    if m.get("name") == settings.ollama_model
                    or m.get("model") == settings.ollama_model
                ),
                None,
            )
            if loaded:
                info["loaded_size_mb"] = float(loaded.get("size", 0)) / (1024 * 1024)
        except Exception as exc:
            info.setdefault("error", f"ps: {type(exc).__name__}: {exc}")
        return info


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
        head_dirs = [
            BERT_DIR / "models" / "category_head",
            BERT_DIR / "models" / "action_head",
        ]
        head_size = sum(_dir_size_mb(d) for d in head_dirs if d.exists())
        encoder_ids = set()
        for d in head_dirs:
            manifest = d / "manifest.json"
            if manifest.exists():
                try:
                    encoder_ids.add(json.loads(manifest.read_text())["encoder_model_id"])
                except Exception:
                    pass

        encoder_size = 0.0
        found_encoder = False
        try:
            from huggingface_hub.constants import HF_HUB_CACHE

            cache = Path(HF_HUB_CACHE)
            for model_id in sorted(encoder_ids):
                folder = cache / ("models--" + model_id.replace("/", "--"))
                if not folder.exists():
                    continue
                ref = folder / "refs" / "main"
                snapshot = folder
                if ref.exists():
                    commit = ref.read_text(encoding="utf-8").strip()
                    candidate = folder / "snapshots" / commit
                    if candidate.exists():
                        snapshot = candidate
                size = _dir_size_mb(snapshot)
                if size:
                    encoder_size += size
                    found_encoder = True
        except Exception:
            pass

        total = head_size + (encoder_size if found_encoder else 0)
        return {
            "model": "bge-small-en + e5-small-multi",
            "model_size_mb": total if (head_size or found_encoder) else None,
            "head_size_mb": head_size if head_size else None,
            "encoder_size_mb": encoder_size if found_encoder else None,
            "loaded_size_mb": None,
            "model_detail": ", ".join(sorted(encoder_ids)),
        }


def make_backend(name: str) -> LlamaBackend | BertBackend:
    if name == "llama":
        return LlamaBackend()
    if name == "bert":
        return BertBackend()
    raise ValueError(f"unknown backend: {name}")


def _dir_size_mb(path: Path) -> float:
    try:
        files = {p.resolve() for p in path.rglob("*") if p.is_file()}
        return sum(p.stat().st_size for p in files) / (1024 * 1024)
    except Exception:
        return 0.0


def unload_ollama() -> None:
    env = os.environ.copy()
    host = settings.ollama_base_url.replace("http://", "").replace("https://", "")
    env["OLLAMA_HOST"] = host.rstrip("/")
    try:
        subprocess.run(
            ["ollama", "stop", settings.ollama_model],
            env=env,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        time.sleep(0.5)
        print(f"[llama] requested unload of {settings.ollama_model}")
    except Exception as exc:
        print(f"[llama] could not unload model: {type(exc).__name__}: {exc}")


# Running and stats
def _timed_predict(backend: LlamaBackend | BertBackend, email: Email) -> tuple:
    start = time.perf_counter()
    pred = backend.predict(email)
    return pred, (time.perf_counter() - start) * 1000


def _call(backend, name, row, phase, run, mode, text) -> CallRecord:
    email = email_for(row, text)
    pred, latency = _timed_predict(backend, email)
    pred.input_tokens, pred.output_tokens = backend.token_usage(email, pred)
    return _record(name, row, pred, latency, phase, run, mode, text)


def _record(backend, row, pred, latency_ms, phase, run, input_mode, text) -> CallRecord:
    return CallRecord(
        backend=backend,
        review_id=str(row["review_id"]),
        phase=phase,
        run=run,
        input_mode=input_mode,
        input_chars=len(text),
        latency_ms=latency_ms,
        category=pred.category,
        action=pred.action,
        raw_valid=pred.raw_valid,
        invalid_reason=pred.invalid_reason,
        input_tokens=pred.input_tokens,
        output_tokens=pred.output_tokens,
        server_load_ms=pred.server_load_ms,
        true_action=str(row["label_key"]),
        true_category=str(row.get("category", "")),
        raw_excerpt=pred.raw_excerpt,
    )


def run_backend(name: str, rows: pd.DataFrame, args: argparse.Namespace) -> tuple:
    records = []
    sampler = MemorySampler(include_ollama=(name == "llama"), enabled=not args.no_memory)
    energy = EnergyMeter(country=args.country, enabled=not args.no_energy)
    backend = None
    init_ms = None
    cold = None
    error = None

    if name == "llama" and args.unload_ollama:
        unload_ollama()
    gc.collect()
    sampler.start()
    energy.start()

    try:
        init_start = time.perf_counter()
        backend = make_backend(name)
        init_ms = (time.perf_counter() - init_start) * 1000

        first = rows.iloc[0]
        full_text = str(first.get("Preview", ""))
        cold = _call(backend, name, first, "cold", 0, "full", full_text)
        records.append(cold)

        for _, row in rows.head(args.warmup).iterrows():
            text = str(row.get("Preview", ""))
            records.append(_call(backend, name, row, "warmup", 0, "full", text))

        for run in range(1, args.runs + 1):
            print(f"[{name}] run {run}/{args.runs} ({len(rows)} emails) ...", flush=True)
            for _, row in rows.iterrows():
                text = str(row.get("Preview", ""))
                records.append(_call(backend, name, row, "main", run, "full", text))

        print(f"[{name}] short-input pass ({len(rows)} emails) ...", flush=True)
        for _, row in rows.iterrows():
            text = str(row.get("Preview", ""))[: args.short_chars]
            records.append(_call(backend, name, row, "length_short", 0, "short", text))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[{name}] benchmark failed: {error}")
        traceback.print_exc()
    finally:
        energy_data = energy.stop()
        memory = sampler.stop()

    consistency, length = _agreement(records, args)
    summary = _summarise(
        name=name,
        backend=backend,
        rows=rows,
        records=records,
        consistency=consistency,
        length=length,
        init_ms=init_ms,
        cold=cold,
        energy=energy_data,
        memory=memory,
        error=error,
        args=args,
    )
    return summary, records


def _agreement(records: list[CallRecord], args: argparse.Namespace) -> tuple:
    main = [r for r in records if r.phase == "main"]
    by_id = defaultdict(list)
    for r in main:
        by_id[r.review_id].append(r)

    consistency = []
    for group in by_id.values():
        if len(group) != args.runs:
            continue
        cats = {r.category for r in group}
        acts = {r.action for r in group}
        consistency.append(len(cats) == 1 and len(acts) == 1)

    full = {r.review_id: r for r in main if r.run == 1}
    short = {r.review_id: r for r in records if r.phase == "length_short"}
    length = [
        full[rid].category == short[rid].category
        and full[rid].action == short[rid].action
        for rid in sorted(set(full) & set(short))
    ]
    return consistency, length


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
    consistency,
    length,
    init_ms,
    cold,
    energy,
    memory,
    error,
    args,
) -> dict:
    main = [r for r in records if r.phase == "main"]
    scored = [r for r in records if r.phase in {"main", "length_short"}]
    latencies = [r.latency_ms for r in main]
    warm_p50 = _pct(latencies, 50)
    warm_p95 = _pct(latencies, 95)

    cold_ms = cold.latency_ms if cold else None
    server_load_ms = cold.server_load_ms if cold else None
    if name == "llama":
        load_ms = (
            (init_ms or 0) + (server_load_ms or 0) if init_ms is not None else None
        )
    else:
        load_ms = init_ms

    input_tokens = [r.input_tokens for r in main if r.input_tokens is not None]
    output_tokens = [r.output_tokens for r in main if r.output_tokens is not None]

    invalid = [r for r in scored if r.raw_valid is False]
    invalid_main = [r for r in main if r.raw_valid is False]
    invalid_rate = len(invalid) / len(scored) if scored and name == "llama" else None
    invalid_main_rate = (
        len(invalid_main) / len(main) if main and name == "llama" else None
    )
    reasons = Counter(r.invalid_reason or "unknown" for r in invalid)

    consistency_rate = _mean(consistency) if args.runs > 1 else None
    length_rate = _mean(length)

    model_info = backend.model_info() if backend is not None else {}
    notes = []
    if error:
        notes.append(f"error: {error}")
    if name == "llama":
        notes.append("cold call includes Ollama load if model was unloaded")
        notes.append("invalid rate uses raw JSON/labels before Pydantic coercion")
    else:
        notes.append("constructor loads both encoders and heads")
    if energy.get("error"):
        notes.append(f"energy: {energy['error']}")
    if model_info.get("error"):
        notes.append(f"model_info: {model_info['error']}")
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
        "load_ms": load_ms,
        "cold_call_ms": cold_ms,
        "warm_p50_ms": warm_p50,
        "warm_p95_ms": warm_p95,
        "peak_total_mb": memory.get("peak_total_mb"),
        "model_size_mb": model_info.get("model_size_mb"),
        "input_tokens_mean": _mean(input_tokens),
        "output_tokens_mean": _mean(output_tokens),
        "energy_kwh": energy.get("energy_kwh"),
        "co2_kg": energy.get("co2_kg"),
        "invalid_format_rate": invalid_rate,
        "invalid_format_rate_main": invalid_main_rate,
        "consistency_exact": consistency_rate,
        "length_both": length_rate,
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
        f"Input: full = body/Preview (Llama cap {manifest['body_char_limit']} chars); "
        f"short = first {manifest['short_chars']} chars",
        "",
    ]
    header = (
        f"{'Backend':<8} {'N':>3} {'Load ms':>8} {'Cold ms':>8} "
        f"{'Warm p50':>9} {'Warm p95':>9} {'Peak MB':>8} {'Model MB':>9} "
        f"{'In tok':>7} {'Out tok':>7} {'Energy kWh':>10} {'Invalid':>7} "
        f"{'Consist.':>8} {'Short/full':>10}"
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
            f"{fmt(row['load_ms']):>8} {fmt(row['cold_call_ms']):>8} "
            f"{fmt(row['warm_p50_ms']):>9} {fmt(row['warm_p95_ms']):>9} "
            f"{fmt(row['peak_total_mb']):>8} {fmt(row['model_size_mb']):>9} "
            f"{fmt(row['input_tokens_mean']):>7} {fmt(row['output_tokens_mean']):>7} "
            f"{fmt(row['energy_kwh'], 6):>10} {fmt(row['invalid_format_rate'], 3):>7} "
            f"{fmt(row['consistency_exact'], 3):>8} {fmt(row['length_both'], 3):>10}"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- Load = classifier construction + Ollama model load (Llama).",
            "- Cold = first call after construction; warm stats exclude cold/warm-up.",
            "- Peak MB is benchmark process + Ollama server RSS (Llama); model MB is on-disk size.",
            "- Llama tokens include the system prompt; BERT tokens are head input tokens.",
            "- Invalid = raw JSON/labels not matching the taxonomy before Pydantic coercion.",
            f"- Consistency = all runs identical; Short/full = first full run vs first "
            f"{manifest['short_chars']} chars.",
            "- Energy is CodeCarbon machine-wide; it may include the Ollama server.",
            "- This is an operational benchmark, not the offline quality evaluation.",
        ]
    )
    if manifest.get("sample_action_counts"):
        lines.append(f"- Sample action counts: {manifest['sample_action_counts']}")
    return "\n".join(lines) + "\n"


def write_artifacts(
    out_dir: Path, summary: pd.DataFrame, runs: pd.DataFrame, manifest: dict
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(summary, out_dir / "operational_performance_summary.csv")
    write_csv(runs, out_dir / "operational_performance_runs.csv")
    write_json(manifest, out_dir / "operational_performance_manifest.json")
    report = render_report(summary, manifest)
    (out_dir / "operational_performance_report.txt").write_text(report, encoding="utf-8")
    print("\n" + "=" * 100)
    print(report)
    print("=" * 100)
    print(f"Saved artifacts -> {out_dir}")


def main() -> None:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.short_chars < 1:
        raise SystemExit("--short-chars must be >= 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")

    rows, meta = load_benchmark_rows(args)
    backends = ["llama", "bert"] if args.backend == "both" else [args.backend]
    print(
        f"Benchmarking {len(rows)} emails x {args.runs} runs "
        f"({', '.join(backends)}) | counts={meta['sample_action_counts']}"
    )

    summary_rows = []
    all_records = []
    for name in backends:
        print(f"\n=== {name} ===", flush=True)
        summary, records = run_backend(name, rows, args)
        summary_rows.append(summary)
        all_records.extend(records)
        if summary.get("error"):
            print(f"[{name}] ERROR: {summary['error']}")
        else:
            peak = summary.get("peak_total_mb")
            peak_s = f"{peak:.1f}" if peak is not None else "n/a"
            print(
                f"[{name}] warm p50={summary['warm_p50_ms']:.1f} ms "
                f"p95={summary['warm_p95_ms']:.1f} ms "
                f"peak={peak_s} MB"
            )

    summary = pd.DataFrame(summary_rows)
    runs = pd.DataFrame([r.__dict__ for r in all_records])
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_csv": display_path(args.review, REPO_ROOT),
        "backend": args.backend,
        "limit": args.limit,
        "total_rows": meta["total_rows"],
        "sample_n": meta["sample_n"],
        "sample_action_counts": meta["sample_action_counts"],
        "sample_review_ids": meta["sample_review_ids"],
        "runs": args.runs,
        "warmup": args.warmup,
        "short_chars": args.short_chars,
        "seed": args.seed,
        "country": args.country,
        "body_char_limit": settings.body_char_limit,
        "ollama_model": settings.ollama_model,
        "taxonomy_sha256_16": meta["taxonomy_sha256_16"],
        "input_protocol": {
            "full": "body/Preview; Llama truncated to body_char_limit, BERT to MAX_LEN tokens",
            "short": f"first {args.short_chars} characters of body/Preview",
        },
        "energy_scope": "CodeCarbon machine-wide; may include Ollama server",
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
                "codecarbon",
            )
        },
    }
    write_artifacts(Path(args.out_dir), summary, runs, manifest)


if __name__ == "__main__":
    main()
