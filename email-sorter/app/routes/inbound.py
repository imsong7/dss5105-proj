"""Mail pushed by Power Automate: the webhook, refresh requests and their bookkeeping."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request

from app.accounts import refresh_url, webhook_owner
from app.config import settings
from app.mail.flow_package import DEFAULT_DAYS
from app.mail.pushed_store import pushed_images, pushed_store, refresh_state
from app.mail.text_utils import clean, outlook_link, strip_html
from app.routes.common import error, parse_window, request_user, sorter
from app.schemas import Email

bp = Blueprint("inbound", __name__)

WEBHOOK_PATH = "/api/inbound/outlook"
REFRESH_DONE_PATH = "/api/inbound/refresh-done"
# Called by Power Automate (server to server) with the webhook token, not by a browser.
TOKEN_PATHS = (WEBHOOK_PATH, REFRESH_DONE_PATH)

# Images a flow may send with an email ("inlineImages", or a raw "attachments"
# list). Posters are read from these; anything else is ignored.
MAX_INBOUND_IMAGES = 3
MAX_INBOUND_IMAGE_BYTES = 2_000_000


# ---- Reading a pushed message ------------------------------------------------

def _normalize_user(value) -> str:
    return str(value or "").strip().lower()


def _inbound_sender(data: dict) -> str:
    sender = data.get("from") or data.get("sender") or ""
    if isinstance(sender, dict):
        address = sender.get("emailAddress")
        if isinstance(address, str):
            return address.strip() or "Unknown sender"
        if not isinstance(address, dict):
            address = sender
        name = str(address.get("name") or "").strip()
        mailbox = str(address.get("address") or "").strip()
        if name and mailbox:
            return f"{name} <{mailbox}>"
        return name or mailbox or "Unknown sender"
    # Flat fields: easier to build in a Power Automate HTTP action than a
    # nested ``from`` object.
    flat_address = str(data.get("fromAddress") or data.get("senderAddress") or "").strip()
    flat_name = str(data.get("fromName") or data.get("senderName") or "").strip()
    if flat_address or flat_name:
        if flat_name and flat_address:
            return f"{flat_name} <{flat_address}>"
        return flat_name or flat_address
    return str(sender).strip() or "Unknown sender"


def _inbound_received(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    # .NET can emit seven fractional-second digits; Python accepts at most six.
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def inbound_email(data: dict) -> Email:
    """Map a Graph ``message`` object (or a flat Power Automate body) to Email."""
    body_value = data.get("body")
    if isinstance(body_value, dict):
        body = str(body_value.get("content") or "")
    else:
        body = str(body_value or data.get("bodyText") or "")
    if not body:
        body = str(data.get("bodyPreview") or data.get("preview") or "")
    if "<" in body and ">" in body:
        body = strip_html(body)
    body = clean(body)[:200_000]

    subject = str(data.get("subject") or "").strip() or "(no subject)"
    sender = _inbound_sender(data)
    received = _inbound_received(
        data.get("receivedDateTime") or data.get("received") or data.get("receivedAt")
    )
    message_id = str(data.get("internetMessageId") or data.get("id") or "").strip()
    if not message_id:
        message_id = hashlib.sha1(
            f"{sender}\n{subject}\n{received}\n{body[:500]}".encode("utf-8")
        ).hexdigest()

    preview = clean(str(data.get("bodyPreview") or data.get("preview") or body), 200)
    return Email(
        id=message_id,
        subject=subject,
        sender=sender,
        received=received,
        preview=preview,
        body=body,
        text_source="body" if body else "empty",
        web_link=outlook_link(str(data.get("webLink") or ""), str(data.get("outlookId") or "")),
    )


def inbound_images(data: dict) -> list[tuple[str, bytes]]:
    items = data.get("inlineImages")
    if items is None:
        items = data.get("attachments")
    if not isinstance(items, list):
        return []
    images: list[tuple[str, bytes]] = []
    for item in items:
        if not isinstance(item, dict) or len(images) >= MAX_INBOUND_IMAGES:
            continue
        lower = {str(key).lower(): value for key, value in item.items()}
        content_type = str(lower.get("contenttype") or "").lower()
        payload = lower.get("contentbytes") or lower.get("$content")
        if not content_type.startswith("image/") or not isinstance(payload, str):
            continue
        try:
            raw = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            continue
        if 0 < len(raw) <= MAX_INBOUND_IMAGE_BYTES:
            images.append((str(lower.get("name") or "image")[:120], raw))
    return images


def inbound_token() -> str:
    supplied = request.headers.get("X-Webhook-Token", "").strip()
    if not supplied:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
    return supplied


def _address_list(value) -> list[str]:
    """Pull email addresses out of a Graph recipient list or a flat string."""
    if isinstance(value, str):
        return [_normalize_user(value)] if value.strip() else []
    if not isinstance(value, list):
        return []
    addresses = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            addresses.append(_normalize_user(entry))
            continue
        if not isinstance(entry, dict):
            continue
        item = entry.get("emailAddress") or entry
        if isinstance(item, dict) and item.get("address"):
            addresses.append(_normalize_user(item["address"]))
    return addresses


def _inbound_owner(data: dict) -> str:
    """Owner address for a pushed message.

    Prefer the ``X-User-Email`` header set by the Power Automate flow, then any
    explicit field in the body, then the first To recipient (which is normally
    the mailbox the flow watches).
    """
    owner = _normalize_user(request.headers.get("X-User-Email"))
    if owner:
        return owner
    for key in ("userEmail", "user_email", "owner", "mailbox", "to"):
        if isinstance(data.get(key), str):
            owner = _normalize_user(data.get(key))
            if owner:
                return owner
    for key in ("toRecipients", "recipients"):
        for address in _address_list(data.get(key)):
            if address:
                return address
    return ""


def _refresh_id(data: dict) -> str | None:
    """The run id the flow echoes back, or ``None`` for a flow imported before ids existed."""
    value = str(data.get("refreshId") or "").strip()
    return value[:64] or None


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _slice_info(data: dict) -> dict:
    """Which date slice of the run a pushed email came from, and that slice's ``top`` limit."""
    return {
        "index": _int_or_none(data.get("slice")),
        "limit": _int_or_none(data.get("sliceTop")),
        "since": str(data.get("sliceSince") or "")[:40],
        "before": str(data.get("sliceBefore") or "")[:40],
    }


