"""Sign-in pages: password login, Outlook-token login, sign-up and sign-out.

Registered by ``install_multiuser`` (Power Automate mode only).
"""

from __future__ import annotations

import json
import secrets
import time

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.accounts import (
    TOKEN_SESSION_KEY,
    GraphLoginError,
    client_address,
    graph_identity,
    graph_tokens,
    is_token_session,
    safe_next,
    session_owner,
    sign_in,
    signup_settings,
    token_login_enabled,
    users,
    write_accounts,
)

bp = Blueprint("auth", __name__)


def _login_page_flags() -> dict:
    settings = signup_settings()
    return {
        "signup": settings["enabled"],
        "token_login": token_login_enabled(),
        "token_needs_code": bool(settings["code"]),
    }


def _new_csrf(key: str) -> str:
    session.permanent = True
    session[key] = secrets.token_hex(32)
    return session[key]


def _csrf_ok(expected: str) -> bool:
    supplied = str(request.form.get("csrf_token") or "")
    return bool(expected) and secrets.compare_digest(supplied, expected)


def _wait_message(wait: int, plural_minutes: bool = True) -> str:
    minutes = max(1, round(wait / 60))
    unit = "minutes" if plural_minutes or minutes != 1 else "minute"
    return f"Try again in about {minutes} {unit}."


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session_owner():
            return redirect(safe_next(request.args.get("next")))
        return render_template(
            "login.html",
            csrf_token=_new_csrf("login_csrf"),
            next_url=safe_next(request.args.get("next")),
            error="",
            **_login_page_flags(),
        )

    email = str(request.form.get("email") or "").strip().lower()
    password = str(request.form.get("password") or "")
    next_url = safe_next(request.form.get("next") or request.args.get("next"))
    expected = session.get("login_csrf", "")
    csrf_token = _new_csrf("login_csrf")

    def fail(message: str, status: int = 401):
        return render_template(
            "login.html",
            csrf_token=csrf_token,
            next_url=next_url,
            error=message,
            email=email,
            **_login_page_flags(),
        ), status

    if not _csrf_ok(expected):
        return fail("Your form expired. Please try again.")
    limiter = current_app.extensions["login_limiter"]
    client = client_address()
    wait = limiter.wait_seconds(email, client)
    if wait:
        return fail(f"Too many failed attempts. {_wait_message(wait, plural_minutes=False)}", 429)
    record = users().get(email)
    valid = bool(record) and check_password_hash(record["password_hash"], password)
    if not valid:
        limiter.record_failure(email, client)
        # The fixed pause makes quick password guessing awkward over one tunnel.
        time.sleep(0.5)
        return fail("Email or password is incorrect.")
    limiter.record_success(email)
    sign_in(email)
    return redirect(next_url)


@bp.post("/login/token")
def login_token():
    """Sign in with a Graph token instead of an account."""
    next_url = safe_next(request.form.get("next"))
    expected = session.get("login_csrf", "")
    token = "".join(str(request.form.get("token") or "").split())
    if token.lower().startswith("bearer"):
        token = token[6:]
    code = str(request.form.get("code") or "").strip()
    csrf_token = _new_csrf("login_csrf")

    def fail(message: str, status: int = 401):
        return render_template(
            "login.html",
            csrf_token=csrf_token,
            next_url=next_url,
            error=message,
            token_open=True,
            **_login_page_flags(),
        ), status

    if not token_login_enabled():
        return fail("Signing in with a token is turned off here.", 403)
    if not _csrf_ok(expected):
        return fail("Your form expired. Please try again.")
    limiter = current_app.extensions["login_limiter"]
    client = client_address()
    wait = limiter.wait_seconds(None, client)
    if wait:
        return fail(f"Too many failed attempts. {_wait_message(wait)}", 429)
    if not token or len(token) > 8000:
        return fail("Paste the access token from Graph Explorer.", 400)
    settings = signup_settings()
    if settings["code"] and not secrets.compare_digest(code, settings["code"]):
        limiter.record_failure(None, client)
        return fail("That sign-up code is not right.", 400)
    try:
        email, name = graph_identity(token)
    except GraphLoginError as exc:
        limiter.record_failure(None, client)
        return fail(str(exc))
    domain = email.rsplit("@", 1)[-1]
    if settings["domains"] and domain not in settings["domains"]:
        allowed = " or ".join("@" + item for item in settings["domains"])
        return fail(f"Use a token from your university account ({allowed}).", 403)

    sign_in(email)
    session[TOKEN_SESSION_KEY] = graph_tokens.put(token)
    if name:
        session["graph_name"] = name
    return redirect(next_url)


def _render_signup(error: str = "", status: int = 200, **values):
    settings = signup_settings()
    return render_template(
        "register.html",
        csrf_token=_new_csrf("signup_csrf"),
        error=error,
        domains=settings["domains"],
        needs_code=bool(settings["code"]),
        **values,
    ), status


def _signup_problem(email: str, password: str, confirm: str, code: str, settings: dict) -> str:
    """Why this sign-up cannot go ahead, or "" when it can."""
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if not email or "@" not in email or " " in email or len(email) > 120:
        return "Enter a valid email address."
    if settings["domains"] and domain not in settings["domains"]:
        allowed = " or ".join("@" + item for item in settings["domains"])
        return f"Use your university email ({allowed})."
    if settings["code"] and not secrets.compare_digest(code, settings["code"]):
        return "That sign-up code is not right."
    if len(password) < 8:
        return "Use a password with at least 8 characters."
    if password != confirm:
        return "The two passwords do not match."
    return ""


@bp.route("/register", methods=["GET", "POST"])
def register():
    settings = signup_settings()
    if not settings["enabled"]:
        return redirect(url_for("auth.login"))
    if session_owner():
        # Already signed in: carry on with step 2 (connect Outlook).
        return redirect(url_for("account.register_connect") if not is_token_session() else "/")
    if request.method == "GET":
        session.permanent = True
        return _render_signup()

    email = str(request.form.get("email") or "").strip().lower()
    name = " ".join(str(request.form.get("name") or "").split())[:40]
    password = str(request.form.get("password") or "")
    confirm = str(request.form.get("confirm") or "")
    code = str(request.form.get("code") or "").strip()
    keep = {"email": email, "name": name}

    if not _csrf_ok(session.get("signup_csrf", "")):
        return _render_signup("Your form expired. Please try again.", 400, **keep)

    limiter = current_app.extensions["signup_limiter"]
    client = client_address()
    wait = limiter.wait_seconds(None, client)
    if wait:
        return _render_signup(f"Too many sign-ups from here. {_wait_message(wait)}", 429, **keep)
    problem = _signup_problem(email, password, confirm, code, settings)
    if problem:
        return _render_signup(problem, 400, **keep)

    accounts = users()
    with current_app.extensions["multiuser_lock"]:
        if email in accounts:
            return _render_signup("An account with this email already exists. Sign in instead.", 400, **keep)
        record = {
            "password_hash": generate_password_hash(password),
            "webhook_token": secrets.token_urlsafe(32),
            "refresh_url": "",
        }
        if name:
            record["name"] = name
        path = current_app.extensions["multiuser_path"]
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        stored[email] = record
        write_accounts(path, stored)
        accounts[email] = record
    limiter.record_failure(None, client)

    sign_in(email)
    # Step 2 of sign-up: connect Outlook before opening the app.
    return redirect(url_for("account.register_connect"))


@bp.post("/logout")
def logout():
    graph_tokens.drop(session.get(TOKEN_SESSION_KEY, ""))
    session.clear()
    return redirect(url_for("auth.login"))

