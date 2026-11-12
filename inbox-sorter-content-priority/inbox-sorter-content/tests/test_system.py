"""Offline tests: no network, no Microsoft token, no Claude API key needed.

  pytest -q
"""
from __future__ import annotations

import base64
import json
import time

import pytest

from src import graph_token, store
from src.config import actions, get_config, topics
from src.llm import Labels, build_system_prompt, parse_labels
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


def fake_jwt(exp: float, scp="Mail.Read User.Read", upn="me@uni.edu") -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'exp': exp, 'scp': scp, 'upn': upn})}.sig"


class FakeClaude:
    def __init__(self, out=None, api_failed=False):
        self.out, self.calls, self.api_failed, self.model, self.last_error = out, 0, api_failed, "fake", None

    def __call__(self, text, received=None):
        self.calls += 1
        self.received = received
        return self.out


# ---------- token handling ----------

def test_token_is_cleaned_and_inspected(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_token, "TOKEN_FILE", tmp_path / "t.txt")
    tok = fake_jwt(time.time() + 3600)
    info = graph_token.save(f"  Bearer {tok[:20]}\n{tok[20:]}  ")
    assert graph_token.load() == tok
    assert 55 < info.minutes_left <= 60 and info.can_read_mail and info.account == "me@uni.edu"
    assert graph_token.get() == tok


def test_expired_token_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_token, "TOKEN_FILE", tmp_path / "t.txt")
    graph_token.save(fake_jwt(time.time() - 10))
    with pytest.raises(graph_token.TokenExpired):
        graph_token.get()


def test_token_without_mail_scope_is_flagged():
    assert graph_token.inspect(fake_jwt(time.time() + 3600, scp="User.Read")).can_read_mail is False


def test_garbage_token_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_token, "TOKEN_FILE", tmp_path / "t.txt")
    with pytest.raises(ValueError):
        graph_token.save("not a token")


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


# ---------- sync (fake mailbox) ----------

def test_sync_labels_new_mail_once_and_retries_on_api_failure(cfg, tmp_path, monkeypatch):
    import src.sync as sync
    con = store.connect(tmp_path / "s.db")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mails = [msg(mid=f"m{i}", received=now) for i in range(3)]
    monkeypatch.setattr(sync, "list_inbox", lambda token, since, max_n: mails)
    monkeypatch.setattr(sync, "my_address", lambda token: ME)

    down = FakeClaude(None, api_failed=True)
    rep = sync.sync_once(con, cfg, "tok", down)
    assert rep.labelled == 0 and rep.remaining == 3 and down.calls == 1   # stops, nothing filed

    ok = FakeClaude(Labels("Career", "Reminder", 0.9, ""))
    assert sync.sync_once(con, cfg, "tok", ok).labelled == 3
    assert sync.sync_once(con, cfg, "tok", ok).labelled == 0              # no duplicates
    assert ok.calls == 3


# ---------- storage ----------

def test_store_never_holds_bodies_and_records_corrections(cfg, tmp_path):
    con = store.connect(tmp_path / "t.db")
    rec = to_record(msg(mid="abc"), ME, cfg)
    store.save(con, rec, classify(rec, cfg, FakeClaude(Labels("Career", "Needs a reply", 0.9, ""))), "m", True)
    cols = [c[1] for c in con.execute("PRAGMA table_info(emails)")]
    assert "body" not in cols and "text" not in cols
    store.save_correction(con, "abc", "action", "Reminder")
    rep = store.corrections_report(con)
    assert rep.iloc[0]["old"] == "Needs a reply" and rep.iloc[0]["new"] == "Reminder"
    assert store.health(con)["correction_rate"] == 1.0


# ---------- priority ranking ----------

from src.priority import Factors, STAR_TEXT, compute, urgency_from_deadline  # noqa: E402
from src.pipeline import Result  # noqa: E402

RECEIVED = "2026-11-10T02:00:00Z"   # 10 Nov, 10:00 in Singapore


def F(c, u, r, deadline=None, susp=False):
    return Factors(c, u, r, deadline, susp, "key point")


