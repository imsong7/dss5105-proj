"""Loading mail and sorting it: emails, classify, backends and their readiness."""

from __future__ import annotations

import io
import logging
import socket
import time
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request, send_file

from app.accounts import session_graph_token
from app.classifiers.backends import BACKEND_INFO, BaseClassifier, create_classifier, list_backends
from app.classifiers.classification_metrics import enabled as metrics_enabled
from app.classifiers.classification_metrics import log_event, new_request_id, set_request_id
from app.classifiers.claude_classifier import claude_ready
from app.classifiers.ml_classifier import models_ready as _ml_ready
from app.classifiers.sender_rules import category_by_rule, coursework_by_rule, sender_address
from app.config import ROOT, settings
from app.extract import poster as poster_module
from app.extract.calendar import ACADEMIC_CALENDAR_LABEL, extract_deadlines, load_academic_calendar
from app.extract.events import parse_event
from app.extract.listings import parse_jobs
from app.extract.ocr import ocr_status, prepare_text
from app.mail.providers import AuthError, MailQuery, ProviderError, build_provider
from app.mail.pushed_store import refresh_state
from app.mail.text_utils import without_link_addresses
from app.routes.common import error, parse_window, request_user, sorter, token_session
from app.schemas import Classification, Email
from app.stores import classification_store
from app.stores.classification_store import with_priority
from app.taxonomy import CONTENT_CATEGORIES, DEFAULT_REPLY, REPLY_NATURE

bp = Blueprint("mail", __name__)


# ---- Backend readiness -------------------------------------------------------

def _ollama_status() -> tuple[bool, bool]:
    """Return ``(server_reachable, configured_model_present)``."""
    raw_url = settings.ollama_base_url
    base_url = raw_url if "://" in raw_url else f"http://{raw_url}"
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 11434)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except (OSError, socket.timeout):
        return False, False
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=2)
        names = [m["name"] for m in r.json().get("models", [])]
        ready = any(
            n == settings.ollama_model or n.split(":")[0] == settings.ollama_model
            for n in names
        )
        return True, ready
    except Exception:
        return True, False


def _encoder_ready(tasks: tuple[str, ...] | str = ("category", "action")) -> bool:
    """Encoder heads are usable when the requested head files and manifests exist."""
    if isinstance(tasks, str):
        tasks = (tasks,)
    models_dir = ROOT.parent / "text-encoders" / "models"
    return all(
        (models_dir / f"{task}_head" / filename).is_file()
        for task in tasks
        for filename in ("head.joblib", "manifest.json")
    )


def _backend_ready(name: str, ollama_ready: bool, *, loaded: bool = False) -> bool | None:
    """Return readiness for a backend, or ``None`` when it cannot be checked cheaply."""
    if name == "llama":
        return ollama_ready
    if name == "encoder":
        return _encoder_ready()
    if name == "ml":
        return _ml_ready()
    if name == "hybrid":
        return _ml_ready(("category",)) and _encoder_ready(("action",))
    if name == "hybrid_claude":
        return _ml_ready(("category",)) and claude_ready()
    if name == "claude":
        return claude_ready()
    return True if loaded else None


def _classifier(backend_name: str) -> BaseClassifier:
    """The loaded classifier for ``backend_name``; loading another replaces it."""
    state = sorter()
    if state.classifier is None or state.classifier_backend != backend_name:
        state.classifier = create_classifier(backend_name)
        state.classifier_backend = backend_name
    return state.classifier


@bp.get("/api/backends")
def backends():
    _, ollama_ready = _ollama_status()
    items = []
    for name in list_backends():
        info = BACKEND_INFO.get(name, {})
        items.append({
            "id": name,
            "label": info.get("label", name),
            "kind": info.get("kind", "unknown"),
            "description": info.get("description", ""),
            "ready": _backend_ready(name, ollama_ready),
        })
    return jsonify({
        "backends": items,
        "default": sorter().backend_name(),
        "max_emails": settings.max_emails,
    })


@bp.get("/api/health")
def health():
    # The UI polls readiness for whichever backend it has selected.
    state = sorter()
    requested = state.backend_name(request.args.get("backend"))
    ollama_up, ollama_ready = _ollama_status()
    backend_ready = _backend_ready(
        requested,
        ollama_ready,
        loaded=state.classifier is not None and state.classifier_backend == requested,
    )
    return jsonify({
        "backend": requested,
        "default_backend": state.backend_name(),
        "backend_ready": backend_ready,
        "ollama_up": ollama_up,
        "ollama": ollama_ready,
        "ollama_ready": ollama_ready,
        "model": settings.ollama_model,
        "model_ready": ollama_ready,
        "encoder_ready": _encoder_ready(),
        "ml_ready": _ml_ready(),
        "hybrid_ready": _ml_ready(("category",)) and _encoder_ready(("action",)),
        "hybrid_claude_ready": _ml_ready(("category",)) and claude_ready(),
        "claude_ready": claude_ready(),
        "ocr": ocr_status(),
    })


