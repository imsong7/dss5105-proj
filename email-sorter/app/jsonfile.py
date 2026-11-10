"""Tiny helpers for the small JSON files kept under ``private/``."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_json(path: Path, default):
    """Return the parsed file, or ``default`` when it is missing or broken."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default
    return data if isinstance(data, type(default)) else default


def write_json_atomic(path: Path, data) -> None:
    """Replace the file in one step so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