@pytest.mark.parametrize("topic,action,f,stars", [
    ("Others", "Needs an action", F(3, 3, 3), 5),            # tuition fee due soon
    ("Promotions", "Needs an action", F(1, 3, 0), 3),        # sale ends tonight
    ("Promotions", "Needs an action", F(3, 3, 3), 3),        # promotions can never exceed 3
    ("Career", "Needs a reply", F(3, 2, 3), 5),              # interview invitation
    ("FoS General", "Needs a reply", F(2, 2, 3), 4),         # lecturer asks for project topic
    ("Canvas", "Reminder", F(2, 3, 2), 4),                   # assignment due tomorrow
    ("Career", "Reminder", F(1, 1, 1), 3),                   # career fair next month
    ("FoS General", "No action needed", F(0, 0, 1), 1),      # newsletter
    ("Others", "Needs an action", F(3, 3, 3, susp=True), 2), # phishing capped
])
def test_priority_examples_combined(cfg, topic, action, f, stars):
    assert compute(topic, action, f, RECEIVED, cfg, model="combined").stars == stars


def test_floor_lifts_serious_and_soon(cfg):
    p = compute("Others", "No action needed", F(3, 2, 1), RECEIVED, cfg, model="combined")
    assert p.stars == 2 and "No action needed cap" in p.notes                # caps win over floors
    p = compute("Others", "Reminder", F(3, 2, 1), RECEIVED, cfg, model="combined")
    assert p.stars == 4
    p = compute("Others", "Further review", F(3, 2, 0), RECEIVED, cfg, model="combined")
    assert p.stars == 3


def test_personal_reply_floor(cfg):
    p = compute("Promotions", "Needs a reply", F(0, 0, 3), RECEIVED, cfg, model="combined")
    assert p.stars == 3 and "personal reply" in p.notes


@pytest.mark.parametrize("deadline,urgency", [
    ("2026-11-10", 3), ("2026-11-12", 3), ("2026-11-15", 2), ("2026-11-17", 2),
    ("2026-11-30", 1), ("2027-01-20", 0), ("2026-11-01", 3), (None, 1), ("next week", 1),
])
def test_urgency_counted_from_arrival(cfg, deadline, urgency):
    assert urgency_from_deadline(deadline, RECEIVED, 1, cfg) == urgency


def test_stars_fixed_from_arrival_not_today(cfg):
    # The same email gets the same stars whenever it is scored: today's date plays no part.
    a = compute("Canvas", "Reminder", F(2, 0, 2, "2026-11-11"), RECEIVED, cfg)
    b = compute("Canvas", "Reminder", F(2, 0, 2, "2026-11-11"), RECEIVED, cfg)
    assert a == b and a.urgency == 3


def test_singapore_day_boundary(cfg):
    # 17:00 UTC on 10 Nov is 01:00 on 11 Nov in Singapore: a deadline of 11 Nov is 0 days away.
    assert urgency_from_deadline("2026-11-11", "2026-11-10T17:00:00Z", 0, cfg) == 3
    assert urgency_from_deadline("2026-11-18", "2026-11-10T17:00:00Z", 0, cfg) == 2


def test_parse_factors(cfg):
    raw = ('{"topic":"Others","action":"Needs an action","confidence":0.9,"reason":"fee",'
           '"consequence":3,"urgency":2,"relevance":3,"deadline":"2026-11-13","suspicious":false,'
           '"key_point":"Tuition due 13 Nov, late fee after"}')
    out = parse_labels(raw, cfg)
    assert out.priority == Factors(3, 2, 3, "2026-11-13", False, "Tuition due 13 Nov, late fee after")


@pytest.mark.parametrize("extra", ['"consequence":5,"urgency":2,"relevance":3',
                                   '"consequence":"high","urgency":2,"relevance":3',
                                   '"consequence":1.5,"urgency":2,"relevance":3',
                                   '"urgency":2,"relevance":3'])
def test_bad_factors_leave_labels_but_no_priority(cfg, extra):
    out = parse_labels('{"topic":"Career","action":"Reminder","confidence":0.9,' + extra + '}', cfg)
    assert out.topic == "Career" and out.priority is None


def test_bad_deadline_is_ignored(cfg):
    out = parse_labels('{"topic":"Career","action":"Reminder","confidence":0.9,"consequence":1,'
                       '"urgency":2,"relevance":2,"deadline":"soon","suspicious":"true"}', cfg)
    assert out.priority.deadline is None and out.priority.suspicious is True


