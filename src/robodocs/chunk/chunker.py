"""Stage 3: content-aware chunking.

Two strategies, picked by document type:

  docs / web docs / notes  -> split at headings, merge tiny sections, pack paragraphs, never cut a
                              code block unless it alone exceeds the limit (then cut on line breaks
                              and re-fence both halves).
  issues / discussions / Q&A -> the Stage 2 thread structure ("## Question", "## Reply ...",
                              "## Accepted answer ...") becomes: one question chunk + one chunk per
                              answer (small replies merged), and EVERY answer chunk is prefixed with
                              the question, so searching for the problem finds the fix.

Each chunk stores `context` (where it comes from) separately from `text`; Stage 4 embeds
context + text, and answers show text with the doc's URL as citation.
"""

import re

from pydantic import BaseModel

from robodocs.config import ChunkingConfig
from robodocs.process.schema import Document

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
THREAD_TYPES = {"issue", "discussion", "qa"}
MAX_QUESTION_CHUNKS = 3    # long questions are mostly pasted logs; the first chunks hold problem + error
FRAMEWORK_NAMES = {"ros2": "ROS 2", "nav2": "Nav2", "moveit2": "MoveIt 2", "ros2_control": "ros2_control",
                   "isaac_sim": "Isaac Sim", "isaac_lab": "Isaac Lab", "mujoco": "MuJoCo", "ros1": "ROS 1",
                   "ros": "ROS", "gazebo": "Gazebo", "general": "Robotics", "notes": "My notes"}
SOURCE_NAMES = {"doc": "docs", "web_doc": "docs", "note": "notes", "issue": "GitHub issue",
                "discussion": "GitHub discussion", "qa": "Q&A"}


class Chunk(BaseModel):
    chunk_id: str                 # "<doc_id>::<n>"
    doc_id: str
    chunk_index: int
    role: str                     # section | question | answer | reply
    context: str                  # "Isaac Sim 5.1 docs | Title > Section" or "Q: title + question start"
    text: str
    # copied from the document so search can filter without a join
    source_type: str
    framework: str
    version: str
    ros_generation: str
    title: str
    url: str
    created_at: str | None = None
    resolved: bool | None = None
    is_accepted: bool = False     # this chunk holds the accepted answer
    by_maintainer: bool = False   # this chunk holds a maintainer reply

    @property
    def embed_text(self) -> str:
        return f"{self.context}\n\n{self.text}"


# ---------------------------------------------------------------------------
# splitting helpers
# ---------------------------------------------------------------------------

def blocks(text: str) -> list[str]:
    """Paragraph-level blocks; a fenced code block is always ONE block."""
    out, buf, in_code = [], [], False
    for line in text.splitlines():
        if FENCE.match(line):
            if not in_code and buf:            # paragraph ends where code starts
                out.append("\n".join(buf)); buf = []
            buf.append(line)
            in_code = not in_code
            if not in_code:                    # fence closed: emit the whole code block
                out.append("\n".join(buf)); buf = []
            continue
        if not in_code and not line.strip():
            if buf:
                out.append("\n".join(buf)); buf = []
            continue
        buf.append(line)
    if buf:
        out.append("\n".join(buf))
    return [b for b in out if b.strip()]


def split_oversized(block: str, max_chars: int) -> list[str]:
    """Last resort for one block bigger than max: cut on line boundaries; re-fence code."""
    lines = block.splitlines()
    fenced = bool(lines) and FENCE.match(lines[0]) is not None
    opener = lines[0].strip() if fenced else ""
    body = lines[1:-1] if fenced and len(lines) > 1 and FENCE.match(lines[-1]) else (lines[1:] if fenced else lines)
    budget = max_chars - (len(opener) + 8 if fenced else 0)
    pieces, cur = [], []
    for line in body:
        line = line if len(line) <= budget else line[:budget]          # minified one-liners
        if cur and sum(len(l) + 1 for l in cur) + len(line) > budget:
            pieces.append(cur); cur = []
        cur.append(line)
    if cur:
        pieces.append(cur)
    return [("\n".join([opener, *p, "```"]) if fenced else "\n".join(p)) for p in pieces]


def pack(blks: list[str], cfg: ChunkingConfig) -> list[str]:
    """Greedy packing of blocks into chunks of <= max_chars, aiming for ~target_chars."""
    chunks, cur = [], ""
    for b in blks:
        if len(b) > cfg.max_chars:
            if cur:
                chunks.append(cur); cur = ""
            chunks.extend(split_oversized(b, cfg.max_chars))
            continue
        if cur and (len(cur) + len(b) + 2 > cfg.max_chars or len(cur) >= cfg.target_chars):
            chunks.append(cur); cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks


def label(doc: Document) -> str:
    name = FRAMEWORK_NAMES.get(doc.framework, doc.framework)
    ver = f" {doc.version}" if doc.version != "unknown" else ""
    return f"{name}{ver} {SOURCE_NAMES[doc.source_type]}"


def fit(cfg: ChunkingConfig, context: str) -> ChunkingConfig:
    """Size limits apply to context + text together (that's what the embedding model sees)."""
    room = max(400, cfg.max_chars - len(context) - 2)
    return cfg.model_copy(update={"max_chars": room, "target_chars": min(cfg.target_chars, room)})


def close_fences(text: str) -> str:
    """Users often open ``` and never close it; never hand a half-open code block downstream."""
    return text + "\n```" if sum(1 for l in text.splitlines() if FENCE.match(l)) % 2 else text


