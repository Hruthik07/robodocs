"""Text-cleaning and labeling helpers used by Stage 2 (parsing & normalization).

Built during Stage 1 to fix two problems found while collecting:
  - Stack Exchange bodies contain HTML entities (&quot; &#39; &lt;) -> fix_html_entities
  - ~12k Stack Exchange questions are ROS 1, which must never be served as a ROS 2 answer
    -> ros_generation
"""

import html
from datetime import datetime, timezone

ROS1_DISTROS = {"boxturtle", "cturtle", "diamondback", "electric", "fuerte", "groovy",
                "hydro", "indigo", "jade", "kinetic", "lunar", "melodic", "noetic"}
ROS2_DISTROS = {"ardent", "bouncy", "crystal", "dashing", "eloquent", "foxy", "galactic",
                "humble", "iron", "jazzy", "kilted", "lyrical", "rolling"}

# Tools/packages that exist in only one ROS generation.
ROS1_ONLY_TAGS = {"catkin", "catkin-make", "catkin-tools", "rospy", "roscpp", "rosrun",
                  "roscore", "rosbuild", "move-base", "gmapping", "rosserial", "nodelet"}
ROS2_ONLY_TAGS = {"ros2", "rclpy", "rclcpp", "colcon", "ament", "ament-cmake", "nav2",
                  "navigation2", "moveit2", "ros2-control", "dds", "fastdds", "cyclonedds",
                  "ros2-launch", "micro-ros"}

# ROS 2's first release (Ardent) shipped Dec 2017. A generic "ros" question asked before
# that can only be about ROS 1.
ROS2_FIRST_RELEASE = datetime(2017, 12, 8, tzinfo=timezone.utc).timestamp()


def fix_html_entities(text: str | None) -> str:
    """'It&#39;s &quot;fine&quot; &lt;3' -> 'It's "fine" <3'.

    Unescapes up to TWICE: ~0.2% of Stack Exchange posts are double-escaped at the source
    (code like '(0x80 &amp;amp; n) &amp;lt;&amp;lt; 1'). Checked on the real data: double-escaped
    code is far more common than posts that literally discuss '&lt;', so we accept losing
    the latter.
    """
    if not text:
        return ""
    once = html.unescape(text)
    return html.unescape(once) if once != text else once


def _distro_of(tag: str) -> str | None:
    """'ros-humble' -> 'humble'; 'ros2-jazzy' -> 'jazzy'; other tags -> None."""
    for prefix in ("ros2-", "ros-"):
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def ros_generation(tags: list[str], created_ts: float | None = None) -> str:
    """Label a question 'ros1', 'ros2', 'both' or 'unknown' from its tags (+ date fallback).

    Order of evidence: distro tags and generation-only tool tags first; if none, a question
    asked before ROS 2 existed is ROS 1; otherwise we honestly say 'unknown'.
    """
    tagset = {t.lower() for t in tags}
    distros = {d for d in map(_distro_of, tagset) if d}
    is1 = bool(distros & ROS1_DISTROS or tagset & ROS1_ONLY_TAGS)
    is2 = bool(distros & ROS2_DISTROS or tagset & ROS2_ONLY_TAGS)

    if is1 and is2:
        return "both"      # e.g. migration questions ("porting from noetic to humble")
    if is1:
        return "ros1"
    if is2:
        return "ros2"
    is_ros = "ros" in tagset or any(t.startswith("ros") for t in tagset)
    if is_ros and created_ts is not None and created_ts < ROS2_FIRST_RELEASE:
        return "ros1"
    return "unknown"   # includes non-ROS questions (arduino, control theory, ...)
