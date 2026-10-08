"""Tests for Stage 1a. Run: conda run -n robodocs python -m pytest -q"""

from pathlib import PureWindowsPath

from robodocs.collect.docs import build_sparse_patterns, github_blob_url


def test_sparse_patterns_subfolder():
    assert sorted(build_sparse_patterns(["docs"], [".md", ".rst"])) == [
        "/docs/**/*.md",
        "/docs/**/*.rst",
    ]


def test_sparse_patterns_whole_repo():
    assert build_sparse_patterns(["."], [".md"]) == ["/**/*.md"]


def test_sparse_patterns_multiple_paths():
    pats = build_sparse_patterns(["doc", "python"], [".rst"])
    assert sorted(pats) == ["/doc/**/*.rst", "/python/**/*.rst"]


def test_blob_url():
    assert (
        github_blob_url("google-deepmind/mujoco", "3.15.0", "doc/overview.rst")
        == "https://github.com/google-deepmind/mujoco/blob/3.15.0/doc/overview.rst"
    )


def test_blob_url_windows_path():
    win_path = str(PureWindowsPath("docs/source/setup/install.rst"))  # backslashes
    url = github_blob_url("isaac-sim/IsaacLab", "release/3.0.0", win_path)
    assert url == "https://github.com/isaac-sim/IsaacLab/blob/release/3.0.0/docs/source/setup/install.rst"
