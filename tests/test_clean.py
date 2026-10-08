from datetime import datetime, timezone

from robodocs.process.clean import fix_html_entities, ros_generation


def ts(year: int) -> float:
    return datetime(year, 6, 1, tzinfo=timezone.utc).timestamp()


# --- fix_html_entities -------------------------------------------------------

def test_entities_unescaped():
    assert fix_html_entities("It&#39;s &quot;fine&quot; &lt;3") == "It's \"fine\" <3"


def test_double_escaped_code_is_fixed():
    # Real case from the data: double-escaped at the source.
    assert fix_html_entities("(0x80 &amp;amp; n) &amp;lt;&amp;lt; 1") == "(0x80 & n) << 1"


def test_plain_text_untouched():
    assert fix_html_entities("x < 3 && y > 2") == "x < 3 && y > 2"


def test_entities_none_is_empty():
    assert fix_html_entities(None) == ""


# --- ros_generation ----------------------------------------------------------

def test_ros1_by_distro():
    assert ros_generation(["ros", "ros-kinetic"]) == "ros1"


def test_ros2_by_distro():
    assert ros_generation(["ros-humble", "navigation"]) == "ros2"


def test_ros2_by_tool_tag():
    assert ros_generation(["colcon", "python"]) == "ros2"


def test_ros1_by_tool_tag():
    assert ros_generation(["catkin", "cmake"]) == "ros1"


def test_both_for_migration_questions():
    assert ros_generation(["ros-noetic", "ros-humble"]) == "both"


def test_old_generic_question_is_ros1():
    assert ros_generation(["ros", "slam"], created_ts=ts(2014)) == "ros1"


def test_recent_generic_question_is_unknown():
    assert ros_generation(["ros", "slam"], created_ts=ts(2023)) == "unknown"


def test_non_ros_question_is_unknown():
    assert ros_generation(["arduino", "motor"], created_ts=ts(2023)) == "unknown"


def test_old_non_ros_question_is_not_labeled_ros1():
    assert ros_generation(["arduino", "motor"], created_ts=ts(2014)) == "unknown"
