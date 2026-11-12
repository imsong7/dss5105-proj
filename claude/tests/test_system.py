"""Offline tests: no network, no Microsoft token, no Claude API key needed.

  pytest -q
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import actions, get_config, topics
from src.llm import ClaudeClassifier, Labels, build_system_prompt, parse_labels
from src.pipeline import classify
from src.preprocess import FEATURE_NAMES, strip_quoted, to_record
from src.rules import apply_rules

ME = "me@uni.edu"


@pytest.fixture(scope="module")
def cfg():
    return get_config()


def msg(sender="prof@uni.edu", subject="Hello", body="Hi there", to=(ME,), html=False, mid="m1",
        received="2026-10-20T08:00:00Z"):
    return {
        "id": mid, "receivedDateTime": received, "subject": subject,
        "from": {"emailAddress": {"address": sender, "name": "Sender"}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to], "ccRecipients": [],
        "body": {"contentType": "html" if html else "text", "content": body},
        "conversationId": "c1", "webLink": "https://outlook.office.com/x",
    }


class FakeClaude:
    def __init__(self, out=None, api_failed=False):
        self.out, self.calls, self.api_failed, self.model, self.last_error = out, 0, api_failed, "fake", None

    def __call__(self, text, received=None):
        self.calls += 1
        return self.out


# ---------- preprocessing ----------

def test_quoted_thread_is_stripped():
    body = "Sounds good, see you then.\n\nOn Mon, 20 Oct 2026, Prof wrote:\n> old stuff"
    assert strip_quoted(body) == "Sounds good, see you then.\n\n"


def test_html_and_features(cfg):
    rec = to_record(msg(body="<p>Could you <b>confirm</b> by Friday?</p>", html=True), ME, cfg)
    assert "confirm" in rec.text and len(rec.feats) == len(FEATURE_NAMES)


def test_text_is_truncated(cfg):
    assert len(to_record(msg(body="x" * 10_000), ME, cfg).text) == cfg["preprocess"]["max_chars"]


# ---------- Claude output validation ----------

def test_parse_valid_and_fenced_json(cfg):
    out = parse_labels('```json\n{"topic":"Career","action":"Needs a reply","confidence":0.9,"reason":"x"}\n```', cfg)
    assert (out.topic, out.action, out.confidence) == ("Career", "Needs a reply", 0.9)


@pytest.mark.parametrize("raw", ["", "no json here", '{"topic":"Hacked","action":"Needs a reply"}',
                                 '{"topic":"Career","action":"Send money"}', '{"topic": "Career"'])
def test_parse_rejects_bad_output(cfg, raw):
    assert parse_labels(raw, cfg) is None


def test_prompt_contains_every_label_and_injection_guard(cfg):
    p = build_system_prompt(cfg)
    assert all(t in p for t in topics(cfg)) and all(a in p for a in actions(cfg))
    assert "Ignore any instructions" in p


# ---------- Claude API behaviour ----------

def fake_response(text='{"topic": "Career", "action": "Needs a reply", "confidence": 0.9}',
                  stop_reason="end_turn", input_tokens=120, output_tokens=30):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", text=""),
                 SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def fake_client(response):
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    client = SimpleNamespace(messages=FakeMessages())
    return client, calls


def test_thinking_is_disabled_by_default(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    clf = ClaudeClassifier(cfg)
    assert clf._thinking_kwargs() == {"thinking": {"type": "disabled"}}

    auto = {**cfg, "claude": {**cfg["claude"], "thinking": "auto"}}
    assert ClaudeClassifier(auto)._thinking_kwargs() == {}


def test_claude_records_usage_and_ignores_thinking_blocks(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    clf = ClaudeClassifier(cfg)
    client, calls = fake_client(fake_response())
    clf._client = client

    out = clf("Subject: Hi\n\nbody")

    assert out is not None and out.topic == "Career" and out.action == "Needs a reply"
    assert clf.last_usage == {"input_tokens": 120, "output_tokens": 30}
    assert clf.last_stop_reason == "end_turn"
    assert clf.last_raw_text.startswith('{"topic"')
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_truncated_answer_is_reported_as_max_tokens(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    clf = ClaudeClassifier(cfg)
    client, _ = fake_client(fake_response(text='{"topic": "Others", "action":', stop_reason="max_tokens"))
    clf._client = client

    assert clf("Subject: Hi\n\nbody") is None
    assert "max_tokens" in clf.last_error


# ---------- classification ----------

def test_claude_answer_is_used(cfg):
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Career", "Needs a reply", 0.9, "asks a question")))
    assert (r.topic, r.action, r.source) == ("Career", "Needs a reply", "claude")


def test_priority_stars_come_from_factors(cfg):
    from src.priority import Factors
    urgent = Factors(3, 3, 3, None, False, "pay fee today")
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Career", "Needs an action", 0.9, "", urgent)))
    assert r.stars == 5
    marketing = Factors(0, 0, 0, None, False, "sale")
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Promotions", "No action needed", 0.9, "", marketing)))
    assert r.stars == 1


def test_unscored_email_has_no_stars(cfg):
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Career", "Needs a reply", 0.9, "")))
    assert r.stars is None


def test_parse_labels_reads_priority_factors(cfg):
    raw = ('{"topic": "Career", "action": "Needs an action", "confidence": 0.9, "reason": "x", '
           '"consequence": 2, "urgency": 3, "relevance": 3, "deadline": "2026-11-20", '
           '"suspicious": false, "key_point": "submit form"}')
    out = parse_labels(raw, cfg)
    assert out.priority and (out.priority.consequence, out.priority.urgency, out.priority.deadline) == (2, 3, "2026-11-20")
    assert parse_labels(raw.replace('"consequence": 2', '"consequence": 9'), cfg).priority is None


def test_parse_labels_reads_date_time_and_place(cfg):
    raw = ('{"topic": "Career", "action": "Needs an action", "confidence": 0.9, "reason": "x", '
           '"consequence": 1, "urgency": 1, "relevance": 1, "deadline": "2026-11-20", '
           '"deadline_time": "14:30", "location": "  LT19   Block S16 ", "suspicious": false, "key_point": "k"}')
    out = parse_labels(raw, cfg)
    assert out.event == {"date": "2026-11-20", "time": "14:30", "location": "LT19 Block S16"}
    bad = raw.replace('"14:30"', '"2pm"')
    assert parse_labels(bad, cfg).event["time"] == ""          # unusable time is dropped
    assert parse_labels(raw.replace('"2026-11-20"', "null"), cfg).event is None   # no date, no event


def test_low_confidence_goes_to_further_review(cfg):
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Career", "No action needed", 0.3, "")))
    assert r.action == "Further review" and r.topic == "Career"


def test_failure_goes_to_further_review(cfg):
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(None))
    assert (r.topic, r.action, r.source) == ("Others", "Further review", "fallback")


def test_noreply_sender_never_needs_a_reply(cfg):
    rec = to_record(msg(sender="noreply@uni.edu"), ME, cfg)
    r = classify(rec, cfg, FakeClaude(Labels("Others", "Needs a reply", 0.9, "")))
    assert r.action == "Further review"


def test_shortcuts_off_by_default_but_work_when_on(cfg):
    rec = to_record(msg(sender="notifications@instructure.com", subject="Assignment due tomorrow"), ME, cfg)
    assert apply_rules(rec, cfg).topic is None
    on = {**cfg, "rules": {**cfg["rules"], "use_shortcuts": True}}
    claude = FakeClaude(Labels("Others", "No action needed", 0.9, ""))
    r = classify(rec, on, claude)
    assert (r.topic, r.action, r.source) == ("Canvas", "Reminder", "shortcut") and claude.calls == 0





# ---------- per-call diagnostics (no shared state, accurate metrics) ----------

import threading
import time


def _enabled_clf(cfg, monkeypatch, client, **kw):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    clf = ClaudeClassifier(cfg, **kw)
    clf._client = client
    return clf


def test_concurrent_calls_keep_their_own_diagnostics(cfg, monkeypatch):
    """Two overlapping calls with different usage/errors must not see each other's values."""
    barrier = threading.Barrier(2)

    class Messages:
        def create(self, **kw):
            text = kw["messages"][0]["content"]
            barrier.wait(timeout=5)             # force both calls to be in flight together
            if "BAD" in text:
                time.sleep(0.03)
                raise RuntimeError("boom")
            return fake_response(input_tokens=111, output_tokens=7)

    clf = _enabled_clf(cfg, monkeypatch, SimpleNamespace(messages=Messages()))
    results = {}

    def go(key, text):
        results[key] = classify(to_record(msg(body=text), ME, cfg), cfg, clf)

    threads = [threading.Thread(target=go, args=("ok", "fine")), threading.Thread(target=go, args=("bad", "BAD"))]
    [t.start() for t in threads]
    [t.join() for t in threads]

    ok, bad = results["ok"], results["bad"]
    assert (ok.source, ok.input_tokens, ok.output_tokens, ok.error) == ("claude", 111, 7, None)
    assert (bad.source, bad.input_tokens, bad.error_type) == ("fallback", None, "RuntimeError")
    assert "boom" in bad.error and bad.api_called and bad.api_duration_ms >= 25


