"""Sign-in for a small team over HTTPS (not an SSO implementation).

This module holds the account data, sessions, Graph-token sign-in and the
request guard. The sign-in pages themselves are in ``app/routes/auth.py``.
"""
import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests
from flask import (
    current_app,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from app.mail.text_utils import strip_bearer

# ---- failed sign-in limit ---------------------------------------------------
# Failures are counted per email and per client address in a sliding window.
# While either is over its limit, sign-in is refused, even with the right
# password, until the oldest failure leaves the window. Counts live in memory.
WINDOW_SECONDS = 15 * 60
MAX_PER_EMAIL = 5
MAX_PER_CLIENT = 20


class LoginLimiter:
    def __init__(
        self,
        window: float = WINDOW_SECONDS,
        per_email: int = MAX_PER_EMAIL,
        per_client: int = MAX_PER_CLIENT,
        clock=time.monotonic,
    ):
        self.window = window
        self.per_email = per_email
        self.per_client = per_client
        self._clock = clock
        self._lock = Lock()
        self._emails: dict[str, deque[float]] = defaultdict(deque)
        self._clients: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, bucket: deque[float], now: float) -> None:
        while bucket and now - bucket[0] >= self.window:
            bucket.popleft()

    def wait_seconds(self, email: str | None, client: str) -> int:
        """Seconds until sign-in is allowed again; ``0`` when it is allowed now.

        ``email=None`` (a token sign-in, a sign-up) checks only the client limit,
        so failures from different people are never pooled under one key.
        """
        now = self._clock()
        with self._lock:
            waits = []
            for bucket, limit in (
                (self._emails.get(email) if email else None, self.per_email),
                (self._clients.get(client), self.per_client),
            ):
                if bucket is None:
                    continue
                self._trim(bucket, now)
                if len(bucket) >= limit:
                    waits.append(self.window - (now - bucket[0]))
            return int(max(waits)) + 1 if waits else 0

    def record_failure(self, email: str | None, client: str) -> None:
        now = self._clock()
        with self._lock:
            if email:
                self._emails[email].append(now)
            self._clients[client].append(now)

    def record_success(self, email: str) -> None:
        with self._lock:
            self._emails.pop(email, None)


SESSION_OWNER_KEY = "mail_owner"
# Paths that do not carry dashboard identity: the login page itself, the
# sign-out action, and the Power Automate calls (authenticated by their token).
PUBLIC_PATHS = {
    "/login", "/login/token", "/logout", "/register",
    "/api/inbound/outlook", "/api/inbound/refresh-done",
}

# ---- sign in with an Outlook (Microsoft Graph) token -----------------------
# A student may skip the account and paste a Graph token instead. Graph itself
# checks the token (GET /me), which also tells us whose mailbox it is. The token
# stays in server memory under a random id; only that id goes in the cookie.
TOKEN_SESSION_KEY = "graph_session"
GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName,displayName"
GRAPH_TOKEN_TTL = 2 * 60 * 60  # Graph tokens last about an hour.


class GraphTokenStore:
    def __init__(self):
        self._items: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    def put(self, token: str) -> str:
        key = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v[1] > now}
            self._items[key] = (token, now + GRAPH_TOKEN_TTL)
        return key

    def get(self, key: str) -> str:
        with self._lock:
            item = self._items.get(key or "")
        return item[0] if item and item[1] > time.monotonic() else ""

    def drop(self, key: str) -> None:
        with self._lock:
            self._items.pop(key or "", None)


graph_tokens = GraphTokenStore()


class GraphLoginError(ValueError):
    """The token was not accepted; the message is safe to show."""


