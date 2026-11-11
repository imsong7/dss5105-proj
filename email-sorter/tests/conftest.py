"""Keep every test away from the real files under ``private/``."""

import os

# Tests that do not pass a provider expect the no-sign-in Graph mode, whatever
# the local .env says (load_dotenv does not override variables already set).
os.environ["MAIL_PROVIDER"] = "graphtoken"
# Never read or write the real saved mail while testing (empty turns saving off).
os.environ["PUSHED_MAIL_FILE"] = ""
os.environ["REFRESH_STATE_FILE"] = ""

import pytest

from app.stores import calendar_feed, classification_store, item_states, profiles, saved_jobs, user_events


@pytest.fixture(autouse=True)
def isolated_private_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(
        user_events, "event_store", user_events.EventStore(tmp_path / "events.json")
    )
    monkeypatch.setattr(
        saved_jobs, "saved_job_store", saved_jobs.SavedJobStore(tmp_path / "saved_jobs.json")
    )
    monkeypatch.setattr(
        classification_store,
        "classify_cache",
        classification_store.ClassifyCache(tmp_path / "classifications.json"),
    )
    monkeypatch.setattr(
        classification_store,
        "correction_store",
        classification_store.CorrectionStore(tmp_path / "corrections.json"),
    )
    monkeypatch.setattr(
        classification_store,
        "sender_rule_store",
        classification_store.SenderRuleStore(tmp_path / "sender_rules.json"),
    )


@pytest.fixture(autouse=True)
def isolated_item_states(tmp_path, monkeypatch):
    monkeypatch.setattr(
        item_states, "item_states", item_states.ItemStateStore(tmp_path / "states.json")
    )


@pytest.fixture(autouse=True)
def isolated_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        calendar_feed, "feed_store", calendar_feed.FeedStore(tmp_path / "feed.json")
    )


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(
        profiles, "profile_store", profiles.ProfileStore(tmp_path / "profiles.json")
    )


@pytest.fixture(autouse=True)
def clean_refresh_state():
    from app.mail.pushed_store import refresh_state

    refresh_state._data.clear()
    yield
    refresh_state._data.clear()
