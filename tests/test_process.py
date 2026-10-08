"""Stage 2 tests. Each case reproduces something found in the real corpus."""

from pathlib import Path

from robodocs.config import get_settings
from robodocs.process.parsers import (demote_headings, generation_from_text, indented_code_to_fenced,
                                      noise_reason, parse_issue, parse_se, se_framework, se_text)
from robodocs.process.rst import rst_to_markdown
from robodocs.process.text import clean_text, images_to_text, mkdocs_to_markdown, trim_code_block
from robodocs.process.version import detect_version

CFG = get_settings().processing


# --- RST -----------------------------------------------------------------------------------------

def test_rst_heading_and_code_block():
    md = rst_to_markdown("Install\n=======\n\n.. code-block:: bash\n\n   sudo apt install ros-jazzy-desktop\n")
    assert md.startswith("# Install")
    assert "```bash\nsudo apt install ros-jazzy-desktop\n```" in md


def test_rst_include_is_resolved(tmp_path: Path):
    (tmp_path / "_locale.rst").write_text("Run ``locale`` first.\n", encoding="utf-8")
    md = rst_to_markdown("Setup\n=====\n\n.. include:: _locale.rst\n", tmp_path)
    assert "Run `locale` first." in md


def test_rst_tabs_keep_content_and_sphinx_machinery_dropped():
    src = (".. toctree::\n   :maxdepth: 1\n\n   a\n   b\n\n.. tabs::\n\n   .. group-tab:: Ubuntu\n\n"
           "      Use apt.\n")
    md = rst_to_markdown(src)
    assert "maxdepth" not in md and "**Ubuntu**" in md and "Use apt." in md


def test_rst_roles_note_and_placeholders():
    src = (".. note::\n\n   See :class:`~isaaclab.sim.SimulationContext` and :ref:`the guide <guide>`.\n\n"
           ".. literalinclude:: ../src/demo.py\n")
    md = rst_to_markdown(src)
    assert "> **Note:** See `isaaclab.sim.SimulationContext` and the guide." in md
    assert "[code included from `../src/demo.py`]" in md


def test_rst_bom_escapes_and_file_metadata():
    md = rst_to_markdown("﻿:github_url: https://x/{BRANCH}/a.rst\n\nisaaclab\\_ov\n============\n")
    assert md.strip() == "# isaaclab_ov"


def test_rst_literal_block_double_colon():
    md = rst_to_markdown("Run this::\n\n    colcon build\n")
    assert "Run this:\n```\ncolcon build\n```" in md


# --- shared cleaning -------------------------------------------------------------------------------

def test_clean_keeps_code_untouched_and_removes_comments_and_emails():
    src = "<!-- template -->\nMail me@x.com\n\n```\n<!-- not a comment in code -->\n```\n"
    out = clean_text(src)
    assert "template" not in out and "[email]" in out and "<!-- not a comment in code -->" in out


def test_images_keep_alt_and_logos_removed():
    src = "![Rosanswers logo](https://i.sstatic.net/yuGTR.png)\n![error dialog](https://x/e.png)"
    assert images_to_text(src).strip() == "[image: error dialog](https://x/e.png)"


def test_huge_log_trimmed_but_error_lines_kept():
    body = [f"line {i}" for i in range(200)]
    body[100] = "RuntimeError: CUDA out of memory"
    out = trim_code_block("\n".join(["```", *body, "```"]))
    assert "RuntimeError: CUDA out of memory" in out and "log lines trimmed" in out
    assert len(out.splitlines()) < 60


def test_mkdocs_anchor_and_admonition():
    out = mkdocs_to_markdown('# Tuning { #tuning-guide }\n!!! note "Heads up"\n    text')
    assert out.splitlines()[0] == "# Tuning" and "> **Heads up:**" in out


# --- version detection ---------------------------------------------------------------------------

def test_version_isaac_sim_from_template():
    assert detect_version("isaac_sim", "Isaac Sim Version: 4.5.0\nOS: Ubuntu") == "4.5"


