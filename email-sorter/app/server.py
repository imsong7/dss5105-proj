"""Flask app factory with pluggable classifier backends.

Usage::

    from app.server import create_app

    app = create_app(backend="bert")   # or "llama", or None to use env/default
"""

import logging
import socket
import time

import requests
from flask import Flask, jsonify, render_template, request

from .classifier_base import (
    BACKEND_INFO,
    BaseClassifier,
    create_classifier,
    list_backends,
)
from .config import ROOT, settings
from .models import Email
from .providers import AuthError, ProviderError, build_provider
from .taxonomy import CONTENT_CATEGORIES, REPLY_NATURE

logging.basicConfig(level=logging.INFO)


def _ollama_status() -> tuple[bool, bool]:
    """Return ``(server_reachable, configured_model_present)``."""
    host = settings.ollama_base_url.replace("http://", "").replace("https://", "")
    port = 11434
    if ":" in host:
        host, port = host.split(":")
        port = int(port)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except (OSError, socket.timeout):
        return False, False
    try:
        r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
        names = [m["name"] for m in r.json().get("models", [])]
        ready = any(
            n == settings.ollama_model or n.split(":")[0] == settings.ollama_model
            for n in names
        )
        return True, ready
    except Exception:
        return True, False


def _bert_ready() -> bool:
    """BERT heads are usable when both head files exist."""
    return all(
        (ROOT.parent / "bert" / "models" / name / "head.joblib").is_file()
        for name in ("category_head", "action_head")
    )


def _backend_ready(name: str, ollama_ready: bool, *, loaded: bool = False) -> bool | None:
    """Return readiness for a backend, or ``None`` when it cannot be checked cheaply."""
    if name == "llama":
        return ollama_ready
    if name == "bert":
        return _bert_ready()
    return True if loaded else None


def create_app(backend: str | None = None) -> Flask:
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
        return render_template("index.html")

    @app.get("/compare")
    def compare():
        return render_template("compare.html")

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
            }
        )

    @app.post("/api/emails")
    def emails():
        data = request.get_json(force=True)
        limit = max(1, min(int(data.get("count", 15)), settings.max_emails))
        try:
            provider = build_provider(data.get("provider", "outlook"), data.get("credentials", {}))
            items = provider.fetch_emails(limit)
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
            result = classifier(backend_name).classify(email)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            out = result.model_dump()
            out["duration_ms"] = duration_ms
            out["backend"] = backend_name
            return jsonify(out)
        except Exception as exc:  # most often: Ollama not running or model not pulled
            logging.exception("classification failed")
            return jsonify({"error": f"Classification failed: {exc}"}), 500

    return app
