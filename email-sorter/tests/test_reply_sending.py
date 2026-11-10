import unittest
from unittest.mock import Mock, patch

from app.reply_sending import ReplySendError, send_reply
from app.schemas import Email
from app.server import create_app

EMAIL = Email(
    id="m1",
    subject="Consultation slot",
    sender="Prof Lim <lim@nus.edu.sg>",
    received="2026-11-01T00:00:00+00:00",
    body="I can meet on Friday at 3pm.",
)


class ReplySendingTests(unittest.TestCase):
    @patch("app.reply_sending.requests.post")
    def test_sends_a_reply_to_the_original_sender(self, post):
        post.return_value = Mock(status_code=202, ok=True, reason="Accepted")

        result = send_reply(EMAIL, "Thank you, Friday works for me.", "token-123")

        self.assertTrue(result["sent"])
        self.assertEqual(result["to"], "lim@nus.edu.sg")
        self.assertEqual(result["subject"], "Re: Consultation slot")
        call = post.call_args
        self.assertEqual(call.args[0], "https://graph.microsoft.com/v1.0/me/sendMail")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer token-123")
        payload = call.kwargs["json"]
        self.assertEqual(payload["message"]["body"]["content"], "Thank you, Friday works for me.")
        self.assertEqual(
            payload["message"]["toRecipients"][0]["emailAddress"]["address"],
            "lim@nus.edu.sg",
        )
        self.assertTrue(payload["saveToSentItems"])

    def test_rejects_a_missing_token(self):
        with self.assertRaises(ReplySendError) as raised:
            send_reply(EMAIL, "Hello", "")
        self.assertEqual(raised.exception.status_code, 400)

    @patch("app.reply_sending.requests.post")
    def test_reports_a_missing_send_permission(self, post):
        post.return_value = Mock(
            status_code=403,
            ok=False,
            reason="Forbidden",
            json=lambda: {"error": {"message": "Access denied"}},
        )

        with self.assertRaises(ReplySendError) as raised:
            send_reply(EMAIL, "Hello", "token-123")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("Mail.Send", str(raised.exception))


class SendReplyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(backend="llama", provider="graphtoken").test_client()

    @patch("app.server.remember_session_graph_token")
    @patch("app.server.send_graph_reply")
    def test_endpoint_returns_the_receipt_and_remembers_the_token(self, send, remember):
        send.return_value = {"sent": True, "to": "lim@nus.edu.sg", "subject": "Re: Consultation slot"}

        response = self.client.post(
            "/api/send-reply",
            json={
                "email": EMAIL.model_dump(),
                "reply": "Thank you, Friday works for me.",
                "token": "token-123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["to"], "lim@nus.edu.sg")
        sent_email, reply, token = send.call_args.args
        self.assertEqual(sent_email.id, "m1")
        self.assertEqual(reply, "Thank you, Friday works for me.")
        self.assertEqual(token, "token-123")
        remember.assert_called_once_with("token-123")

    @patch("app.server.remember_session_graph_token")
    @patch("app.server.send_graph_reply")
    def test_endpoint_reports_send_errors(self, send, remember):
        send.side_effect = ReplySendError("The token is missing Mail.Send permission.", 403)

        response = self.client.post(
            "/api/send-reply",
            json={"email": EMAIL.model_dump(), "reply": "Hello", "token": "token-123"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("Mail.Send", response.get_json()["error"])
        remember.assert_not_called()

    def test_endpoint_rejects_a_missing_reply(self):
        response = self.client.post("/api/send-reply", json={"email": EMAIL.model_dump()})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
