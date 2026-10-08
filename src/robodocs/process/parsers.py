"""Stage 2, step 2: one parser per raw source -> Document.

Every parser yields (Document | None, reason). None + reason = dropped, so the run report can say
exactly WHY each item was removed ("no_answer", "noise_file", ...).
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from robodocs.config import ProcessingConfig
from robodocs.process.clean import fix_html_entities, ros_generation
from robodocs.process.html import html_to_markdown
from robodocs.process.rst import rst_to_markdown
from robodocs.process.schema import Document
from robodocs.process.text import clean_text, mkdocs_to_markdown, strip_front_matter
from robodocs.process.version import DISTRO_IN_TEXT, ROS2_DISTROS, detect_version

Result = tuple[Document | None, str]

ROS_FRAMEWORKS = {"ros2", "nav2", "moveit2", "ros2_control"}
MAINTAINER_ROLES = {"MEMBER", "OWNER", "COLLABORATOR"}
LOW_VALUE = re.compile(r"^\s*(\+1|same( here| issue| problem| for me)?|me too|any (update|news|progress)s?|"
                       r"bump|thanks?( you)?( so much)?|following|subscribed?)\W*$", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
TEMPLATE_SECTIONS = re.compile(r"(?ims)^#{2,4}\s*(checklist|acceptance criteria)\s*$.*?(?=^#{1,4}\s|\Z)")
SE_BOILERPLATE = re.compile(
    r"(?im)^\s*(-{3,}|\[?Originally posted\]?.*|This (answer|question) was \*\*ACCEPTED\*\*.*|"
    r"Post score: -?\d+\s*|### Original comments\s*)$")
USER_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
DEPRECATION_NOTE = re.compile(r"(?i)deprecated|replaced by|renamed to|moved to|no longer")
SE_COMMENT_HEADER = re.compile(r"\*\*Comment by \[([^\]]+)\]\([^)]*\) on ([\d-]+)\*\*:\\?")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def first_heading(text: str, fallback: str) -> str:
    m = HEADING.search(text)
    return m.group(1).strip() if m else fallback


def noise_reason(path: str, cfg: ProcessingConfig) -> str | None:
    p = PurePosixPath(path)
    if p.name in cfg.noise_names:
        return "noise_file"
    if set(p.parts[:-1]) & set(cfg.noise_dirs):
        return "noise_file"
    if p.suffix == ".rst" and p.name.startswith("_"):
        return "include_fragment"      # pulled into other pages via `.. include::`
    return None


def iso(ts: float | int | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def indented_code_to_fenced(text: str) -> str:
    """Stack Exchange uses 4-space indented code. Fence it so later stages never split it."""
    out, block, prev_blank = [], [], True
    lines = text.splitlines()

    def flush():
        while block and not block[-1].strip():
            block.pop()
        if block:
            indent = min(len(l) - len(l.lstrip()) for l in block if l.strip())
            out.extend(["```", *[l[indent:] for l in block], "```"])
        block.clear()

    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        is_code = (not in_fence and (line.startswith("    ") or line.startswith("\t"))
                   and (block or prev_blank) and not re.match(r"^\s*([-*+]|\d+\.)\s", line))
        if is_code or (block and not line.strip()):
            block.append(line.replace("\t", "    "))
        else:
            flush()
            out.append(line)
        prev_blank = not line.strip()
    flush()
    return "\n".join(out)


def strip_template_sections(body: str) -> str:
    return TEMPLATE_SECTIONS.sub("", body or "")


def demote_headings(text: str | None) -> str:
    """User-written '## Bug report' -> '**Bug report**' (code blocks untouched).

    Our thread structure uses '#' title + '## Question/Reply/Answer'. Stage 3 chunks on those, so
    headings typed by users inside a post must not look like structure.
    """
    out, in_code = [], False
    for line in (text or "").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
        m = None if in_code else USER_HEADING.match(line)
        out.append(f"**{m.group(2)}**" if m else line)
    return "\n".join(out)


def author(node: dict | None) -> str:
    return ((node or {}).get("author") or {}).get("login") or "ghost"


def is_bot(login: str, cfg: ProcessingConfig) -> bool:
    l = login.lower()
    return l.endswith("[bot]") or l.endswith("-bot") or l in {b.lower() for b in cfg.bot_logins}


def useful(body: str | None) -> bool:
    return bool(body and body.strip()) and not LOW_VALUE.match(body)


def finish(doc: Document, cfg: ProcessingConfig) -> Result:
    # Short deprecation notes are kept: "omni.isaac.core ... Replaced by isaacsim.core.api" IS the answer
    # to a common error. (Found while checking what the too_short rule dropped.)
    if len(doc.text) < cfg.min_chars and not (doc.source_type == "doc" and DEPRECATION_NOTE.search(doc.text)):
        return None, "too_short"
    return doc.finalize(), "kept"


# ---------------------------------------------------------------------------
# D1-D4, D6: git docs (.rst / .md)
# ---------------------------------------------------------------------------

def parse_git_docs(raw: Path, cfg: ProcessingConfig) -> Iterator[Result]:
    for manifest in sorted(raw.glob("docs/*/*/manifest.json")):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        folder, fw, ver = manifest.parent.parent.name, m["framework"], m["version"]
        # {REPOS_FILE_BRANCH} sits inside ros2_control/ROS 2 doc links; we know the exact branch.
        subs = {"REPOS_FILE_BRANCH": m["ref"], **cfg.substitutions.get(fw, {}).get(ver, {})}
        for f in m["files"]:
            reason = noise_reason(f["path"], cfg)
            if reason:
                yield None, reason
                continue
            p = manifest.parent / f["path"]
            raw_text = p.read_text(encoding="utf-8", errors="replace")
            md = (rst_to_markdown(raw_text, p.parent) if p.suffix == ".rst"
                  else mkdocs_to_markdown(strip_front_matter(raw_text)))
            for key, value in subs.items():
                md = md.replace("{" + key + "}", value)
            text = clean_text(md)
            yield finish(Document(
                doc_id=f"doc:{folder}:{ver}:{f['path']}", source_type="doc", framework=fw, version=ver,
                ros_generation="ros2" if fw in ROS_FRAMEWORKS else "n/a",
                title=first_heading(text, PurePosixPath(f["path"]).stem), text=text, url=f["url"],
                collected_at=m["collected_at"], tags=[folder] if folder != fw else []), cfg)


# ---------------------------------------------------------------------------
# D5: docs website (HTML)
# ---------------------------------------------------------------------------

def parse_web_docs(raw: Path, cfg: ProcessingConfig) -> Iterator[Result]:
    for manifest in sorted(raw.glob("web/*/*/manifest.json")):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for f in m["files"]:
            reason = noise_reason(f["path"], cfg)
            if reason:
                yield None, reason
                continue
            title, md = html_to_markdown((manifest.parent / f["path"]).read_text(encoding="utf-8", errors="replace"))
            text = clean_text(md)
            yield finish(Document(
                doc_id=f"web:{m['framework']}:{m['version']}:{f['path']}", source_type="web_doc",
                framework=m["framework"], version=m["version"], ros_generation="n/a",
                title=title or PurePosixPath(f["path"]).stem, text=text, url=f["url"],
                collected_at=m["collected_at"]), cfg)


# ---------------------------------------------------------------------------
# D7: GitHub issues
# ---------------------------------------------------------------------------

def parse_issue(it: dict, cfg: ProcessingConfig) -> Result:
    fw, repo = it["_meta"]["framework"], it["_meta"]["repo"]
    if it.get("stateReason") == "DUPLICATE":
        return None, "closed_as_duplicate"
    comments = [c for c in it["comments"]["nodes"] if not is_bot(author(c), cfg) and useful(c.get("body"))]
    if not comments:
        return None, "no_answer"
    maintainer = any(c["authorAssociation"] in MAINTAINER_ROLES for c in comments)
    if it.get("stateReason") == "NOT_PLANNED" and not maintainer:
        return None, "not_planned_unanswered"
    closer = ((it.get("timelineItems") or {}).get("nodes") or [{}])[0].get("closer") or {}
    by_pr = closer.get("__typename") == "PullRequest"

    body = strip_template_sections(it.get("body"))
    parts = [f"# {it['title']}", "", f"## Question (@{author(it)}, {it['createdAt'][:10]})", "",
             demote_headings(body)]
    for c in comments:
        role = "maintainer " if c["authorAssociation"] in MAINTAINER_ROLES else ""
        parts += ["", f"## Reply ({role}@{author(c)}, {c['createdAt'][:10]})", "", demote_headings(c["body"])]
    if by_pr:
        parts += ["", "## Resolution", "", f"Closed by pull request: {closer.get('title')} ({closer.get('url')})"]
    labels = [l["name"] for l in it["labels"]["nodes"]]
    return finish(Document(
        doc_id=f"gh:{repo}#{it['number']}", source_type="issue", framework=fw,
        version=detect_version(fw, f"{it['title']}\n{it.get('body') or ''}", labels),
        ros_generation="ros2" if fw in ROS_FRAMEWORKS else "n/a",
        title=it["title"], text=clean_text("\n".join(parts)), url=it["url"],
        created_at=it["createdAt"], updated_at=it.get("updatedAt"), collected_at=it["_meta"]["collected_at"],
        tags=labels, resolved=it.get("stateReason") == "COMPLETED" and (maintainer or by_pr),
        closed_by_pr=by_pr, maintainer_answered=maintainer,
        score=(it.get("reactions") or {}).get("totalCount")), cfg)


# ---------------------------------------------------------------------------
# D8: GitHub discussions
# ---------------------------------------------------------------------------

def parse_discussion(d: dict, cfg: ProcessingConfig) -> Result:
    fw, repo = d["_meta"]["framework"], d["_meta"]["repo"]
    answer = d.get("answer")
    others = [c for c in d["comments"]["nodes"]
              if not c.get("isAnswer") and not is_bot(author(c), cfg) and useful(c.get("body"))]
    if not answer and not others:
        return None, "no_answer"
    parts = [f"# {d['title']}", "", f"## Question (@{author(d)}, {d['createdAt'][:10]})", "",
             demote_headings(d.get("body"))]
    if answer:
        parts += ["", f"## Accepted answer (@{author(answer)}, {answer['createdAt'][:10]})", "",
                  demote_headings(answer["body"])]
    maintainer = bool(answer and answer.get("authorAssociation") in MAINTAINER_ROLES)
    for c in others:
        role = "maintainer " if c["authorAssociation"] in MAINTAINER_ROLES else ""
        maintainer |= bool(role)
        parts += ["", f"## Reply ({role}@{author(c)}, {c['createdAt'][:10]})", "", demote_headings(c["body"])]
        for r in (c.get("replies") or {}).get("nodes", []):
            if useful(r.get("body")) and not is_bot(author(r), cfg):
                parts += ["", f"### Follow-up (@{author(r)})", "", demote_headings(r["body"])]
    labels = [l["name"] for l in d["labels"]["nodes"]]
    return finish(Document(
        doc_id=f"ghd:{repo}#{d['number']}", source_type="discussion", framework=fw,
        version=detect_version(fw, f"{d['title']}\n{d.get('body') or ''}", labels),
        ros_generation="ros2" if fw in ROS_FRAMEWORKS else "n/a",
        title=d["title"], text=clean_text("\n".join(parts)), url=d["url"],
        created_at=d["createdAt"], updated_at=d.get("updatedAt"), collected_at=d["_meta"]["collected_at"],
        tags=labels + ([d["category"]["name"]] if d.get("category") else []),
        resolved=bool(answer), has_accepted_answer=bool(answer), maintainer_answered=maintainer,
        score=d.get("upvoteCount")), cfg)


# ---------------------------------------------------------------------------
# D9: Stack Exchange
# ---------------------------------------------------------------------------

def se_framework(tags: list[str], generation: str) -> str:
    t = {x.lower() for x in tags}
    if generation == "ros1":
        return "ros1"
    if t & {"ros2-control", "ros2-controllers"}:
        return "ros2_control"
    if t & {"moveit", "moveit2"}:
        return "moveit2"
    if t & {"nav2", "navigation2"}:
        return "nav2"
    if "mujoco" in t:
        return "mujoco"
    if t & {"nvidia-isaac", "isaac-sim", "isaac"}:
        return "isaac_sim"
    if generation in {"ros2", "both"} or any(x.startswith("ros") for x in t):
        return "ros2" if generation in {"ros2", "both"} else "ros"
    if any("gazebo" in x for x in t):
        return "gazebo"
    return "general"


def se_text(md: str) -> str:
    md = fix_html_entities(md)
    md = SE_COMMENT_HEADER.sub(lambda m: f"**Comment ({m.group(2)}):**", md)
    md = SE_BOILERPLATE.sub("", md)
    return demote_headings(indented_code_to_fenced(md))


def generation_from_text(text: str) -> str:
    """Fallback when tags are silent: 'I'm using ... for ROS Noetic' -> ros1."""
    m = DISTRO_IN_TEXT.search(text)
    if not m:
        return "unknown"
    return "ros2" if m.group(1).lower() in ROS2_DISTROS else "ros1"


