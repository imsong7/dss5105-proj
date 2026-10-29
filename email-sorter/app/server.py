"""Flask app factory with pluggable classifier backends.

Usage::

    from app.server import create_app

    app = create_app(backend="bert")   # encoder backend; or "llama", or None
"""

import hashlib
import logging
import re
import secrets
import socket
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, abort, jsonify, render_template, request

from .academic_calendar import (
    ACADEMIC_CALENDAR_LABEL,
    load_academic_calendar,
)
from .classifier_base import (
    BACKEND_INFO,
    BaseClassifier,
    create_classifier,
    list_backends,
)
from .config import ROOT, settings
from .deadline_extractor import extract_deadline
from .inbound_store import inbound_store
from .ml_classifier import models_ready as _ml_ready
from .models import Classification, Email
from .ocr_pipeline import ocr_status, prepare_text
from .providers import AuthError, MailQuery, ProviderError, build_provider
from .rules import category_by_rule
from .taxonomy import CONTENT_CATEGORIES, DEFAULT_REPLY, REPLY_NATURE
from .textutil import clean, strip_html

logging.basicConfig(level=logging.INFO)


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


def _inbound_email(data: dict) -> Email:
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
    message_id = str(
        data.get("internetMessageId") or data.get("id") or ""
    ).strip()
    if not message_id:
        message_id = hashlib.sha1(
            f"{sender}\n{subject}\n{received}\n{body[:500]}".encode("utf-8")
        ).hexdigest()

    preview = clean(
        str(data.get("bodyPreview") or data.get("preview") or body), 200
    )
    return Email(
        id=message_id,
        subject=subject,
        sender=sender,
        received=received,
        preview=preview,
        body=body,
        text_source="body" if body else "empty",
    )


def _inbound_token() -> str:
    supplied = request.headers.get("X-Webhook-Token", "").strip()
    if not supplied:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
    return supplied


def _normalize_user(value) -> str:
    return str(value or "").strip().lower()


def _request_user(payload=None) -> str:
    """Current dashboard user, from ``X-User-Email`` or the JSON body.

    This identifies a person, it does not authenticate them; added by the
    browser after the first-visit prompt.
    """
    supplied = request.headers.get("X-User-Email", "")
    if not supplied.strip() and isinstance(payload, dict):
        supplied = payload.get("user") or payload.get("user_email") or ""
    return _normalize_user(supplied)


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


def _ollama_status() -> tuple[bool, bool]:
    """Return ``(server_reachable, configured_model_present)``."""
    raw_url = settings.ollama_base_url
    base_url = raw_url if "://" in raw_url else f"http://{raw_url}"
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 11434)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except (OSError, socket.timeout):
        return False, False
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=2)
        names = [m["name"] for m in r.json().get("models", [])]
        ready = any(
            n == settings.ollama_model or n.split(":")[0] == settings.ollama_model
            for n in names
        )
        return True, ready
    except Exception:
        return True, False


def _bert_ready(tasks: tuple[str, ...] | str = ("category", "action")) -> bool:
    """Encoder heads are usable when the requested head files and manifests exist."""
    if isinstance(tasks, str):
        tasks = (tasks,)
    models_dir = ROOT.parent / "text-encoders" / "models"
    return all(
        (models_dir / f"{task}_head" / filename).is_file()
        for task in tasks
        for filename in ("head.joblib", "manifest.json")
    )


def _backend_ready(name: str, ollama_ready: bool, *, loaded: bool = False) -> bool | None:
    """Return readiness for a backend, or ``None`` when it cannot be checked cheaply."""
    if name == "llama":
        return ollama_ready
    if name == "bert":
        return _bert_ready()
    if name == "ml":
        return _ml_ready()
    if name == "hybrid":
        return _ml_ready(("category",)) and _bert_ready(("action",))
    return True if loaded else None