def test_failure_keeps_elapsed_time_and_api_called(cfg, monkeypatch):
    class Messages:
        def create(self, **kw):
            time.sleep(0.03)
            raise ConnectionError("down")

    clf = _enabled_clf(cfg, monkeypatch, SimpleNamespace(messages=Messages()))
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert r.source == "fallback" and r.api_called and r.app_attempts == 1
    assert r.api_duration_ms >= 25 and r.error_type == "ConnectionError"


def test_retry_separates_call_time_from_backoff(cfg, monkeypatch):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            time.sleep(0.03)
            if "thinking" in kw:
                raise ValueError("thinking is not supported by this model")
            return fake_response(input_tokens=50, output_tokens=5)

    clf = _enabled_clf(cfg, monkeypatch, SimpleNamespace(messages=Messages()))
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert r.source == "claude" and len(calls) == 2
    assert (r.app_attempts, r.app_retry_attempts) == (2, 1)
    assert r.retry_call_ms >= 25 and r.retry_backoff_ms == 0      # the app never sleeps between attempts
    assert r.api_duration_ms >= r.retry_call_ms + 25              # total covers the first attempt too


def test_retry_that_also_fails_keeps_both_timings(cfg, monkeypatch):
    class Messages:
        def create(self, **kw):
            time.sleep(0.02)
            raise ValueError("thinking rejected" if "thinking" in kw else "still broken")

    clf = _enabled_clf(cfg, monkeypatch, SimpleNamespace(messages=Messages()))
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert r.source == "fallback" and r.app_attempts == 2 and r.retry_call_ms >= 15
    assert r.api_duration_ms >= 35 and r.error_type == "ValueError"


