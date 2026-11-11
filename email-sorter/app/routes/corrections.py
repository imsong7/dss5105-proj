"""Labels the student fixed by hand, and the sender rules they create."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.classifiers.sender_rules import sender_address
from app.routes.common import error, request_user
from app.stores import classification_store
from app.stores.classification_store import CorrectionError

bp = Blueprint("corrections", __name__)


@bp.post("/api/corrections")
def save_correction():
    owner = request_user()
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
        return error(str(exc), 400)
    return jsonify({
        "saved": True,
        "id": record["id"],
        "rule": bool(payload.get("remember_sender")),
    }), 201


@bp.delete("/api/corrections/<path:email_id>")
def delete_correction(email_id):
    owner = request_user()
    record = classification_store.correction_store.delete(owner, email_id)
    if record is None:
        return error("No correction for this email.", 404)
    # Undoing the fix also removes the rule it created.
    if record.get("rule") and record.get("sender_key"):
        classification_store.sender_rule_store.delete(owner, record["sender_key"])
    return jsonify({"deleted": True})


@bp.delete("/api/sender-rules")
def delete_sender_rule():
    sender = sender_address(request.args.get("sender", ""))
    if not classification_store.sender_rule_store.delete(request_user(), sender):
        return error("No rule for this sender.", 404)
    return jsonify({"deleted": True})