@bp.get("/api/taxonomy")
def taxonomy():
    return jsonify({"content": CONTENT_CATEGORIES, "reply": REPLY_NATURE, "max_emails": settings.max_emails})


@bp.get("/api/academic-calendar")
def academic_calendar():
    """NUS term dates and holidays shown beside the email deadline candidates."""
    events = load_academic_calendar()
    return jsonify({"label": ACADEMIC_CALENDAR_LABEL, "events": events, "available": bool(events)})


# ---- Mail and its sorting ----------------------------------------------------

def saved_result(email_id: str, sender: str, backend_name: str, corrections: dict,
                 rules: dict, cache: dict, priorities: dict | None = None) -> dict | None:
    """A result the student already has, with their own stars on top (if they set any)."""
    found = _saved_labels(email_id, sender, backend_name, corrections, rules, cache)
    stars = (priorities or {}).get(email_id)
    return with_priority(found, stars) if found and stars else found


def _saved_labels(email_id: str, sender: str, backend_name: str, corrections: dict,
                  rules: dict, cache: dict) -> dict | None:
    """A result the student already has: their correction, their sender
    rule, or a cached model answer (in that order). None when unsorted."""
    fixed = corrections.get(email_id)
    if fixed:
        return {
            "content_category": fixed["content_category"],
            "reply_nature": fixed["reply_nature"],
            "reason": "Corrected by you.",
            "deadline": None,
            "duration_ms": 0,
            "backend": backend_name,
            "model_name": "You",
            "corrected": True,
            "original": {
                "content_category": fixed["original_category"],
                "reply_nature": fixed["original_action"],
            },
            "cached": True,
        }
    rule = rules.get(sender_address(sender)) if sender else None
    if rule:
        return {
            "content_category": rule["content_category"],
            "reply_nature": rule["reply_nature"],
            "reason": "Your rule for this sender.",
            "deadline": None,
            "duration_ms": 0,
            "backend": backend_name,
            "model_name": "Your rule",
            "rule": True,
            "cached": True,
        }
    cached = cache.get(email_id)
    return {**cached, "cached": True} if cached else None


@bp.post("/api/emails")
def emails():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return error("Expected a JSON object.", 400)
    try:
        limit = max(1, min(int(data.get("count", 15)), settings.max_emails))
    except (TypeError, ValueError):
        return error("`count` must be a whole number.", 400)
    try:
        since, before = parse_window(data)
    except ValueError as exc:
        return error(str(exc), 400)

    owner = request_user()
    query = MailQuery(limit=limit, since=since, before=before)
    try:
        kind = data.get("provider", "outlook")
        credentials = dict(data.get("credentials") or {})
        if kind == "powerautomate":
            # Strict per-user view: only this person's pushed mail.
            credentials["owner"] = owner
        elif kind == "outlook" and not str(credentials.get("token") or "").strip() and token_session():
            credentials["token"] = session_graph_token()
        provider = build_provider(kind, credentials)
        items = [prepare_text(email, provider, owner) for email in provider.fetch_emails(query)]
    except AuthError as exc:
        return error(str(exc), 401)
    except ProviderError as exc:
        return error(str(exc), 502)

    # Results the student already has come back with the mail, so a page
    # reload (or reopening the app) shows them at once instead of re-sorting.
    backend_name = str(sorter().backend_name(data.get("backend")))
    corrections = classification_store.correction_store.all_for(owner)
    rules = classification_store.sender_rule_store.all_for(owner)
    cache = classification_store.classify_cache.all_for(owner, backend_name)
    priorities = classification_store.priority_store.all_for(owner)
    serialized_emails = []
    for email in items:
        serialized = email.model_dump()
        if serialized.get("poster") and serialized["poster"].get("has_image"):
            # A saved email can outlive its preview (older saves kept previews in memory only).
            serialized["poster"] = {**serialized["poster"], "has_image": poster_module.thumbs.has(owner, email.id)}
        serialized["saved_classification"] = saved_result(
            email.id, email.sender, backend_name, corrections, rules, cache, priorities
        )
        found = extract_deadlines(email)
        for candidate in found:
            # A date read off a poster image is marked so the UI can say so.
            candidate["from_image"] = bool(
                email.ocr_text and candidate.get("text") and candidate["text"] in email.ocr_text
            )
        serialized["deadline_candidate"] = found[0] if found else None
        serialized["deadline_candidates"] = found
        # A job digest becomes a list of jobs (None for other mail).
        serialized["jobs"] = parse_jobs(email.body, email.subject)
        # An event announced in the text becomes an event card (a poster's card wins).
        serialized["event"] = None if email.poster or serialized["jobs"] else parse_event(email)
        serialized_emails.append(serialized)
    body = {
        "emails": serialized_emails,
        "window": {
            "since": since.isoformat() if since else None,
            "before": before.isoformat() if before else None,
            "limit": limit,
        },
    }
    if data.get("provider") == "powerautomate":
        # Whether the flow is still sending, and whether its last run got everything.
        body["sync"] = refresh_state.status(owner)
    return jsonify(body)


