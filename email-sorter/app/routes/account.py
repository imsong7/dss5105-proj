"""Who is signed in, their profile, and connecting their Power Automate flow."""

from __future__ import annotations

import io
import secrets

from flask import Blueprint, jsonify, redirect, render_template, request, send_file
from flask import session as flask_session

from app.accounts import authenticated_owner, flow_url_problem, is_account, save_flow_url, session_graph_token, users
from app.config import settings
from app.mail.flow_package import build_flow_package
from app.routes.common import (
    account_for,
    display_name,
    error,
    mail_source,
    request_user,
    sorter,
    token_session,
    webhook_endpoint,
)
from app.stores import profiles
from app.stores.profiles import ProfileError

bp = Blueprint("account", __name__)

SETUP_NOT_USED = "Outlook flow setup is not used in this mode."


@bp.get("/api/session")
def session_info():
    """Who is signed in and which mail source the app was launched with."""
    owner = authenticated_owner()
    is_token = token_session()
    info = {
        "email": owner,
        "name": display_name(owner),
        "provider": mail_source(owner),
        # Students with an account may switch between their flow and a token.
        "canChooseSource": sorter().mail_provider == "powerautomate" and not is_token,
        "maxEmails": settings.max_emails,
    }
    if is_token:
        # Their own token, pasted at sign-in, so the app needs no second paste.
        info["graphToken"] = session_graph_token()
    return jsonify(info)


@bp.post("/api/profile")
def update_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    owner = request_user()
    try:
        if "source" in data:
            if sorter().mail_provider != "powerautomate" or not owner or token_session():
                return error("The mail source is fixed in this mode.", 400)
            profiles.profile_store.set_source(owner, data["source"])
        if "name" in data or "source" not in data:
            profiles.profile_store.set_name(owner, data.get("name"))
    except ProfileError as exc:
        return error(str(exc), 400)
    return jsonify({"name": display_name(owner), "provider": mail_source(owner)})


def _setup_account() -> tuple[str, dict | None]:
    """The signed-in owner and their account, or ``None`` when flow setup does not apply."""
    owner = request_user()
    account = account_for(owner)
    if sorter().mail_provider != "powerautomate" or not owner or not account:
        return owner, None
    return owner, account


@bp.get("/api/setup")
def setup_info():
    """Everything the student types into Power Automate, for their own account.

    The webhook token is a secret, so it is only returned to the signed-in
    owner of that account (responses are never cached).
    """
    owner, account = _setup_account()
    if account is None:
        return error(SETUP_NOT_USED, 404)
    return jsonify({
        "endpoint": webhook_endpoint(),
        "email": owner,
        "token": account["webhook_token"],
        "flow_url_saved": bool(account.get("refresh_url")),
    })


@bp.get("/api/setup/flow.zip")
def setup_flow_package():
    """A ready-made flow with this account's own address, email and token."""
    owner, account = _setup_account()
    if account is None:
        return error(SETUP_NOT_USED, 404)
    package = build_flow_package(webhook_endpoint(), owner, account["webhook_token"])
    return send_file(
        io.BytesIO(package),
        mimetype="application/zip",
        as_attachment=True,
        download_name="inbox-sorter-flow.zip",
        max_age=0,
    )


@bp.post("/api/setup/flow-url")
def save_flow_url_api():
    """Save the HTTP address of the student's imported flow (JSON)."""
    if sorter().mail_provider != "powerautomate":
        return error(SETUP_NOT_USED, 404)
    owner = authenticated_owner()
    data = request.get_json(silent=True) if request.is_json else None
    if not owner or owner not in users() or not isinstance(data, dict):
        return error("Expected a JSON object.", 400)
    url = str(data.get("url") or "").strip()
    problem = flow_url_problem(url)
    if problem:
        return error(problem, 400)
    save_flow_url(owner, url)
    return jsonify({"saved": bool(url)})


@bp.route("/register/connect", methods=["GET", "POST"])
def register_connect():
    """Step 2 of sign-up: connect Outlook before the app opens.

    The account already exists (its flow file carries its own token), but
    the student stays in the sign-up pages until they pick how mail arrives.
    """
    owner = request_user()
    if sorter().mail_provider != "powerautomate" or not is_account(owner):
        return redirect("/")
    account = account_for(owner)

    def page(message: str = "", status: int = 200, notice: str = ""):
        flask_session["connect_csrf"] = secrets.token_hex(32)
        return render_template(
            "connect.html",
            csrf_token=flask_session["connect_csrf"],
            name=display_name(owner),
            email=owner,
            flow_saved=bool(account.get("refresh_url")),
            error=message,
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
