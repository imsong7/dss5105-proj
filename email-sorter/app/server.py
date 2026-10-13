import logging

import requests
from flask import Flask, jsonify, render_template, request

from .classifier import EmailClassifier
from .config import ROOT, settings
from .models import Email
from .providers import AuthError, ProviderError, build_provider
from .taxonomy import CONTENT_CATEGORIES, REPLY_NATURE

logging.basicConfig(level=logging.INFO)


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    state = {"classifier": None}

    def classifier() -> EmailClassifier:
        if state["classifier"] is None:  # created on first use
            state["classifier"] = EmailClassifier()
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
        try:
            r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
            names = [m["name"] for m in r.json().get("models", [])]
            ready = any(n == settings.ollama_model or n.split(":")[0] == settings.ollama_model for n in names)
            return jsonify({"ollama": True, "model": settings.ollama_model, "model_ready": ready})
        except Exception:
            return jsonify({"ollama": False, "model": settings.ollama_model, "model_ready": False})

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
            email = Email(**request.get_json(force=True)["email"])
            result = classifier().classify(email)
            return jsonify(result.model_dump())
        except Exception as exc:  # most often: Ollama not running or model not pulled
            logging.exception("classification failed")
            return jsonify({"error": f"Classification failed: {exc}"}), 500

    return app
