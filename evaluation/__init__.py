"""Shared helpers for the evaluation scripts."""

import importlib.metadata
import json
from pathlib import Path

import numpy as np


def package_version(package: str) -> str | None:
    """Return an installed package version, or ``None`` when unavailable."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def display_path(path: str, repo_root: Path) -> str:
    """Prefer a repo-relative path in committed artifacts."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def write_csv(frame, path: Path) -> None:
    """Write a DataFrame as a UTF-8 CSV artifact."""
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(data: dict, path: Path) -> None:
    """Write a JSON artifact."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def bootstrap_proportion(flags, n_boot: int, seed: int) -> tuple:
    """Return point estimate and percentile 95% CI for a proportion."""
    values = np.asarray(flags, dtype=float)
    if not len(values):
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = [rng.choice(values, len(values), replace=True).mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(values.mean()), float(lo), float(hi)