def parse_se(q: dict, cfg: ProcessingConfig) -> Result:
    answers = [a for a in q.get("answers", []) if a.get("is_accepted") or a.get("score", 0) >= 0]
    if not answers:
        return None, "no_answer"
    answers.sort(key=lambda a: (not a.get("is_accepted"), -a.get("score", 0)))
    title = fix_html_entities(q["title"])
    body = se_text(q.get("body_markdown", ""))
    gen = ros_generation(q["tags"], q["creation_date"])
    if gen == "unknown":
        gen = generation_from_text(f"{title}\n{body}")
    fw = se_framework(q["tags"], gen)
    parts = [f"# {title}", "", f"## Question ({iso(q['creation_date'])[:10]})", "", body]
    for a in answers:
        label = "Accepted answer" if a.get("is_accepted") else "Answer"
        parts += ["", f"## {label} (score {a.get('score', 0)})", "", se_text(a.get("body_markdown", ""))]
    site = q["_meta"]["site"]
    return finish(Document(
        doc_id=f"se:{site}:{q['question_id']}", source_type="qa", framework=fw,
        version=detect_version(fw if fw != "ros" else "ros2", f"{title}\n{body}", q["tags"]),
        ros_generation=gen, title=title, text=clean_text("\n".join(parts)), url=q["link"],
        created_at=iso(q["creation_date"]), updated_at=iso(q.get("last_activity_date")),
        collected_at=q["_meta"]["collected_at"], tags=q["tags"],
        resolved=any(a.get("is_accepted") for a in answers), has_accepted_answer=bool(q.get("accepted_answer_id")),
        score=q.get("score")), cfg)


# ---------------------------------------------------------------------------
# D10: own notes
# ---------------------------------------------------------------------------

def parse_notes(raw: Path, cfg: ProcessingConfig) -> Iterator[Result]:
    manifest = raw / "notes" / "manifest.json"
    if not manifest.exists():
        return
    m = json.loads(manifest.read_text(encoding="utf-8"))
    for f in m["files"]:
        text = clean_text(strip_front_matter((raw / "notes" / f["path"]).read_text(encoding="utf-8")))
        yield finish(Document(
            doc_id=f"note:{f['path']}", source_type="note", framework="notes", ros_generation="n/a",
            title=first_heading(text, PurePosixPath(f["path"]).stem), text=text, url=f"notes/{f['path']}",
            updated_at=f.get("modified_at"), collected_at=m["collected_at"]), cfg)


def iter_packed(raw: Path, pattern: str) -> Iterator[dict]:
    for f in sorted(raw.glob(f"packed/{pattern}")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)
