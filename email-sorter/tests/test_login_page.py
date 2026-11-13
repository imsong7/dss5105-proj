"""Tests for the session login page that replaced the HTTP Basic popup."""

import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from app.mail.pushed_store import pushed_store
from app.server import create_app

ACCOUNT_A = "alice@example.com"
ACCOUNT_B = "bob@example.com"
PASSWORD = "test-password-123"
TOKEN_A = "a" * 43
TOKEN_B = "b" * 43


class LoginPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "multiuser.json"
        path.write_text(
            json.dumps(
                {
                    ACCOUNT_A: {
                        "password_hash": generate_password_hash(PASSWORD),
                        "webhook_token": TOKEN_A,
                        "refresh_url": "",
                        "name": "Alice Tan",
                    },
                    ACCOUNT_B: {
                        "password_hash": generate_password_hash(PASSWORD),
                        "webhook_token": TOKEN_B,
                        "refresh_url": "",
                    },
                }
            ),
            encoding="utf-8",
        )
        self.env = patch.dict(
            os.environ,
            {
                "MULTIUSER_CONFIG_FILE": str(path),
                "SESSION_SECRET": "test-session-secret",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        pushed_store.clear()
        self.addCleanup(pushed_store.clear)
        self.app = create_app(backend="llama", provider="powerautomate")
        self.client = self.app.test_client()

    def sign_in(self, email=ACCOUNT_A, password=PASSWORD, next_url="/"):
        page = self.client.get(f"/login?next={next_url}").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        return self.client.post(
            "/login",
            data={
                "email": email,
                "password": password,
                "csrf_token": csrf,
                "next": next_url,
            },
        )

    def test_dashboard_redirects_to_login_when_signed_out(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertIn("next", response.headers["Location"])

    def test_display_name_comes_from_the_account_until_changed(self):
        self.sign_in()
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "Alice Tan")

        self.client.post("/api/profile", json={"name": "Ali"})
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "Ali")

        self.client.post("/api/profile", json={"name": ""})
        self.assertEqual(self.client.get("/api/session").get_json()["name"], "Alice Tan")

    def test_calendar_feed_needs_token_not_login(self):
        # Calendar apps cannot sign in: a bad token is a 404, not a redirect.
        self.assertEqual(self.client.get("/feed/not-a-token.ics").status_code, 404)

        self.sign_in()
        link = self.client.get("/api/feed").get_json()["url"]
        anonymous = self.app.test_client()
        response = anonymous.get("/feed/" + link.rsplit("/feed/", 1)[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/calendar")
        self.assertEqual(anonymous.get("/api/feed").status_code, 401)

    def test_no_basic_auth_challenge_is_sent(self):
        response = self.client.get("/")

        self.assertNotIn("WWW-Authenticate", response.headers)

    def test_api_returns_401_with_login_url(self):
        response = self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["login_url"], "/login")

    def test_login_page_is_public(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sign in", response.get_data(as_text=True))

    def test_static_assets_are_public(self):
        response = self.client.get("/static/style.css")

        self.assertEqual(response.status_code, 200)

    def test_webhook_still_works_without_login(self):
        response = self.client.post(
            "/api/inbound/outlook",
            json={"subject": "Hi", "body": "There", "from": "prof@nus.edu.sg"},
            headers={"X-Webhook-Token": TOKEN_A},
        )

        self.assertEqual(response.status_code, 200)

    def test_wrong_password_is_rejected(self):
        response = self.sign_in(password="wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertIn("incorrect", response.get_data(as_text=True))

    def test_login_without_csrf_token_is_rejected(self):
        response = self.client.post(
            "/login", data={"email": ACCOUNT_A, "password": PASSWORD}
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("expired", response.get_data(as_text=True))

    def test_signed_in_session_reaches_the_dashboard_and_api(self):
        login = self.sign_in(next_url="/?view=today")

        self.assertEqual(login.status_code, 302)
        self.assertEqual(login.headers["Location"], "/?view=today")

        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["email"], ACCOUNT_A)
        self.assertEqual(session["provider"], "powerautomate")

        response = self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
        )
        self.assertEqual(response.status_code, 200)

    def test_mismatched_x_user_email_is_rejected_after_login(self):
        self.sign_in()

        response = self.client.get(
            "/api/inbound/diagnostics", headers={"X-User-Email": ACCOUNT_B}
        )

        self.assertEqual(response.status_code, 403)

    def test_logout_clears_the_session(self):
        self.sign_in()

        logout = self.client.post("/logout")
        self.assertEqual(logout.status_code, 302)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_open_redirect_next_values_are_ignored(self):
        login = self.sign_in(next_url="https://evil.example.com/")

        self.assertEqual(login.headers["Location"], "/")

    def test_existing_basic_auth_still_works_for_tooling(self):
        response = self.client.post(
            "/api/emails",
            json={"provider": "powerautomate", "credentials": {}, "count": 10},
            auth=(ACCOUNT_A, PASSWORD),
        )

        self.assertEqual(response.status_code, 200)

    def test_repeated_wrong_passwords_lock_the_account_for_a_while(self):
        with patch("app.routes.auth.time.sleep"):
            for _ in range(5):
                self.assertEqual(self.sign_in(password="wrong-password").status_code, 401)

            locked = self.sign_in(password="wrong-password")
            self.assertEqual(locked.status_code, 429)
            self.assertIn("Too many failed attempts", locked.get_data(as_text=True))

            # Even the right password waits: guessing cannot go on in the meantime.
            self.assertEqual(self.sign_in().status_code, 429)

    def test_another_account_is_not_locked_out(self):
        with patch("app.routes.auth.time.sleep"):
            for _ in range(5):
                self.sign_in(password="wrong-password")

            self.assertEqual(self.sign_in(email=ACCOUNT_B).status_code, 302)

    def test_a_good_sign_in_clears_earlier_failures(self):
        with patch("app.routes.auth.time.sleep"):
            for _ in range(4):
                self.sign_in(password="wrong-password")
            self.assertEqual(self.sign_in().status_code, 302)
            self.client.post("/logout")

            for _ in range(4):
                self.assertEqual(self.sign_in(password="wrong-password").status_code, 401)

    def test_setup_info_is_private_to_the_signed_in_account(self):
        self.assertEqual(self.client.get("/api/setup").status_code, 401)

        self.sign_in()
        data = self.client.get("/api/setup", headers={"X-Forwarded-Proto": "https"}).get_json()

        self.assertEqual(data["endpoint"], "https://localhost/api/inbound/outlook")
        self.assertEqual(data["email"], ACCOUNT_A)
        self.assertEqual(data["token"], TOKEN_A)
        self.assertNotIn(TOKEN_B, str(data))

    def test_flow_package_is_filled_in_for_the_signed_in_account(self):
        self.assertEqual(self.client.get("/api/setup/flow.zip").status_code, 401)

        self.sign_in()
        response = self.client.get("/api/setup/flow.zip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            definition_name = next(name for name in names if name.endswith("definition.json"))
            text = archive.read(definition_name).decode("utf-8")
            for name in names:
                json.loads(archive.read(name))

        flow = json.loads(text)["properties"]["definition"]
        http = flow["actions"]["Send_each_email"]["actions"]["HTTP"]["inputs"]
        self.assertEqual(http["uri"], "http://localhost/api/inbound/outlook")
        self.assertEqual(http["headers"]["X-User-Email"], ACCOUNT_A)
        self.assertEqual(http["headers"]["X-Webhook-Token"], TOKEN_A)
        self.assertNotIn(TOKEN_B, text)
        self.assertNotIn("tenantId", text)

    def test_flow_url_is_saved_and_only_power_automate_hosts_are_allowed(self):
        self.sign_in()
        bad = self.client.post("/api/setup/flow-url", json={"url": "https://evil.example.com/hook"})
        self.assertEqual(bad.status_code, 400)
        plain = self.client.post("/api/setup/flow-url", json={"url": "http://prod-1.logic.azure.com/x"})
        self.assertEqual(plain.status_code, 400)

        url = "https://prod-12.southeastasia.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x"
        self.assertEqual(self.client.post("/api/setup/flow-url", json={"url": url}).status_code, 200)
        self.assertTrue(self.client.get("/api/setup").get_json()["flow_url_saved"])
        # The guide says whether the downloadable flow sends poster images.
        from app.mail import flow_package
        self.assertEqual(self.client.get("/api/setup").get_json()["flow_sends_images"], flow_package.INCLUDE_IMAGES)
        self.assertTrue(self.client.get("/api/inbound/diagnostics").get_json()["refresh_configured"])
        stored = json.loads(Path(os.environ["MULTIUSER_CONFIG_FILE"]).read_text())
        self.assertEqual(stored[ACCOUNT_A]["refresh_url"], url)
        self.assertEqual(stored[ACCOUNT_B]["refresh_url"], "")

    def test_each_student_can_switch_to_an_outlook_token(self):
        self.sign_in()
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["provider"], "powerautomate")
        self.assertTrue(session["canChooseSource"])

        response = self.client.post("/api/profile", json={"source": "outlook"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["provider"], "outlook")
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["provider"], "outlook")
        # Switching the source leaves the display name alone.
        self.assertEqual(session["name"], "Alice Tan")

        self.assertEqual(self.client.post("/api/profile", json={"source": "gmail"}).status_code, 400)

        # Another student keeps the default.
        other = self.app.test_client()
        page = other.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        other.post("/login", data={"email": ACCOUNT_B, "password": PASSWORD, "csrf_token": csrf, "next": "/"})
        self.assertEqual(other.get("/api/session").get_json()["provider"], "powerautomate")

        self.client.post("/api/profile", json={"source": "powerautomate"})
        self.assertEqual(self.client.get("/api/session").get_json()["provider"], "powerautomate")

    def token_sign_in(self, token="graph-token-123", status=200, me=None, **fields):
        page = self.client.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        reply = MagicMock(status_code=status, content=b"{}")
        reply.json.return_value = me if me is not None else {
            "mail": "Dana@u.nus.edu", "displayName": "Dana Lee"
        }
        with patch("app.accounts.requests.get", return_value=reply) as get:
            response = self.client.post(
                "/login/token", data={"token": token, "csrf_token": csrf, "next": "/", **fields}
            )
        return response, get

    def test_sign_in_page_offers_the_token_option(self):
        page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("Use an Outlook token instead", page)

    def test_student_can_sign_in_with_a_graph_token_without_an_account(self):
        response, get = self.token_sign_in()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer graph-token-123")
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["email"], "dana@u.nus.edu")
        self.assertEqual(session["name"], "Dana Lee")
        self.assertEqual(session["provider"], "outlook")
        self.assertFalse(session["canChooseSource"])
        self.assertEqual(session["graphToken"], "graph-token-123")
        # No account was created, and the token is not stored in the cookie.
        stored = json.loads(Path(os.environ["MULTIUSER_CONFIG_FILE"]).read_text())
        self.assertNotIn("dana@u.nus.edu", stored)
        cookie = self.client.get_cookie("session")
        self.assertNotIn("graph-token-123", cookie.value if cookie else "")

        self.client.post("/logout")
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_token_sign_in_rejects_bad_tokens_and_other_domains(self):
        response, _ = self.token_sign_in(status=401)
        self.assertEqual(response.status_code, 401)
        self.assertIn("expired", response.get_data(as_text=True))

        response, _ = self.token_sign_in(me={"mail": "someone@gmail.com"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_bad_tokens_from_other_people_do_not_lock_out_token_sign_in(self):
        rejected = MagicMock(status_code=401, content=b"{}")
        for index in range(6):  # more than the per-email limit (5), each from its own address
            page = self.client.get("/login").get_data(as_text=True)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
            with patch("app.accounts.requests.get", return_value=rejected):
                response = self.client.post(
                    "/login/token",
                    data={"token": "expired", "csrf_token": csrf, "next": "/"},
                    headers={"X-Forwarded-For": f"10.0.0.{index}"},
                )
            self.assertEqual(response.status_code, 401)

        response, _ = self.token_sign_in()          # someone else, with a good token
        self.assertEqual(response.status_code, 302)

    def test_token_sign_in_can_be_turned_off(self):
        with patch.dict(os.environ, {"ALLOW_TOKEN_LOGIN": "0"}):
            self.assertNotIn("Use an Outlook token instead", self.client.get("/login").get_data(as_text=True))
            response, get = self.token_sign_in()
        self.assertEqual(response.status_code, 403)
        get.assert_not_called()

    def test_connect_step_saves_flow_url_or_picks_a_token(self):
        self.register()
        page = self.client.get("/register/connect")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("Step 2 of 2", text)
        self.assertIn("/api/setup/flow.zip", text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', text).group(1)

        bad = self.client.post("/register/connect", data={
            "csrf_token": csrf, "action": "flow-url", "url": "https://evil.example.com/x"})
        self.assertEqual(bad.status_code, 400)

        csrf = re.search(r'name="csrf_token" value="([^"]+)"', bad.get_data(as_text=True)).group(1)
        url = "https://prod-1.southeastasia.logic.azure.com/workflows/x/triggers/manual/paths/invoke?sig=y"
        good = self.client.post("/register/connect", data={"csrf_token": csrf, "action": "flow-url", "url": url})
        self.assertEqual(good.status_code, 200)
        self.assertIn("Saved", good.get_data(as_text=True))
        self.assertTrue(self.client.get("/api/setup").get_json()["flow_url_saved"])

        csrf = re.search(r'name="csrf_token" value="([^"]+)"', good.get_data(as_text=True)).group(1)
        token = self.client.post("/register/connect", data={"csrf_token": csrf, "action": "token"})
        self.assertEqual(token.headers["Location"], "/")
        self.assertEqual(self.client.get("/api/session").get_json()["provider"], "outlook")

    def test_signed_in_register_link_goes_to_the_connect_step(self):
        self.sign_in()
        response = self.client.get("/register")
        self.assertTrue(response.headers["Location"].endswith("/register/connect"))

    def test_connect_step_needs_a_signed_in_account(self):
        response = self.client.get("/register/connect")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_emails_come_back_with_saved_results_after_a_reload(self):
        from app.stores import classification_store
        self.sign_in()
        self.client.post(
            "/api/inbound/outlook",
            json={"internetMessageId": "m-1", "subject": "Hi", "body": "There", "from": "prof@nus.edu.sg"},
            headers={"X-Webhook-Token": TOKEN_A},
        )
        first = self.client.post("/api/emails", json={"provider": "powerautomate", "count": 10, "backend": "ml"}).get_json()
        email = first["emails"][0]
        self.assertIsNone(email["saved_classification"])

        classification_store.classify_cache.put(
            ACCOUNT_A, "ml", email["id"], {"content_category": "general", "reply_nature": "reminder", "reason": "x"}
        )
        again = self.client.post("/api/emails", json={"provider": "powerautomate", "count": 10, "backend": "ml"}).get_json()
        saved = again["emails"][0]["saved_classification"]
        self.assertEqual(saved["reply_nature"], "reminder")
        self.assertTrue(saved["cached"])

    def test_cross_site_writes_are_refused(self):
        self.sign_in()
        evil = self.client.post(
            "/api/profile", json={"name": "Hacked"}, headers={"Origin": "https://evil.ngrok-free.dev"}
        )
        self.assertEqual(evil.status_code, 403)
        same = self.client.post(
            "/api/profile", json={"name": "Ali"}, headers={"Origin": "http://localhost"}
        )
        self.assertEqual(same.status_code, 200)
        # The Power Automate webhook is server-to-server and keeps working.
        pushed = self.client.post(
            "/api/inbound/outlook",
            json={"subject": "Hi", "body": "There", "from": "prof@nus.edu.sg"},
            headers={"X-Webhook-Token": TOKEN_A, "Origin": "https://flow.example"},
        )
        self.assertEqual(pushed.status_code, 200)

    def test_pages_cannot_be_framed_and_big_bodies_are_refused(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

        huge = self.client.post(
            "/api/inbound/outlook",
            data=b"x" * (self.app.config["MAX_CONTENT_LENGTH"] + 1),
            headers={"X-Webhook-Token": TOKEN_A, "Content-Type": "application/json"},
        )
        self.assertEqual(huge.status_code, 413)

    def test_non_object_json_is_a_400_not_a_crash(self):
        self.sign_in()
        self.assertEqual(self.client.post("/api/emails", json=[1, 2]).status_code, 400)
        self.assertEqual(self.client.post("/api/classify", json="x").status_code, 400)

    def register(self, **fields):
        page = self.client.get("/register").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        form = {
            "name": "Carol",
            "email": "carol@u.nus.edu",
            "password": "carol-pass-123",
            "confirm": "carol-pass-123",
            "csrf_token": csrf,
        }
        form.update(fields)
        return self.client.post("/register", data=form)

    def test_new_student_can_sign_up_and_gets_their_own_token(self):
        response = self.register()

        self.assertEqual(response.status_code, 302)
        # Step 2 of sign-up: connect Outlook before the app opens.
        self.assertTrue(response.headers["Location"].endswith("/register/connect"))
        session = self.client.get("/api/session").get_json()
        self.assertEqual(session["email"], "carol@u.nus.edu")
        self.assertEqual(session["name"], "Carol")

        setup = self.client.get("/api/setup").get_json()
        self.assertGreaterEqual(len(setup["token"]), 32)
        self.assertNotIn(setup["token"], (TOKEN_A, TOKEN_B))

        stored = json.loads(Path(os.environ["MULTIUSER_CONFIG_FILE"]).read_text())
        self.assertIn("carol@u.nus.edu", stored)
        self.assertNotEqual(stored["carol@u.nus.edu"]["password_hash"], "carol-pass-123")

        # The new token is accepted by the webhook straight away.
        pushed = self.app.test_client().post(
            "/api/inbound/outlook",
            json={"subject": "Hi", "body": "There", "from": "prof@nus.edu.sg"},
            headers={"X-Webhook-Token": setup["token"]},
        )
        self.assertEqual(pushed.status_code, 200)

    def test_sign_up_rejects_other_domains_and_duplicates(self):
        self.assertEqual(self.register(email="someone@gmail.com").status_code, 400)
        self.assertEqual(self.register(email=ACCOUNT_A).status_code, 400)
        self.assertEqual(self.register(confirm="different-pass").status_code, 400)
        self.assertEqual(self.register(password="short", confirm="short").status_code, 400)

    def test_sign_up_code_is_required_when_set(self):
        with patch.dict(os.environ, {"SIGNUP_CODE": "dss5105"}):
            self.assertEqual(self.register().status_code, 400)
            self.assertEqual(self.register(code="dss5105").status_code, 302)

    def test_sign_up_can_be_turned_off(self):
        with patch.dict(os.environ, {"ALLOW_SIGNUP": "0"}):
            self.assertEqual(self.client.get("/register").status_code, 302)


if __name__ == "__main__":
    unittest.main()
