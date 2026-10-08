"""Tests for Stage 1c pure helpers (no network)."""

from robodocs.collect.stackexchange import next_cursor, source_dir_name
from robodocs.config import StackExchangeSource


def test_source_dir_name():
    assert source_dir_name(StackExchangeSource(site="robotics")) == "robotics"
    assert source_dir_name(StackExchangeSource(site="stackoverflow", tag="ros2")) == "stackoverflow__ros2"


def test_cursor_moves_to_newest_date():
    items = [{"creation_date": 100}, {"creation_date": 150}, {"creation_date": 120}]
    assert next_cursor(fromdate=50, page=1, items=items) == (150, 1)


def test_cursor_resets_page_when_date_moves():
    assert next_cursor(fromdate=50, page=3, items=[{"creation_date": 60}]) == (60, 1)


def test_cursor_pages_when_stuck_on_same_timestamp():
    items = [{"creation_date": 200}] * 100   # bulk import: identical timestamps
    assert next_cursor(fromdate=200, page=1, items=items) == (200, 2)
