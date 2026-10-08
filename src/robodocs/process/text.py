"""Shared text cleaning (Stage 2, step 3). Applied to every source after parsing.

Rule: never modify the inside of fenced code blocks except to trim giant pasted logs,
and when trimming, always keep the lines that look like errors.
"""

import re
import unicodedata

FENCE = re.compile(r"^(\s*)(```|~~~)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
HTML_IMG = re.compile(r"<img\b[^>]*?(?:alt=[\"']([^\"']*)[\"'])?[^>]*>", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
LOGOS_AND_BADGES = re.compile(
    r"!\[(?:Rosanswers|ROS Answers|Gazebo Answers)[^\]]*logo\]\([^)]*\)"   # migrated ROS Answers posts
    r"|\[!\[[^\]]*\]\([^)]*(?:shields\.io|badge)[^)]*\)\]\([^)]*\)"       # [![badge](..)](..)
    r"|!\[[^\]]*\]\([^)]*(?:shields\.io|badge)[^)]*\)", re.I)
MKDOCS_ATTR = re.compile(r"\s*\{\s*[#:.][^}\n]*\}")                       # "# Title { #anchor }"
MKDOCS_ADMONITION = re.compile(r"^(!!!|\?\?\?\+?)\s*(\w+)(?:\s+\"([^\"]*)\")?\s*$")
ERROR_LINE = re.compile(r"(?i)error|exception|traceback|failed|fatal|warn|not found|cannot|undefined|"
                        r"segmentation|abort|denied|no module|^\s*File \"")

MAX_CODE_LINES = 80        # code/log blocks longer than this get trimmed
KEEP_HEAD, KEEP_TAIL = 15, 25


def split_fences(text: str) -> list[tuple[bool, str]]:
    """Split Markdown into [(is_code, chunk)], so prose cleaning never touches code."""
    parts, buf, in_code = [], [], False
    for line in text.splitlines():
        if FENCE.match(line):
            if not in_code:
                if buf:
                    parts.append((False, "\n".join(buf)))
                buf, in_code = [line], True
            else:
                buf.append(line)
                parts.append((True, "\n".join(buf)))
                buf, in_code = [], False
            continue
        buf.append(line)
    if buf:
        parts.append((in_code, "\n".join(buf)))
    return parts


def trim_code_block(block: str) -> str:
    """Keep head + tail + every error-looking line of a huge pasted log."""
    lines = block.splitlines()
    if len(lines) <= MAX_CODE_LINES:
        return block
    fence_open, body, fence_close = lines[0], lines[1:-1], lines[-1]
    head, tail, middle = body[:KEEP_HEAD], body[-KEEP_TAIL:], body[KEEP_HEAD:-KEEP_TAIL]
    errors = [l for l in middle if ERROR_LINE.search(l)][:20]
    note = f"[... {len(middle) - len(errors)} log lines trimmed ...]"
    return "\n".join([fence_open, *head, note, *errors, *(["[...]"] if errors else []), *tail, fence_close])


def images_to_text(text: str) -> str:
    """![alt](url) -> [image: alt](url). Keeps the link so an answer can say 'see screenshot'."""
    text = LOGOS_AND_BADGES.sub("", text)
    text = MD_IMAGE.sub(lambda m: f"[image: {m.group(1).strip() or 'screenshot'}]({m.group(2)})", text)
    return HTML_IMG.sub(lambda m: f"[image: {(m.group(1) or 'screenshot').strip()}]", text)


def mkdocs_to_markdown(text: str) -> str:
    """Nav2 docs use MkDocs extensions: strip '{ #anchor }', turn '!!! note' into a quote."""
    out = []
    for line in text.splitlines():
        m = MKDOCS_ADMONITION.match(line)
        if m:
            out.append(f"> **{(m.group(3) or m.group(2)).strip().capitalize()}:**")
            continue
        out.append(MKDOCS_ATTR.sub("", line) if line.lstrip().startswith("#") else line)
    return "\n".join(out)


def strip_front_matter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def clean_text(text: str) -> str:
    """Final pass for every document."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    out = []
    for is_code, chunk in split_fences(text):
        if is_code:
            out.append(trim_code_block(chunk))
            continue
        chunk = HTML_COMMENT.sub("", chunk)
        chunk = images_to_text(chunk)
        chunk = EMAIL.sub("[email]", chunk)
        chunk = "\n".join(l.rstrip() for l in chunk.splitlines())
        out.append(chunk)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
