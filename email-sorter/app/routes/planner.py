"""The student's planning data: calendar events, item states, the .ics feed and saved jobs.

Stores are looked up per request (``user_events.event_store`` and so on) so
tests can point them at temporary files.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request

from app.routes.common import error, forwarded_proto, request_user
from app.stores import calendar_feed, saved_jobs, user_events
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

    response = current_app.response_class(_ics_body(owner), mimetype="text/calendar")
    response.headers["Content-Disposition"] = 'inline; filename="deadlines.ics"'
    return response


def _ics_body(owner: str) -> str:
    """The student's deadlines and own events as one calendar file."""
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
    return calendar_feed.build_ics("NusBox deadlines", items)


@bp.get("/api/feed/download")
def feed_download():
    """The same calendar as a file to save, for Outlook, Apple Calendar or Google Calendar."""
    response = current_app.response_class(_ics_body(request_user()), mimetype="text/calendar")
    response.headers["Content-Disposition"] = 'attachment; filename="nusbox-calendar.ics"'
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
