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

from .classifier_base import BaseClassifier, create_classifier
from .config import ROOT, settings
from .models import Email
from .providers import AuthError, ProviderError, build_provider
from .taxonomy import CONTENT_CATEGORIES, REPLY_NATURE

logging.basicConfig(level=logging.INFO)


def create_app(backend: str | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
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

    @app.get("/api/taxonomy")
    def taxonomy():
        return jsonify(
            {"content": CONTENT_CATEGORIES, "reply": REPLY_NATURE, "max_emails": settings.max_emails}
        )

    @app.get("/api/health")
    def health():
        # Quick socket check: is Ollama even listening? (1s timeout, no HTTP overhead)
        host = settings.ollama_base_url.replace("http://", "").replace("https://", "")
        port = 11434
        if ":" in host:
            host, port = host.split(":")
            port = int(port)
        ollama_up = False
        try:
            with socket.create_connection((host, port), timeout=1):
                ollama_up = True
        except (OSError, socket.timeout):
            ollama_up = False

        ready = False
        names = []
        if ollama_up:
            try:
                r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
                names = [m["name"] for m in r.json().get("models", [])]
                ready = any(n == settings.ollama_model or n.split(":")[0] == settings.ollama_model for n in names)
            except Exception:
                pass
        backend_name = backend or settings.model_backend
        backend_ready = ready if backend_name == "llama" else bool(state["classifier"])
        return jsonify(
            {
                "ollama": ready,
                "model": settings.ollama_model,
                "model_ready": ready,
                "backend": backend_name,
                "backend_ready": backend_ready,
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
