"""Small-team HTTPS demo authentication; not an SSO implementation."""
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import Response, current_app, g, jsonify, request
from werkzeug.security import check_password_hash


def users():
    return current_app.extensions["multiuser_accounts"]


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


def install_multiuser(app):
    # Browsers cache Basic auth per realm. A fresh realm per app start means
    # the browser asks again instead of silently reusing an old login.
    realm = f"Email Sorter {secrets.token_hex(4)}"
    configured = os.getenv("MULTIUSER_CONFIG_FILE", "").strip()
    if not configured:
        raise RuntimeError("Set MULTIUSER_CONFIG_FILE to your private accounts JSON file.")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(app.root_path).parent / path
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
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

    @app.before_request
    def require_identity():
        # Only the canonical ingestion route uses webhook credentials.
        if request.path == "/api/inbound/outlook":
            return None
        auth = request.authorization
        owner = str(auth.username or "").strip().lower() if auth else ""
        record = accounts.get(owner)
        valid = bool(auth and auth.type.lower() == "basic" and record and
                     check_password_hash(record["password_hash"], auth.password or ""))
        if not valid:
            return Response("Authentication required.", 401, {
                "WWW-Authenticate": f'Basic realm="{realm}", charset="UTF-8"',
                "Cache-Control": "no-store",
            })
        g.mail_owner = owner
        supplied = request.headers.get("X-User-Email", "").strip().lower()
        if supplied and supplied != owner:
            return jsonify(error="Mailbox email must match the authenticated account. Switch the dashboard email or sign in with the correct account."), 403
        return None

    @app.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
