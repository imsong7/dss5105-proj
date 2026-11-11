"""Optional structured JSON diagnostics for /api/classify.

Set CLASSIFICATION_METRICS=1 to enable. All logging failures are swallowed so
metrics can never break a request or mask an exception.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from typing import Any

_ENABLED = os.environ.get("CLASSIFICATION_METRICS") == "1"
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "classification_request_id", default=None
)

log = logging.getLogger("classification.metrics")


def enabled() -> bool:
    return _ENABLED


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str | None) -> None:
    if request_id:
        _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def _serialize_value(value: Any) -> Any:
    if value is None:
        return "unknown"
    return value


def log_event(event: str, **fields: Any) -> None:
    if not _ENABLED:
        return
    try:
        payload = {
            "event": event,
            "request_id": _request_id.get(),
            "timestamp": time.time(),
        }
        for key, value in fields.items():
            payload[key] = _serialize_value(value)
        log.info(json.dumps(payload, default=str))
    except Exception:
        # Logging failures must not break requests or mask original exceptions.
        log.exception("classification metrics logging failed")
