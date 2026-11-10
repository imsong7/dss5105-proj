"""Flask app factory with pluggable classifier backends.

Usage::

    from app.server import create_app

    app = create_app(backend="encoder")   # text-encoder backend; or "llama", or None
"""

import hashlib
import io
import logging
import re
import secrets
import socket
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file
from flask import session as flask_session

from .accounts import (
    install_multiuser,
    authenticated_owner,
    flow_url_problem,
    is_account,
    is_token_session,
    save_flow_url,
    session_graph_token,
    webhook_owner,
    refresh_url,
)
from .backends import (
    BACKEND_INFO,
    BaseClassifier,
    create_classifier,
    list_backends,
)
from .calendar import (
    ACADEMIC_CALENDAR_LABEL,
    extract_deadline,
    extract_deadlines,
    load_academic_calendar,
)
from .claude_classifier import claude_ready
from .flow_package import build_flow_package
from .config import ROOT, settings
from .ml_classifier import models_ready as _ml_ready
from .ocr import ocr_status, prepare_text
from .providers import AuthError, MailQuery, ProviderError, build_provider
from .pushed_store import pushed_store
from .reply_drafting import ReplyDraftError, generate_reply
from .schemas import Classification, Email
from .sender_rules import category_by_rule, coursework_by_rule, sender_address
from .taxonomy import CONTENT_CATEGORIES, DEFAULT_REPLY, REPLY_NATURE
from .text_utils import clean, strip_html
from . import calendar_feed, classification_store, item_states as item_state_module, profiles, user_events
from .calendar_feed import FeedError
from .item_states import StateError
from .profiles import ProfileError
from .classification_store import CorrectionError
from .user_events import EventError

logging.basicConfig(level=logging.INFO)

# Output of ``npm run build`` in frontend/. Checked per request, so building
# while the server runs takes effect without a restart.
REACT_INDEX = ROOT / "static" / "app" / "index.html"


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
    """Return the authenticated dashboard account."""
    return authenticated_owner()

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


def _encoder_ready(tasks: tuple[str, ...] | str = ("category", "action")) -> bool:
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
    if name == "encoder":
        return _encoder_ready()
    if name == "ml":
        return _ml_ready()
    if name == "hybrid":
        return _ml_ready(("category",)) and _encoder_ready(("action",))
    if name == "hybrid_claude":
        return _ml_ready(("category",)) and claude_ready()
    if name == "claude":
        return claude_ready()
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
        return "outlook"
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


