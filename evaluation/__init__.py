"""Shared helpers for the evaluation scripts."""

import importlib.metadata
import json
from pathlib import Path


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
