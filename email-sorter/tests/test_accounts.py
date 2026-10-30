import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

SPEC = importlib.util.spec_from_file_location("multiuser_test_target", Path(__file__).resolve().parents[1] / "app" / "accounts.py")
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)

class MultiuserAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "accounts.json"
        path.write_text(json.dumps({
            "a@example.com": {"password_hash": generate_password_hash("alpha-password-123"), "webhook_token": "a" * 43, "refresh_url": "https://example.com/a"},
            "b@example.com": {"password_hash": generate_password_hash("bravo-password-123"), "webhook_token": "b" * 43, "refresh_url": "https://example.com/b"},
        }))
        self.app = Flask(__name__)
        with patch.dict(os.environ, {"MULTIUSER_CONFIG_FILE": str(path)}):
            security.install_multiuser(self.app)
        @self.app.get("/who")
        def who():
            return jsonify(owner=security.authenticated_owner(), refresh=security.refresh_url())
        @self.app.post("/api/inbound/outlook")
        def webhook():
            owner = security.webhook_owner(__import__("flask").request.headers.get("X-Webhook-Token", ""))
            return jsonify(owner=owner), (200 if owner else 401)
        self.client = self.app.test_client()

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get("/who").status_code, 401)

    def test_wrong_password_denied(self):
        self.assertEqual(self.client.get("/who", auth=("a@example.com", "wrong")).status_code, 401)

    def test_identity_and_refresh_bound(self):
        response = self.client.get("/who", auth=("a@example.com", "alpha-password-123"))
        self.assertEqual(response.get_json(), {"owner": "a@example.com", "refresh": "https://example.com/a"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_header_spoof_denied(self):
        response = self.client.get("/who", auth=("a@example.com", "alpha-password-123"), headers={"X-User-Email": "b@example.com"})
        self.assertEqual(response.status_code, 403)

    def test_webhook_token_binds_owner(self):
        response = self.client.post("/api/inbound/outlook", headers={"X-Webhook-Token": "b" * 43})
        self.assertEqual(response.get_json()["owner"], "b@example.com")

    def test_unknown_webhook_token_denied(self):
        self.assertEqual(self.client.post("/api/inbound/outlook", headers={"X-Webhook-Token": "wrong"}).status_code, 401)

if __name__ == "__main__":
    unittest.main()