def create_app(backend: str | None = None, provider: str | None = None) -> Flask:
    mail_provider = normalize_provider(provider or settings.mail_provider)
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    # Only pushed mail is filed per account. A Graph token is a single mailbox
    # and needs no app login, so do not show the Basic auth prompt for it.
    if mail_provider == "powerautomate":
        install_multiuser(app)

    state = {"classifier": None, "backend": None}
    inbound_attempts: deque[dict] = deque(maxlen=20)

    # ---- Protection for an app that is reachable from the internet (ngrok) ----
    # Cap request bodies so nobody can exhaust memory with a huge upload.
    app.config["MAX_CONTENT_LENGTH"] = settings.max_request_bytes

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "That request is too large."}), 413

    @app.before_request
    def _same_origin_writes_only():
        """Block cross-site requests that change data (CSRF).

        Browsers send an Origin header on every cross-site POST. A write from a
        page on another site (even another ngrok address) is refused. The
        Power Automate webhook is server-to-server and carries its own token.
        """
        if request.method in ("GET", "HEAD", "OPTIONS") or request.path == "/api/inbound/outlook":
            return None
        origin = request.headers.get("Origin")
        if origin is None:
            return None  # Not a browser (tests, scripts, Power Automate).
        if origin == "null" or urlparse(origin).netloc != request.host:
            return jsonify({"error": "Cross-site request refused."}), 403
        return None

    @app.after_request
    def _security_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        # No framing (clickjacking), no plugins, forms only post back here.
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
        )
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

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

    def react_dashboard():
        """The built React app (frontend/ builds into static/app/)."""
        if REACT_INDEX.is_file():
            return send_file(REACT_INDEX, mimetype="text/html")
        return (
            "The app is not built yet. Run: cd frontend && npm install && npm run build",
            503,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    @app.get("/")
    def index():
        return react_dashboard()

    @app.get("/api/session")
    def session_info():
        """Who is signed in and which mail source the app was launched with."""
        owner = authenticated_owner()
        token_session = _token_session()
        info = {
            "email": owner,
            "name": _display_name(owner),
            "provider": _mail_source(owner),
            # Students with an account may switch between their flow and a token.
            "canChooseSource": mail_provider == "powerautomate" and not token_session,
            "maxEmails": settings.max_emails,
        }
        if token_session:
            # Their own token, pasted at sign-in, so the app needs no second paste.
            info["graphToken"] = session_graph_token()
        return jsonify(info)

    def _token_session() -> bool:
        return mail_provider == "powerautomate" and is_token_session()

    def _mail_source(owner: str) -> str:
        """Where this student's mail comes from. Only accounts can choose."""
        if mail_provider != "powerautomate" or not owner:
            return mail_provider
        if _token_session():
            return "outlook"
        return profiles.profile_store.source(owner) or mail_provider

    def _display_name(owner: str) -> str:
        """A name chosen in the app, else the one given when the account was made."""
        chosen = profiles.profile_store.name(owner)
        if chosen:
            return chosen
        account = app.extensions.get("multiuser_accounts", {}).get(owner, {})
        if not account and _token_session():
            return str(flask_session.get("graph_name", "")).strip()
        return str(account.get("name", "")).strip()

    @app.post("/api/profile")
    def update_profile():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        owner = _request_user()
        try:
            if "source" in data:
                if mail_provider != "powerautomate" or not owner or _token_session():
                    return jsonify({"error": "The mail source is fixed in this mode."}), 400
                profiles.profile_store.set_source(owner, data["source"])
            if "name" in data or "source" not in data:
                profiles.profile_store.set_name(owner, data.get("name"))
        except ProfileError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"name": _display_name(owner), "provider": _mail_source(owner)})

    @app.get("/api/setup")
    def setup_info():
        """Everything the student types into Power Automate, for their own account.

        The webhook token is a secret, so it is only returned to the signed-in
        owner of that account (responses are never cached).
        """
        owner = _request_user()
        account = app.extensions.get("multiuser_accounts", {}).get(owner)
        if mail_provider != "powerautomate" or not owner or not account:
            return jsonify({"error": "Outlook flow setup is not used in this mode."}), 404

        return jsonify({
            "endpoint": _webhook_endpoint(),
            "email": owner,
            "token": account["webhook_token"],
            "flow_url_saved": bool(account.get("refresh_url")),
        })

    def _webhook_endpoint() -> str:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
        return f"{scheme}://{request.host}/api/inbound/outlook"

    @app.get("/api/setup/flow.zip")
    def setup_flow_package():
        """A ready-made flow with this account's own address, email and token."""
        owner = _request_user()
        account = app.extensions.get("multiuser_accounts", {}).get(owner)
        if mail_provider != "powerautomate" or not owner or not account:
            return jsonify({"error": "Outlook flow setup is not used in this mode."}), 404

        package = build_flow_package(_webhook_endpoint(), owner, account["webhook_token"])
        return send_file(
            io.BytesIO(package),
            mimetype="application/zip",
            as_attachment=True,
            download_name="inbox-sorter-flow.zip",
            max_age=0,
        )

    @app.route("/register/connect", methods=["GET", "POST"], endpoint="register_connect")
    def register_connect():
        """Step 2 of sign-up: connect Outlook before the app opens.

        The account already exists (its flow file carries its own token), but
        the student stays in the sign-up pages until they pick how mail arrives.
        """
        owner = _request_user()
        if mail_provider != "powerautomate" or not is_account(owner):
            return redirect("/")
        account = app.extensions["multiuser_accounts"][owner]

        def page(error: str = "", status: int = 200, notice: str = ""):
            flask_session["connect_csrf"] = secrets.token_hex(32)
            return render_template(
                "connect.html",
                csrf_token=flask_session["connect_csrf"],
                name=_display_name(owner),
                email=owner,
                flow_saved=bool(account.get("refresh_url")),
                error=error,
                notice=notice,
            ), status

        if request.method == "GET":
            return page()

        expected = flask_session.get("connect_csrf", "")
        supplied = str(request.form.get("csrf_token") or "")
        if not expected or not secrets.compare_digest(supplied, expected):
            return page("Your form expired. Please try again.", 400)

        action = request.form.get("action")
        if action == "token":
            profiles.profile_store.set_source(owner, "outlook")
            return redirect("/")
        if action == "flow-url":
            url = str(request.form.get("url") or "").strip()
            problem = flow_url_problem(url) or ("" if url else "Paste the HTTP URL first.")
            if problem:
                return page(problem, 400)
            save_flow_url(owner, url)
            profiles.profile_store.set_source(owner, "powerautomate")
            return page(notice="Saved. Your flow is connected; open the app to see your mail.")
        # "Open the app" (or anything else): go in with Power Automate.
        profiles.profile_store.set_source(owner, "powerautomate")
        return redirect("/")

    @app.get("/api/inbound/diagnostics")
    def inbound_diagnostics():
        """Return only this account's owner-tagged webhook attempts."""
        owner = _request_user()

        if not owner:
            return jsonify({
                "error": "Authentication required.",
            }), 401

        attempts = [
            item
            for item in list(inbound_attempts)
            if item.get("owner") == owner
        ]

        return jsonify({
            "configured": True,
            "endpoint": "/api/inbound/outlook",
            "refresh_configured": bool(refresh_url()),
            "attempts": attempts,
        })
    
    @app.post("/api/inbound/refresh")
    def inbound_refresh():
        """Trigger only the authenticated user's registered flow."""
        owner = _request_user()

        if not owner:
            return jsonify({
                "error": "Authentication required.",
            }), 401

        url = refresh_url()

        if not url:
            return jsonify({
                "error": "No flow is configured for this account.",
            }), 503

        data = request.get_json(silent=True)

        if data is None:
            data = {}

        if not isinstance(data, dict):
            return jsonify({
                "error": "Expected a JSON object.",
            }), 400

        try:
            since = _parse_datetime(data.get("since"))
            before = _parse_datetime(data.get("before"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if since and before and since > before:
            return jsonify({
                "error": "`since` must be earlier than `before`.",
            }), 400

        payload = {"owner": owner}

        if since:
            payload["since"] = since.isoformat()

        if before:
            payload["before"] = before.isoformat()

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=15,
                allow_redirects=False,
            )
        except requests.RequestException:
            return jsonify({
                "error": "Could not reach the Power Automate flow.",
            }), 502

        if not 200 <= response.status_code < 300:
            return jsonify({
                "error": (
                    "Power Automate rejected the refresh request "
                    f"({response.status_code})."
                ),
            }), 502

        return jsonify({
            "requested": True,
            "owner": owner,
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
        return react_dashboard()

    def receive_inbound():
        """Store mail under the owner bound to the webhook token."""
        owner = webhook_owner(_inbound_token())

        if not owner:
            return jsonify({
                "error": "Invalid webhook token.",
            }), 401

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "Expected a JSON object with the email fields.",
            }), 400

        claimed_owner = _inbound_owner(data)

        if claimed_owner and claimed_owner != owner:
            return jsonify({
                "error": "Owner does not match webhook token.",
            }), 403

        email = _inbound_email(data)
        stored, duplicate = pushed_store.add(email, owner)

        return jsonify({
            "status": "duplicate" if duplicate else "stored",
            "id": stored.id,
            "owner": owner,
            "stored": len(pushed_store.all(owner)),
        })

    @app.post("/api/inbound/outlook")
    def inbound_outlook():
        """Receive one Outlook message from a Power Automate HTTP action."""
        return receive_inbound()

    @app.post("/")
    @app.post("/dashboard-v2")
    def inbound_on_wrong_path():
        abort(405)

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

    # Personal calendar events. The store is looked up per request so tests can
    # point ``user_events.event_store`` at a temporary file.
    @app.get("/api/events")
    def list_events():
        return jsonify({"events": user_events.event_store.list(_request_user())})

    @app.post("/api/events")
    def create_event():
        try:
            event = user_events.event_store.create(
                _request_user(), request.get_json(silent=True)
            )
        except EventError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(event), 201

    @app.put("/api/events/<event_id>")
    def update_event(event_id):
        try:
            event = user_events.event_store.update(
                _request_user(), event_id, request.get_json(silent=True)
            )
        except EventError as exc:
            return jsonify({"error": str(exc)}), 400
        if event is None:
            return jsonify({"error": "Event not found."}), 404
        return jsonify(event)

    @app.delete("/api/events/<event_id>")
    def delete_event(event_id):
        if not user_events.event_store.delete(_request_user(), event_id):
            return jsonify({"error": "Event not found."}), 404
        return jsonify({"deleted": True})

    @app.get("/api/item-states")
    def list_item_states():
        return jsonify({"states": item_state_module.item_states.list(_request_user())})

    @app.post("/api/item-states")
    def set_item_state():
        try:
            record = item_state_module.item_states.set(
                _request_user(), request.get_json(silent=True)
            )
        except StateError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"state": record})

    def _feed_urls(token: str) -> dict:
        proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
        host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0].strip()
        path = f"{host}/feed/{token}.ics"
        return {"url": f"{proto}://{path}", "webcal": f"webcal://{path}"}

    @app.get("/api/feed")
    def feed_info():
        return jsonify(_feed_urls(calendar_feed.feed_store.token_for(_request_user())))

    @app.post("/api/feed/rotate")
    def feed_rotate():
        return jsonify(_feed_urls(calendar_feed.feed_store.rotate(_request_user())))

    @app.post("/api/feed/sync")
    def feed_sync():
        data = request.get_json(silent=True)
        try:
            count = calendar_feed.feed_store.set_items(
                _request_user(), (data or {}).get("items") if isinstance(data, dict) else None
            )
        except FeedError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"synced": count})

    @app.get("/feed/<name>")
    def feed_ics(name):
        token = name[:-4] if name.endswith(".ics") else ""
        owner = calendar_feed.feed_store.owner_for(token) if token else None
        if owner is None:
            abort(404)

        items = calendar_feed.feed_store.items(owner)
        for event in user_events.event_store.list(owner):
            items.append({
                "key": f"event:{event['id']}",
                "title": event["title"],
                "date": event["date"],
                "time": event.get("time", ""),
                "detail": event.get("notes", ""),
                "url": "",
            })
        body = calendar_feed.build_ics("Inbox sorter deadlines", items)
        response = app.response_class(body, mimetype="text/calendar")
        response.headers["Content-Disposition"] = 'inline; filename="deadlines.ics"'
        return response

    @app.get("/api/taxonomy")
    def taxonomy():
        return jsonify(
            {"content": CONTENT_CATEGORIES, "reply": REPLY_NATURE, "max_emails": settings.max_emails}
        )

    @app.get("/api/academic-calendar")
    def academic_calendar():
        """NUS term dates and holidays shown beside the email deadline candidates."""
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
        encoder_ready = _encoder_ready()
        ml_ready = _ml_ready()
        hybrid_ready = _ml_ready(("category",)) and _encoder_ready(("action",))
        hybrid_claude_ready = _ml_ready(("category",)) and claude_ready()
        claude_backend_ready = claude_ready()
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
                "encoder_ready": encoder_ready,
                "ml_ready": ml_ready,
                "hybrid_ready": hybrid_ready,
                "hybrid_claude_ready": hybrid_claude_ready,
                "claude_ready": claude_backend_ready,
                "ocr": ocr_status(),
            }
        )

    @app.post("/api/emails")
    def emails():
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
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
            elif kind == "outlook" and not str(credentials.get("token") or "").strip() and _token_session():
                credentials["token"] = session_graph_token()
            provider = build_provider(kind, credentials)
            items = provider.fetch_emails(query)
            items = [prepare_text(email, provider) for email in items]
        except AuthError as exc:
            return jsonify({"error": str(exc)}), 401
        except ProviderError as exc:
            return jsonify({"error": str(exc)}), 502
        # Results the student already has come back with the mail, so a page
        # reload (or reopening the app) shows them at once instead of re-sorting.
        owner = _request_user()
        backend_name = str(data.get("backend") or backend or settings.model_backend)
        corrections = classification_store.correction_store.all_for(owner)
        rules = classification_store.sender_rule_store.all_for(owner)
        cache = classification_store.classify_cache.all_for(owner, backend_name)
        emails_with_deadlines = []
        for email in items:
            serialized = email.model_dump()
            serialized["saved_classification"] = _saved_result(
                email.id, email.sender, backend_name, corrections, rules, cache
            )
            found = extract_deadlines(email)
            serialized["deadline_candidate"] = found[0] if found else None
            serialized["deadline_candidates"] = found
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

    def _saved_result(email_id: str, sender: str, backend_name: str, corrections: dict,
                      rules: dict, cache: dict) -> dict | None:
        """A result the student already has: their correction, their sender
        rule, or a cached model answer (in that order). None when unsorted."""
        fixed = corrections.get(email_id)
        if fixed:
            return {
                "content_category": fixed["content_category"],
                "reply_nature": fixed["reply_nature"],
                "reason": "Corrected by you.",
                "deadline": None,
                "duration_ms": 0,
                "backend": backend_name,
                "model_name": "You",
                "corrected": True,
                "original": {
                    "content_category": fixed["original_category"],
                    "reply_nature": fixed["original_action"],
                },
                "cached": True,
            }
        rule = rules.get(sender_address(sender)) if sender else None
        if rule:
            return {
                "content_category": rule["content_category"],
                "reply_nature": rule["reply_nature"],
                "reason": "Your rule for this sender.",
                "deadline": None,
                "duration_ms": 0,
                "backend": backend_name,
                "model_name": "Your rule",
                "rule": True,
                "cached": True,
            }
        cached = cache.get(email_id)
        return {**cached, "cached": True} if cached else None

    @app.post("/api/classify")
    def classify():
        try:
            data = request.get_json(force=True)
            if not isinstance(data, dict) or not isinstance(data.get("email"), dict):
                return jsonify({"error": "Expected a JSON object with an email."}), 400
            email = Email(**data["email"])
            backend_name = data.get("backend") or backend or settings.model_backend
            owner = _request_user()

            # A student's own correction beats any model result, then their
            # sender rule, then an answer this backend already gave.
            fixed = classification_store.correction_store.get(owner, email.id)
            hit = classification_store.classify_cache.get(owner, backend_name, email.id)
            saved = _saved_result(
                email.id,
                email.sender,
                backend_name,
                {email.id: fixed} if fixed else {},
                classification_store.sender_rule_store.all_for(owner),
                {email.id: hit} if hit else {},
            )
            if saved:
                return jsonify(saved)

            t0 = time.perf_counter()
            rule_category = category_by_rule(email.sender)
            dates = extract_deadlines(email) if not rule_category else []
            coursework = (
                None
                if rule_category
                else coursework_by_rule(
                    email.subject,
                    email.body or email.preview,
                    bool(dates),
                    bool(dates) and dates[0]["event_type"] == "exam",
                )
            )
            if coursework:
                model_name = "Course rule (model skipped)"
                result = Classification(
                    content_category=coursework[0],
                    reply_nature=coursework[1],
                    deadline=None,
                    reason=coursework[2],
                )
            elif rule_category:
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
            classification_store.classify_cache.put(owner, backend_name, email.id, out)
            return jsonify(out)
        except Exception as exc:  # most often: Ollama not running or model not pulled
            logging.exception("classification failed")
            return jsonify({"error": f"Classification failed: {exc}"}), 500

    @app.post("/api/draft-reply")
    def draft_reply():
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("email"), dict):
            return jsonify({"error": "Expected a JSON object with an email."}), 400
        try:
            email = Email(**data["email"])
        except Exception as exc:
            return jsonify({"error": f"Invalid email: {exc}"}), 400

        owner = _request_user()
        try:
            result = generate_reply(email, owner, _display_name(owner))
        except ReplyDraftError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        except Exception as exc:
            logging.exception("reply drafting failed")
            return jsonify({"error": f"Drafting failed: {exc}"}), 502
        return jsonify(result)

    @app.post("/api/corrections")
    def save_correction():
        owner = _request_user()
        payload = request.get_json(silent=True)
        try:
            record = classification_store.correction_store.save(owner, payload)
            if payload.get("remember_sender"):
                classification_store.sender_rule_store.set(
                    owner,
                    record["sender_key"],
                    record["content_category"],
                    record["reply_nature"],
                )
                classification_store.correction_store.mark_rule(owner, record["id"])
        except CorrectionError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "saved": True,
            "id": record["id"],
            "rule": bool(payload.get("remember_sender")),
        }), 201

    @app.delete("/api/corrections/<path:email_id>")
    def delete_correction(email_id):
        owner = _request_user()
        record = classification_store.correction_store.delete(owner, email_id)
        if record is None:
            return jsonify({"error": "No correction for this email."}), 404
        # Undoing the fix also removes the rule it created.
        if record.get("rule") and record.get("sender_key"):
            classification_store.sender_rule_store.delete(owner, record["sender_key"])
        return jsonify({"deleted": True})

    @app.delete("/api/sender-rules")
    def delete_sender_rule():
        sender = sender_address(request.args.get("sender", ""))
        if not classification_store.sender_rule_store.delete(_request_user(), sender):
            return jsonify({"error": "No rule for this sender."}), 404
        return jsonify({"deleted": True})

    return app