def test_prompt_has_priority_rubric(cfg):
    p = build_system_prompt(cfg)
    assert "consequence" in p and "suspicious" in p and "how to label or rank it" in p


def test_classify_gives_stars_and_passes_received_date(cfg):
    claude = FakeClaude(Labels("Others", "Needs an action", 0.9, "", F(3, 3, 3)))
    rec = to_record(msg(received=RECEIVED), ME, cfg)
    r = classify(rec, cfg, claude)
    assert r.stars == 5 and claude.received == RECEIVED


def test_stars_use_final_labels_after_guardrails(cfg):
    # Low confidence moves the action to Further review; stars are computed from that final action.
    claude = FakeClaude(Labels("Promotions", "Needs an action", 0.3, "", F(1, 3, 0)))
    r = classify(to_record(msg(), ME, cfg), cfg, claude)
    assert r.action == "Further review" and r.priority.score == 2.0 * 1 + 1.5 * 3 + 0   # content only


def test_failure_is_unrated(cfg):
    assert classify(to_record(msg(), ME, cfg), cfg, FakeClaude(None)).stars is None


def test_missing_factors_is_unrated(cfg):
    r = classify(to_record(msg(), ME, cfg), cfg, FakeClaude(Labels("Career", "Reminder", 0.9, "")))
    assert r.topic == "Career" and r.stars is None


def test_shortcut_uses_neutral_factors(cfg):
    on = {**cfg, "rules": {**cfg["rules"], "use_shortcuts": True}}
    rec = to_record(msg(sender="notifications@instructure.com", subject="Assignment due"), ME, on)
    r = classify(rec, on, FakeClaude(None))
    assert r.source == "shortcut" and r.stars == 2     # content only: 2 + 1.5 + 1 = 4.5


def test_star_override_and_display(cfg, tmp_path):
    con = store.connect(tmp_path / "p.db")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec = to_record(msg(mid="p1", received=now), ME, cfg)
    store.save(con, rec, classify(rec, cfg, FakeClaude(Labels("Promotions", "Needs an action", 0.9, "",
                                                                F(1, 3, 0)))), "m", True)
    row = store.dashboard_rows(con, 7, 10).iloc[0]
    assert row["stars"] == 3 and row["stars_auto"] == 3
    store.save_correction(con, "p1", "stars", 1)
    row = store.dashboard_rows(con, 7, 10).iloc[0]
    assert row["stars"] == 1 and row["stars_auto"] == 3          # override shown, original kept
    assert store.health(con)["star_override_rate"] == 1.0
    with pytest.raises(ValueError):
        store.save_correction(con, "p1", "stars", 6)


