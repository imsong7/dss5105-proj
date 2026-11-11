"""Jobs a student saved from job digests, per account, in ``private/saved_jobs.json``."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from app.config import ROOT
from app.stores.jsonfile import read_json, write_json_atomic

SAVED_JOBS_PATH = ROOT / "private" / "saved_jobs.json"
MAX_SAVED = 100
TEXT_FIELDS = {"title": 160, "company": 120, "type": 30, "mode": 30, "location": 60,
               "period": 60, "pay": 60, "programme": 30}


class SavedJobError(ValueError):
    """The job cannot be saved; the message is safe to show."""


def clean_job(value) -> dict:
    if not isinstance(value, dict):
        raise SavedJobError("Expected a job.")
    url = str(value.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or len(url) > 600:
        raise SavedJobError("A saved job needs its https link.")
    job_id = str(value.get("id") or url).strip()[:120]
    job = {"id": job_id, "url": url, "easy_apply": bool(value.get("easy_apply"))}
    for field, limit in TEXT_FIELDS.items():
        job[field] = " ".join(str(value.get(field) or "").split())[:limit]
    if not job["title"]:
        raise SavedJobError("A saved job needs a title.")
    return job


class SavedJobStore:
    def __init__(self, path: Path = SAVED_JOBS_PATH):
        self.path = Path(path)
        self._lock = Lock()

    def list(self, owner: str) -> list[dict]:
        with self._lock:
            data = read_json(self.path, {})
        return list(data.get(owner, []))

    def save(self, owner: str, value) -> dict:
        job = clean_job(value)
        job["saved_at"] = int(time.time())
        with self._lock:
            data = read_json(self.path, {})
            jobs = [item for item in data.get(owner, []) if item.get("id") != job["id"]]
            jobs.insert(0, job)
            data[owner] = jobs[:MAX_SAVED]
            write_json_atomic(self.path, data)
        return job

    def remove(self, owner: str, job_id: str) -> bool:
        with self._lock:
            data = read_json(self.path, {})
            jobs = data.get(owner, [])
            kept = [item for item in jobs if item.get("id") != job_id]
            if len(kept) == len(jobs):
                return False
            data[owner] = kept
            write_json_atomic(self.path, data)
        return True


saved_job_store = SavedJobStore()
