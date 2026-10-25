"""Shared helpers for the evaluation scripts."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Sequence

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


def bootstrap_proportion(
    flags: Sequence[bool], n_boot: int, seed: int
) -> tuple[float, float, float]:
    """Return point estimate and percentile 95% CI for a proportion."""
    values = np.asarray(flags, dtype=float)
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    point = float(values.mean())
    rng = np.random.default_rng(seed)
    boots = np.array(
        [rng.choice(values, size=len(values), replace=True).mean() for _ in range(n_boot)]
    )
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return point, float(lo), float(hi)