def _chunk(doc: Document, i: int, role: str, context: str, text: str, **kw) -> Chunk:
    return Chunk(chunk_id=f"{doc.doc_id}::{i}", doc_id=doc.doc_id, chunk_index=i, role=role, context=context,
                 text=close_fences(text.strip()), source_type=doc.source_type, framework=doc.framework, version=doc.version,
                 ros_generation=doc.ros_generation, title=doc.title, url=doc.url, created_at=doc.created_at,
                 resolved=doc.resolved, **kw)


# ---------------------------------------------------------------------------
# strategy 1: documentation (heading-aware)
# ---------------------------------------------------------------------------

def sections(text: str) -> list[tuple[list[str], str]]:
    """[(heading_path, section_text_including_its_heading)] in document order."""
    out, stack, buf, in_code = [], [], [], False
    path: list[str] = []
    for line in text.splitlines():
        if FENCE.match(line):
            in_code = not in_code
        m = None if in_code else HEADING.match(line)
        if m:
            if any(l.strip() for l in buf):
                out.append((path, "\n".join(buf)))
            level, title = len(m.group(1)), m.group(2)
            stack = [s for s in stack if s[0] < level] + [(level, title)]
            path = [t for _, t in stack]
            buf = [line]
            continue
        buf.append(line)
    if any(l.strip() for l in buf):
        out.append((path, "\n".join(buf)))
    return out


def chunk_doc(doc: Document, cfg: ChunkingConfig) -> list[Chunk]:
    secs = sections(doc.text)
    # merge small sections into the following one (keeps a lone heading with its content)
    merged: list[tuple[list[str], str]] = []
    for path, body in secs:
        if merged and len(merged[-1][1]) < cfg.min_chars and len(merged[-1][1]) + len(body) <= cfg.max_chars:
            merged[-1] = (merged[-1][0], merged[-1][1] + "\n\n" + body)
        else:
            merged.append((path, body))
    chunks, i = [], 0
    base = label(doc)
    for path, body in merged:
        crumbs = " > ".join(path[1:] if path and path[0] == doc.title else path)
        context = f"{base} | {doc.title}" + (f" > {crumbs}" if crumbs else "")
        for piece in pack(blocks(body), fit(cfg, context)):
            chunks.append(_chunk(doc, i, "section", context, piece))
            i += 1
    return chunks


# ---------------------------------------------------------------------------
# strategy 2: Q&A threads
# ---------------------------------------------------------------------------

def thread_parts(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split Stage 2 thread text into (question_body, [(answer_heading, answer_body), ...])."""
    parts = re.split(r"(?m)^## (.+)$", text)
    # parts = [pre (title), h1, body1, h2, body2, ...]
    question, answers = "", []
    for heading, body in zip(parts[1::2], parts[2::2]):
        if heading.startswith("Question"):
            question = body.strip()
        else:
            answers.append((heading.strip(), body.strip()))
    return question, answers


def chunk_thread(doc: Document, cfg: ChunkingConfig) -> list[Chunk]:
    question, answers = thread_parts(doc.text)
    base = label(doc)
    q_excerpt = re.sub(r"\s+", " ", question)[: cfg.question_context_chars]
    answer_context = f"{base} | Q: {doc.title}\n{q_excerpt}"

    chunks, i = [], 0
    q_context = f"{base} | Q: {doc.title}"
    for piece in (pack(blocks(question), fit(cfg, q_context)) or [""])[:MAX_QUESTION_CHUNKS]:
        chunks.append(_chunk(doc, i, "question", q_context, piece or doc.title))
        i += 1

    # group answers: accepted / maintainer / high-value answers stand alone, small replies get merged
    groups: list[list[tuple[str, str]]] = []
    for heading, body in answers:
        standalone = heading.startswith(("Accepted answer", "Resolution")) or "maintainer" in heading
        if (groups and not standalone and not _is_standalone(groups[-1][0][0])
                and sum(len(b) for _, b in groups[-1]) + len(body) <= cfg.target_chars):
            groups[-1].append((heading, body))
        else:
            groups.append([(heading, body)])

    for group in groups:
        heading0 = group[0][0]
        accepted = any(h.startswith("Accepted answer") for h, _ in group)
        maintainer = any("maintainer" in h for h, _ in group)
        role = "answer" if (accepted or maintainer or heading0.startswith(("Answer", "Resolution"))) else "reply"
        text = "\n\n".join(f"**{h}**\n\n{b}" for h, b in group)
        for piece in pack(blocks(text), fit(cfg, answer_context)):
            chunks.append(_chunk(doc, i, role, answer_context, piece, is_accepted=accepted, by_maintainer=maintainer))
            i += 1
    return chunks


def _is_standalone(heading: str) -> bool:
    return heading.startswith(("Accepted answer", "Resolution")) or "maintainer" in heading


def chunk_document(doc: Document, cfg: ChunkingConfig) -> list[Chunk]:
    return chunk_thread(doc, cfg) if doc.source_type in THREAD_TYPES else chunk_doc(doc, cfg)


# ---------------------------------------------------------------------------
# baseline for comparison: naive fixed-size windows (what most tutorials do)
# ---------------------------------------------------------------------------

def naive_chunks(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    step = size - overlap
    return [text[s:s + size] for s in range(0, max(len(text) - overlap, 1), step)]