_PROVIDER_ALIASES = {
    "graph": "outlook",
    "graphtoken": "outlook",
    "graph-token": "outlook",
    "outlook": "outlook",
    "powerautomate": "powerautomate",
    "power-automate": "powerautomate",
    "pushed": "powerautomate",
}


def normalize_provider(value: str | None) -> str:
    """Map a ``--provider`` value to the internal provider id.

    ``graphtoken``/``graph`` both mean the Outlook Graph provider; unknown
    values are rejected so a typo in ``--provider`` or ``MAIL_PROVIDER`` does
    not silently change where mail comes from.
    """
    key = str(value or "").strip().lower()
    if not key:
        return "powerautomate"
    if key not in _PROVIDER_ALIASES:
        raise ValueError(
            f"Unknown mail provider {value!r}. Use 'graphtoken' or 'powerautomate'."
        )
    return _PROVIDER_ALIASES[key]


def _parse_datetime(value) -> datetime | None:
    """Parse an ISO 8601 string from the UI; ``None``/empty means "no bound"."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Date bounds must be ISO 8601 strings.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 date: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def create_app(backend: str | None = None, version: int = 1, provider: str | None = None) -> Flask:
    mail_provider = normalize_provider(provider or settings.mail_provider)
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    # The mail source is fixed at launch, so every page renders the same value
    # instead of offering a dropdown.
    app.jinja_env.globals["mail_provider"] = mail_provider
    state = {"classifier": None, "backend": None}
    inbound_attempts: deque[dict] = deque(maxlen=20)

    @app.after_request
    def _record_inbound_attempt(response):
        """Remember webhook calls so the dashboard can show what arrived."""
        is_page_post = (
            request.method == "POST"
            and request.path in ("/", "/dashboard-v2")
            and bool(_inbound_token())
        )
        if request.path == "/api/inbound/outlook" or response.status_code == 405 or is_page_post:
            payload = response.get_json(silent=True)
            if not isinstance(payload, dict):
                payload = {}
            inbound_attempts.appendleft({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "owner": payload.get("owner"),
                "result": payload.get("status"),
                "error": payload.get("error"),
            })
        return response

    def classifier(backend_name: str | None = None) -> BaseClassifier:
        name = backend_name or backend or settings.model_backend
        if state["classifier"] is None or state["backend"] != name:
            state["classifier"] = create_classifier(name)
            state["backend"] = name
        return state["classifier"]

    @app.get("/")
    def index():
        template = "dashboard_v2.html" if version == 2 else "index.html"
        return render_template(template)

    @app.get("/api/inbound/diagnostics")
    def inbound_diagnostics():
        """What the webhook has received lately, for the sidebar hint."""
        return jsonify({
            "configured": bool(settings.inbound_webhook_token),
            "endpoint": "/api/inbound/outlook",
            "refresh_configured": bool(settings.powerautomate_refresh_url),
            "attempts": list(inbound_attempts),
        })

    @app.post("/api/inbound/refresh")
    def inbound_refresh():
        """Ask the Power Automate flow to backfill a window now.

        The flow's "When an HTTP request is received" trigger takes
        ``{owner, since, before}`` and pushes the matching messages back to
        ``/api/inbound/outlook``. Only the trigger URL lives in ``.env``.
        """
        url = settings.powerautomate_refresh_url
        if not url:
            return jsonify({
                "error": "Set POWER_AUTOMATE_REFRESH_URL in .env and restart the app.",
            }), 503
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        owner = _request_user(data)
        payload = {"owner": owner}
        for key in ("since", "before"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                payload[key] = value.strip()
        try:
            response = requests.post(url, json=payload, timeout=15)
        except requests.RequestException as error:
            return jsonify({
                "error": f"Could not reach the Power Automate trigger: {error}",
            }), 502
        if response.status_code >= 400:
            return jsonify({
                "error": (
                    "Power Automate rejected the refresh request "
                    f"({response.status_code}). The trigger URL may have expired; "
                    "copy it again from the flow and update .env."
                ),
            }), 502
        return jsonify({
            "requested": True,
            "owner": owner or None,
            "since": payload.get("since"),
            "before": payload.get("before"),
        })

    @app.errorhandler(405)
    def method_not_allowed(error):
        """Explain a wrong method instead of Flask's bare 405 page."""
        path = request.path
        if path == "/api/inbound/outlook":
            message = (
                "This webhook only accepts POST. In Power Automate, set the HTTP "
                "action Method to POST (it defaults to GET) and put the message JSON "
                "in the Body."
            )
        elif path.startswith("/api/"):
            message = (
                f"{path} only accepts POST from the dashboard. Opening it in a "
                "browser always shows this page."
            )
        else:
            message = f"{path} does not accept a {request.method} request."
            if request.method == "POST" and path in ("/", "/dashboard-v2"):
                message = (
                    "This is the dashboard page, not the webhook. Add "
                    "/api/inbound/outlook to the end of the tunnel URL in the HTTP "
                    "action's URI."
                )
        preferred = request.accept_mimetypes.best_match(["application/json", "text/html"])
        if preferred == "application/json":
            return jsonify({"error": message, "methods": ["POST"]}), 405
        return render_template(
            "method_not_allowed.html", path=path, message=message
        ), 405

    @app.get("/dashboard-v2")
    def dashboard_v2():
        return render_template("dashboard_v2.html")

    def receive_inbound():
        """Store one pushed message; shared by the webhook and the root fallback."""
        expected = settings.inbound_webhook_token
        if not expected:
            return jsonify({
                "error": "Set POWER_AUTOMATE_WEBHOOK_TOKEN in .env and restart the app.",
            }), 503
        if not secrets.compare_digest(_inbound_token(), expected):
            return jsonify({"error": "Invalid webhook token."}), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object with the email fields."}), 400
        email = _inbound_email(data)
        owner = _inbound_owner(data)
        if not owner:
            logging.warning(
                "Inbound mail has no owner; send X-User-Email so the dashboard can show it."
            )
        stored, duplicate = inbound_store.add(email, owner)
        payload = {
            "status": "duplicate" if duplicate else "stored",
            "id": stored.id,
            "owner": owner or None,
            "stored": len(inbound_store),
        }
        if request.path != "/api/inbound/outlook":
            payload["warning"] = (
                f"Received on {request.path}. This worked, but the HTTP action's URI "
                "should end in /api/inbound/outlook."
            )
        return jsonify(payload)

    @app.post("/api/inbound/outlook")
    def inbound_outlook():
        """Receive one Outlook message from a Power Automate HTTP action."""
        return receive_inbound()

    @app.post("/")
    @app.post("/dashboard-v2")
    def inbound_on_wrong_path():
        """A flow that posts to the page root still delivers its mail.

        Without a token this is just a stray POST, so let the 405 page explain
        the correct URI instead of silently accepting it.
        """
        if not _inbound_token():
            abort(405)
        return receive_inbound()

    @app.get("/api/backends")
    def backends():
        _, ollama_ready = _ollama_status()
        items = []
        for name in list_backends():
            info = BACKEND_INFO.get(name, {})
            items.append(
                {
                    "id": name,
                    "label": info.get("label", name),
                    "kind": info.get("kind", "unknown"),
                    "description": info.get("description", ""),
                    "ready": _backend_ready(name, ollama_ready),
                }
            )
        return jsonify(
            {
                "backends": items,
                "default": backend or settings.model_backend,
                "max_emails": settings.max_emails,
            }
        )

    @app.get("/api/taxonomy")
    def taxonomy():
        return jsonify(
            {"content": CONTENT_CATEGORIES, "reply": REPLY_NATURE, "max_emails": settings.max_emails}
        )

    @app.get("/api/academic-calendar")
    def academic_calendar():
        """NUS term dates and holidays shown beside the Canvas deadlines."""
        events = load_academic_calendar()
        return jsonify(
            {
                "label": ACADEMIC_CALENDAR_LABEL,
                "events": events,
                "available": bool(events),
            }
        )

    @app.get("/api/health")
    def health():
        # The UI polls readiness for whichever backend it has selected.
        requested = request.args.get("backend") or backend or settings.model_backend
        ollama_up, ollama_ready = _ollama_status()
        bert_ready = _bert_ready()
        ml_ready = _ml_ready()
        hybrid_ready = _ml_ready(("category",)) and _bert_ready(("action",))
        backend_ready = _backend_ready(
            requested,
            ollama_ready,
            loaded=state["classifier"] is not None and state["backend"] == requested,
        )

        return jsonify(
            {
                "backend": requested,
                "default_backend": backend or settings.model_backend,
                "backend_ready": backend_ready,
                "ollama_up": ollama_up,
                "ollama": ollama_ready,
                "ollama_ready": ollama_ready,
                "model": settings.ollama_model,
                "model_ready": ollama_ready,
                "bert_ready": bert_ready,
                "ml_ready": ml_ready,
                "hybrid_ready": hybrid_ready,
                "ocr": ocr_status(),
            }
        )

    @app.post("/api/emails")
    def emails():
        data = request.get_json(force=True)
        try:
            limit = max(1, min(int(data.get("count", 15)), settings.max_emails))
        except (TypeError, ValueError):
            return jsonify({"error": "`count` must be a whole number."}), 400
        try:
            since = _parse_datetime(data.get("since"))
            before = _parse_datetime(data.get("before"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if since and before and since > before:
            return jsonify({"error": "`since` must be earlier than `before`."}), 400

        query = MailQuery(limit=limit, since=since, before=before)
        try:
            kind = data.get("provider", "outlook")
            credentials = dict(data.get("credentials") or {})
            if kind == "powerautomate":
                # Strict per-user view: only this person's pushed mail.
                credentials["owner"] = _request_user(data)
            provider = build_provider(kind, credentials)
            items = provider.fetch_emails(query)
            items = [prepare_text(email, provider) for email in items]
        except AuthError as exc:
            return jsonify({"error": str(exc)}), 401
        except ProviderError as exc:
            return jsonify({"error": str(exc)}), 502
        emails_with_deadlines = []
        for email in items:
            serialized = email.model_dump()
            serialized["deadline_candidate"] = extract_deadline(email)
            emails_with_deadlines.append(serialized)
        return jsonify(
            {
                "emails": emails_with_deadlines,
                "window": {
                    "since": since.isoformat() if since else None,
                    "before": before.isoformat() if before else None,
                    "limit": limit,
                },
            }
        )

    @app.post("/api/classify")
    def classify():
        try:
            data = request.get_json(force=True)
            email = Email(**data["email"])
            backend_name = data.get("backend") or backend or settings.model_backend
            t0 = time.perf_counter()
            rule_category = category_by_rule(email.sender)
            if rule_category:
                model_name = "Sender rule (model skipped)"
                result = Classification(
                    content_category=rule_category,
                    reply_nature=DEFAULT_REPLY,
                    deadline=None,
                    reason=f"Sender rule matched and set category to {rule_category}.",
                )
            else:
                selected_classifier = classifier(backend_name)
                result = selected_classifier.classify(email)
                model_name = getattr(
                    selected_classifier, "model_name", backend_name
                )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            out = result.model_dump()
            out["duration_ms"] = duration_ms
            out["backend"] = backend_name
            out["model_name"] = model_name
            out["text_source"] = email.text_source
            out["ocr_confidence"] = email.ocr_confidence
            out["ocr_notes"] = email.ocr_notes
            return jsonify(out)
        except Exception as exc:  # most often: Ollama not running or model not pulled
            logging.exception("classification failed")
            return jsonify({"error": f"Classification failed: {exc}"}), 500

    return app