# ---- Routes ------------------------------------------------------------------

@bp.after_app_request
def record_inbound_attempt(response):
    """Remember webhook calls so the dashboard can show what arrived."""
    is_page_post = (
        request.method == "POST"
        and request.path == "/"
        and bool(inbound_token())
    )
    if request.path == WEBHOOK_PATH or response.status_code == 405 or is_page_post:
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        sorter().inbound_attempts.appendleft({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "owner": payload.get("owner"),
            "result": payload.get("status"),
            "error": payload.get("error"),
        })
    return response


@bp.post(WEBHOOK_PATH)
def inbound_outlook():
    """Receive one Outlook message from a Power Automate HTTP action.

    The mail is stored under the owner bound to the webhook token.
    """
    owner = webhook_owner(inbound_token())
    if not owner:
        return error("Invalid webhook token.", 401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Expected a JSON object with the email fields.", 400)

    claimed_owner = _inbound_owner(data)
    if claimed_owner and claimed_owner != owner:
        return error("Owner does not match webhook token.", 403)

    email = inbound_email(data)
    stored, duplicate = pushed_store.add(email, owner)
    # Count it towards its run even if it was already stored: it was still retrieved.
    refresh_state.arrival(owner, stored.id, _refresh_id(data), _slice_info(data), received=email.received_at)
    if not duplicate:
        # Read later, once, by the OCR/poster step when the inbox loads.
        pushed_images.put(owner, stored.id, inbound_images(data))

    return jsonify({
        "status": "duplicate" if duplicate else "stored",
        "id": stored.id,
        "owner": owner,
        "stored": len(pushed_store.all(owner)),
    })


@bp.get("/api/inbound/diagnostics")
def inbound_diagnostics():
    """Return only this account's owner-tagged webhook attempts."""
    owner = request_user()
    if not owner:
        return error("Authentication required.", 401)

    attempts = [item for item in list(sorter().inbound_attempts) if item.get("owner") == owner]
    return jsonify({
        "configured": True,
        "endpoint": WEBHOOK_PATH,
        "refresh_configured": bool(refresh_url()),
        "attempts": attempts,
        "last_refresh": refresh_state.last(owner),
        "refresh": refresh_state.status(owner),
    })


@bp.post("/api/inbound/refresh")
def inbound_refresh():
    """Trigger only the authenticated user's registered flow."""
    owner = request_user()
    if not owner:
        return error("Authentication required.", 401)

    url = refresh_url()
    if not url:
        return error("No flow is configured for this account.", 503)

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return error("Expected a JSON object.", 400)

    try:
        since, before = parse_window(data)
    except ValueError as exc:
        return error(str(exc), 400)

    # After one complete refresh, only ask for newer mail (a custom band or "full" reads it all).
    requested = since or datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS)
    incremental = False
    if settings.flow_incremental and not before and not data.get("full"):
        newer = refresh_state.incremental_since(owner, requested, bool(pushed_store.all(owner)))
        if newer:
            since, incremental = newer, True

    # Record the run before calling the flow, so pushes that arrive at once are counted.
    refresh_id, created = refresh_state.begin(owner, requested, incremental)
    if not created:
        return jsonify({"requested": False, "already_running": True, "refresh_id": refresh_id, "owner": owner})

    payload = {"owner": owner, "refreshId": refresh_id}
    if since:
        payload["since"] = since.isoformat()
    if before:
        payload["before"] = before.isoformat()
    if settings.flow_refresh_top > 0:
        payload["top"] = min(settings.flow_refresh_top, 1000)  # Get emails V3 allows up to 1000

    try:
        response = requests.post(url, json=payload, timeout=15, allow_redirects=False)
    except requests.RequestException:
        refresh_state.failed(owner, refresh_id, "flow unreachable")
        return error("Could not reach the Power Automate flow.", 502)

    if not 200 <= response.status_code < 300:
        refresh_state.failed(owner, refresh_id, f"flow answered {response.status_code}")
        return error(f"Power Automate rejected the refresh request ({response.status_code}).", 502)

    return jsonify({
        "requested": True,
        "refresh_id": refresh_id,
        "owner": owner,
        "since": payload.get("since"),
        "before": payload.get("before"),
        "incremental": incremental,
    })


@bp.post(REFRESH_DONE_PATH)
def inbound_refresh_done():
    """The flow calls this last, only when every step succeeded."""
    owner = webhook_owner(inbound_token())
    if not owner:
        return error("Invalid webhook token.", 401)

    data = request.get_json(silent=True)
    result = refresh_state.done(owner, _refresh_id(data if isinstance(data, dict) else {}))
    summary = result["refresh"]
    if summary:
        complete = {
            True: "complete",
            False: "INCOMPLETE (a slice hit its limit or got mail outside its dates)",
            None: "completeness unknown",
        }
        print(
            f"[refresh] {'incremental' if summary['incremental'] else 'full'} refresh done in "
            f"{summary['duration_s']}s; first email after {summary['first_email_after_s']}s; "
            f"{summary['emails_pushed']} emails pushed; {complete[summary['complete']]}.",
            flush=True,
        )
        for item in summary.get("slices", []):
            print(
                f"[refresh]   slice {item['index']} ({item['since'] or '?'} .. {item['before'] or 'now'}): "
                f"{item['count']}/{item['limit']} emails, {item['outside']} dated outside the slice",
                flush=True,
            )
    return jsonify(result)
