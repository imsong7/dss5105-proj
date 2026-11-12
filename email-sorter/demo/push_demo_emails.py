"""Put made-up demo emails into a NusBox account, for screen recordings.

Nothing in the app imports this file. It only sends data when you run it, to the account
whose webhook token you give it, so use a demo account and not a real one.

    python demo/push_demo_emails.py --token WEBHOOK_TOKEN --email demo@example.com
    python demo/push_demo_emails.py --token ... --email ... --url https://your-domain.ngrok-free.dev
    python demo/push_demo_emails.py --dry-run

The webhook token is the account's ``webhook_token`` in private/multiuser.json (it is also
inside the flow zip). Dates in the emails (due tomorrow, in 3 days, ...) are worked out
from today, so run it just before you record.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HERE = Path(__file__).resolve().parent
SINGAPORE = ZoneInfo("Asia/Singapore")
TOKENS = re.compile(r"\{(day|weekday)\+(\d+)\}")


def fill_dates(text: str, today: datetime) -> str:
    """{day+3} becomes "15 Nov 2026" and {weekday+3} becomes "Sunday" (3 days from today)."""

    def replace(match: re.Match) -> str:
        target = today + timedelta(days=int(match.group(2)))
        if match.group(1) == "weekday":
            return target.strftime("%A")
        return f"{target.day} {target.strftime('%b %Y')}"

    return TOKENS.sub(replace, text)


def build_messages(now: datetime | None = None) -> list[dict]:
    """The demo emails as the flat JSON body the Power Automate flow posts."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.astimezone(SINGAPORE)
    messages = []
    for item in json.loads((HERE / "demo_emails.json").read_text(encoding="utf-8")):
        body = fill_dates(item["body"], today)
        messages.append({
            "internetMessageId": f"demo-{item['id']}@nusbox.demo",
            "subject": fill_dates(item["subject"], today),
            "from": item["from"],
            "receivedDateTime": (now - timedelta(hours=item["hours_ago"])).isoformat(),
            "bodyPreview": body[:200],
            "body": body,
        })
    return messages


def push(messages: list[dict], url: str, token: str, email: str, post=requests.post) -> dict:
    """Send every message; returns how many were stored, duplicates and failures."""
    endpoint = url.rstrip("/") + "/api/inbound/outlook"
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": token,
        "X-User-Email": email,
        "ngrok-skip-browser-warning": "true",
    }
    result = {"stored": 0, "duplicate": 0, "failed": 0}
    for message in messages:
        try:
            response = post(endpoint, json=message, headers=headers, timeout=20)
        except requests.RequestException as exc:
            print(f"  failed: {message['subject']!r}: {exc}")
            result["failed"] += 1
            continue
        status = response.status_code
        if status == 200:
            kind = (response.json() or {}).get("status")
            result["duplicate" if kind == "duplicate" else "stored"] += 1
        else:
            print(f"  failed ({status}): {message['subject']!r}")
            result["failed"] += 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:5001", help="app address (default: this Mac)")
    parser.add_argument("--token", help="the demo account's webhook token")
    parser.add_argument("--email", help="the demo account's email address")
    parser.add_argument("--dry-run", action="store_true", help="print the emails and send nothing")
    args = parser.parse_args(argv)

    messages = build_messages()
    if args.dry_run:
        for message in messages:
            print(f"{message['receivedDateTime'][:16]}  {message['from'][:34]:34}  {message['subject']}")
        print(f"\n{len(messages)} demo emails (nothing sent).")
        return 0

    if not args.token or not args.email:
        parser.error("--token and --email are required (or use --dry-run)")
    result = push(messages, args.url, args.token, args.email)
    print(f"Done: {result['stored']} stored, {result['duplicate']} already there, {result['failed']} failed.")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
