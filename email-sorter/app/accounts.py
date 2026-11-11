"""Small-team HTTPS demo authentication with a login page; not an SSO implementation."""
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
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

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

    def wait_seconds(self, email: str, client: str) -> int:
        """Seconds until sign-in is allowed again; ``0`` when it is allowed now."""
        now = self._clock()
        with self._lock:
            waits = []
            for bucket, limit in (
                (self._emails.get(email), self.per_email),
                (self._clients.get(client), self.per_client),
            ):
                if bucket is None:
                    continue
                self._trim(bucket, now)
                if len(bucket) >= limit:
                    waits.append(self.window - (now - bucket[0]))
            return int(max(waits)) + 1 if waits else 0

    def record_failure(self, email: str, client: str) -> None:
        now = self._clock()
        with self._lock:
            self._emails[email].append(now)
            self._clients[client].append(now)

    def record_success(self, email: str) -> None:
        with self._lock:
            self._emails.pop(email, None)


SESSION_OWNER_KEY = "mail_owner"
# Paths that do not carry dashboard identity: the login page itself, the
# sign-out action, and the Power Automate webhook (authenticated by its token).
PUBLIC_PATHS = {"/login", "/login/token", "/logout", "/register", "/api/inbound/outlook", "/api/inbound/refresh-done"}

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
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
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
            _write_accounts(path, stored)
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


