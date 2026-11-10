"""Keep every test away from the real files under ``private/``."""

import os

# Tests that do not pass a provider expect the no-sign-in Graph mode, whatever
# the local .env says (load_dotenv does not override variables already set).
os.environ["MAIL_PROVIDER"] = "graphtoken"

import pytest

from app import calendar_feed, classification_store, item_states, profiles, user_events


@pytest.fixture(autouse=True)
def isolated_private_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(
        user_events, "event_store", user_events.EventStore(tmp_path / "events.json")
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