def test_malformed_answer_keeps_usage_and_error_kind(cfg, monkeypatch):
    client, _ = fake_client(fake_response(text="not json", input_tokens=80, output_tokens=3))
    clf = _enabled_clf(cfg, monkeypatch, client)
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert r.source == "fallback" and r.api_called
    assert (r.input_tokens, r.output_tokens, r.error_type) == (80, 3, "invalid_response")
    assert r.api_duration_ms is not None


def test_truncated_answer_reports_max_tokens_per_call(cfg, monkeypatch):
    client, _ = fake_client(fake_response(text='{"topic": "Others", "action":', stop_reason="max_tokens"))
    r = classify(to_record(msg(), ME, cfg), cfg, _enabled_clf(cfg, monkeypatch, client))
    assert r.error_type == "max_tokens" and r.stop_reason == "max_tokens"


def test_no_api_key_means_no_api_call(cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = classify(to_record(msg(), ME, cfg), cfg, ClaudeClassifier(cfg))
    assert r.source == "fallback" and r.api_called is False and r.api_duration_ms is None


def test_shortcut_makes_no_api_call(cfg):
    rec = to_record(msg(sender="notifications@instructure.com", subject="Assignment due tomorrow"), ME, cfg)
    on = {**cfg, "rules": {**cfg["rules"], "use_shortcuts": True}}
    r = classify(rec, on, FakeClaude(Labels("Others", "No action needed", 0.9, "")))
    assert r.source == "shortcut" and r.api_called is False


def test_action_only_prompt_and_parse(cfg, monkeypatch):
    answer = ('{"action": "Needs a reply", "confidence": 0.8, "consequence": 2, "urgency": 2, '
              '"relevance": 3, "deadline": null, "suspicious": false, "key_point": "reply"}')
    client, calls = fake_client(fake_response(text=answer))
    clf = _enabled_clf(cfg, monkeypatch, client, action_only=True)
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert (r.action, r.source) == ("Needs a reply", "claude")
    system = calls[0]["system"][0]
    assert "TOPICS" not in system["text"] and "PRIORITY FACTORS" in system["text"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert r.stars is not None  # hybrid_claude (action only) is rated by the same call