def _safe_next(value) -> str:
    """Only allow same-site relative paths as post-login redirects."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _signup_settings() -> dict:
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


def _write_accounts(path: Path, data: dict) -> None:
    """Replace the accounts file in one step, readable only by this user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def install_multiuser(app):
    configured = os.getenv("MULTIUSER_CONFIG_FILE", "").strip()
    if not configured:
        raise RuntimeError("Set MULTIUSER_CONFIG_FILE to your private accounts JSON file.")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(app.root_path).parent / path
    signup = _signup_settings()
    if not path.exists() and signup["enabled"]:
        _write_accounts(path, {})
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or (not raw and not signup["enabled"]):
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
    app.extensions["multiuser_accounts"] = accounts
    app.extensions["multiuser_path"] = path
    accounts_lock = Lock()
    app.extensions["multiuser_lock"] = accounts_lock

    app.secret_key = _session_secret(app)
    app.config.update(
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Opt in once the app is only used over HTTPS (for example the ngrok URL);
        # Safari will not send a Secure cookie to plain http://127.0.0.1.
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"},
    )
    limiter = LoginLimiter()

    def client_address() -> str:
        # Behind ngrok the last X-Forwarded-For entry is the address ngrok saw.
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        return forwarded or request.remote_addr or "unknown"

    def session_owner() -> str:
        email = str(session.get(SESSION_OWNER_KEY) or "").strip().lower()
        # A token sign-in has no account record; Graph vouched for the address.
        return email if email in accounts or (email and is_token_session()) else ""

    def basic_owner() -> str:
        # Tooling (tests, scripts) may still send HTTP Basic credentials.
        # We never advertise the Basic scheme, so browsers show the login
        # page instead of the popup.
        auth = request.authorization
        owner = str(auth.username or "").strip().lower() if auth else ""
        record = accounts.get(owner)
        valid = bool(
            auth and auth.type.lower() == "basic" and record
            and check_password_hash(record["password_hash"], auth.password or "")
        )
        return owner if valid else ""

    @app.before_request
    def require_identity():
        # Only the canonical ingestion route uses webhook credentials.
        # Calendar apps cannot sign in, so the feed is guarded by its secret token.
        if request.path in PUBLIC_PATHS or request.path.startswith("/feed/") or request.endpoint == "static":
            return None
        owner = session_owner() or basic_owner()
        if not owner:
            if request.path.startswith("/api/") or request.method == "POST":
                return jsonify(error="Please sign in again.", login_url=url_for("login")), 401
            next_url = request.path
            if request.query_string:
                next_url = f"{next_url}?{request.query_string.decode('utf-8', 'replace')}"
            return redirect(url_for("login", next=next_url))
        g.mail_owner = owner
        supplied = request.headers.get("X-User-Email", "").strip().lower()
        if supplied and supplied != owner:
            return jsonify(error="Mailbox email must match the authenticated account. Switch the dashboard email or sign in with the correct account."), 403
        return None

    def login_page_flags() -> dict:
        settings = _signup_settings()
        return {
            "signup": settings["enabled"],
            "token_login": token_login_enabled(),
            "token_needs_code": bool(settings["code"]),
        }

    @app.post("/login/token", endpoint="login_token")
    def login_with_token():
        """Sign in with a Graph token instead of an account."""
        next_url = _safe_next(request.form.get("next"))
        csrf_expected = session.get("login_csrf", "")
        csrf_supplied = str(request.form.get("csrf_token") or "")
        token = "".join(str(request.form.get("token") or "").split())
        if token.lower().startswith("bearer"):
            token = token[6:]
        code = str(request.form.get("code") or "").strip()
        session.permanent = True
        session["login_csrf"] = secrets.token_hex(32)

        def fail(message: str, status: int = 401):
            return render_template(
                "login.html",
                csrf_token=session["login_csrf"],
                next_url=next_url,
                error=message,
                token_open=True,
                **login_page_flags(),
            ), status

        if not token_login_enabled():
            return fail("Signing in with a token is turned off here.", 403)
        if not csrf_expected or not secrets.compare_digest(csrf_supplied, csrf_expected):
            return fail("Your form expired. Please try again.")
        client = client_address()
        wait = limiter.wait_seconds("", client)
        if wait:
            minutes = max(1, round(wait / 60))
            return fail(f"Too many failed attempts. Try again in about {minutes} minutes.", 429)
        if not token or len(token) > 8000:
            return fail("Paste the access token from Graph Explorer.", 400)
        settings = _signup_settings()
        if settings["code"] and not secrets.compare_digest(code, settings["code"]):
            limiter.record_failure("", client)
            return fail("That sign-up code is not right.", 400)
        try:
            email, name = graph_identity(token)
        except GraphLoginError as exc:
            limiter.record_failure("", client)
            return fail(str(exc))
        domain = email.rsplit("@", 1)[-1]
        if settings["domains"] and domain not in settings["domains"]:
            allowed = " or ".join("@" + item for item in settings["domains"])
            return fail(f"Use a token from your university account ({allowed}).", 403)

        session.clear()
        session.permanent = True
        session[SESSION_OWNER_KEY] = email
        session[TOKEN_SESSION_KEY] = graph_tokens.put(token)
        if name:
            session["graph_name"] = name
        return redirect(next_url)

    @app.route("/login", methods=["GET", "POST"], endpoint="login")
    def login():
        owner = session_owner()
        if request.method == "GET":
            if owner:
                return redirect(_safe_next(request.args.get("next")))
            csrf_token = secrets.token_hex(32)
            session.permanent = True
            session["login_csrf"] = csrf_token
            return render_template(
                "login.html",
                csrf_token=csrf_token,
                next_url=_safe_next(request.args.get("next")),
                error="",
                **login_page_flags(),
            )

        email = str(request.form.get("email") or "").strip().lower()
        password = str(request.form.get("password") or "")
        next_url = _safe_next(request.form.get("next") or request.args.get("next"))
        csrf_expected = session.get("login_csrf", "")
        csrf_supplied = str(request.form.get("csrf_token") or "")
        session.permanent = True
        session["login_csrf"] = secrets.token_hex(32)

        def fail(message: str, status: int = 401):
            return render_template(
                "login.html",
                csrf_token=session["login_csrf"],
                next_url=next_url,
                error=message,
                email=email,
                **login_page_flags(),
            ), status

        if not csrf_expected or not secrets.compare_digest(csrf_supplied, csrf_expected):
            return fail("Your form expired. Please try again.")
        client = client_address()
        wait = limiter.wait_seconds(email, client)
        if wait:
            minutes = max(1, round(wait / 60))
            response = fail(
                f"Too many failed attempts. Try again in about {minutes} minute{'s' if minutes != 1 else ''}.",
                429,
            )
            return response
        record = accounts.get(email)
        # The fixed pause makes quick password guessing awkward over one tunnel.
        valid = bool(record)
        if valid:
            valid = check_password_hash(record["password_hash"], password)
        if not valid:
            limiter.record_failure(email, client)
            time.sleep(0.5)
            return fail("Email or password is incorrect.")
        limiter.record_success(email)
        # Rotate the session so the pre-login CSRF id is never reused.
        session.clear()
        session.permanent = True
        session[SESSION_OWNER_KEY] = email
        return redirect(next_url)

    # Accounts made from one address are capped per hour, so nobody can create
    # them in bulk. Typos do not count; a campus network shares one address.
    signup_limiter = LoginLimiter(per_email=10**6, per_client=10, window=60 * 60)

    def render_signup(error: str = "", status: int = 200, **values):
        session["signup_csrf"] = secrets.token_hex(32)
        settings = _signup_settings()
        return render_template(
            "register.html",
            csrf_token=session["signup_csrf"],
            error=error,
            domains=settings["domains"],
            needs_code=bool(settings["code"]),
            **values,
        ), status

    @app.route("/register", methods=["GET", "POST"], endpoint="register")
    def register():
        settings = _signup_settings()
        if not settings["enabled"]:
            return redirect(url_for("login"))
        if session_owner():
            # Already signed in: carry on with step 2 (connect Outlook).
            return redirect(url_for("account.register_connect") if not is_token_session() else "/")
        if request.method == "GET":
            session.permanent = True
            return render_signup()

        email = str(request.form.get("email") or "").strip().lower()
        name = " ".join(str(request.form.get("name") or "").split())[:40]
        password = str(request.form.get("password") or "")
        confirm = str(request.form.get("confirm") or "")
        code = str(request.form.get("code") or "").strip()
        expected = session.get("signup_csrf", "")
        supplied = str(request.form.get("csrf_token") or "")
        keep = {"email": email, "name": name}

        if not expected or not secrets.compare_digest(supplied, expected):
            return render_signup("Your form expired. Please try again.", 400, **keep)

        client = client_address()
        wait = signup_limiter.wait_seconds("", client)
        if wait:
            minutes = max(1, round(wait / 60))
            return render_signup(
                f"Too many sign-ups from here. Try again in about {minutes} minutes.", 429, **keep
            )
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if not email or "@" not in email or " " in email or len(email) > 120:
            return render_signup("Enter a valid email address.", 400, **keep)
        if settings["domains"] and domain not in settings["domains"]:
            allowed = " or ".join("@" + item for item in settings["domains"])
            return render_signup(f"Use your university email ({allowed}).", 400, **keep)
        if settings["code"] and not secrets.compare_digest(code, settings["code"]):
            return render_signup("That sign-up code is not right.", 400, **keep)
        if len(password) < 8:
            return render_signup("Use a password with at least 8 characters.", 400, **keep)
        if password != confirm:
            return render_signup("The two passwords do not match.", 400, **keep)

        with accounts_lock:
            if email in accounts:
                return render_signup(
                    "An account with this email already exists. Sign in instead.", 400, **keep
                )
            record = {
                "password_hash": generate_password_hash(password),
                "webhook_token": secrets.token_urlsafe(32),
                "refresh_url": "",
            }
            if name:
                record["name"] = name
            path = app.extensions["multiuser_path"]
            stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            stored[email] = record
            _write_accounts(path, stored)
            accounts[email] = record
        signup_limiter.record_failure("", client)

        session.clear()
        session.permanent = True
        session[SESSION_OWNER_KEY] = email
        # Step 2 of sign-up: connect Outlook before opening the app.
        return redirect(url_for("account.register_connect"))

    @app.post("/api/setup/flow-url")
    def save_flow_url_api():
        """Save the HTTP address of the student's imported flow (JSON)."""
        owner = authenticated_owner()
        data = request.get_json(silent=True) if request.is_json else None
        if not owner or owner not in accounts or not isinstance(data, dict):
            return jsonify(error="Expected a JSON object."), 400
        url = str(data.get("url") or "").strip()
        problem = flow_url_problem(url)
        if problem:
            return jsonify(error=problem), 400
        save_flow_url(owner, url)
        return jsonify(saved=bool(url))

    @app.post("/logout")
    def logout():
        graph_tokens.drop(session.get(TOKEN_SESSION_KEY, ""))
        session.clear()
        return redirect(url_for("login"))

    @app.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
