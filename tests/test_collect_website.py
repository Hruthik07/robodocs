"""Tests for Stage 1a-web pure helpers (no network)."""

from robodocs.collect.website import page_url, parse_sphinx_index


def test_parse_standard_sphinx_index():
    js = 'Search.setIndex({"docnames": ["index", "guide/install"], "titles": []})'
    assert parse_sphinx_index(js) == ["guide/install.html", "index.html"]


def test_parse_nvidia_theme_index_dedups_anchors():
    js = ('const searchData = {"envversion": {}, "data": ['
          '{"filename": "ros2/setup.html"}, {"filename": "ros2/setup.html#step-2"}, '
          '{"filename": "index.html"}]};')
    assert parse_sphinx_index(js) == ["index.html", "ros2/setup.html"]


def test_page_url():
    assert (page_url("https://docs.example.com/", "6.1.0", "a/b.html")
            == "https://docs.example.com/6.1.0/a/b.html")
