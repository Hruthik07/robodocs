"""Stage 2, step 5: detect which version an issue / Q&A post is about.

Docs already know their version (git branch / URL). Issues and Q&A usually don't, so we look at,
in order: tags/labels, then the problem statement (not the comments: replies often mention *other*
versions, e.g. "fixed in 6.0"). If nothing is found we return "unknown". Guessing would undermine
the "version-correct answers" promise.
"""

import re

ROS2_DISTROS = ["ardent", "bouncy", "crystal", "dashing", "eloquent", "foxy", "galactic", "humble",
                "iron", "jazzy", "kilted", "lyrical", "rolling"]
ROS1_DISTROS = ["indigo", "jade", "kinetic", "lunar", "melodic", "noetic"]
ROS_FAMILY = {"ros2", "nav2", "moveit2", "ros2_control", "ros1"}

_DISTROS = "|".join(ROS2_DISTROS + ROS1_DISTROS)
DISTRO_RE = re.compile(r"\b(" + _DISTROS + r")\b", re.I)            # for TAGS only ("ros-humble")
# In free text, distro names are often plain English ("humble opinion", "soldering iron"), so we
# require ROS context: "ROS 2 Humble", "ROS2-jazzy", "/opt/ros/noetic", "ros-jazzy-desktop".
# Also matches issue-template forms seen in the data: "ROS2 Version:\n- Humble binaries",
# "ROS Distro: Humble", "**ROS 2 Distro**: Foxy", "ROS version or commit hash: jazzy".
DISTRO_IN_TEXT = re.compile(
    r"(?:\bros\s*2?\s*(?:version|distro(?:bution)?)?(?:\s+or\s+commit\s+hash)?\s*[:=*_-]*\s*(?:[-*]\s*)?"
    r"|/opt/ros/|\bros-)(" + _DISTROS + r")\b", re.I)
PATTERNS = {
    # "Isaac Sim 5.1", "Isaac Sim Version: 4.5.0", "isaacsim==5.1.0", "isaac-sim 4.2"
    "isaac_sim": re.compile(r"isaac[\s_-]?sim[^\d\n]{0,25}?(\d\.\d+)(?:\.\d+)?|isaacsim==(\d\.\d+)", re.I),
    # "Isaac Lab 2.3", "IsaacLab v2.2.1", "Isaac Lab Version: 3.0.0-beta"
    "isaac_lab": re.compile(r"isaac[\s_-]?lab[^\d\n]{0,25}?v?(\d\.\d+)(?:\.\d+)?", re.I),
    # "MuJoCo 3.3.7", "mujoco==3.2.0", "mujoco version: 3.1"
    "mujoco": re.compile(r"mujoco[^\d\n]{0,20}?(\d\.\d+)(?:\.\d+)?", re.I),
}


def detect_version(framework: str, problem_text: str, tags: list[str] | None = None) -> str:
    tags = [t.lower() for t in (tags or [])]
    if framework in ROS_FAMILY:
        for t in tags:                                  # tags like "ros-humble", "ros2-jazzy"
            m = DISTRO_RE.search(t)
            if m:
                return m.group(1).lower()
        m = DISTRO_IN_TEXT.search(problem_text or "")
        return m.group(1).lower() if m else "unknown"

    pattern = PATTERNS.get(framework)
    if not pattern:
        return "unknown"
    m = pattern.search(problem_text or "")
    if not m:
        return "unknown"
    return next(g for g in m.groups() if g)
