"""Flask app factory with pluggable classifier backends.

Usage::

    from app.server import create_app

    app = create_app(backend="bert")   # encoder backend; or "llama", or None
"""

import logging
import socket
import time
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request

from .classifier_base import (
    BACKEND_INFO,
    BaseClassifier,
    create_classifier,
    list_backends,
)
from .claude_classifier import claude_ready
from .config import ROOT, settings
from .ml_classifier import models_ready as _ml_ready
from .models import Classification, Email
from .ocr_pipeline import ocr_status, prepare_text
from .providers import AuthError, ProviderError, build_provider
from .rules import category_by_rule
from .taxonomy import CONTENT_CATEGORIES, DEFAULT_REPLY, REPLY_NATURE

logging.basicConfig(level=logging.INFO)


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


def _bert_ready() -> bool:
    """Encoder heads are usable when both head files and manifests exist."""
    models_dir = ROOT.parent / "text-encoders" / "models"
    return all(
        (models_dir / name / filename).is_file()
        for name in ("category_head", "action_head")
        for filename in ("head.joblib", "manifest.json")
    )


def _backend_ready(name: str, ollama_ready: bool, *, loaded: bool = False) -> bool | None:
    """Return readiness for a backend, or ``None`` when it cannot be checked cheaply."""
    if name == "llama":
        return ollama_ready
    if name == "bert":
        return _bert_ready()
    if name == "ml":
        return _ml_ready()
    if name == "claude":
        return claude_ready()
    return True if loaded else None


def create_app(backend: str | None = None, version: int = 1) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    state = {"classifier": None, "backend": None}

    def classifier(backend_name: str | None = None) -> BaseClassifier:
        name = backend_name or backend or settings.model_backend
        if state["classifier"] is None or state["backend"] != name:
            state["classifier"] = create_classifier(name)
            state["backend"] = name
        return state["classifier"]

    @app.get("/")
    def index():
        template = "dashboard_v2.html" if version == 2 else "index.html"
        return render_template(template)

    @app.get("/compare")
    def compare():
        return render_template("compare.html")

    @app.get("/dashboard-v2")
    def dashboard_v2():
        return render_template("dashboard_v2.html")

    @app.get("/api/backends")
    def backends():
        _, ollama_ready = _ollama_status()
        items = []
        for name in list_backends():
            info = BACKEND_INFO.get(name, {})
            items.append(
                {
                    "id": name,
                    "label": info.get("label", name),
                    "kind": info.get("kind", "unknown"),
                    "description": info.get("description", ""),
                    "ready": _backend_ready(name, ollama_ready),
                }
            )
        return jsonify(
            {
                "backends": items,
                "default": backend or settings.model_backend,
                "max_emails": settings.max_emails,
            }
        )

    @app.get("/api/taxonomy")
    def taxonomy():
        return jsonify(
            {"content": CONTENT_CATEGORIES, "reply": REPLY_NATURE, "max_emails": settings.max_emails}
        )

    @app.get("/api/health")
    def health():
        # The UI polls readiness for whichever backend it has selected.
        requested = request.args.get("backend") or backend or settings.model_backend
        ollama_up, ollama_ready = _ollama_status()
        bert_ready = _bert_ready()
        ml_ready = _ml_ready()
        claude_backend_ready = claude_ready()
        backend_ready = _backend_ready(
            requested,
            ollama_ready,
            loaded=state["classifier"] is not None and state["backend"] == requested,
        )

        return jsonify(
            {
                "backend": requested,
                "default_backend": backend or settings.model_backend,
                "backend_ready": backend_ready,
                "ollama_up": ollama_up,
                "ollama": ollama_ready,
                "ollama_ready": ollama_ready,
                "model": settings.ollama_model,
                "model_ready": ollama_ready,
                "bert_ready": bert_ready,
                "ml_ready": ml_ready,
                "claude_ready": claude_backend_ready,
                "ocr": ocr_status(),
            }
        )

    @app.post("/api/emails")
    def emails():
        data = request.get_json(force=True)
        limit = max(1, min(int(data.get("count", 15)), settings.max_emails))
        try:
            provider = build_provider(data.get("provider", "outlook"), data.get("credentials", {}))
            items = provider.fetch_emails(limit)
            items = [prepare_text(email, provider) for email in items]
        except AuthError as exc:
            return jsonify({"error": str(exc)}), 401
        except ProviderError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"emails": [e.model_dump() for e in items]})

    @app.post("/api/classify")
    def classify():
        try:
            data = request.get_json(force=True)
            email = Email(**data["email"])
            backend_name = data.get("backend") or backend or settings.model_backend
            t0 = time.perf_counter()
            rule_category = category_by_rule(email.sender)
            if rule_category:
                model_name = "Sender rule (model skipped)"
                result = Classification(
                    content_category=rule_category,
                    reply_nature=DEFAULT_REPLY,
                    deadline=None,
                    reason=f"Sender rule matched and set category to {rule_category}.",
                )
            else:
                selected_classifier = classifier(backend_name)
                result = selected_classifier.classify(email)
                model_name = getattr(
                    selected_classifier, "model_name", backend_name
                )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            out = result.model_dump()
            out["duration_ms"] = duration_ms
            out["backend"] = backend_name
            out["model_name"] = model_name
            out["text_source"] = email.text_source
            out["ocr_confidence"] = email.ocr_confidence
            out["ocr_notes"] = email.ocr_notes
            return jsonify(out)
        except Exception as exc:  # most often: Ollama not running or model not pulled
            logging.exception("classification failed")
            return jsonify({"error": f"Classification failed: {exc}"}), 500

    return app
