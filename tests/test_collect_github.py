"""Tests for Stage 1b pure helpers (no network)."""

from datetime import datetime, timedelta, timezone

from robodocs.collect.github import get_token, repo_dir_name, seconds_until


def test_repo_dir_name():
    assert repo_dir_name("isaac-sim/IsaacLab") == "isaac-sim__IsaacLab"


def test_token_prefers_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "  abc123 ")
    assert get_token() == "abc123"


def test_seconds_until_future():
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 590 <= seconds_until(future) <= 600


def test_seconds_until_past_is_zero():
    assert seconds_until("2020-01-01T00:00:00Z") == 0.0
