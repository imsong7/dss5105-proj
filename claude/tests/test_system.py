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

    def __call__(self, text):
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