def test_version_mujoco_from_python():
    assert detect_version("mujoco", "mujoco.__version__ == '3.1.2'") == "3.1"


def test_version_ros_tag_beats_text():
    assert detect_version("ros2", "I use ROS 2 Humble", ["ros-jazzy"]) == "jazzy"


def test_version_from_ros_issue_templates():
    assert detect_version("nav2", "- ROS2 Version:\n  - Humble binaries") == "humble"
    assert detect_version("ros2", "**ROS 2 Distro**: Foxy") == "foxy"
    assert detect_version("ros2_control", "ROS Distro: Rolling") == "rolling"


def test_distro_words_need_ros_context():
    assert detect_version("ros2", "In my humble opinion the iron is hot") == "unknown"
    assert generation_from_text("installed /opt/ros/noetic yesterday") == "ros1"
    assert generation_from_text("soldering iron, humble robot") == "unknown"


# --- GitHub / Stack Exchange parsing ---------------------------------------------------------------

def _issue(**kw):
    base = {"number": 1, "title": "Crash on start", "body": "## Bug report\nIt crashes.\n### Checklist\n- [x] I searched",
            "url": "https://github.com/o/r/issues/1", "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-02T00:00:00Z", "stateReason": "COMPLETED", "author": {"login": "asker"},
            "labels": {"nodes": []}, "reactions": {"totalCount": 0}, "timelineItems": {"nodes": []},
            "comments": {"nodes": [
                {"body": "+1", "createdAt": "2025-01-01T01:00:00Z", "authorAssociation": "NONE", "author": {"login": "u"}},
                {"body": "stale", "createdAt": "2025-01-01T02:00:00Z", "authorAssociation": "NONE",
                 "author": {"login": "github-actions"}},
                {"body": "Set `headless=True` and it works. " * 8, "createdAt": "2025-01-01T03:00:00Z",
                 "authorAssociation": "MEMBER", "author": {"login": "dev"}}]},
            "_meta": {"framework": "isaac_lab", "repo": "o/r", "collected_at": "2026-10-07T00:00:00+00:00"}}
    base.update(kw)
    return base


def test_issue_thread_structure_and_filters():
    doc, reason = parse_issue(_issue(), CFG)
    assert reason == "kept" and doc.resolved and doc.maintainer_answered
    assert "## Reply (maintainer @dev" in doc.text
    assert "+1" not in doc.text and "stale" not in doc.text          # low-value + bot comments removed
    assert "**Bug report**" in doc.text and "Checklist" not in doc.text  # headings demoted, template stripped


def test_issue_without_real_answer_dropped():
    doc, reason = parse_issue(_issue(comments={"nodes": []}), CFG)
    assert doc is None and reason == "no_answer"


def test_se_boilerplate_removed_and_code_fenced():
    md = ("Question text\n\n    rosrun pkg node\n\n[Originally posted](https://answers.ros.org/q/1) by "
          "[x](https://answers.ros.org/u/1) on ROS Answers with karma: 5 on 2013-01-01\n")
    out = se_text(md)
    assert "Originally posted" not in out and "```\nrosrun pkg node\n```" in out


def test_se_framework_mapping():
    assert se_framework(["ros-kinetic"], "ros1") == "ros1"
    assert se_framework(["nav2", "ros2"], "ros2") == "nav2"
    assert se_framework(["arduino"], "unknown") == "general"


def test_demote_headings_skips_code():
    assert demote_headings("## Title\n```\n## not a heading\n```") == "**Title**\n```\n## not a heading\n```"


def test_indented_code_not_confused_with_lists():
    assert "```" not in indented_code_to_fenced("1. step one\n    continued text")


def test_noise_rules():
    assert noise_reason("skills/x/SKILL.md", CFG) == "noise_file"
    assert noise_reason("source/Installation/_Apt-Repositories.rst", CFG) == "include_fragment"
    assert noise_reason("docs/source/setup/install.rst", CFG) is None
