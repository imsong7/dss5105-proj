"""Drafting a reply with the LLM and sending it through Microsoft Graph."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.accounts import remember_session_graph_token, session_graph_token
from app.mail.reply_drafting import ReplyDraftError, generate_reply
from app.mail.reply_sending import ReplySendError
from app.mail.reply_sending import send_reply as send_graph_reply
from app.routes.common import display_name, error, request_user
from app.schemas import Email

bp = Blueprint("replies", __name__)


class _BadRequest(Exception):
    """The request body is unusable; the message is safe to show."""


def _email_request() -> tuple[dict, Email]:
    """The JSON body and the email in it."""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("email"), dict):
        raise _BadRequest("Expected a JSON object with an email.")
    try:
        return data, Email(**data["email"])
    except Exception as exc:
        raise _BadRequest(f"Invalid email: {exc}") from exc


@bp.post("/api/draft-reply")
def draft_reply():
    try:
        _, email = _email_request()
    except _BadRequest as exc:
        return error(str(exc), 400)

    owner = request_user()
    try:
        result = generate_reply(email, owner, display_name(owner))
    except ReplyDraftError as exc:
        return error(str(exc), exc.status_code)
    except Exception as exc:
        logging.exception("reply drafting failed")
        return error(f"Drafting failed: {exc}", 502)
    return jsonify(result)


@bp.post("/api/send-reply")
def send_reply():
    try:
        data, email = _email_request()
    except _BadRequest as exc:
        return error(str(exc), 400)

    reply = data.get("reply")
    if not isinstance(reply, str):
        return error("Expected the reply text.", 400)
    provided_token = str(data.get("token") or "").strip()
    token = provided_token or session_graph_token()
    try:
        result = send_graph_reply(email, reply, token)
    except ReplySendError as exc:
        return error(str(exc), exc.status_code)
    except Exception as exc:
        logging.exception("reply sending failed")
        return error(f"Sending failed: {exc}", 502)
    if provided_token:
        remember_session_graph_token(provided_token)
    return jsonify(result)