def test_old_database_is_upgraded(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""CREATE TABLE predictions (email_id TEXT PRIMARY KEY, topic TEXT, action TEXT,
        confidence REAL, source TEXT, reason TEXT, rules_fired TEXT, model TEXT, visible INTEGER, created TEXT);
        INSERT INTO predictions VALUES ('x','Career','Reminder',0.9,'claude','','','m',1,'2026-11-01');""")
    old.commit(); old.close()
    con = store.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
    assert {"stars_auto", "stars_user", "deadline", "suspicious"} <= cols
    assert con.execute("SELECT topic, stars_auto FROM predictions").fetchone() == ("Career", None)


def test_reclassify_keeps_labels_and_owner_stars(cfg, tmp_path, monkeypatch):
    import src.sync as sync
    con = store.connect(tmp_path / "r.db")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mails = [msg(mid="a", received=now), msg(mid="b", received=now)]
    monkeypatch.setattr(sync, "list_inbox", lambda token, since, max_n: mails)
    monkeypatch.setattr(sync, "my_address", lambda token: ME)
    for m in mails:   # labelled before priority existed: no factors
        rec = to_record(m, ME, cfg)
        store.save(con, rec, Result("Career", "Needs a reply", 0.9, "claude"), "m", True)
    store.save_correction(con, "a", "topic", "Medical")
    store.save_correction(con, "b", "stars", 2)
    n, err = sync.reclassify_priority(con, cfg, "tok", 14,
                                      FakeClaude(Labels("Promotions", "Reminder", 0.9, "", F(2, 2, 3))))
    assert n == 2 and err is None
    a = con.execute("SELECT topic, action, stars_auto FROM predictions WHERE email_id='a'").fetchone()
    assert a == ("Medical", "Needs a reply", 4)      # your corrected label kept; content-only stars
    b = con.execute("SELECT stars_auto, stars_user FROM predictions WHERE email_id='b'").fetchone()
    assert b[1] == 2                                  # your star override kept


def test_evaluation_priority_metrics():
    from src.evaluate import priority_metrics
    m = priority_metrics([5, 5, 1, 2, 3, None], [4, 5, 4, 2, 3, 3])
    assert m["priority_rated"] == 5 and m["priority_critical_recall"] == 1.0
    assert m["priority_over_ranking"] == 0.5 and m["priority_within_one"] == 0.8


def test_star_text():
    assert STAR_TEXT[3] == "\u2605\u2605\u2605\u2606\u2606"


# ---------- robust answers: structured tool output, tolerant matching, retry, failure log ----------

from types import SimpleNamespace  # noqa: E402

from src import llm as llm_mod  # noqa: E402
from src.llm import ClaudeClassifier, check, extract_json, match_label  # noqa: E402

GOOD = {"topic": "Others", "action": "Needs an action", "confidence": 0.9, "reason": "fee",
        "consequence": 3, "urgency": 3, "relevance": 3, "deadline": "2026-11-13", "suspicious": False,
        "key_point": "Tuition due"}


class FakeAPI:
    """Stands in for anthropic.Anthropic(): returns queued replies, records requests."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tool_reply(data, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="tool_use", input=data)])


def text_reply(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def make_clf(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(llm_mod, "FAILURE_LOG", tmp_path / "fails.jsonl")

    def make(replies):
        c = ClaudeClassifier(cfg)
        c._client = FakeAPI(replies)
        return c
    return make


@pytest.mark.parametrize("given,expected", [
    ("Needs Action", "Needs an action"), ("Needs Reply", "Needs a reply"), ("needs an action", "Needs an action"), ("NEEDS AN ACTION", "Needs an action"),
    (" No action needed. ", "No action needed"), ("Needs a Reply", "Needs a reply"),
    ("fos general", "FoS General"), ("FoS-General", "FoS General"), ("Other", "Others"),
    ("Promotion", "Promotions"), ("Spam", None), (None, None), (3, None),
])
def test_label_matching_is_tolerant_but_not_loose(cfg, given, expected):
    assert match_label(given, topics(cfg) + actions(cfg)) == expected


@pytest.mark.parametrize("conf,expected", [(0.8, 0.8), ("0.8", 0.8), ("high", 0.9), ("85%", 0.85),
                                           (85, 0.85), ("unsure", 0.5), (None, 0.5)])
def test_confidence_variants_do_not_fail(cfg, conf, expected):
    out, problem = check({**GOOD, "confidence": conf}, cfg)
    assert problem is None and out.confidence == expected


def test_json_with_text_around_it(cfg):
    raw = 'Here is my answer:\n{"topic":"Career","action":"Reminder","confidence":0.9}\nHope that {helps}!'
    assert extract_json(raw)["topic"] == "Career" and parse_labels(raw, cfg).topic == "Career"


def test_check_names_the_problem(cfg):
    assert check(None, cfg)[1] == "no JSON object in the reply"
    assert "unknown topic" in check({**GOOD, "topic": "Spam"}, cfg)[1]
    assert "unknown action" in check({**GOOD, "action": "Ignore"}, cfg)[1]


def test_tool_use_answer(make_clf):
    clf = make_clf([tool_reply(GOOD)])
    out = clf("Subject: fee\n\nPay by Friday", "2026-11-10T02:00:00Z")
    req = clf._client.requests[0]
    assert out.topic == "Others" and out.priority.consequence == 3
    assert req["tool_choice"] == {"type": "tool", "name": "record_labels"}
    assert req["tools"][0]["input_schema"]["properties"]["action"]["enum"][0] == "Needs a reply"
    assert "Received: 2026-11-10T02:00:00Z" in req["messages"][0]["content"]


def test_plain_text_answer_still_accepted(make_clf):
    assert make_clf([text_reply("```json\n" + json.dumps(GOOD) + "\n```")])("x").action == "Needs an action"


def test_bad_answer_is_retried_then_succeeds(make_clf):
    clf = make_clf([tool_reply({**GOOD, "action": "Pay"}), tool_reply(GOOD)])
    assert clf("x").action == "Needs an action" and len(clf._client.requests) == 2
    assert not llm_mod.FAILURE_LOG.exists()


def test_bad_answers_are_logged_without_email_text(make_clf):
    clf = make_clf([tool_reply({**GOOD, "topic": "Spam"}), text_reply("I can't classify this.")])
    assert clf("Subject: secret body text") is None and clf.api_failed is False
    entry = json.loads(llm_mod.FAILURE_LOG.read_text().strip())
    assert entry["problems"] == ["unknown topic 'Spam'", "no JSON object in the reply"]
    assert "secret body text" not in llm_mod.FAILURE_LOG.read_text()
    assert "unusable" in clf.last_error


def test_cut_off_answer_is_reported(make_clf):
    clf = make_clf([text_reply('{"topic": "Car', stop="max_tokens")] * 2)
    assert clf("x") is None and "max_tokens" in clf.last_error


def test_api_error_is_not_retried_or_logged(make_clf):
    clf = make_clf([RuntimeError("network down")])
    assert clf("x") is None and clf.api_failed and len(clf._client.requests) == 1
    assert not llm_mod.FAILURE_LOG.exists()


def test_failure_reason_shown_in_why_column(cfg, make_clf):
    clf = make_clf([tool_reply({**GOOD, "action": "Pay"})] * 2)
    r = classify(to_record(msg(), ME, cfg), cfg, clf)
    assert r.source == "fallback" and r.reason == "classification failed: Claude's answer was unusable: unknown action 'Pay'"


def test_reclassify_redoes_failed_emails(cfg, tmp_path, monkeypatch):
    import src.sync as sync
    con = store.connect(tmp_path / "f.db")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mails = [msg(mid="f1", received=now), msg(mid="f2", received=now)]
    monkeypatch.setattr(sync, "list_inbox", lambda token, since, max_n: mails)
    monkeypatch.setattr(sync, "my_address", lambda token: ME)
    for m in mails:
        rec = to_record(m, ME, cfg)
        store.save(con, rec, classify(rec, cfg, FakeClaude(None)), "m", True)   # both failed
    store.save_correction(con, "f2", "topic", "Career")                          # you fixed f2's topic
    n, err = sync.reclassify_priority(con, cfg, "tok", 14,
                                      FakeClaude(Labels("Others", "Needs an action", 0.9, "", F(3, 3, 3))))
    assert n == 2 and err is None
    f1 = con.execute("SELECT topic, action, source, stars_auto FROM predictions WHERE email_id='f1'").fetchone()
    assert f1 == ("Others", "Needs an action", "claude", 5)                      # fully redone
    f2 = con.execute("SELECT topic, action, stars_auto FROM predictions WHERE email_id='f2'").fetchone()
    assert f2[0] == "Career" and f2[2] is not None                               # your fix kept, stars added



# ---------- content-only model (this version) ----------

from src.priority import MODELS  # noqa: E402


@pytest.mark.parametrize("f,stars", [
    (F(3, 3, 3), 5),            # tuition fee due soon: 13.5
    (F(1, 3, 0), 3),            # sale ends tonight: 6.5
    (F(2, 3, 0), 3),            # sale, consequence overrated: 8.5 -> 4, mass-marketing cap 3
    (F(1, 3, 3), 4),            # marketing that Claude reads as personal: 9.5 (no topic cap here)
    (F(3, 2, 3), 5),            # interview invitation: 12.0
    (F(2, 3, 3), 5),            # clinic confirm tomorrow: 11.5
    (F(2, 2, 3), 4),            # lecturer asks for topic: 10.0
    (F(2, 3, 2), 4),            # assignment due tomorrow: 10.5
    (F(1, 1, 1), 2),            # career fair next month: 4.5
    (F(0, 0, 1), 1),            # newsletter: 1.0
    (F(3, 3, 3, susp=True), 2), # phishing capped
])
def test_content_only_examples(cfg, f, stars):
    assert cfg["priority"]["model"] == "content_only"
    assert compute("Others", "Needs an action", f, RECEIVED, cfg).stars == stars


@pytest.mark.parametrize("f", [F(3, 3, 3), F(1, 3, 0), F(1, 3, 3), F(0, 0, 3), F(2, 1, 2)])
def test_content_only_ignores_labels(cfg, f):
    results = [compute(t, a, f, RECEIVED, cfg) for t in topics(cfg) for a in actions(cfg)]
    assert len({(p.stars, p.score, tuple(p.notes)) for p in results}) == 1


def test_content_only_has_no_label_rules(cfg):
    # The combined model caps Promotions at 3 and No action needed at 2; content only does not.
    f = F(2, 3, 3)
    assert compute("Promotions", "No action needed", f, RECEIVED, cfg).stars == 5
    assert compute("Promotions", "No action needed", f, RECEIVED, cfg, model="combined").stars == 2


def test_floor_still_applies_in_content_only(cfg):
    p = compute("Others", "Reminder", F(3, 2, 0), RECEIVED, cfg)   # 9.0 -> 4; floor 4; cap 3 wins
    assert p.stars == 3 and p.notes == ["mass marketing cap"]
    p = compute("Others", "Reminder", F(3, 2, 1), RECEIVED, cfg)   # 10.0 -> 4
    assert p.stars == 4


def test_unknown_model_rejected(cfg):
    with pytest.raises(ValueError):
        compute("Others", "Reminder", F(1, 1, 1), RECEIVED, cfg, model="magic")


def test_stored_stars_record_their_model(cfg, tmp_path):
    con = store.connect(tmp_path / "m.db")
    rec = to_record(msg(mid="m1"), ME, cfg)
    store.save(con, rec, classify(rec, cfg, FakeClaude(Labels("Others", "Reminder", 0.9, "", F(2, 2, 2)))), "m", True)
    assert con.execute("SELECT priority_model FROM predictions").fetchone()[0] == "content_only"


def test_compare_scores_both_models_without_api_calls(cfg, tmp_path, monkeypatch):
    import src.compare as cmp
    import src.dataset as ds
    import src.evaluate as ev
    from dataclasses import asdict
    monkeypatch.setattr(ds, "RAW", tmp_path / "raw.jsonl")
    monkeypatch.setattr(ds, "LABELS", tmp_path / "labels.jsonl")
    monkeypatch.setattr(ev, "CACHE", tmp_path / "cache.jsonl")
    monkeypatch.setattr(cmp, "CACHE", tmp_path / "cache.jsonl")
    monkeypatch.setattr(cmp, "REPORTS", tmp_path)
    key = cmp.cache_key(cfg)
    cases = [("p", "Promotions", "Needs an action", F(1, 3, 3), 2),   # personalised promo
             ("t", "Others", "Needs an action", F(3, 3, 3), 5)]       # tuition
    raw, labels, cache = [], [], []
    for eid, topic, action, f, stars in cases:
        rec = to_record(msg(mid=eid, subject=eid, received=RECEIVED), ME, cfg)
        raw.append(rec.to_dict())
        labels.append({"id": eid, "topic": topic, "action": action, "stars": stars})
        res = asdict(Result(topic, action, 0.9, "claude", factors=f))
        res.pop("priority")
        cache.append({"id": eid, "key": key, "result": res})
    ds.write_jsonl(ds.RAW, raw); ds.write_jsonl(ds.LABELS, labels); ds.write_jsonl(ev.CACHE, cache)
    rows = cmp.score_both(cfg)
    by = {x["row"]["id"]: {m: x["stars"][m].stars for m in MODELS} for x in rows}
    assert by["p"] == {"content_only": 4, "combined": 3}
    assert by["t"] == {"content_only": 5, "combined": 5}
    assert cmp.summary(rows, "content_only")["promotions_above_3"] == 1
    assert cmp.summary(rows, "combined")["promotions_above_3"] == 0
    monkeypatch.setattr("sys.argv", ["compare"])
    cmp.main()
    assert any(p.name.startswith("compare_") for p in tmp_path.iterdir())
