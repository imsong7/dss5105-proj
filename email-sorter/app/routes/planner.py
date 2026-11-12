"""The student's planning data: calendar events, item states, the .ics feed and saved jobs.

Stores are looked up per request (``user_events.event_store`` and so on) so
tests can point them at temporary files.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request

from app.extract.event_from_email import ExtractionError, extract_event
from app.routes.common import error, forwarded_proto, request_user
from app.schemas import Email
from app.stores import calendar_feed, email_events, saved_jobs, user_events
from app.stores import item_states as item_state_module
from app.stores.calendar_feed import FeedError
from app.stores.item_states import StateError
from app.stores.saved_jobs import SavedJobError
from app.stores.user_events import EventError

bp = Blueprint("planner", __name__)


# ---- Personal calendar events -------------------------------------------------

@bp.get("/api/events")
def list_events():
    return jsonify({"events": user_events.event_store.list(request_user())})


@bp.post("/api/events")
def create_event():
    try:
        event = user_events.event_store.create(request_user(), request.get_json(silent=True))
    except EventError as exc:
        return error(str(exc), 400)
    return jsonify(event), 201


@bp.post("/api/events/scan")
def scan_email_for_event():
    """What Claude finds in one email: ``{"event": {...}}`` or ``{"event": null}``.

    Each email is read once; the answer is kept. Nothing is added to the calendar here.
    """
    data = request.get_json(silent=True)
    try:
        email = Email(**data["email"])
    except Exception:
        return error("Expected a JSON object with an email.", 400)

    owner = request_user()
    known, event = email_events.email_event_store.get(owner, email.id)
    if known:
        return jsonify({"event": event})
    try:
        event = extract_event(email)
    except ExtractionError as exc:
        if exc.status_code != 422:
            return error(str(exc), exc.status_code)  # not stored: try again later
        event = None  # Claude read it and there is no event
    email_events.email_event_store.put(owner, email.id, event)
    return jsonify({"event": event})


@bp.put("/api/events/<event_id>")
def update_event(event_id):
    try:
        event = user_events.event_store.update(request_user(), event_id, request.get_json(silent=True))
    except EventError as exc:
        return error(str(exc), 400)
    if event is None:
        return error("Event not found.", 404)
    return jsonify(event)


@bp.delete("/api/events/<event_id>")
def delete_event(event_id):
    if not user_events.event_store.delete(request_user(), event_id):
        return error("Event not found.", 404)
    return jsonify({"deleted": True})


# ---- Done / snoozed state of inbox items --------------------------------------

@bp.get("/api/item-states")
def list_item_states():
    return jsonify({"states": item_state_module.item_states.list(request_user())})


@bp.post("/api/item-states")
def set_item_state():
    try:
        record = item_state_module.item_states.set(request_user(), request.get_json(silent=True))
    except StateError as exc:
        return error(str(exc), 400)
    return jsonify({"state": record})


# ---- Calendar subscription (.ics) ------------------------------------------------

def _feed_urls(token: str) -> dict:
    host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0].strip()
    path = f"{host}/feed/{token}.ics"
    return {"url": f"{forwarded_proto()}://{path}", "webcal": f"webcal://{path}"}


@bp.get("/api/feed")
def feed_info():
    return jsonify(_feed_urls(calendar_feed.feed_store.token_for(request_user())))


@bp.post("/api/feed/rotate")
def feed_rotate():
    return jsonify(_feed_urls(calendar_feed.feed_store.rotate(request_user())))


@bp.post("/api/feed/sync")
def feed_sync():
    data = request.get_json(silent=True)
    try:
        count = calendar_feed.feed_store.set_items(
            request_user(), (data or {}).get("items") if isinstance(data, dict) else None
        )
    except FeedError as exc:
        return error(str(exc), 400)
    return jsonify({"synced": count})


@bp.get("/feed/<name>")
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
    response = current_app.response_class(body, mimetype="text/calendar")
    response.headers["Content-Disposition"] = 'inline; filename="deadlines.ics"'
    return response


# ---- Saved jobs --------------------------------------------------------------------

@bp.get("/api/saved-jobs")
def list_saved_jobs():
    return jsonify({"jobs": saved_jobs.saved_job_store.list(request_user())})


@bp.post("/api/saved-jobs")
def save_job():
    try:
        job = saved_jobs.saved_job_store.save(request_user(), request.get_json(silent=True))
    except SavedJobError as exc:
        return error(str(exc), 400)
    return jsonify({"job": job})


@bp.delete("/api/saved-jobs/<path:job_id>")
def remove_saved_job(job_id: str):
    if not saved_jobs.saved_job_store.remove(request_user(), job_id):
        return error("That job is not saved.", 404)
    return jsonify({"removed": True})
