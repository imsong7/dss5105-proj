"""Load config.yaml and .env. Every other module reads settings from here."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


@lru_cache(maxsize=1)
def get_config(path: str | None = None) -> dict:
    """Read and validate config.yaml. Call get_config.cache_clear() to reload."""
    p = Path(path or os.environ.get("INBOX_SORTER_CONFIG", ROOT / "config.yaml"))
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate(cfg)
    return cfg


def topics(cfg: dict) -> list[str]:
    return list(cfg["topics"].keys())


def actions(cfg: dict) -> list[str]:
    """Action labels in tie-break priority order (first wins)."""
    return list(cfg["actions"].keys())


def validate(cfg: dict) -> None:
    for key in ("topics", "actions", "claude", "rules"):
        if key not in cfg:
            raise ValueError(f"config.yaml is missing the '{key}' section")
    if cfg.get("fallback_topic") not in cfg["topics"]:
        raise ValueError("fallback_topic must be one of the topics")
    if cfg.get("fallback_action") not in cfg["actions"]:
        raise ValueError("fallback_action must be one of the actions")
    for ex in cfg.get("examples") or []:
        if ex.get("topic") not in cfg["topics"] or ex.get("action") not in cfg["actions"]:
            raise ValueError(f"Example has an unknown label: {ex}")
