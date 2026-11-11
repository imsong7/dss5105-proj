"""Flask app factory with pluggable classifier backends.

Usage::

    from app.server import create_app

    app = create_app(backend="encoder")   # text-encoder backend; or "llama", or None

The routes live in ``app/routes/`` (one blueprint per area). This module only
builds the app: sign-in, protection for an internet-facing app, the dashboard
pages and the error pages.
"""

import logging
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, render_template, request, send_file

from app.accounts import install_multiuser
from app.config import ROOT, settings
from app.routes import SorterState, register_blueprints
from app.routes.inbound import TOKEN_PATHS, WEBHOOK_PATH

logging.basicConfig(level=logging.INFO)

# Output of ``npm run build`` in frontend/. Checked per request, so building
# while the server runs takes effect without a restart.
REACT_INDEX = ROOT / "static" / "app" / "index.html"

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

    app.extensions["sorter"] = SorterState(default_backend=backend, mail_provider=mail_provider)
    _install_protection(app)
    _install_pages(app)
    register_blueprints(app)
    return app


def _install_protection(app: Flask) -> None:
    """Protection for an app that is reachable from the internet (ngrok)."""
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
        if request.method in ("GET", "HEAD", "OPTIONS") or request.path in TOKEN_PATHS:
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


def _react_dashboard():
    """The built React app (frontend/ builds into static/app/)."""
    if REACT_INDEX.is_file():
        return send_file(REACT_INDEX, mimetype="text/html")
    return (
        "The app is not built yet. Run: cd frontend && npm install && npm run build",
        503,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


def _install_pages(app: Flask) -> None:
    """The dashboard pages and a helpful 405 page."""

    @app.get("/")
    def index():
        return _react_dashboard()

    @app.get("/dashboard-v2")
    def dashboard_v2():
        return _react_dashboard()

    @app.post("/")
    @app.post("/dashboard-v2")
    def inbound_on_wrong_path():
        abort(405)

    @app.errorhandler(405)
    def method_not_allowed(_error):
        """Explain a wrong method instead of Flask's bare 405 page."""
        path = request.path
        if path == WEBHOOK_PATH:
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
                    f"{WEBHOOK_PATH} to the end of the tunnel URL in the HTTP "
                    "action's URI."
                )
        preferred = request.accept_mimetypes.best_match(["application/json", "text/html"])
        if preferred == "application/json":
            return jsonify({"error": message, "methods": ["POST"]}), 405
        return render_template("method_not_allowed.html", path=path, message=message), 405
