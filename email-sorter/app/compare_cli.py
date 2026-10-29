"""Terminal comparison of classifier backends.

The dashboard keeps pushed mail in memory, so the CLI asks a running app for the
same batch instead of opening its own (empty) store::

    python run.py --compare --owner you@u.nus.edu --days 30

Each message is then classified locally with every selected backend, and the
results are printed as a table (optionally saved as CSV).
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import shorten

import requests

from .classifier_base import BACKEND_INFO, create_classifier, list_backends
from .models import Classification, Email
from .taxonomy import CONTENT_CATEGORIES

def parse_backends(value: str | None) -> list[str]:
    """Turn ``llama,ml`` into ``["llama", "ml"]``; empty means every backend."""
    if not value or value.strip().lower() in {"all", "*"}:
        return list_backends()
    names: list[str] = []
    for part in value.replace(" ", ",").split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name not in BACKEND_INFO:
            available = ", ".join(list_backends())
            raise ValueError(f"Unknown backend '{name}'. Available: {available}")
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("Pick at least one backend.")
    return names


def fetch_emails(
    url: str,
    provider: str,
    credentials: dict,
    owner: str,
    limit: int,
    days: int,
) -> list[Email]:
    """Fetch the batch from the running app, so pushed mail is visible."""
    payload: dict = {
        "provider": provider,
        "credentials": credentials,
        "count": limit,
    }
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        payload["since"] = since.isoformat()
    headers = {"X-User-Email": owner} if owner else {}
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/emails",
            json=payload,
            headers=headers,
            timeout=300,
        )
    except requests.RequestException as error:
        raise SystemExit(
            f"Could not reach the app at {url}: {error}\n"
            "Start it first with `python run.py --version 2`."
        )
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise SystemExit(
            f"Fetch failed ({response.status_code}): {data.get('error') or response.text[:200] or 'no details'}"
        )
    return [Email(**item) for item in data.get("emails", [])]


def compare_emails(
    emails: list[Email],
    backends: list[str],
    factory=create_classifier,
) -> tuple[dict, dict, dict, dict]:
    """Classify every email with every backend.

    Returns ``(results, latencies_ms, errors, unavailable)`` keyed by backend
    name (then by email id for the first three).
    """
    results: dict[str, dict[str, Classification]] = {}
    latencies: dict[str, dict[str, float]] = {}
    errors: dict[str, dict[str, str]] = {}
    unavailable: dict[str, str] = {}

    for name in backends:
        results[name] = {}
        latencies[name] = {}
        errors[name] = {}
        try:
            classifier = factory(name)
        except Exception as error:  # noqa: BLE001 - a missing model is data, not a crash
            unavailable[name] = str(error)
            continue
        for email in emails:
            started = time.perf_counter()
            try:
                results[name][email.id] = classifier.classify(email)
                latencies[name][email.id] = (time.perf_counter() - started) * 1000
            except Exception as error:  # noqa: BLE001 - report and keep going
                errors[name][email.id] = str(error)

    return results, latencies, errors, unavailable


def _agreement(
    emails: list[Email],
    baseline: dict[str, Classification],
    current: dict[str, Classification],
    field: str,
) -> str:
    pairs = [
        (baseline[email.id], current[email.id])
        for email in emails
        if email.id in baseline and email.id in current
    ]
    if not pairs:
        return "—"
    same = sum(getattr(left, field) == getattr(right, field) for left, right in pairs)
    return f"{same}/{len(pairs)} ({same / len(pairs):.0%})"


def _label(name: str) -> str:
    return BACKEND_INFO.get(name, {}).get("label", name)


def _category_label(key: str) -> str:
    return CONTENT_CATEGORIES.get(key, {}).get("label", key)


def _slow_backend(name: str, latencies: dict[str, dict[str, float]]) -> bool:
    values = list(latencies.get(name, {}).values())
    return bool(values) and sum(values) / len(values) >= 1000


def print_report(
    emails: list[Email],
    backends: list[str],
    results: dict,
    latencies: dict,
    errors: dict,
    unavailable: dict,
    subtitle: str,
) -> None:
    count = len(emails)
    print(f"Compare {count} email{'s' if count != 1 else ''} · {subtitle}")
    print()

    baseline_name = next((name for name in backends if results.get(name)), None)
    baseline = results.get(baseline_name, {}) if baseline_name else {}

    rows = []
    for name in backends:
        if name in unavailable:
            rows.append((_label(name), "—", "—", "—", unavailable[name], "—"))
            continue
        ok = len(results[name])
        avg = sum(latencies[name].values()) / ok if ok else 0
        category = _agreement(emails, baseline, results[name], "content_category") if name != baseline_name else "—"
        reply = _agreement(emails, baseline, results[name], "reply_nature") if name != baseline_name else "—"
        rows.append((_label(name), str(ok), str(len(errors[name])), f"{avg:.0f}ms", category, reply))

    headers = ("Backend", "OK", "Err", "Avg", "Category agree", "Reply agree")
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(6)]
    print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(headers)).rstrip())
    print("  ".join("-" * widths[i] for i in range(6)))
    for row in rows:
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)).rstrip())

    if unavailable:
        print()
        for name, message in unavailable.items():
            print(f"{_label(name)}: unavailable — {message}")

    print()
    labels = [(name, _label(name)) for name in backends if name not in unavailable]
    subject_width = min(42, max(12, max((len(email.subject or "(no subject)") for email in emails), default=12)))
    print("Subject".ljust(subject_width), "  ".join(label for _, label in labels))
    for email in emails:
        cells = []
        for name, _ in labels:
            result = results[name].get(email.id)
            if result is None:
                cells.append("error" if email.id in errors[name] else "—")
            else:
                cells.append(f"{_category_label(result.content_category)} / {result.reply_nature}")
        subject = shorten(email.subject or "(no subject)", width=subject_width, placeholder="…")
        print(subject.ljust(subject_width), "  ".join(cells))

    if any(_slow_backend(name, latencies) for name in backends if name not in unavailable):
        print()
        print("Note: an average above 1000ms is the local model loading or warming up.")


def write_csv(
    path: str,
    emails: list[Email],
    backends: list[str],
    results: dict,
    latencies: dict,
    errors: dict,
) -> None:
    fieldnames = ["id", "received", "subject", "sender"]
    for name in backends:
        fieldnames += [
            f"{name}_category",
            f"{name}_reply",
            f"{name}_deadline",
            f"{name}_ms",
            f"{name}_error",
        ]
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for email in emails:
            row: dict[str, object] = {
                "id": email.id,
                "received": email.received,
                "subject": email.subject,
                "sender": email.sender,
            }
            for name in backends:
                result = results.get(name, {}).get(email.id)
                row[f"{name}_category"] = result.content_category if result else ""
                row[f"{name}_reply"] = result.reply_nature if result else ""
                row[f"{name}_deadline"] = (result.deadline or "") if result else ""
                milliseconds = latencies.get(name, {}).get(email.id)
                row[f"{name}_ms"] = f"{milliseconds:.0f}" if milliseconds is not None else ""
                row[f"{name}_error"] = errors.get(name, {}).get(email.id, "")
            writer.writerow(row)
    print(f"\nCSV written to {target}")


def run_compare(
    *,
    url: str,
    provider: str,
    owner: str,
    token: str,
    backends: list[str],
    limit: int,
    days: int,
    output: str | None,
) -> int:
    if provider == "powerautomate" and not owner:
        print(
            "Pass --owner you@u.nus.edu (or set MAIL_OWNER) so the CLI reads the "
            "same pushed inbox as the dashboard.",
            file=sys.stderr,
        )
        return 2
    credentials = {"token": token} if provider == "outlook" else {}

    emails = fetch_emails(url, provider, credentials, owner, limit, days)
    if not emails:
        window = f"last {days} days" if days > 0 else "no date window"
        print(f"No emails found ({window}). Run the Power Automate flow or check --days/--owner.")
        return 1

    source = "pushed inbox" if provider == "powerautomate" else "Outlook Graph"
    subtitle = f"{source}"
    if owner:
        subtitle += f" · owner {owner}"
    subtitle += f" · last {days} days" if days > 0 else " · no date window"

    results, latencies, errors, unavailable = compare_emails(emails, backends)
    print_report(emails, backends, results, latencies, errors, unavailable, subtitle)
    if output:
        write_csv(output, emails, backends, results, latencies, errors)

    if all(name in unavailable for name in backends):
        return 1
    return 0