def graph_identity(token: str) -> tuple[str, str]:
    """Return (email, display name) of the mailbox the token belongs to."""
    try:
        response = requests.get(
            GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise GraphLoginError("Could not reach Microsoft. Check your connection and try again.") from exc
    if response.status_code == 401:
        raise GraphLoginError("That token is not valid or has expired. Copy a fresh one from Graph Explorer.")
    if response.status_code != 200:
        raise GraphLoginError(
            f"Microsoft did not accept the token ({response.status_code}). Make sure it is the Graph Explorer access token."
        )
    data = response.json() if response.content else {}
    email = str(data.get("mail") or data.get("userPrincipalName") or "").strip().lower()
    if "@" not in email:
        raise GraphLoginError("Could not find the email address for this token.")
    name = " ".join(str(data.get("displayName") or "").split())[:40]
    return email, name


def is_token_session() -> bool:
    return bool(session.get(TOKEN_SESSION_KEY))


def session_graph_token() -> str:
    return graph_tokens.get(session.get(TOKEN_SESSION_KEY, ""))


def remember_session_graph_token(token: str) -> None:
    """Keep a send token in server memory under the signed-in session."""
    token = strip_bearer(token)
    if not token:
        return
    previous = session.get(TOKEN_SESSION_KEY, "")
    session[TOKEN_SESSION_KEY] = graph_tokens.put(token)
    if previous:
        graph_tokens.drop(previous)


def token_login_enabled() -> bool:
    return os.getenv("ALLOW_TOKEN_LOGIN", "1").strip().lower() not in {"0", "false", "no"}


SESSION_LIFETIME = timedelta(hours=12)
# Where Power Automate "When a HTTP request is received" trigger URLs live.
FLOW_URL_HOSTS = (".logic.azure.com", ".powerplatform.com")


def flow_url_problem(url: str) -> str:
    """Why ``url`` cannot be a flow trigger address, or "" when it is fine.

    The app later POSTs to it to ask for new mail, so only Power Automate
    addresses are accepted: the server never calls arbitrary URLs.
    """
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
        or not host.endswith(FLOW_URL_HOSTS) or len(url) > 2000
    ):
        return (
            "Paste the HTTP URL from your flow's trigger. It starts with https:// and "
            "ends in logic.azure.com or powerplatform.com."
        )
    return ""


def save_flow_url(owner: str, url: str) -> None:
    """Store an already checked flow address for ``owner`` (file and memory)."""
    app_accounts = current_app.extensions["multiuser_accounts"]
    with current_app.extensions["multiuser_lock"]:
        path = current_app.extensions["multiuser_path"]
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if owner in stored:
            stored[owner]["refresh_url"] = url
            write_accounts(path, stored)
        app_accounts[owner]["refresh_url"] = url


def is_account(owner: str) -> bool:
    """A password account (not a token sign-in)."""
    return bool(owner) and owner in current_app.extensions.get("multiuser_accounts", {}) and not is_token_session()


def users():
    # Empty in the no-login (Graph token) mode, where nobody can push mail.
    return current_app.extensions.get("multiuser_accounts", {})


def authenticated_owner():
    return getattr(g, "mail_owner", "")


def webhook_owner(token):
    if not token:
        return ""
    for email, record in users().items():
        if secrets.compare_digest(token, record["webhook_token"]):
            return email
    return ""


def refresh_url():
    return users().get(authenticated_owner(), {}).get("refresh_url", "")


def _session_secret(app) -> str:
    """Stable session-signing key so logins survive app restarts."""
    configured = os.getenv("SESSION_SECRET", "").strip()
    if configured:
        return configured
    path = Path(app.root_path).parent / "private" / "session_secret"
    if path.is_file():
        secret = path.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)
    return secret


def safe_next(value) -> str:
    """Only allow same-site relative paths as post-login redirects."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def signup_settings() -> dict:
    """Self sign-up: on by default, limited to university addresses.

    ALLOW_SIGNUP=0 turns it off. ALLOWED_EMAIL_DOMAINS is a comma list.
    SIGNUP_CODE, when set, must be typed in, so only people you give it to
    can make an account.
    """
    domains = os.getenv("ALLOWED_EMAIL_DOMAINS", "u.nus.edu,nus.edu.sg")
    return {
        "enabled": os.getenv("ALLOW_SIGNUP", "1").strip().lower() not in {"0", "false", "no"},
        "domains": [item.strip().lower().lstrip("@") for item in domains.split(",") if item.strip()],
        "code": os.getenv("SIGNUP_CODE", "").strip(),
    }


def write_accounts(path: Path, data: dict) -> None:
    """Replace the accounts file in one step, readable only by this user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


# ---- who is asking ----------------------------------------------------------

def client_address() -> str:
    # Behind ngrok the last X-Forwarded-For entry is the address ngrok saw.
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
    return forwarded or request.remote_addr or "unknown"


