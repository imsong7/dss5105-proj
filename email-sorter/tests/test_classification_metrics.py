"""Metrics are opt-in, accurate, free of email content and never break classification."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.classifiers import classification_metrics
from app.schemas import Email
from tests.test_claude_classifier import _classifier


def _result(**over):
    base = dict(
        topic="Others", action="Needs a reply", confidence=0.9, source="claude",
        reason="r", rules_fired=[], api_called=True, api_duration_ms=900,
        input_tokens=120, output_tokens=9, stop_reason="end_turn", app_attempts=2,
        app_retry_attempts=1, retry_call_ms=400, retry_backoff_ms=0, error=None, error_type=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


SECRET = Email(id="msg-id-123", subject="Secret subject", sender="alice@private.example", body="Secret body text")


class MetricsTests(unittest.TestCase):
    def _events(self, result, enabled=True):
        with patch.object(classification_metrics, "_ENABLED", enabled), \
                self.assertLogs("classification.metrics", level="INFO") if enabled else _NoLogs() as cm:
            _classifier(result).classify(SECRET)
        return [json.loads(r.getMessage()) for r in cm.records] if enabled else []

    def test_retry_call_time_is_not_reported_as_backoff(self):
        call = next(e for e in self._events(_result()) if e["event"] == "claude_api_call")
        self.assertEqual((call["retry_call_ms"], call["retry_backoff_ms"]), (400, 0))
        self.assertEqual((call["app_attempts"], call["app_retry_attempts"]), (2, 1))
        self.assertEqual((call["sdk_retries"], call["sdk_retry_wait_ms"]), ("unknown", "unknown"))
        self.assertNotIn("app_retry_wait_ms", call)

    def test_api_called_comes_from_the_invocation_not_the_source(self):
        failed = _result(source="fallback", api_called=True, api_duration_ms=700, error_type="Timeout")
        call = next(e for e in self._events(failed) if e["event"] == "claude_api_call")
        self.assertTrue(call["api_called"])
        self.assertEqual((call["api_duration_ms"], call["error_type"]), (700, "Timeout"))

        shortcut = _result(source="shortcut", api_called=False, api_duration_ms=None, input_tokens=None)
        call = next(e for e in self._events(shortcut) if e["event"] == "claude_api_call")
        self.assertFalse(call["api_called"])
        self.assertEqual(call["api_duration_ms"], "unknown")

    def test_no_email_content_or_ids_are_logged(self):
        text = json.dumps(self._events(_result(error="alice@private.example leaked", error_type="X")))
        for secret in ("Secret", "alice@private", "msg-id-123"):
            self.assertNotIn(secret, text)  # `error` text is never logged; only error_type
        self.assertNotIn("leaked", text)

    def test_disabled_by_default_logs_nothing(self):
        with patch.object(classification_metrics, "_ENABLED", False), \
                self.assertNoLogs("classification.metrics"):
            _classifier(_result()).classify(SECRET)

    def test_logging_failure_does_not_affect_classification(self):
        with patch.object(classification_metrics, "_ENABLED", True), \
                patch.object(classification_metrics.log, "info", side_effect=RuntimeError("sink down")), \
                patch.object(classification_metrics.log, "exception"):
            out = _classifier(_result()).classify(SECRET)
        self.assertEqual(out.reply_nature, "needs_reply")


class _NoLogs:
    def __enter__(self): return SimpleNamespace(records=[])
    def __exit__(self, *a): return False


if __name__ == "__main__":
    unittest.main()
