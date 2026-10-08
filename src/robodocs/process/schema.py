"""Step 1 of Stage 2: the Document contract.

Every source (git docs, web docs, issues, discussions, Q&A, notes) is turned into this one shape,
so Stage 3+ never needs to know where a document came from.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel

SourceType = Literal["doc", "web_doc", "issue", "discussion", "qa", "note"]


class Document(BaseModel):
    doc_id: str                         # stable across re-runs, e.g. "gh:isaac-sim/IsaacLab#516"
    source_type: SourceType
    framework: str                      # ros2 | nav2 | moveit2 | ros2_control | isaac_sim | isaac_lab |
                                        # mujoco | ros | ros1 | gazebo | general | notes
    version: str = "unknown"            # "jazzy", "5.1", "3.15", ... or "unknown" (never guessed)
    ros_generation: str = "unknown"     # ros1 | ros2 | both | unknown | n/a (not a ROS framework)
    title: str
    text: str                           # clean Markdown: headings + code blocks preserved
    url: str                            # citation link
    created_at: str | None = None       # ISO 8601 (None for docs: they are versioned snapshots)
    updated_at: str | None = None
    collected_at: str | None = None
    tags: list[str] = []
    # quality signals (used later to rank trustworthy answers higher)
    resolved: bool | None = None        # issue closed as completed AND someone answered
    has_accepted_answer: bool | None = None
    closed_by_pr: bool | None = None
    maintainer_answered: bool | None = None
    score: int | None = None
    content_hash: str = ""              # sha256 of text: change detection + exact dedup

    def finalize(self) -> "Document":
        self.content_hash = content_hash(self.text)
        return self


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