def session_owner() -> str:
    email = str(session.get(SESSION_OWNER_KEY) or "").strip().lower()
    # A token sign-in has no account record; Graph vouched for the address.
    return email if email in users() or (email and is_token_session()) else ""


def sign_in(email: str) -> None:
    """Start a fresh session for ``email`` (rotated, so a pre-login id is never reused)."""
    session.clear()
    session.permanent = True
    session[SESSION_OWNER_KEY] = email


def _require_identity():
    # Only the canonical ingestion route uses webhook credentials.
    # Calendar apps cannot sign in, so the feed is guarded by its secret token.
    if request.path in PUBLIC_PATHS or request.path.startswith("/feed/") or request.endpoint == "static":
        return None
    # Only a session from the sign-in pages counts, so every password check goes
    # through their attempt limit (no HTTP Basic credentials on API calls).
    owner = session_owner()
    if not owner:
        if request.path.startswith("/api/") or request.method == "POST":
            return jsonify(error="Please sign in again.", login_url=url_for("auth.login")), 401
        next_url = request.path
        if request.query_string:
            next_url = f"{next_url}?{request.query_string.decode('utf-8', 'replace')}"
        return redirect(url_for("auth.login", next=next_url))
    g.mail_owner = owner
    supplied = request.headers.get("X-User-Email", "").strip().lower()
    if supplied and supplied != owner:
        return jsonify(error="Mailbox email must match the authenticated account. Switch the dashboard email or sign in with the correct account."), 403
    return None


def _private_response(response):
    # Static files are public and versioned (?v=), so let the browser cache them.
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ---- setup -------------------------------------------------------------------

def _load_accounts(path: Path, signup_enabled: bool) -> dict:
    """Read and check the accounts file; refuse to start on anything unsafe."""
    if not path.exists() and signup_enabled:
        write_accounts(path, {})
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or (not raw and not signup_enabled):
        raise RuntimeError("The multi-user accounts file must be a non-empty object.")
    accounts = {}
    tokens = set()
    for key, record in raw.items():
        email = str(key).strip().lower()
        if "@" not in email or email in accounts or not isinstance(record, dict):
            raise RuntimeError("Invalid or duplicate account in multi-user configuration.")
        password_hash = record.get("password_hash", "")
        token = record.get("webhook_token", "")
        url = record.get("refresh_url", "")
        if not isinstance(password_hash, str) or not password_hash.startswith(("scrypt:", "pbkdf2:")):
            raise RuntimeError("Use a Werkzeug-generated password hash for every account.")
        if not isinstance(token, str) or len(token) < 32 or token in tokens:
            raise RuntimeError("Every account needs a distinct, random webhook token (32+ characters).")
        if not isinstance(url, str):
            raise RuntimeError("refresh_url must be a string.")
        if url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise RuntimeError("Refresh URLs must be HTTPS URLs without userinfo or fragments.")
        tokens.add(token)
        accounts[email] = dict(record)
    return accounts


def install_multiuser(app) -> None:
    """Load the accounts, require sign-in on every request, and add the sign-in pages."""
    from app.routes.auth import bp as auth_pages  # noqa: PLC0415 - the pages import this module
    # Default: private/multiuser.json, created empty on first start when sign-up is on.
    configured = os.getenv("MULTIUSER_CONFIG_FILE", "").strip() or "private/multiuser.json"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(app.root_path).parent / path

    app.extensions["multiuser_accounts"] = _load_accounts(path, signup_settings()["enabled"])
    app.extensions["multiuser_path"] = path
    app.extensions["multiuser_lock"] = Lock()
    app.extensions["login_limiter"] = LoginLimiter()
    # Accounts made from one address are capped per hour, so nobody can create
    # them in bulk. Typos do not count; a campus network shares one address.
    app.extensions["signup_limiter"] = LoginLimiter(per_client=10, window=60 * 60)

    app.secret_key = _session_secret(app)
    app.config.update(
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
        SEND_FILE_MAX_AGE_DEFAULT=3600,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Opt in once the app is only used over HTTPS (for example the ngrok URL);
        # Safari will not send a Secure cookie to plain http://127.0.0.1.
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"},
    )
    app.before_request(_require_identity)
    app.after_request(_private_response)
    app.register_blueprint(auth_pages)