def _rule_result(email: Email) -> tuple[Classification, str] | None:
    """A free answer from the course or sender rules, or ``None`` to ask the model."""
    rule_category = category_by_rule(email.sender)
    if rule_category:
        return Classification(
            content_category=rule_category,
            reply_nature=DEFAULT_REPLY,
            deadline=None,
            reason=f"Sender rule matched and set category to {rule_category}.",
        ), "Sender rule (model skipped)"
    dates = extract_deadlines(email)
    coursework = coursework_by_rule(
        email.subject,
        email.body or email.preview,
        bool(dates),
        bool(dates) and dates[0]["event_type"] == "exam",
    )
    if coursework:
        return Classification(
            content_category=coursework[0],
            reply_nature=coursework[1],
            deadline=None,
            reason=coursework[2],
        ), "Course rule (model skipped)"
    return None


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


@bp.post("/api/classify")
def classify():
    set_request_id(new_request_id() if metrics_enabled() else None)
    t_total = time.perf_counter()
    backend_name = None
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict) or not isinstance(data.get("email"), dict):
            return error("Expected a JSON object with an email.", 400)
        email = Email(**data["email"])
        # "<https://...>" addresses help buttons, not the model: drop them
        # so they do not use up the part of the email the model reads.
        email.body = without_link_addresses(email.body)
        backend_name = sorter().backend_name(data.get("backend"))
        owner = request_user()

        # A student's own correction beats any model result, then their
        # sender rule, then an answer this backend already gave.
        t_cache = time.perf_counter()
        fixed = classification_store.correction_store.get(owner, email.id)
        hit = classification_store.classify_cache.get(owner, backend_name, email.id)
        saved = saved_result(
            email.id,
            email.sender,
            backend_name,
            {email.id: fixed} if fixed else {},
            classification_store.sender_rule_store.all_for(owner),
            {email.id: hit} if hit else {},
            classification_store.priority_store.all_for(owner),
        )
        cache_lookup_ms = _ms_since(t_cache)
        if saved:
            source = "correction" if fixed else "rule" if saved.get("rule") else "cache"
            log_event(
                "classify_result",
                backend=backend_name,
                source=source,
                total_ms=_ms_since(t_total),
                cache_lookup_ms=cache_lookup_ms,
                model_name=saved.get("model_name"),
                success=True,
            )
            return jsonify(saved)

        t_model = time.perf_counter()
        by_rule = _rule_result(email)
        if by_rule:
            result, model_name = by_rule
        else:
            selected = _classifier(backend_name)
            result = selected.classify(email)
            model_name = getattr(selected, "model_name", backend_name)
        model_ms = _ms_since(t_model)
        out = result.model_dump()
        out["duration_ms"] = model_ms
        out["backend"] = backend_name
        out["model_name"] = model_name
        out["text_source"] = email.text_source
        out["ocr_confidence"] = email.ocr_confidence
        out["ocr_notes"] = email.ocr_notes

        t_save = time.perf_counter()
        classification_store.classify_cache.put(owner, backend_name, email.id, out)
        save_ms = _ms_since(t_save)

        log_event(
            "classify_result",
            backend=backend_name,
            source="model",
            total_ms=_ms_since(t_total),
            cache_lookup_ms=cache_lookup_ms,
            model_ms=model_ms,
            save_ms=save_ms,
            model_name=model_name,
            success=True,
        )
        # The cache keeps the model's own rating; the student's stars go on top of it only here.
        return jsonify(with_priority(out, classification_store.priority_store.all_for(owner).get(email.id)))
    except Exception as exc:  # most often: Ollama not running or model not pulled
        log_event(
            "classify_error",
            backend=backend_name or "unknown",
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
            total_ms=_ms_since(t_total),
        )
        logging.exception("classification failed")
        return error(f"Classification failed: {exc}", 500)


@bp.get("/api/emails/<path:email_id>/poster.jpg")
def poster_preview(email_id: str):
    """A small preview of the poster in this account's email (404 otherwise)."""
    data = poster_module.thumbs.get(request_user(), email_id)
    if data is None:
        return error("No poster preview.", 404)
    response = send_file(io.BytesIO(data), mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response
